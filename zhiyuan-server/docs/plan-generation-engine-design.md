# 方案编排引擎设计

## 1. 目标

当前 `sessionDetailV2` 已经以 planning state 为主工作台，后续默认视图也将稳定落在 V2。

因此 backend 不能再只提供：

- 候选池生成
- 草稿选择
- 简单排序生成
- 审查与补偿

而需要提供一套能够直接支撑 V2 的“方案编排引擎”。

这套能力的目标是：

- 在用户尚未手动选草稿时，系统能自动生成一套默认填报方案
- 在用户已经选过草稿甚至部分手排后，系统仍能给出专业视角更合理的编排建议
- 在两种志愿模式下都能工作
  - `major`
  - `majorGroup`
- 在生成阶段尽量前置满足结构性规则
  - 冲稳保配比
  - 本省保底
  - 概率倒挂
  - 梯度断层
  - 数量要求
  - 组内专业数量要求

这里的“编排”不是单一排序，而是：

- 选谁进入方案
- 这些志愿怎么分层
- 最终顺序怎么排
- 是否需要补位

## 2. 当前问题

当前 backend 已具备：

- 基础候选池
- 推荐覆盖层
- 草稿与排序状态
- review 与 compensation

但 `generateOrderedPlan()` 当前主要解决的是：

- 对现有草稿生成一个默认顺序
- 先按 tier
- 再按录取率 / 区间位次 / 推荐分做区间内排序

对应代码：

- [PlanningStateService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java#L429)
- [PlanningStateService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java#L2238)

这还不足以覆盖 V2 后续真实需要的两类场景：

### 2.1 场景 A：系统初始自动方案

用户尚未主动从候选中选择志愿，系统需要从当前全部可选志愿中自动生成一套默认可填报方案。

这时 backend 不能只做“候选查询”，还需要做：

- 从候选工作集里自动选取一批志愿
- 自动形成冲稳保结构
- 自动生成可解释的默认排序

### 2.2 场景 B：草稿后二次编排

用户已经在草稿区选过志愿，甚至可能：

- 还没排顺序
- 已经部分手动排序
- 已经固定部分位置

这时 backend 需要在尊重用户显式操作的前提下，给出“更专业的建议排序”。

## 3. 核心设计原则

### 3.1 统一输入上下文

所有编排能力都必须基于统一上下文，而不是各接口临时拼装：

- 用户分数、位次、省份、批次
- 志愿模式
- 硬约束
- 软意向
- 当前策略型
- 候选池状态
- 推荐覆盖层
- 草稿状态
- 排序状态

### 3.2 先选方案，再排顺序

编排不能只理解为排序。

至少要拆成：

1. 候选工作集形成
2. 方案选取
3. 顺序编排
4. 结构校正

### 3.3 review 中的结构性规则应尽量前置

以下规则不应完全依赖 review 事后报错：

- `ratio_distribution`
- `safety_guard`
- `probability_inversion`
- `probability_gap`
- `count_validation`

补充说明：

- 当前版本里，`unit_major_count_validation` 已不再作为 `majorGroup` 模式的现行规则。
- `requiredMajorCount` 只表示“每个已选专业组最多保留多少个主选专业”。
- 若组内天然少于该值，属于正常数据形态，不进入 review / adjustment / compensation。
- 下文若出现 `unit_major_count_validation`，默认视为历史设计痕迹，除非明确标注“历史方案”。

这些规则应尽量在方案生成阶段就主动满足或主动修复。

以下规则仍可主要保留在 review：

- `high_tuition`
- `admission_limit`
- `special_enrollment`
- `edge_score`
- `cooperative_program`

原因是这些更多属于提醒、资格核验或用户接受度问题，而非纯编排问题。

### 3.4 用户显式操作优先于系统建议

若用户已经：

- 手动调序
- 固定位置
- 锁定草稿

则系统建议排序必须在这些边界内工作，而不是粗暴重排。

## 4. 统一编排框架

建议将“方案编排引擎”抽象为统一的四步流程。

### 4.1 Step 1：形成候选工作集

候选工作集来源：

- 基础候选池
- recommendation overlay

输出：

- 当前可用于编排的全部候选
- 每条候选的显式结构化字段
  - `tier`
  - `majorTier`
  - `admissionRatio`
  - `rankInTier`
  - `finalScore`
  - `provinceName`
  - `schoolId`
  - `schoolName`
  - `volunteerModel`
  - 标签与限报信息

### 4.2 Step 2：计算目标结构

根据上下文计算本次编排的目标结构：

- 总目标数量
- 冲 / 稳 / 保目标数量
- 本省保底最低数量
- 组内专业最低数量
- 当前是否允许系统补位
- 当前是否允许系统改动用户已有顺序

这一步不能只依赖 `requiredCount`，还需要显式补充：

- `requiredTierCounts`
- `requiredMajorCount`
- `safetyGuardTarget`

### 4.3 Step 3：生成方案骨架

先决定“谁进入方案”以及“方案基本分层是什么”，再决定最终顺序。

这一步的目标不是单纯取 `finalScore` 最高，而是多目标平衡：

- 满足 tier 配额
- 满足保底要求
- 避免 tier 内部过密或过疏
- 优先保留专家优选组合
- 保留用户已选草稿

### 4.4 Step 4：顺序编排与校正

在方案骨架内做最终排序：

- 先保证不倒挂
- 再尽量压缩相邻 gap
- 再保证本省保底位置合理
- 最后在局部内按 `finalScore` 与用户意向细化

若仍存在明显断层，则进入“补位”流程：

- 从候选工作集中找中间概率带候选
- 插入缺口
- 重新校正顺序

## 5. 两类主场景

## 5.1 场景 A：系统初始自动方案

### 输入

- 当前 planning state
- 当前候选工作集
- 用户画像、硬约束、软意向
- 当前志愿模式
- 当前策略型

### 当前实现补充约束

为避免 V2 初始方案在真实会话中出现“候选池已更新但仍复用旧初排结果”的偏差，当前 `generateInitialPlan(forceRegenerate=true)` 需要同时满足两点：

- 强制重建 `candidatePoolState`
- 强制重建 `initialRecommendationState`

否则会出现：

- `candidatePoolState.requiredTierCounts` 已经按最新策略型或最新供给计算
- 但 `draftPlanState / orderedPlanState` 仍沿用历史 `initialRecommendationState`
- 最终表现为真实会话里冲稳保比例与当前候选供给不一致

当前 backend 已按该语义修正，`forceRegenerate` 不再只作用于候选层。

### majorGroup 汇总口径

`majorGroup` 模式下，`initialRecommendationState` 可以按“组内主选专业条目”展开存储，但 `draft/ordered summary` 必须按“专业组单位”统计，而不是按摊平后的专业条目统计。

统一约束如下：

- `summary.total` 按专业组数统计
- `summary.tierCounts` 按专业组代表层级统计
- 组内专业条目仅用于展示与后续组内调整，不参与组层数量汇总

否则前端会出现：

- 已选 48 个专业组，但 `draft/ordered total` 显示为 100+ 条
- review / 调整分析误把组内专业条目数当作志愿数

### 输出

- 一套完整默认方案
- 同步写入：
  - `draftPlanState`
  - `orderedPlanState`
- 标记系统生成来源与原因

### 处理逻辑

1. 从候选工作集中过滤掉明显不可补位对象
2. 按冲稳保目标数切 tier 配额
3. 每个 tier 内按：
   - 概率主轴
   - 推荐分
   - 未来发展导向分
   - 本省保底优先
   - 风险惩罚
   生成候选优先序
4. 不是简单截断，而是做梯度抽样
5. 形成方案后执行一次结构校正
6. 若仍有 gap 或数量不足，则自动补位

### 关键结论

“专家优选组合”在这里应作为候选选取的重要信号，但不能直接等于最终方案。

最终方案应是：

- 专家优选
- tier 配额
- 梯度要求
- 本省保底
- 未来发展导向

共同作用后的结果。

### 当前已接入的未来发展导向

当前先落最小能力：`futureDevelopment.careerTypes` 中若推导出 `"体制内"` / `"考公"` 导向，则会在候选工作集上额外计算 `futureDevelopmentScore`，并用于：

- 初始方案候选优先序
- `majorGroup` 组内主选专业优先序
- 已有草稿生成默认排序时的局部比较

当前实现链路：

1. `profileState.latentProfile.futureDevelopment.careerTypes`
2. `buildDerivedPreferences()`
3. `employmentOrientationInferred`
4. `buildFutureDevelopmentSignals()`
5. `applyFutureDevelopmentScores()`
6. 进入 `buildInitialRecommendationCandidateComparator()` / `buildMajorGroupInnerCandidateComparator()` / `buildDraftOrderedComparator()`

当前启发式加分信号：

- 公办
- 本科
- 师范 / 政法 / 财经 / 农林 / 医药
- 法学、汉语言、思想政治、教育、行政管理、公共管理、政治学、马克思等专业方向

当前启发式减分信号：

- 民办
- 中外合作
- 高学费

边界说明：

- 这类导向当前不会改变 `candidatePoolState` 的成员集合
- 也不会直接变成硬约束筛掉候选
- 当前主要作用在“谁更值得优先进入方案、以及默认顺序如何更贴近导向”
- `review` 暂不把它作为硬性否决规则，后续再补“目标一致性分析”

## 5.2 场景 B：草稿后二次编排

### 输入

- 当前 planning state
- 当前 draft / ordered 状态
- 当前候选工作集
- 用户画像、硬约束、软意向
- 当前志愿模式

### 输出

- 一份“分析 + 建议”结果
- 默认先写入 `planAdjustmentState`
- 不直接覆盖：
  - `draftPlanState`
  - `orderedPlanState`

### 处理逻辑

1. 读取当前草稿与排序，识别用户已显式干预的边界
2. 分析当前方案是否存在：
   - 数量不足
   - 冲稳保失衡
   - 梯度断层
   - 与硬约束冲突
   - 与软意向明显背离
3. 生成建议动作，而不是直接应用：
   - `reorder`
   - `add`
   - `replace`
   - `remove`
4. 仅在用户显式确认后，才真正执行建议并回写草稿或排序

### 关键结论

“草稿后二次编排”本质上不是“重新排一遍”，而是：

- 先分析当前方案哪里有问题
- 再给出建议
- 最后在用户确认后应用

这条链路应视为 `review` 的上层封装，`review` 输出的结构性问题需要直接进入建议生成，而不是单独停留在只读提示。

## 6. V2 阶段的状态拆分

为避免把“候选默认推荐”和“当前方案调整建议”继续混进同一组字段，建议在 `planningState` 内新增两块状态。

### 6.1 `initialRecommendationState`

作用：

- 承接“当前候选视图下的专家优选组合”
- 只作用候选区和默认推荐顺序
- 不直接改草稿
- 不直接改排序

建议字段：

- `generatedAt`
- `sourceVersion`
- `candidateViewVersion`
- `profileVersion`
- `summary`
- `items`

其中：

- `summary`
  - `total`
  - `expertPreferredCount`
  - `tierCounts`
- `items`
  - `volunteerId`
  - `expertComboTag`
  - `comboScore`
  - `recommendTier`
  - `reasonCodes`

### 6.2 `planAdjustmentState`

作用：

- 承接“当前草稿/排序的分析结果与调整建议”
- 默认只生成建议，不直接覆盖现有方案

建议字段：

- `generatedAt`
- `sourceVersion`
- `draftVersion`
- `orderedVersion`
- `status`
- `analysis`
- `suggestions`

其中：

- `analysis`
  - `hasInsufficientCount`
  - `hasTierImbalance`
  - `hasProbabilityGap`
  - `hasConstraintConflicts`
  - `hasPreferenceDeviation`
  - `summaryText`
- `suggestions`
  - `reorderSuggestions`
  - `addSuggestions`
  - `replaceSuggestions`
  - `removeSuggestions`

## 7. Backend 接口建议

## 7.1 初始方案生成

### `POST /inner/planning/{tenantId}/session/initial-recommendation/generate`

输入建议：

- `chatSessionId`
- `forceRegenerate`

职责：

- 基于 `candidatePoolState + candidateViewState + recommendationOverlayState`
- 生成 `initialRecommendationState`

注意：

- 这一步只生成候选层推荐结果
- 不直接写 `draftPlanState`
- 不直接写 `orderedPlanState`

### `GET /inner/planning/{tenantId}/session/initial-recommendation`

职责：

- 供 frontend / agent 读取当前候选层的专家优选结果

## 7.2 调整式方案生成

### `POST /inner/planning/{tenantId}/session/plan-adjustment/analyze`

输入建议：

- `chatSessionId`
- `target`
  - `draft`
  - `ordered`
- `includeReview`

职责：

- 先分析当前方案
- 再生成建议
- 回写 `planAdjustmentState`

### `POST /inner/planning/{tenantId}/session/plan-adjustment/apply`

输入建议：

- `chatSessionId`
- `suggestionIds`
- `applyMode`
  - `reorder_only`
  - `append_only`
  - `replace_and_reorder`

职责：

- 仅在用户显式确认后执行建议
- 回写草稿、排序以及操作日志

## 8. 打脏规则建议

### 8.1 `initialRecommendationState`

以下变化后应打脏：

- `profileState`
- `candidateViewState`
- `recommendationOverlayState`

以下变化后默认不打脏：

- 草稿变化
- 排序变化

### 8.2 `planAdjustmentState`

以下变化后应打脏：

- 草稿变化
- 排序变化
- 画像变化
- 候选视图变化
- 推荐覆盖层变化

## 9. 前后端交互边界

### 9.1 初始方案生成

在 `sessionDetailV2` 当前阶段，初始方案生成分两种入口：

- 前端采集入口：
  - 会话基础信息已完整，首次进入工作台时可直接生成一份可编辑的初始方案
  - 先执行 `initialRecommendation` 的组建与结构修复，再把修复后的结果写入 `draftPlanState + orderedPlanState`
  - 前端在“方案”栏展示，并给系统生成条目标记 `优选`
- 非前端采集入口 / 仅候选浏览入口：
  - 仍可先落到 `initialRecommendationState`
  - 由候选区展示 `专家优选组合`
  - 由候选默认排序和标签语义隐式发挥作用

### 9.1.1 当前实现与缺口

当前实现约定补充：

- `generateInitialPlan` 不再直接按候选池做“简单抽草稿”
- 它会先复用 `buildInitialRecommendationState()`：
  - 按冲稳保目标数做首轮选取
  - 依次执行 `count_validation / safety_guard / unit_major_count_validation / probability_inversion / probability_gap / ratio_distribution` 对应的结构修复
- 然后将修复后的 `initialRecommendationState.items` 映射为 `draftPlanState.items`
- 最后再走 `reorderDraftPlanInternal(..., "initial_auto")` 生成默认方案

这意味着前端采集入口下的初始化方案，与“专家优选组合”使用的是同一套底层组建结果，而不是两套不同口径的自动选取逻辑。

但当前实现仍存在一个关键语义缺口：

- `major` 模式下，`requiredCount` 表示“专业志愿条目数”，当前实现语义基本成立
- `majorGroup` 模式下，`requiredCount` 表示“专业组志愿数”，而不是“专业条目数”
- 现有 planning state 仍以扁平 `CandidateItemDTO` 为初始推荐和初始方案的直接组建单位
- 这会导致 `majorGroup` 模式下，把“应选 48 个专业组”误当成“应选 48 条专业志愿”

老版本初始优选方案的正确语义应继续保留：

1. 先走现有推荐主链：
   - 候选过滤
   - 九宫格划分
   - 分区间 rank 打分
   - 合并成冲/稳/保三大区间
2. 在 `major` 模式下：
   - 直接以单专业志愿为单位做目标数截断与优选标记
3. 在 `majorGroup` 模式下：
   - 先以院校/专业组为单位做目标数截断与优选标记
   - 再在每个已选组内按专业排序结果保留 `requiredMajorCount` 个主选专业
   - 组内剩余专业仅作为备选专业保留，不计入“志愿位数”

因此，`majorGroup` 模式下当前的主要缺口不是“组内专业数没补齐”，而是：

- 方案主单位选错了
- 组内专业数约束只是事后补救，没有前置到组选取主链路

### 9.1.1.1 `majorGroup` 模式修复原则

针对 `majorGroup` 模式，后续实现应遵循以下约定：

#### A. 候选池保留扁平条目，但方案生成改用组层单位

- `candidatePoolState.items` 继续保留扁平 `CandidateItemDTO`
- 用于筛选、搜索、专业级展示、组内候补展示
- 但 `initialRecommendation / draft / ordered / review / adjustment` 在 `majorGroup` 模式下，应引入组层 `unit`

建议组层聚合键：

- 优先 `planSchoolDataId`
- 兜底 `schoolId + tier + schoolName`

#### B. `requiredCount` 与 `requiredMajorCount` 分层生效

- `requiredCount`
  - `major` 模式下表示“专业志愿数量”
  - `majorGroup` 模式下表示“专业组志愿数量”
- `requiredMajorCount`
  - 仅在 `majorGroup` 模式下表示“每个专业组主选专业数”

#### C. 初始推荐与初始方案先选组，再补组内专业

`majorGroup` 模式下正确的组建顺序应为：

1. 从扁平 candidate 聚合出组层 `PlanningUnit`
2. 按冲/稳/保目标数在组层做首轮选取
3. 在组层执行结构修复：
   - `count_validation`
   - `ratio_distribution`
   - `probability_inversion`
   - `probability_gap`
   - `safety_guard`
4. 组选定后，再对每个组按组内专业排序保留前 `requiredMajorCount` 个主选专业
5. 若组内天然不足 `requiredMajorCount`，直接保留现状，不视为风险或缺陷

组内选专业时，还应额外满足一条安全垫约束：

- 每个已选专业组的主选专业集合里，至少要有 1 个专业满足
  - `major.admissionRatio > unit.schoolEnrollRatio`

这条约束的含义是：

- 组层已经被选入方案后，组内主选专业不能全部都处在“低于或等于组整体录取率”的风险侧
- 主选专业里至少需要保留 1 个录取率高于组层录取率的专业，作为组内安全垫专业

建议命名为：

- `group_inner_safety_guard`

处理优先级建议：

1. 先过滤掉不满足硬约束的专业
2. 若存在 `admissionRatio > schoolEnrollRatio` 的专业：
   - 主选专业集合中至少保留 1 个这样的专业
3. 其余主选名额再按组内专业排序规则补齐
4. 若组内不存在这样的专业：
   - 不强行造数
   - 记录 `group_inner_safety_guard` 命中，保留到 `review / planAdjustment`

也就是说：

- `requiredMajorCount` 在 `majorGroup` 模式下只是组内主选专业的截断上限
- 它不能被提升为“组完整性”校验，更不能参与组选优劣比较
- `group_inner_safety_guard` 才是当前保留的组内结构约束，且仅在“存在可用安全垫专业但主选里没保留”时命中

当前 backend 已落地的最小闭环是：

- `generateInitialPlan`
  - 先按组生成初始优选
  - 再在组内按排序截断到 `requiredMajorCount`
  - 组内优先保留至少 1 个 `admissionRatio > schoolEnrollRatio` 的专业
- `runReview / planAdjustment/analyze`
  - `count_validation / ratio_distribution / probability_inversion / probability_gap / safety_guard`
    - 已切到“组层快照”执行
    - 即按专业组数量、专业组梯度和专业组保底语义审查
  - `group_inner_safety_guard`
    - 继续按平铺专业条目执行
    - 只承担组内安全垫校验，不再引入组内数量风险

这保证了当前 backend 在 `majorGroup` 模式下至少不会再出现：

- 初始优选按组生成
- 审查 / 调整又把组内 2 个专业误判成 2 个独立志愿
- 最终把“2 个专业组 x 每组 2 专业”错误识别成“4 条志愿超额/失衡”

在这条链路上还需要补一层“组选质量替换”约束，避免出现“组层数量够了，但被选中的专业组本身不成型”的情况：

1. 先按组代表做首轮冲/稳/保选取与组层结构修复
2. 再逐个检查已入选组是否同时满足：
   - 能补齐到 `requiredMajorCount`
   - 组内至少存在 1 个 `admissionRatio > schoolEnrollRatio` 的安全垫专业
3. 若某个已选组不满足，而剩余候选中存在同 tier 且组质量更高的替代组：
   - 用替代组替换当前弱组
   - 将原因记为组选修复，而不是继续保留到后续 `planAdjustment`
4. 组选替换完成后，需要重新执行一轮组层 `probability_inversion / probability_gap / ratio_distribution` 回刷

这样初始方案的目标就从“先选出来再提示问题”升级为“能在生成阶段修掉的先修掉”，确保 fresh initial plan 不会一进入 `planAdjustment/analyze` 就立刻暴露：

- `unit_major_count_validation`
- `group_inner_safety_guard`
- `probability_inversion`
- `probability_gap`

#### D. draft / ordered 建议升级为组层结构

当前 `draftPlanState.items` / `orderedPlanState.items` 是平铺条目，便于快速验证，但不适合作为 `majorGroup` 模式的长期结构。

建议演进为：

- `DraftUnitDTO`
  - `unitId`
  - `tier`
  - `schoolName`
  - `source`
  - `locked`
  - `majorItems[]`
- `OrderedUnitDTO`
  - `unitId`
  - `tier`
  - `schoolName`
  - `source`
  - `locked`
  - `pinned`
  - `pinnedPosition`
  - `orderedBy`
  - `orderReason`
  - `majorItems[]`

这样后续“拖动排序 / 固定位置 / 删除 / 审查建议”才能稳定作用在专业组层。

#### E. 恢复组层主单位的兼容改造路径

本轮改造不建议直接推翻现有 `planningState` 的所有扁平结构，而应遵循：

- 候选层继续扁平
- 方案层恢复组层
- 前端与 agent 通过兼容字段渐进切换

核心原则如下：

1. `candidatePoolState.items` 继续保留扁平 `CandidateItemDTO`
   - 继续服务候选区分页、筛选、搜索、标签聚合、专业级详情展示
   - 继续作为推荐覆盖层、画像筛选与 filter option 的基础输入
2. `majorGroup` 模式下的方案主链切回组层 `unit`
   - `initialRecommendation`
   - `draft`
   - `ordered`
   - `review`
   - `planAdjustment`
3. `major` 模式保持现状
   - 仍以单条专业志愿作为主单位
   - 不强行套入组层结构

建议新增一层组态对象，但不替换候选对象：

- `PlanningUnitDTO`
  - `unitId`
  - `planSchoolDataId`
  - `schoolId`
  - `schoolName`
  - `tier`
  - `schoolEnrollRatio`
  - `finalScore`
  - `preferred`
  - `selectedMajors[]`
  - `allMajors[]`
  - `requiredMajorCount`
  - `complete`
  - `hasSafetyMajor`
- `DraftUnitDTO`
  - `unitId`
  - `tier`
  - `source`
  - `locked`
  - `majorItems[]`
- `OrderedUnitDTO`
  - `unitId`
  - `tier`
  - `source`
  - `locked`
  - `pinned`
  - `pinnedPosition`
  - `orderedBy`
  - `orderReason`
  - `majorItems[]`

这里有两个关键字段语义要固定：

- `unitId`
  - 在 `majorGroup` 模式下统一等于 `planSchoolDataId`
  - 表示一个专业组志愿位
- `volunteerId`
  - 继续表示组内的具体专业条目
  - 不再承担专业组主单位语义

#### F. 上下游兼容边界

##### F.1 backend

backend 先补“组聚合能力”，再逐步切主链：

1. 新增统一组聚合器
   - 输入：扁平 `CandidateItemDTO`
   - 输出：`PlanningUnitDTO`
2. `majorGroup` 模式下的初始方案生成改为：
   - 先聚组
   - 再组选
   - 再组内选专业
3. `review / planAdjustment` 改读组层快照
   - 组层规则只看 `unit`
   - 组内规则只看 `majorItems`

这一步不要求立刻删除旧字段，而是建议先双轨输出：

- 旧字段保留：
  - `initialRecommendationState.items`
  - `draftPlanState.items`
  - `orderedPlanState.items`
- 新字段补充：
  - `initialRecommendationState.units`
  - `draftPlanState.units`
  - `orderedPlanState.units`

这样可以保证：

- 旧调用方不立即失效
- 新前端和新 agent 可以优先读取 `units`
- backend 可以逐步把内部主链切到组层，而不是一次性替换所有 DTO

##### F.2 frontend

frontend 的兼容策略应分为“候选区”和“方案区”两部分：

- 候选区
  - 继续消费扁平 `items`
  - 在展示层按 `planSchoolDataId` 做临时聚合
  - 保持现有筛选、搜索、分页协议不变
- 方案区
  - `majorGroup` 模式优先消费 `units`
  - 按“专业组 -> 主选专业/备选专业”两级展示
  - 组与组之间支持整体上下移
  - 组内专业支持内部上下移

这意味着：

- 当前候选页签无需因本次改造整体重写
- 主要改造集中在“方案 / 草稿 / 排序 / 审查结果展示”

##### F.3 agent

agent 不应继续假设 `majorGroup` 模式下方案主单位是扁平专业条目。

建议兼容约定：

- 候选分析
  - 继续允许读取扁平候选
  - 便于做意向筛选、标签命中、补充候选解释
- 方案分析
  - 优先读取组层 `units`
  - 审查、调优、替换建议按组输出
- 动作编排
  - 新增组层动作语义：
    - `add_unit`
    - `replace_unit`
    - `move_unit`
  - 组内动作单独建模：
    - `add_major`
    - `remove_major`
    - `move_major`

agent 在过渡期可采用：

- 若接口返回 `units`，优先按 `units` 分析和回复
- 若无 `units`，才回退到旧的扁平 `items`

#### G. 分阶段实施顺序

为降低回归风险，建议按以下顺序推进：

第一阶段：组聚合能力落地

- 新增 `PlanningUnitDTO` 及聚合器
- 不改前端协议
- 不改 agent 动作协议
- 只用于 backend 内部验证与单测

第二阶段：初始方案主链切组层

- `generateInitialPlan`
- `buildInitialRecommendationStateForMajorGroup`
- `draft / ordered` 生成逻辑

这一步目标是先修正“系统生成出来的方案是否正确”，不急于覆盖所有交互动作。

第三阶段：review / planAdjustment 切组层

- 组层规则按 `unit` 执行
- 组内规则按 `majorItems` 执行
- suggestions 增加 `unitId`

第四阶段：前端方案区切 `units`

- 方案展示切两级结构
- 草稿与排序交互切到组层
- 候选区保持扁平输入

第五阶段：agent 动作编排切组层

- 对话里的“调方案 / 看建议 / 替换 / 重排”优先作用在 `unit`
- 组内专业增删调顺序作为次级动作补入

#### G.1 第一阶段的具体开发拆解

第一阶段只落“组聚合能力”和组层 DTO，不改前端协议，不切现有对外主链。

建议新增 DTO：

- `PlanningUnitDTO`
- `PlanningUnitMajorDTO`
- `DraftUnitDTO`
- `OrderedUnitDTO`

建议先在以下状态对象上补充兼容字段：

- `InitialRecommendationStateDTO`
  - 新增 `units`
- `DraftPlanStateDTO`
  - 新增 `units`
- `OrderedPlanStateDTO`
  - 新增 `units`

第一阶段建议新增或改造的方法：

- `PlanningStateService`
  - 新增 `groupCandidatesToPlanningUnits(...)`
  - 新增 `buildPlanningUnit(...)`
  - 新增 `selectUnitMajors(...)`
  - 新增 `countUnitTierCounts(...)`
  - 新增 `evaluatePlanningUnitQuality(...)`
- 保持以下现有方法暂不切主链，只允许内部复用新聚合能力：
  - `buildInitialRecommendationStateForMajorGroup(...)`
  - `generateInitialPlan(...)`
  - `analyzePlanAdjustment(...)`
  - `runReview(...)`

第一阶段单测建议：

- 同一 `planSchoolDataId` 能稳定聚成一个 `unit`
- `requiredMajorCount` 生效后，`selectedMajors` 数量正确
- 存在 `admissionRatio > schoolEnrollRatio` 的专业时，`hasSafetyMajor=true`
- 组内专业不足时，`complete=false`
- 同一候选输入下，组聚合结果顺序稳定

第一阶段完成标准：

- backend 已能从扁平候选构造稳定的组层结构
- 但现有接口仍可继续只返回旧 `items`
- 文档与单测都能证明组层语义完整

#### G.2 第二阶段的具体开发拆解

第二阶段开始把 `majorGroup` 模式下的初始方案主链切到组层。

必须切换的方法：

- `buildInitialRecommendationStateForMajorGroup(...)`
- `buildMajorGroupInitialRecommendationSelection(...)`
- `repairMajorGroupRepresentativeSelection(...)`
- `rebuildMajorGroupInitialRecommendationUnits(...)`
- `generateInitialPlan(...)`
- `replaceDraftWithInitialRecommendation(...)`

切换原则：

- 不再“先挑代表专业再组选”
- 改为“先按 `PlanningUnitDTO` 做组选，再回填组内专业”
- `InitialRecommendationStateDTO.items` 允许继续保留，作为对旧调用方的兼容平铺结果
- `InitialRecommendationStateDTO.units` 作为新主结果

第二阶段建议删除或收缩的旧语义：

- `buildMajorGroupUnitRepresentative(...)`
  - 不再承担组选主单位语义
  - 如仍保留，只能作为展示用代表信息
- `findWeakMajorGroupRepresentative(...)`
- `findReplacementMajorGroupRepresentative(...)`
  - 逐步替换为组层质量比较版本

第二阶段单测建议：

- `majorGroup` 模式下总数按“组数”命中 `requiredCount`
- 每组主选专业数按 `requiredMajorCount` 生效
- “高分但组结构差”会被“略低分但结构完整”的组替换
- fresh initial plan 不应立刻打出可修复的：
  - `unit_major_count_validation`
  - `group_inner_safety_guard`
  - `probability_inversion`
  - `probability_gap`

第二阶段完成标准：

- `majorGroup` 模式下系统生成方案的主单位已恢复为组
- 旧前端若仍读 `items`，不会立刻报错
- 新前端可开始切 `units`

第二阶段当前已落地的实现收口如下：

- 初始推荐先从扁平候选聚合出 `PlanningUnitDTO`
- 组选、组选质量替换、tier 统计都以 `unit` 为主语义执行
- `initialRecommendation.units` 已作为主结果返回
- `initialRecommendation.items` 继续由 `units.selectedMajors` 平铺回填，保证旧调用方兼容
- `generateInitialPlan` 在 `majorGroup` 模式下会把 `draft.units`、`ordered.units` 一并从初始推荐同步落出

本阶段仍保留的兼容折中：

- 概率梯度与 tier 目标修补仍复用既有候选级算法，但输入对象已是 `unit` 的代表投影
- 手动编辑草稿 / 排序后的 `units` 维护仍是过渡形态，后续要在第三、四阶段统一切到组层动作语义

#### G.3 第三阶段的具体开发拆解

第三阶段把审查和调整建议的主语义切到组层，避免继续在“组”和“专业条目”之间来回误判。

必须切换的方法：

- `runReview(...)`
- `reviewCountValidation(...)`
- `reviewRatioDistribution(...)`
- `reviewProbabilityInversion(...)`
- `reviewProbabilityGap(...)`
- `reviewSafetyGuard(...)`
- `analyzePlanAdjustment(...)`
- `buildPlanAdjustmentOrderedSnapshot(...)`
- `buildStructuralOrderedSnapshot(...)`
- `buildCompensationPreview(...)`

规则切换原则：

- 组层规则：
  - `count_validation`
  - `ratio_distribution`
  - `probability_inversion`
  - `probability_gap`
  - `safety_guard`
  - 统一按 `unit` 执行
- 组内规则：
  - `unit_major_count_validation`
  - `group_inner_safety_guard`
  - 统一按 `unit.majorItems` 执行

第三阶段 DTO 兼容建议：

- `ReviewCheckDTO`
  - 新增 `affectedUnitIds`
- `CompensationActionDTO`
  - 新增 `unitIds`
  - `majorGroup` 模式下优先输出组层动作
- `PlanAdjustmentSuggestionsDTO`
  - 支持区分组层建议和组内建议

第三阶段完成标准：

- 审查结果的数量、梯度、保底口径全部回到组层
- 调整建议默认按组输出
- 组内建议只作为次级补充动作出现

第三阶段当前已落地的实现收口如下：

- `buildStructuralOrderedSnapshot(...)` 在 `majorGroup` 模式下优先读取 `ordered.units`
- `reviewCountValidation / reviewRatioDistribution / reviewProbabilityInversion / reviewProbabilityGap / reviewSafetyGuard`
  - 已切换为组层 `OrderedUnitDTO` 口径
- `unit_major_count_validation / group_inner_safety_guard`
  - 继续基于组内专业聚合结果执行
- `buildCompensationPreview(...)`
  - `majorGroup` 模式下优先产出组层补偿动作
  - `unitIds` 指向专业组
  - `volunteerIds` 继续兼容摊平后的组内专业
- `buildPlanAdjustmentOrderedSnapshot(...)`
  - 在 `majorGroup` 模式下会同步维护 `ordered.units`
- `OrderedUnitDTO`
  - 已补齐 `provinceName / cityName / admissionRatio / finalScore / schoolEnrollRatio`
  - 供组层审查和补偿直接使用

第三阶段仍保留的兼容折中：

- `AddSuggestionDTO / ReplaceSuggestionDTO / ReorderSuggestionDTO`
  - 已补充组层兼容字段
    - `affectedUnitIds`
    - `candidateUnitIds`
    - `removeUnitIds`
    - `orderedUnitIds`
  - `ReplacementPairDTO` 额外补充 `fromUnitId / toUnitId`
  - `PlanAdjustmentCandidateSummaryDTO` 额外补充 `unitId`
  - apply 仍沿用旧的 `volunteerIds` 执行，当前阶段不直接改动作协议
- `ordered.items`
  - 仍保留为兼容平铺视图
  - 但 `majorGroup` 的结构性规则不再以它为主判断口径

#### G.4 frontend 与 agent 的接入清单

为了控制联调风险，frontend 和 agent 的接入顺序建议晚于 backend 主链切换。

frontend 需要关注的接口读取点：

- `getInitialRecommendationState`
- `getDraftState`
- `getOrderedPlanState`
- `getReviewState`
- `analyzePlanAdjustment`

frontend 需要优先改造的页面区块：

- `sessionDetailV2` 方案区
- `sessionDetailV2` 草稿区
- `sessionDetailV2` 排序交互
- `sessionDetailV2` 审查结果展示

agent 需要优先改造的读取点：

- 方案现状概览
- 审查命中分析
- 调整建议生成
- replace / reorder / add suggestion 的目标对象识别

agent 过渡期建议：

- 若后端返回 `units`，优先使用 `units`
- 若仅有 `items`，才回退旧逻辑
- 不在 agent 层自行猜测“哪些专业条目属于同一组”作为长期方案

#### H. 本轮改造的非目标

为了避免范围失控，本轮不建议同时处理以下内容：

- 重做候选区的扁平数据协议
- 重做标签体系与组层 DTO 的一次性完全统一
- 一次性删除所有旧 `items` 字段
- 强诉求折中求解
- 多目标全局最优重排

本轮目标应收口为：

- `majorGroup` 模式下恢复“组是方案主单位”
- 不破坏当前 frontend 候选区与 agent 候选分析能力
- 给后续排序、审查、补偿和动作编排建立稳定的组层语义基础

### 9.1.1.2 `sessionDetailV2` 方案区展示约定

前端“方案”区在 `majorGroup` 模式下应改为两级展示，而不是继续把组内专业平铺成一列排序条目。

展示结构：

- 一级：院校 / 专业组
  - 学校名 / 专业组名
  - 冲稳保
  - 推荐度
  - 录取率
  - 地域
  - 学校标签
  - `优选 / 系统初排 / 手动调整 / 已固定`
- 二级：组内专业
  - 前 `requiredMajorCount` 个专业标记为主选专业
  - 其余专业折叠为备选专业
  - 专业层继续展示录取率、冲稳保、专业标签、历年分数等信息

这层应尽量复用旧版 `sessionDetail/Volunteer` 中已经验证过的“院校/专业组 -> 专业 -> 主选/备选”展示方式，而不是继续维持当前 planning workspace 的扁平排序条目模型。

### 9.1.2 建议的三层结构

建议把初始推荐正式拆成三层：

#### A. 单志愿打分层

直接复用现有 rank 输出：

- `baseScore`
- `intentScore`
- `finalScore`
- `rankInTier`
- `preferred`

这层只表达“单个志愿本身有多值得推荐”。

#### B. 初始粗组装层

在候选全集上，先按冲/稳/保目标数构造一版基础集合。

输入：

- `candidatePoolState.items`
- `recommendationOverlayState`
- `requiredCount`
- `requiredTierCounts`
- 当前志愿模式

输出：

- 一版按 tier 目标数初步选出的候选集合

这层主要解决：

- 数量分配
- tier 目标对齐
- 分数优先的基础截断

#### C. 结构修复层

在粗组装结果上，继续针对核心审查规则做修复。

第一批建议只前置以下规则：

- `count_validation`
- `ratio_distribution`
- `probability_gap`
- `safety_guard`
- `unit_major_count_validation`

这层主要解决：

- 数量补足
- 本省保底安全
- 梯度断层修复
- 专业组/院校组内专业数合法性

修复完成后的集合，才应真正写入 `initialRecommendationState.items`。

### 9.1.3 第一版输入约定

第一版建议只使用 planning 层当前已具备的输入，不额外引入新的远端依赖：

- `candidatePoolState.items`
- `recommendationOverlayState.items`
- `candidatePoolState.requiredCount`
- `candidatePoolState.requiredTierCounts`
- `candidatePoolState.requiredMajorCount`
- `candidatePoolState.sourceProvinceName`
- `candidatePoolState.userScore`
- `candidatePoolState.volunteerModel`

其中 `candidatePoolState.requiredTierCounts` 的生成口径约定为：

- 优先使用当前会话持久化的 `USER_SCORE_KEY.strategyType` 配合 `need_count` 重新计算
- 若远端 `recommendVolunteerList.userScoreDetail.strategyType` 有值，可直接使用
- 只有在两处都拿不到 `strategyType` 时，才回退读取旧 `three_target_count_map / sprints_count / safes_count / protects_count`

这样可以保证“前端问卷已确定策略类型，但远端推荐响应未回传该字段”的场景下，初始化方案、初始推荐与候选区建议数量仍保持同一套冲稳保目标口径。

合并后每个候选至少需要具备：

- `volunteerId`
- `tier`
- `schoolId`
- `provinceName`
- `admissionRatio`
- `finalScore`
- `rankInTier`
- `preferred`

在 `majorGroup` 模式下，还需要能识别“同一组/同一院校单元”的归属关系，用于组内数量校验。

### 9.1.4 初始粗组装流程

第一版不引入复杂最优化求解，先采用启发式策略。

建议流程：

1. 按 `tier` 将候选分为 `冲 / 稳 / 保`
2. 每个 tier 内按以下主排序排队：
   - `finalScore desc`
   - `admissionRatio asc`
   - `rankInTier asc`
3. 按 `requiredTierCounts` 先取每个 tier 的目标数
4. 若某个 tier 数量不足，则记录缺口，后续从相邻 tier 借位

借位顺序建议：

- 冲缺口优先由稳补
- 稳缺口优先由保或冲补
- 保缺口优先由稳补，但补完后仍需再跑安全修复

这一步得到的是：

- `draft_initial_set`

它还不是最终初始推荐，只是一版粗解。

### 9.1.4.1 建议的数据结构

为避免在实现时把“候选项”“已选项”“剩余池”和“修复动作”混在一起，建议第一版至少引入以下内部对象。

#### A. `InitialRecommendationCandidate`

表示参与初始推荐组建的标准化候选项。

建议字段：

- `volunteerId`
- `tier`
- `schoolId`
- `unitId`
- `provinceName`
- `admissionRatio`
- `finalScore`
- `rankInTier`
- `preferred`
- `localProtectCandidate`
- `unitSatisfied`
- `unitSize`
- `sourceTags`

字段含义：

- `unitId`
  - `major` 模式下可先退化为 `volunteerId`
  - `majorGroup` 模式下建议指向“专业组/院校组单元”
- `localProtectCandidate`
  - 是否属于“本省 + 保区”候选
- `unitSatisfied`
  - 当前候选所属单元是否具备被补齐为合法单元的可能
- `unitSize`
  - 当前单元在候选全集中的可用专业数量

#### B. `InitialRecommendationSelectionState`

表示当前一轮组建中的可变快照。

建议字段：

- `selected`
- `remaining`
- `targetCount`
- `targetTierCounts`
- `currentTierCounts`
- `localProtectCount`
- `gaps`
- `unitStats`
- `appliedRepairs`

字段含义：

- `selected`
  - 当前已选集合
- `remaining`
  - 尚未入选的候选池
- `gaps`
  - 当前排序下识别出的断层列表
- `unitStats`
  - 记录各 `unitId` 当前已选数量 / 可补数量
- `appliedRepairs`
  - 已执行的修复动作日志

#### C. `InitialRecommendationRepairAction`

建议统一记录每次修复动作。

建议字段：

- `type`
  - `fill_count`
  - `replace_for_local_protect`
  - `fill_unit_major`
  - `fill_probability_gap`
  - `swap_boundary`
- `ruleCode`
- `addVolunteerIds`
- `removeVolunteerIds`
- `detail`

这样可以在第一版就保留解释能力，后续也便于前端和 agent 消费“系统为什么这么组”。

### 9.1.4.2 候选标准化约定

为了避免实现时反复判断不同模式，建议在组建前先做一次标准化：

1. 合并 `candidatePoolState.items + recommendationOverlayState.items`
2. 补出统一排序字段：
   - `effectiveScore`
     - 优先取 `finalScore`
     - 缺失时回退 `rankInTier`
   - `effectiveAdmissionRatio`
     - 优先取 `admissionRatio`
     - 缺失时该候选不参与 gap 修复主排序
3. 补出模式相关单元字段：
   - `major`
     - `unitId = volunteerId`
   - `majorGroup`
     - `unitId = schoolId` 或专业组唯一标识
4. 补出修复辅助字段：
   - `localProtectCandidate`
   - `unitSize`
   - `canFillUnit`

这里建议在组建器入口就完成标准化，后续修复逻辑只面向统一对象工作。

### 9.1.4.3 第一版主排序与淘汰排序

第一版需要同时定义：

- 入选主排序
- 边际淘汰排序

否则“怎么选”和“修复时先踢谁”会不一致。

#### A. 入选主排序

建议为：

1. `effectiveScore desc`
2. `preferred desc`
3. `effectiveAdmissionRatio asc`
4. `rankInTier asc`

意图：

- 先吃到高分和既有优选信号
- 同分时优先保留梯度更靠前的候选

#### B. 边际淘汰排序

建议不要只按低分踢人，而是构造“边际价值”排序，从低到高淘汰。

第一版建议按以下顺序判断谁更可淘汰：

1. 非本省保区
2. 不参与任何组内数量补齐
3. 不位于 gap 修复关键区间
4. `preferred=false`
5. `effectiveScore` 更低
6. `effectiveAdmissionRatio` 更靠近已有密集区

这条规则的目标是：

- 让修复动作尽量局部
- 不因为一次 gap 修复把安全性或单元合法性打坏

### 9.1.4.4 `major` 与 `majorGroup` 的组建单位差异

#### A. `major`

在 `major` 模式下，第一版仍可把单条志愿视为最小组建单位：

- 选取单位：单条专业志愿
- 修复单位：单条专业志愿

#### B. `majorGroup`

在 `majorGroup` 模式下，不能只以单专业为中心。

建议：

- 组建单位仍然是单条可填报志愿
- 但修复和合法性判断必须提升到 `unitId`
- 即：
  - 选的时候可以先按单条分数进入
  - 修的时候必须看整组能否成型

这实际上是一个“单条入场、单元校验”的折中策略，适合第一版快速落地。

### 9.1.4.5 粗组装伪代码

```text
normalize all candidates
bucket by tier
sort each tier by primary comparator

selected = []
remaining = all normalized candidates

for tier in [冲, 稳, 保]:
  target = requiredTierCounts[tier]
  take top target from tier bucket into selected
  remove from remaining

if total(selected) < requiredCount:
  borrow from adjacent tiers by predefined order

build selectionState(selected, remaining)
return selectionState
```

### 9.1.5 结构修复流程

### 9.1.5.0 当前实现口径

当前 backend 已落地的第一版修复链路，与 [PlanningStateService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java) 一致，执行顺序为：

1. `count_validation`
2. `safety_guard`
3. `unit_major_count_validation`
4. `probability_inversion`
5. `probability_gap`
6. `rebalanceInitialRecommendationTierCounts`

其中有两个实现约束需要明确：

- `probability_inversion` 当前只做“同 tier 内替换”修复，也就是优先用同一冲/稳/保区间里的剩余候选替换掉倒挂边界上的异常项，避免把 tier 骨架打散。
- `probability_gap` 修复不是命中一个 gap 就直接换人，而是会在“当前已选集合 x 剩余候选池”的组合里，找一组能让整体 gap 指标更优的替换动作。
- `probability_gap` 修复不会接受“虽然断层更平滑，但把冲稳保目标配额搞坏”的替换；也就是说 gap 修复必须满足 `tierDeviationAfter <= tierDeviationBefore`。

当前 summary 中已经会沉淀：

- `localProtectCount`
- `gapFixCount`
- `unresolvedGapCount`
- `unitCompletionCount`
- `appliedRepairCount`
- `unresolvedRuleCodes`

这些字段表示的是“系统在初始推荐组建阶段实际做过什么修复，以及还有哪些规则没有彻底修平”。

### 9.1.5.0.1 2026-05-10 生产观察与当前问题

结合 3.0.0 上线过程中新建会话 `2075 / 2076` 的生产状态检查，当前算法的真实语义需要按下面口径理解：

1. 初始推荐生成会主动尝试修复 `probability_gap`，但它不是硬性保证。
2. 断层判断口径仍是旧规则：按最终方案集合的 `admissionRatio asc` 排序，相邻录取率差值 `> 8` 即命中 `probability_gap`。
3. 修复时会从剩余候选中寻找落在断层区间内的候选，通过替换让整体 gap 指标变好。
4. 替换动作必须同时满足 `tierDeviationAfter <= tierDeviationBefore`，也就是不能为了抹平断层明显破坏冲稳保配额。
5. 若候选池里没有合适替换，系统会保留当前方案，同时在 `initialRecommendationState.summary` 中记录 `unresolvedGapCount`，并把 `probability_gap` 写入 `unresolvedRuleCodes`。

本次生产观察结果：

- 会话 `2075`：`major` 模式，排序区 `96` 个专业条目，冲/稳/保为 `28 / 28 / 40`，未发现相邻录取率差值 `> 8` 的断层；`initialRecommendationState.summary.unresolvedRuleCodes=[]`。
- 会话 `2076`：`majorGroup` 模式，排序区 `30` 个专业组、`64` 个专业条目，冲/稳/保为 `9 / 9 / 12`；初始生成已执行 `gapFixCount=3`，但仍剩余 `unresolvedGapCount=2`，`unresolvedRuleCodes=['probability_gap']`。
- 会话 `2076` 中仍存在两个断层：`10.0 -> 26.0`，差值 `16.0`；`38.0 -> 52.0`，差值 `14.0`。因此线上看到相邻志愿录取率差值超过 `8`，在当前实现下属于“已尽力修复但仍未完全解决”的状态，不代表新建会话又走回了老方案导入逻辑。

当前存在的问题：

- 产品理解上容易把 `probability_gap` 理解成硬约束，但当前实现是 best-effort 修复。只要候选池和冲稳保配额共同限制导致无法替换，系统仍会返回可用方案。
- `orderedPlanState.summary.gradientOk` 的语义偏窄，目前更接近“顺序/倒挂检查结果”，没有完整覆盖 `probability_gap`。因此可能出现 `gradientOk=true`，但 `reviewState.checks.probability_gap.passed=false` 的不一致展示。
- `majorGroup` 模式下 review 详情当前更偏向展示首个断层样例，summary 才记录剩余断层数量；如果前端只展示简短审查文案，用户会低估断层范围。
- 如果前端只读取排序区 summary，不展示 `initialRecommendationState.summary.unresolvedRuleCodes` 或 `reviewState.checks.probability_gap`，就会让用户误以为方案梯度已经完全通过。

后续建议按优先级处理：

1. 重新定义 `gradientOk`：要么纳入 `probability_gap`，要么改名为更准确的 `sequenceOk`，避免与审查结论冲突。
2. 前端方案页应优先展示 `reviewState.checks.probability_gap` 的结果；当 `unresolvedGapCount > 0` 时，用用户能理解的文案提示“部分相邻志愿录取率跨度较大，建议人工确认或继续调整”。
3. 如果产品要求“初始方案必须无 `> 8` 断层”，生成阶段需要升级为硬约束：扩大候选替换窗口、允许跨 tier 小幅借位、或在无法满足时返回“需要人工确认”的结构化状态，而不是静默返回。
4. 增加 `2076` 类似的 `majorGroup` 回归样本，覆盖“已执行 gap 修复但仍有 unresolved gap”的场景，防止后续把 best-effort 状态误判为通过。

#### A. `count_validation`

目标：

- 最终数量必须与目标数量一致

修复方式：

- 若不足：
  - 从剩余候选里继续补
  - 优先补当前缺口最大的 tier
- 若超出：
  - 移除边际价值最低的条目

这里的“边际价值最低”不应只看低分，还要同时考虑：

- 是否破坏 tier 目标
- 是否破坏本省保底
- 是否扩大梯度断层
- 是否破坏组内数量

#### B. `safety_guard`

目标：

- 当 `userScore < 580` 时，保区至少有 `2` 个本省志愿

修复方式：

- 在剩余候选里查找本省保区候选
- 优先替换当前保区内非本省且边际价值较低的项
- 若无法补足，则在 `summary` 中显式记录该风险仍未被修复

这条规则在第一版中应视作高优先级硬修复。

#### C. `unit_major_count_validation`

目标：

- 在 `majorGroup` / 组内填报模式下，每个单元满足要求的专业数量

修复方式：

- 先按组或院校单元聚合当前已选项
- 若某单元数量不足：
  - 优先从同单元剩余候选中补专业
- 若同单元无法补满：
  - 该单元不适合作为初始推荐主单元
  - 需考虑整体降级或替换为完整度更高的单元

这意味着在 `majorGroup` 模式下，组建单位不能只看“单个专业分高不高”，还要看“整个组是否可合法成型”。

#### D. `probability_gap`

目标：

- 相邻录取率差值尽量不超过 `8`

修复方式：

1. 将当前集合按 `admissionRatio asc` 排序
2. 检查相邻差值是否 `> 8`
3. 若命中断层：
   - 在剩余候选里寻找落在 gap 区间内的候选
   - 优先选择既能填补 gap、又不破坏 tier 目标和安全性的候选
   - 通过“插入 + 淘汰边际最低项”的方式修复
4. 若无法修复：
   - 在 `summary` 中记录未修复 gap

第一版先兼容旧规则阈值，不引入多轴 gap 模型。

#### E. `probability_inversion`

目标：

- 最终按“冲 -> 稳 -> 保”展示时，不出现前一位录取率高于后一位的明显倒挂

当前实现方式：

1. 先按最终展示顺序对当前已选集合排序
2. 找出相邻的倒挂对：
   - `previous.admissionRatio > current.admissionRatio`
3. 优先尝试同 tier 替换：
   - 若倒挂发生在前一条，则用同 tier 且录取率更低的剩余候选替换前一条
   - 若倒挂发生在后一条，则用同 tier 且录取率更高的剩余候选替换后一条
4. 只接受能让整体倒挂数量或最大倒挂幅度下降的替换
5. 若没有合适候选，则保留：
   - `unresolvedRuleCodes += probability_inversion`

这样做的原因是：

- 倒挂规则本质是顺序结构问题
- 但初始推荐仍需要优先维持 `requiredTierCounts` 形成的冲稳保骨架
- 因此第一版不做跨 tier 借位修倒挂，而是先用同 tier 局部替换收敛最明显的问题

### 9.1.5.0.1 示例 A：本省保底修复

假设粗组装后目标结构是：

- `1冲 1稳 3保`

用户条件：

- 北京考生
- `totalScore = 560`

粗组装结果：

- 冲：北京院校 A
- 稳：天津院校 B
- 保：河北院校 C
- 保：河南院校 D
- 保：北京院校 E

此时保区只有 `1` 个本省志愿，不满足：

- `userScore < 580` 时，保区至少 `2` 个本省志愿

若剩余候选里还有：

- 保：北京院校 F

那么修复动作会是：

1. 识别当前 `localProtectCount = 1`
2. 从 `remaining` 中找“保区 + 本省”候选
3. 优先替换当前保区里“非本省”的边际低价值项
4. 结果变为：
   - 冲：北京院校 A
   - 稳：天津院校 B
   - 保：河北院校 C
   - 保：北京院校 E
   - 保：北京院校 F

此时：

- `localProtectCount = 2`
- `unresolvedRuleCodes` 不包含 `safety_guard`

### 9.1.5.0.2 示例 B：概率断层完全修复

假设目标结构是：

- `2冲 2稳 0保`

粗组装后按录取率排序为：

- `10`
- `18`
- `42`
- `48`

剩余候选池里还有：

- `26`
- `34`

这时存在两个大断层：

- `18 -> 42`
- `26/34` 都能落在中间区间

当前实现不会简单地“拿第一个中间值来替换一个最低分条目”，而是会枚举：

- 哪个 `filler` 进入
- 哪个 `removable` 被换出
- 换完后整体还剩几个 gap
- 最大 gap 是否变小
- 是否打坏 `2冲 2稳 0保`

最终更优结果可能是：

- `10`
- `18`
- `26`
- `34`

此时：

- `gapFixCount >= 2`
- `unresolvedGapCount = 0`
- `unresolvedRuleCodes` 不包含 `probability_gap`

### 9.1.5.0.3 示例 C：概率断层部分修复但保留未解决标记

假设粗组装后为：

- `10`
- `20`
- `50`
- `58`

剩余候选池里只有：

- `28`
- `36`

系统会优先修掉最大的可修断层：

- 把 `50/58` 侧的极端值替换为 `28/36`

可能得到：

- `10`
- `20`
- `28`
- `36`

这时大断层已经显著收敛，但仍然存在：

- `10 -> 20` 的小断层

而剩余候选里已经没有更合适的中间值，所以系统不会继续做无效替换，而是落下：

- `gapFixCount >= 1`
- `unresolvedGapCount = 1`
- `unresolvedRuleCodes += probability_gap`

这表示：

- 系统已经尽力修复主要断层
- 但候选窗口不足，当前组合仍有剩余梯度问题

### 9.1.5.1 修复优先级

第一版建议固定修复顺序，不做动态权重调度：

1. `count_validation`
2. `safety_guard`
3. `unit_major_count_validation`
4. `probability_inversion`
5. `probability_gap`

说明：

- `ratio_distribution` 在初始粗组装阶段已经通过 `requiredTierCounts` 尽量前置满足
- 因此修复阶段无需把它作为独立高频替换规则
- 若前面几步修复导致 tier 计数被破坏，再在末尾做一次轻量回平衡

### 9.1.5.2 局部替换原则

第一版所有修复都建议遵循“局部替换，不整体推翻”的原则。

建议约束：

- 单次修复优先只替换 `1~2` 个条目
- 修复后立即重新计算：
  - `currentTierCounts`
  - `localProtectCount`
  - `unitStats`
  - `gaps`
- 若一次修复引入更大副作用，则回滚本次修复，尝试次优候选

这样可以避免：

- 为了修一个断层，把本省保底打坏
- 为了补一个组内数量，把整个 tier 结构打散

### 9.1.5.3 gap 修复的候选筛选规则

在 `probability_gap` 修复中，候选筛选建议分三步：

1. 区间过滤
   - `admissionRatio` 必须落在 gap 两端之间
2. 合法性过滤
   - 插入后不能导致 `safety_guard` 从满足变不满足
   - 插入后不能使 `unit_major_count_validation` 更差
3. 排序选择
   - 与 gap 中点距离更近优先
   - `effectiveScore` 更高优先
   - `preferred=true` 优先

对应淘汰对象的选择则反向执行边际淘汰排序。

### 9.1.5.4 轻量回平衡

完成所有硬修复后，建议最后统一做一次回平衡校验：

- 总数是否正确
- 各 tier 数量是否仍等于目标数
- 本省保区数量是否仍满足
- 单元数量是否合法

若其中任一被破坏，则只允许做一次轻量回平衡：

- 优先在同 tier 内做替换
- 其次才跨 tier 调整

### 9.1.5.5 结构修复伪代码

```text
repair count first
repair safety_guard
repair unit_major_count_validation

loop:
  detect probability gaps
  if no gap:
    break
  try fill the highest-priority gap
  if no feasible repair candidate:
    mark unresolved and continue

recheck total/tier/localProtect/unitStats
do one final rebalance if needed
emit final selection + repair logs + unresolved rules
```

### 9.1.6 推荐结果输出约定

最终写入 `initialRecommendationState` 的，不应再只是“旧 `preferred=true` 的透传结果”，而应是：

- 经过粗组装
- 再经过结构修复
- 最终被纳入系统初始推荐集合

建议 `summary` 第一版补充以下结构化信息：

- `total`
- `expertPreferredCount`
- `tierCounts`
- `localProtectCount`
- `gapFixCount`
- `unresolvedGapCount`
- `unitCompletionCount`
- `unresolvedRuleCodes`

这样 frontend / agent 后续才能解释：

- 当前初始推荐为什么这样选
- 系统在组建阶段修过哪些结构问题
- 哪些规则已经满足
- 哪些风险仍然存在但暂时无法修复

### 9.1.6.1 建议新增的解释字段

若后续允许扩展 DTO，建议 `summary` 或附属元信息第一版补充：

- `appliedRepairCount`
- `appliedRepairTypes`
- `tierBorrowStats`
- `generationMode`
  - `score_only`
  - `score_plus_repair`

这样可以区分：

- 只是按分数粗选出来的结果
- 已经经过结构修复的结果

### 9.1.6.2 候选项级别的解释约定

对于最终入选的每个条目，建议后续允许附加轻量原因码：

- `selected_by_tier_target`
- `selected_by_local_protect`
- `selected_by_gap_fill`
- `selected_by_unit_completion`

这些原因码不一定第一版就对外暴露，但建议在内部先保留，便于后续解释和调试。

### 9.1.7 第一版实现边界

第一版建议只做“启发式可控解”，不直接上全局最优化求解器。

原因：

- 当前规则已足够形成稳定的局部修复闭环
- 更容易与旧推荐结果做 A/B 比较
- 更方便逐步接入强诉求折中逻辑

实现边界建议为：

- 保留现有 `recommendationOverlayState`
- 保留现有 `preferred` 作为粗选信号
- 新增一个独立的“初始推荐组建器”
- `buildInitialRecommendationState(...)` 改为调用组建器，而不是直接筛 `preferred=true`

第一版不做的内容：

- 强诉求折中求解
- 多目标全局最优
- review 全规则全部前置
- 跨多轮偏好变化的历史权重记忆

### 9.1.8 第一版验证口径

至少补以下几类验证：

- 数量刚好时直接生成
- 某个 tier 候选不足时的借位行为
- 分数低于 `580` 且保区本省不足 `2` 个时的安全修复
- 存在明显 `>8` 断层时的 gap 修复
  - 需要同时覆盖“可完全修复”和“候选窗口不足只能部分修复”两类用例
- `majorGroup` 模式下组内数量不足时的补组或换组
- “高分但结构差”与“略低分但结构完整”之间的取舍

建议测试分层：

#### A. 纯组建单测

- 不依赖 controller / persistence
- 直接验证粗组装和修复动作

#### B. planning service 单测

- 验证 `buildInitialRecommendationState(...)` 的输入输出
- 验证 stale flag 和版本回写

#### C. 回归对比测试

- 对比“旧 preferred 透传”与“新组建算法”结果差异
- 重点看：
  - 数量
  - tier 分布
  - 本省保底数
  - gap 数量
  - 组内合法性

### 9.2 调整式方案生成

在 `sessionDetailV2` 当前阶段，调整式方案生成默认遵循：

- 先分析
- 再出建议
- 用户确认后再应用

若当前草稿数量不足，也应优先给出“补充建议候选”，而不是静默补入草稿。

对于 `majorGroup` 模式，还应补充一条结构性约定：

- `planAdjustment/analyze` 与后续 `apply` 不能继续直接以扁平专业条目作为唯一操作单位
- 否则会把“换一个专业”误当成“换一个专业组志愿”，直接破坏组层结构

因此 `majorGroup` 模式下，调整式方案生成必须拆成两层：

#### 9.2.1 组层调整

先处理专业组这一层的动作：

- `add`
  - 新增一个专业组志愿
- `replace`
  - 换出一个专业组，换入另一个专业组
- `reorder`
  - 调整专业组在整张方案中的先后顺序

这层优先承接：

- `count_validation`
- `ratio_distribution`
- `probability_inversion`
- `probability_gap`
- `safety_guard`

#### 9.2.2 组内调整

组选定后，再处理组内专业：

- 补专业
- 换组内专业
- 调整主选 / 备选专业归属

这层优先承接：

- `unit_major_count_validation`
- `group_inner_safety_guard`

也就是说：

- `majorGroup` 模式下的 `planAdjustment` 必须与初始方案生成保持同样的“双层编排”语义
- 不能出现“初始化方案按组生成，但一进入调整就退化成按专业条目平铺操作”的情况

## 10. `planAdjustmentState.analysis` 的两层规则口径

V2 不应直接用“新生成算法规则”覆盖现有审查规则，而应拆成两层：

### 10.1 现有审查兼容规则

这层规则优先复用当前已有的 review / risk management 口径，保证：

- 旧规则不漂移
- 已有话术和用户心智不被打乱
- 新的调整式方案生成能够复用现有风险定义

当前应优先兼容：

- `ratio_distribution`
- `safety_guard`
- `probability_inversion`
- `probability_gap`
- `count_validation`
- `unit_major_count_validation`
- `group_inner_safety_guard`

当前 backend 第一版 `planAdjustment/analyze` 的实现约定：

- 先桥接 `count_validation / unit_major_count_validation / ratio_distribution / probability_inversion / probability_gap / safety_guard`
- `majorGroup` 模式下，上述结构规则先在“组层快照”上执行，再补做 `unit_major_count_validation / group_inner_safety_guard`
- 规则判断直接复用既有 `review*` 方法，避免新链路和旧审查口径漂移
- 可直接转成补充候选的规则，优先复用现有 compensation 结果映射到 `planAdjustmentState.suggestions`
- `probability_inversion` 当前已补入第一版建议映射：默认产出局部 `reorderSuggestion`；若同 tier 内存在可替补候选，还会补充第一版 `replaceSuggestion`，用于提示“换掉倒挂边界项后再维持区间骨架”
- `probability_gap` 当前除了补充型 `addSuggestion` 外，也会产出第一版 `replaceSuggestion`，用于提示“拿哪个中间梯度候选替掉当前断层边界项”
- `ratio_distribution` 当前在“冲区占比过高”场景下，已补入第一版 `replaceSuggestion`，用于提示“换出部分冲区条目并补入保区候选”；若只是区间缺口，则仍以 `addSuggestion` 为主
- `group_inner_safety_guard` 当前先产出 `addSuggestion`，提示补入组内安全垫专业；`apply` 仍未自动执行
- 其余只产出分析结论、不强行生成不稳定的替换/删除建议，后续再补强

当前 `review` 全量规则与 `planAdjustment/analyze` 的覆盖边界如下：

- 已进入 `planAdjustment/analyze`
  - `count_validation`
  - `unit_major_count_validation`
  - `group_inner_safety_guard`
  - `ratio_distribution`
  - `probability_inversion`
  - `probability_gap`
  - `safety_guard`
- 暂未进入 `planAdjustment/analyze`
  - `high_tuition`
  - `admission_limit`
  - `special_enrollment`
  - `edge_score`
  - `cooperative_program`

这 5 条规则当前仍保留在 `reviewState`，未进入 `planAdjustment/analyze` 的原因：

- 它们更偏“提示确认”而非“自动编排”
- 命中后通常需要用户补充真实偏好或硬约束，不能仅靠 backend 稳定地产生单一最优替换动作
- 若直接生成 `replace/remove`，容易把“风险提示”误做成“系统替用户改方案”

因此当前约定是：

- `planAdjustment/analyze` 先承接“可直接编排”的结构规则
- `reviewState` 继续承接“需要用户确认”的提示规则
- 后续若要把上述 5 条规则接入 `planAdjustment`，应优先走“提示 + 可选筛选/排除动作”模式，而不是直接生成强替换建议

### 10.2 方案生成增强规则

这层规则用于支撑“初始方案生成”和“调整式建议生成”的更细粒度算法约束。

它们可以参考但不应直接替代现有审查口径，例如：

- `tier_target_deviation`
- 更细的 gap 多轴判断
- `constraint_conflict`
- `preference_deviation`

原则：

- 审查层先兼容旧规则
- 生成层再做增强
- 前者优先保证口径稳定，后者优先保证方案质量

## 11. 第一批最小规则集

V2 第一批不追求把所有 review 规则都迁入“调整式方案生成”，而是先收敛出一组能够稳定形成建议闭环的最小规则集。

建议第一批按以下 5 类落地，但需要注意：其中前 3 类要优先兼容旧审查口径。

### 11.1 `count_validation`

含义：

- 当前草稿或排序数量不足，尚未达到目标方案数量

依赖字段：

- `draftPlanState.summary.total`
- `orderedPlanState.summary.total`
- `orderedPlanState.summary.targetCount`
- `candidatePoolState.requiredCount`

命中条件建议：

- 若存在排序结果，则优先比较 `orderedPlanState.summary.total < orderedPlanState.summary.targetCount`
- 若尚无排序结果，则比较 `draftPlanState.summary.total < candidatePoolState.requiredCount`

建议动作类型：

- `add`

建议输出模板：

- `summary`
  - 当前方案数量不足，建议补充若干符合当前偏好与约束的志愿
- `affectedVolunteerIds`
  - 允许为空
- `suggestionTypes`
  - `add`

适用模式：

- `major`
- `majorGroup`

补充说明：

- 这里应优先对齐当前“数量校验”规则，不建议继续只保留泛化的 `insufficient_count`
- 对总数不足、总数过多都可命中

### 11.2 `unit_major_count_validation`

含义：

- 组内 / 院校内所选专业数不符合当前省份要求

依赖字段：

- 志愿模式
- 当前省份规则
- 每个院校 / 专业组下要求填报的专业数量
- 用户当前已选专业数量

命中条件建议：

- `major`
  - 总体专业数不等于省份要求数量时命中
- `majorGroup`
  - 任一专业组下所选专业数不等于该省要求数量时命中
- `school`
  - 任一院校下所选专业数不等于该省要求数量时命中

建议动作类型：

- `add`
- `remove`

适用模式：

- `major`
- `majorGroup`
- `school`

### 11.3 `ratio_distribution`

含义：

- 当前方案中冲稳保分布明显失衡
- 这一条应优先兼容现有 review / risk_management 口径，而不是先用泛化目标偏差替代

依赖字段：

- 当前草稿或排序内各 `tier` 占比

命中条件建议：

- 先按当前既定规则实现：
  - `冲 > 40%`
  - `冲 < 20%`
  - `保 < 20%`
  - `冲 > 40% 且 保 < 20%`
  - `冲 < 20% 且 保 < 20%`

建议动作类型：

- `add`
- `reorder`

生成阶段补充约束：

- 初始推荐在做 `probability_gap` 修复时，应优先选择“不恶化冲稳保目标配额”的替换动作
- 若存在可修复断层，则先消减最大且可填补的 gap
- 若候选窗口不足以完全抹平断层，则保留 `unresolvedRuleCodes += probability_gap`，并记录剩余未解决 gap 数量
- `replace`

建议输出模板：

- `summary`
  - 当前方案的冲稳保结构不均衡，建议补充或替换对应区间志愿，并调整区间内顺序
- `affectedVolunteerIds`
  - 当前失衡区间内的条目
- `suggestionTypes`
  - `add/reorder/replace`

适用模式：

- `major`
- `majorGroup`

补充说明：

- 若后续要引入 `requiredTierCounts` 驱动的目标偏差规则，建议单独命名为 `tier_target_deviation`
- 不要直接混入 `ratio_distribution`

### 11.4 `probability_gap`

含义：

- 相邻志愿之间存在明显的录取概率或区间梯度断层

依赖字段：

- `orderedPlanState.items`
- 录取概率字段

命中条件建议：

- 先按现有 risk management 规则兼容：
  - 将志愿表按录取概率从小到大排序
  - 检测相邻两项差值是否 `> 8%`
  - 若 `> 8%` 则命中

建议动作类型：

- `add`
- `reorder`

建议输出模板：

- `summary`
  - 当前方案存在梯度断层，建议插入中间梯度候选或调整相邻顺序
- `affectedVolunteerIds`
  - 命中断层的相邻条目
- `suggestionTypes`
  - `add/reorder`

适用模式：

- `major`
- `majorGroup`

补充说明：

- 这是第一批中最值得从算法层提前规避的规则之一
- 但第一版应先兼容既有 `8%` 阈值口径
- 多轴 gap 判断可在后续作为增强规则补入

### 11.5 `constraint_conflict`

含义：

- 当前草稿或排序中存在与用户已确认硬约束冲突的志愿

依赖字段：

- `profileState`
- `constraintState`
- `candidateViewState`
- 排序项或草稿项对应的地域、院校、专业、招生类型、限报标签

命中条件建议：

- 志愿命中已确认的排除省份 / 城市 / 院校 / 专业 / 招生类型 / 限报约束

建议动作类型：

- `remove`
- `replace`

建议输出模板：

- `summary`
  - 当前方案中存在与已确认报考约束冲突的志愿，建议移除或替换
- `affectedVolunteerIds`
  - 必填
- `suggestionTypes`
  - `remove/replace`

适用模式：

- `major`
- `majorGroup`

### 11.6 `preference_deviation`

含义：

- 当前方案虽然不违反硬约束，但与用户当前软意向明显背离

依赖字段：

- `profileState`
- `recommendationOverlayState`
- 志愿的地域、院校、专业、标签与推荐分

命中条件建议：

- 某些条目长期不命中当前偏好方向
- 且其推荐分明显低于同区间其他可替代项

建议动作类型：

- `replace`
- `reorder`

建议输出模板：

- `summary`
  - 当前方案中有部分志愿与最近确认的偏好不够贴合，建议替换或后移
- `affectedVolunteerIds`
  - 偏离项
- `suggestionTypes`
  - `replace/reorder`

适用模式：

- `major`
- `majorGroup`

## 12. 第一批规则的统一输出结构

建议每条分析规则统一输出为：

- `ruleCode`
- `severity`
- `hit`
- `summary`
- `affectedVolunteerIds`
- `suggestionTypes`

示意：

```json
{
  "ruleCode": "probability_gap",
  "severity": "warning",
  "hit": true,
  "summary": "当前稳区和保区之间存在明显梯度断层，建议补入 2 个中间梯度志愿。",
  "affectedVolunteerIds": ["ps2_m2", "ps3_m3"],
  "suggestionTypes": ["add", "reorder"]
}
```

其中 `severity` 第一批建议先只用三档：

- `info`
- `warning`
- `error`

## 13. 第一批实现优先级

建议实现顺序：

1. `count_validation`
2. `unit_major_count_validation`
3. `probability_gap`
4. `ratio_distribution`
5. `constraint_conflict`
6. `preference_deviation`

原因：

- 前四类都已有较明确的旧规则基线，更适合先兼容再接到调整式链路
- `constraint_conflict` 和 `preference_deviation` 需要更多画像、推荐语义与标签映射参与，适合放在第一批后半段接入

## 14. `planAdjustmentState.suggestions` 建议对象结构

分析规则命中后，backend 不能只返回一句描述性结论，还需要产出可被前端展示、agent 解读、后续应用接口消费的结构化建议对象。

第一阶段建议统一拆成四类：

- `add`
- `reorder`
- `replace`
- `remove`

## 14.1 通用字段

无论哪类建议，建议统一具备以下字段：

- `id`
- `type`
- `ruleCode`
- `title`
- `description`
- `severity`
- `target`
- `affectedVolunteerIds`
- `reasonCodes`

字段说明：

- `id`
  - 建议项唯一标识，供后续 `apply` 接口引用
- `type`
  - `add / reorder / replace / remove`
- `ruleCode`
  - 对应分析命中的规则
- `title`
  - 前端简短展示标题
- `description`
  - 面向用户的解释性文案
- `severity`
  - `info / warning / error`
- `target`
  - `draft` 或 `ordered`
- `affectedVolunteerIds`
  - 当前方案中受影响的条目
- `reasonCodes`
  - 供前端和 agent 做精简解释的原因枚举

## 14.2 `addSuggestions`

适用场景：

- 数量不足
- 冲稳保某区间明显不足
- 梯度断层需要插入中间候选

建议字段：

- 通用字段
- `candidateVolunteerIds`
- `candidateSummaries`
- `insertAfterVolunteerId`
- `preferredApplyMode`

字段说明：

- `candidateVolunteerIds`
  - 建议补入的候选志愿 ID 列表
- `candidateSummaries`
  - 轻量展示信息，避免前端必须再次查整表才知道建议补谁
- `insertAfterVolunteerId`
  - 若是补位型建议，可给出默认插入位置参考
- `preferredApplyMode`
  - 建议默认应用模式
  - 第一批建议值：
    - `append_only`
    - `replace_and_reorder`

`candidateSummaries` 建议最少包含：

- `volunteerId`
- `schoolName`
- `majorName`
- `tier`
- `admissionRatio`
- `finalScore`

## 14.3 `reorderSuggestions`

适用场景：

- 梯度断层
- 冲稳保区间内部顺序不合理
- 与推荐优先级明显背离，但不需要换条目

建议字段：

- 通用字段
- `fromPositions`
- `toPositions`
- `orderedVolunteerIds`
- `preferredApplyMode`

字段说明：

- `fromPositions`
  - 原位置列表
- `toPositions`
  - 建议位置列表
- `orderedVolunteerIds`
  - 应用后建议顺序
- `preferredApplyMode`
  - 第一批固定为 `reorder_only`

补充约定：

- 若用户已有 `pinned` 项，生成 `orderedVolunteerIds` 时不得跨越固定边界
- 若用户已有显式手调，建议中需要尽量只调整命中问题的局部区间

## 14.4 `replaceSuggestions`

适用场景：

- 与硬约束冲突
- 与软意向明显背离
- 某区间存在更优替代项

建议字段：

- 通用字段
- `removeVolunteerIds`
- `candidateVolunteerIds`
- `replacementPairs`
- `preferredApplyMode`

字段说明：

- `removeVolunteerIds`
  - 建议移出的当前方案条目
- `candidateVolunteerIds`
  - 建议换入的候选条目
- `replacementPairs`
  - 一一对应的替换建议
- `preferredApplyMode`
  - 第一批建议值：
    - `replace_and_reorder`

`replacementPairs` 建议结构：

- `fromVolunteerId`
- `toVolunteerId`
- `reasonCodes`

## 14.5 `removeSuggestions`

适用场景：

- 当前方案中存在明确不应保留的冲突项
- 该条目应直接移出，但暂不自动补替代项

建议字段：

- 通用字段
- `removeVolunteerIds`
- `preferredApplyMode`

字段说明：

- `removeVolunteerIds`
  - 建议移除的条目
- `preferredApplyMode`
  - 第一批建议值：
    - `replace_and_reorder`
    - 若无补位则可退化为 `reorder_only`

## 15. `applyMode` 第一批约定

为避免第一阶段应用接口过于复杂，建议只支持三类应用模式：

- `reorder_only`
- `append_only`
- `replace_and_reorder`

语义如下：

### 15.1 `reorder_only`

- 只调整当前排序
- 不补新志愿
- 不替换现有志愿

### 15.2 `append_only`

- 只把建议候选补入草稿或排序尾部
- 不主动替换现有条目
- 适合数量不足场景

### 15.3 `replace_and_reorder`

- 允许移除、替换和局部重排
- 适合硬约束冲突、偏好偏离、结构修复场景

## 16. 建议对象的前端展示边界

为避免建议对象再次退化成“只是一段提示文案”，建议前端至少区分以下两层：

### 16.1 建议摘要层

面向排序区顶部或建议卡片列表展示：

- `title`
- `description`
- `severity`
- `type`

### 16.2 建议详情层

面向用户展开查看时展示：

- 命中的规则
- 受影响条目
- 建议补入 / 替换 / 调整的目标条目
- 应用后的预期动作

## 17. 建议对象与 agent 的边界

Agent 在这一层不负责自行构造建议对象，只负责：

- 识别用户是否在请求“分析方案”
- 调 backend 生成 `planAdjustmentState`
- 将 backend 返回的建议对象转为：
  - 左侧解释
  - 右侧排序区联动
  - 用户确认后的应用动作

也就是说：

- 建议对象的事实来源在 backend
- agent 只消费，不自行发明新的建议结构

## 18. 生成增强规则的补充说明

在兼容旧审查规则之后，后续仍可以补充更偏“生成优化”的增强规则，但建议与旧规则分名管理。

例如：

- `tier_target_deviation`
- `probability_gap_multi_axis`

### 18.1 `tier_target_deviation`

### A. 目标

识别当前方案在冲稳保目标数上是否偏离系统建议结构，用于辅助生成更优方案，而不是替代旧 `ratio_distribution` 规则。

### B. 统计对象

第一批建议优先按以下顺序取统计对象：

1. 若存在 `orderedPlanState.items`
   - 优先按排序结果统计
2. 若尚无排序结果但存在 `draftPlanState.items`
   - 按草稿结果统计
3. 否则
   - 不命中本规则

### C. 目标值来源

按以下优先级确定目标数量：

1. `candidatePoolState.requiredTierCounts`
2. 若缺失，则退化使用：
   - `candidatePoolState.requiredCount`
   - 结合当前策略型换算冲稳保目标

### D. 实际值定义

记：

- `targetSprint`
- `targetSafe`
- `targetProtect`
- `actualSprint`
- `actualSafe`
- `actualProtect`

每个值都表示对应 tier 的数量。

### E. 单区间偏差值

定义每个区间的偏差：

- `deltaSprint = actualSprint - targetSprint`
- `deltaSafe = actualSafe - targetSafe`
- `deltaProtect = actualProtect - targetProtect`

绝对偏差：

- `absDeltaTier = abs(actualTier - targetTier)`

相对偏差：

- `ratioDeltaTier = absDeltaTier / max(targetTier, 1)`

### F. 命中条件

第一批建议使用双阈值判定，命中任一即视为失衡：

1. 绝对偏差阈值
   - `absDeltaTier >= 2`
2. 相对偏差阈值
   - `ratioDeltaTier >= 0.3`

也就是：

- 目标 10 个，实际少 3 个，命中
- 目标 4 个，实际少 1 个，不命中
- 目标 4 个，实际少 2 个，命中

### G. 严重程度建议

- `warning`
  - 仅 1 个 tier 命中阈值
- `error`
  - 2 个及以上 tier 同时命中阈值
  - 或 `protect` 明显不足

其中对 `protect` 区间做一条额外收紧：

- 若 `actualProtect < targetProtect - 1`
  - 即使其他区间未命中，也建议至少记为 `warning`

### H. 输出建议方向

- 若某区间数量不足
  - 优先给 `add`
- 若某区间数量过多且另一侧不足
  - 给 `replace`
- 若总量足够但局部排序与 tier 呈现不合理
  - 可附加 `reorder`

### I. `major` / `majorGroup` 适配

第一批先统一口径：

- `major`
  - 直接按志愿条目统计
- `majorGroup`
  - 仍按“院校专业组志愿条目”统计

也就是说：

- 不按组内专业数做 tier_imbalance
- 组内专业数量约束继续留给其他规则处理

### 18.2 `probability_gap_multi_axis`

### A. 目标

在兼容旧 `probability_gap` 的基础上，进一步用多轴信息辅助发现结构性断层。

### B. 判定对象

第一批仅对“当前最终呈现顺序”做判断：

1. 若存在 `orderedPlanState.items`
   - 只看排序结果
2. 若无排序结果
   - 本规则默认不命中

原因：

- 梯度断层本质上是顺序结构问题
- 草稿未排序时，先不强行判断 gap

### C. 主轴选择

第一批建议采用“单主轴 + 多辅助轴”的方式，避免一开始过于复杂。

主轴：

- 普通使用 `schoolEnrollRatio`

辅助轴：

- `admissionRatio`
- `rankInTier`
- `finalScore`

选择理由：

- 当前工作台院校/专业组层主要使用 `schoolEnrollRatio`
- 这一主轴和前端候选、排序展示语义更一致
- `admissionRatio` 与 `rankInTier` 可作为兜底与辅助判断

### D. 基础排序值

对排序项定义主排序值：

- `mainProbabilityValue = schoolEnrollRatio`

若为空，则回退：

1. `admissionRatio`
2. 若仍为空，则回退 `rankInTier`
3. 若仍为空，则该条目不参与 `probability_gap` 判断

### E. 同 tier 内部断层判定

对同一 tier 内相邻两项 `A -> B`：

- `gap = abs(mainProbabilityValue(A) - mainProbabilityValue(B))`

第一批建议阈值：

- 若 `gap >= 12`
  - 判定为同 tier 断层

补充辅助条件：

- 若 `gap >= 8` 且 `rankInTier` 差值明显过大
  - 也可命中

其中“明显过大”建议先定义为：

- `abs(rankInTier(A) - rankInTier(B)) >= 15`

### F. 跨 tier 断层判定

第一批建议只看两类跨 tier 边界：

1. `冲 -> 稳`
2. `稳 -> 保`

但阈值与同 tier 分开。

对边界相邻两项：

- `boundaryGap = abs(mainProbabilityValue(A) - mainProbabilityValue(B))`

第一批建议阈值：

- 若 `boundaryGap >= 18`
  - 判定为跨 tier 断层

原因：

- 跨 tier 本就允许存在更大的梯度
- 但若断层过大，说明中间带候选缺失，应优先补位

### G. 严重程度建议

- `warning`
  - 仅 1 处断层
- `error`
  - 2 处及以上断层
  - 或 `稳 -> 保` 边界出现超大断层

其中“超大断层”第一批建议定义为：

- `boundaryGap >= 25`

### H. 输出建议方向

- 同 tier 内部断层
  - 优先给 `reorder`
  - 若缺明显中间带，则给 `add`
- 跨 tier 断层
  - 优先给 `add`
  - 必要时附加 `reorder`

### I. `major` / `majorGroup` 适配

第一批先统一规则，不分模式：

- `major`
  - 直接使用条目级主轴值
- `majorGroup`
  - 仍按院校专业组这一条志愿的主轴值判断

也就是说：

- 暂不把组内专业展开后再做断层判断
- 组内专业内部排序或数量不足，不纳入本规则

### 18.3 第一批的保守实现策略

为降低误报，第一批建议遵循：

- `tier_imbalance`
  - 宁可保守少报，也不轻易把轻微偏差认定为结构失衡
- `probability_gap`
  - 宁可先只识别明显断层，也不把正常梯度误判成问题

实现建议：

- 所有阈值先落常量配置
- 后续结合联调样本再调优
- 不要第一版就做动态学习或策略型分组阈值

- 当前草稿集合
- 用户是否已有手排
- 是否有 pinned
- 是否允许系统补位

### 输出

- 建议排序结果
- 必要时附带“建议补充哪些志愿”

### 子场景

#### B1. 用户仅选草稿，未手排

允许系统整体重编：

- 直接对现有草稿生成建议排序
- 若草稿本身结构不足，可给出补位建议

#### B2. 用户部分手排

系统应保留用户显式形成的相对顺序，只对未干预区块重编。

#### B3. 用户已固定部分位置

将 pinned 视为硬边界：

- 固定位置不动
- 剩余槽位局部优化

### 关键结论

这类场景里，“是否补位”应是可控策略，而不是默认强插。

建议拆为两种模式：

- `reorder_only`
  - 只重排现有草稿
- `reorder_and_complete`
  - 允许从候选池补位

## 6. 梯度断层是否应前移到算法层

结论：应前移，但只能做到“尽量规避”，不能保证完全消失。

原因：

- 若草稿或候选工作集本身缺少中间概率带候选，单靠重排无法消除 gap
- 因此需要将梯度优化分成两层：

### 6.1 局部重排

目标：

- 不倒挂
- 尽量减小相邻 gap

适用于：

- 候选已经足够密集
- 只需要换位即可改善梯度

### 6.2 中间带补位

若发现相邻 gap 超过阈值，则：

- 找到 gap 区间
- 取中点
- 从候选工作集中找最接近中点的候选
- 做 1~2 个补位建议

这实际上是把当前 `fill_probability_gap` 的 compensation 能力前移到方案生成阶段。

## 7. 两种志愿模式的编排差异

## 7.1 `major` 模式

排序对象就是单条志愿。

优化重点：

- 冲稳保比例
- 概率梯度
- 推荐分
- 本省保底
- 用户硬约束 / 软意向

适合直接做线性排序优化。

## 7.2 `majorGroup` 模式

不能只排“组”，还必须考虑组内专业补齐。

建议拆成双层：

### A. 组层编排

先决定各院校 / 专业组在整张方案中的位置。

优化目标：

- 冲稳保
- 概率梯度
- 本省保底
- 组层推荐分

### B. 组内专业编排

再决定组内专业如何补齐与排序。

优化目标：

- 满足 `requiredMajorCount`
- 保留用户已明确选择的专业
- 在组内补充合适专业
- 避免全是同类高风险专业

### 关键结论

`majorGroup` 模式不能简单复用当前单条志愿排序器，必须引入：

- 组层候选
- 组内补全
- 双层排序

## 8. 建议的能力拆分

不建议所有场景继续复用一个 `generateOrderedPlan()`。

建议拆为以下能力：

### 8.1 `generateInitialPlan`

用于：

- 初次进入工作台
- 用户还未选草稿

职责：

- 自动选方案
- 自动生成默认排序

### 8.2 `reorderDraftPlan`

用于：

- 用户已有草稿
- 需要系统给出建议排序

职责：

- 仅对现有草稿重排
- 或按策略允许补位

### 8.3 `refinePlanGradient`

用于：

- 修复概率倒挂
- 修复梯度断层
- 做局部换位或插入补位

### 8.4 `completeGroupedPlan`

用于：

- `majorGroup` 模式
- 组内专业不够

职责：

- 组内补齐
- 组层与组内层联动

## 9. planning state 建议扩展

为支撑这套能力，建议补充显式状态：

### 9.1 `planGenerationState`

记录最近一次方案生成：

- `mode`
  - `initial_auto`
  - `draft_reorder`
  - `draft_reorder_and_complete`
- `sourceVersion`
- `generatedAt`
- `usedOverlayVersion`
- `allowAutoComplete`
- `respectedPinnedCount`

### 9.2 `orderedPlanState`

建议补充：

- `generationMode`
- `gradientAdjusted`
- `autoCompleted`
- `preservedPinnedCount`
- `preservedManualOrderCount`

### 9.3 `reviewState`

审查可以继续保留，但其定位应转为：

- 检查生成阶段是否仍有漏项
- 对偏约束型、提醒型规则做提示
- 为后续补偿提供挂钩

## 10. 对前端 V2 的接口建议

前端 V2 后续建议按场景调用不同能力：

### 10.1 首次进入工作台

- 若无草稿且无排序
- 调用 `generateInitialPlan`

### 10.2 用户选完草稿后

- 调用 `reorderDraftPlan`

补充当前 V2 的基础交互约定：

- 用户在候选区“加入草稿”后，backend 会先保证 `draftPlanState` 与 `orderedPlanState` 的集合一致
- 若当前还没有显式生成过排序方案，但草稿已非空，则会按草稿当前顺序即时补出一份可编辑的 `orderedPlanState`
- 若当前已存在排序方案，则新增草稿项默认追加到排序尾部；已从草稿移除的项会同步从排序方案中删除
- 这一步只做“集合补齐与尾插同步”，不主动重排既有顺序，也不覆盖用户已做的手动排序/固定位置

### 10.3 用户点击“优化当前方案”

- 调用 `refinePlanGradient`

### 10.4 `majorGroup` 模式组内不足

- 调用 `completeGroupedPlan`

### 10.5 后续方向: 方案构建算子编排化

这部分先作为后续工作约定，当前版本不展开实现细节。

后续目标不是继续把所有方案构建逻辑都固化在 backend 默认流程里一次性自动完成，而是：

- 将“候选范围确认、初始组建、梯度修复、保底修复、专业组选专业、审查分析、方案调整、方案应用”拆成一组可独立调用的方案算子能力
- 由对话层根据用户诉求决定调用顺序、是否继续下一步、是否需要用户确认
- 支持围绕同一份方案进行多轮分析、取舍、局部重算与最终确认

这条约定的核心边界是：

- 当前系统默认编排只提供一版可用初始方案
- 后续更完整的“最后方案”应允许通过多轮对话逐步生成，而不是完全由系统静默自动处理
- 面板继续承担单点查看与基础操作，对复杂方案推演、取舍说明和动作编排，由对话层承接

## 11. 实现顺序建议

建议按以下顺序推进：

1. 先抽出统一“编排上下文”对象
2. 再实现 `generateInitialPlan`
3. 再实现 `reorderDraftPlan`
4. 将当前 `fill_probability_gap` 从纯补偿能力前移为编排阶段能力
5. 最后再做 `majorGroup` 模式的双层编排

## 12. 最终结论

V2 后续需要的不是单一“排序功能”，而是一套完整的方案编排引擎。

这套引擎至少要覆盖：

- 从全量候选自动产出初始方案
- 对草稿做二次专业重排
- 对梯度和结构性规则做前置修复
- 对 `majorGroup` 模式做组层与组内双层编排

否则：

- 系统初始方案只能是“候选截断”
- 草稿建议排序只能是“简单重排”
- review 会持续承担本该由生成阶段解决的结构性问题
