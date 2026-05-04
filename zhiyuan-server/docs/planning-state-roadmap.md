# planningState 详细落地路线

## 1. 文档目的

本文档用于把跨模块总设计映射到 backend 的可执行落地项，明确：

- backend 在整体方案中的职责
- 当前已实现能力
- 后续每期接口与状态变化
- 每一阶段的验证和测试要求

整体设计请同时参见：

- [planning_state_full_design.md](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/planning_state_full_design.md)
- [planning-recommendation-current-state.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/planning-recommendation-current-state.md)

## 2. backend 职责边界

backend 是统一规划状态的事实来源，负责：

- 持久化 `planningState`
- 管理版本、阶段、失效标记
- 提供画像、候选、草稿、排序、审查、补偿接口
- 复用现有推荐链路生成候选池
- 对接 rank 的打分与标签
- 对接前端和 v3 agent 的操作请求

backend 不负责：

- 前端页面交互本身
- agent 话术编排本身
- rank 的底层评分算法本身

## 2.1 三类用户诉求语义

后续 backend 设计需要严格区分以下三类语义：

### A. 临时查看

典型场景：

- 看看北京有哪些计算机相关志愿
- 先筛一些稳区里的师范类
- 看看学费低的有哪些

特点：

- 只影响当前查询结果或候选面板视图
- 不改画像
- 不改推荐系数
- 不改草稿、排序、审查

### B. 方案偏好

典型场景：

- 更想去北京
- 不太想去山西
- 更看重就业
- 可以多关注计算机周边专业

特点：

- 需要写入画像或规划状态
- 影响专家推荐系数、专家优选组合、默认推荐顺序
- 原则上不直接改变候选基础池成员

### C. 方案约束

典型场景：

- 只报计算机相关专业
- 不报中外合作
- 不去北京
- 学费必须低于某个阈值

特点：

- 属于硬限制
- 在当前 `sessionDetailV2` 语义下，不自动改动 `candidatePoolState` 基础成员
- 会进入候选视图筛选条件，并连带影响后续推荐理解
- 用户确认后，需要把约束同步到工作台筛选栏，让用户直接看到筛选结果变化
- 建议在落状态前要求用户确认

## 2.2 对话主流程与方案编排语义

在 `sessionDetailV2` 下，不应把“用户提到一个方向词”直接理解为“要改方案”。

建议统一按以下主流程推进：

1. 先识别用户正在谈什么主题
2. 优先提供信息承接与右侧查看入口
3. 再判断是否需要沉淀为软意向或硬约束
4. 用户确认后才落真实状态
5. 只有当用户明确提出方案诉求时，才进入方案编排

由此，对话侧建议统一收口为四类诉求：

- `Explore`
  - 只查看，不改状态
- `Prefer`
  - 软意向，确认后更新推荐承接层
- `Constrain`
  - 硬约束，确认后联动候选视图层
- `Plan`
  - 用户明确要求分析、生成、调整、重排方案

进入 `Plan` 后，再细分为五类方案动作：

- `PlanQuery`
  - 仅查看当前方案层现状
- `PlanAnalyze`
  - 诊断当前方案问题
- `PlanAdjust`
  - 生成调整建议
- `PlanGenerate`
  - 按当前状态生成一版方案
- `PlanReorder`
  - 对已有草稿或已有方案重新排序

补充说明：

- 更泛化的候选查询语义，不属于 `PlanQuery`
- “某个地域、院校、专业方向下还有哪些可选”应继续归在临时查询 / `Explore`
- `PlanQuery` 只承接当前草稿、当前排序、当前审查、当前调整建议等方案层现状读取

当前阶段的产品策略应保持为：

- 查询优先由右侧面板承接
- 建议优先由对话承接
- 未确认前，不落偏好/约束状态
- 未获得执行授权前，不自动修改正式方案

## 2.3 当前实现的收口顺序建议

为了让 backend 状态语义和 agent 路由语义逐步一致，建议按以下顺序推进，而不是直接散点修补。

### A. 先收入口

先把进入 backend 的请求明确分成：

- 临时查询
- 软意向确认
- 硬约束确认
- 方案动作

要求：

- 临时查询不写规划主状态
- 软意向和硬约束必须能区分不同的后续影响范围
- 方案动作不应继续退回到“长期画像更新”入口

### B. 再收 `Plan` 动作边界

与 agent 约定统一的五类方案动作：

- `PlanQuery`
- `PlanAnalyze`
- `PlanAdjust`
- `PlanGenerate`
- `PlanReorder`

要求：

- backend 接口和状态语义要能支撑这五类动作的稳定边界
- 不再让“分析”和“重排”混入同一类操作

### C. 最后再统一 stale 规则

只有在入口和动作边界稳定后，stale 规则才适合最终收敛。

否则会出现：

- 旧入口按历史方式打脏
- 新动作按新语义判断可复用
- 两边互相冲突

因此后续 stale 修正建议以：

- 软意向确认入口
- 硬约束确认入口
- 候选视图入口
- 草稿/排序/审查入口

这四组入口为主线统一处理。

## 3. 当前状态结构

当前 backend 已承载以下主状态：

- `profileState`
- `constraintState`
- `candidatePoolState`
- `draftPlanState`
- `orderedPlanState`
- `reviewState`
- `pendingActions`

建议后续演进为以下三层清晰结构：

- `candidatePoolState`
  - 基础候选池，只承载基础成员与摘要
- `recommendationOverlayState`
  - 推荐覆盖层，承载推荐系数、专家优选组合、推荐理由
- `draftPlanState` / `orderedPlanState` / `reviewState`
  - 面向方案构建和审查的状态

### 3.1 `phase`

当前已使用或建议使用的阶段值：

- `profile_ready`
- `candidate_generated`
- `drafting`
- `ordered`
- `reviewed`
- `completed`

### 3.2 `staleFlags`

当前已使用的失效标记：

- `candidatePool`
- `recommendationOverlay`
- `orderedPlan`
- `review`

基础规则：

- 硬约束变化 -> 当前阶段不自动重建 `candidatePoolState`，但会更新候选视图筛选条件，并让 `recommendationOverlay` 失效
- 软意向变化 -> 原则上只让 `recommendationOverlay` 失效，不直接触发候选基础池整体重建
- 临时查看 -> 只影响当前查询结果，不改规划主状态
- 工作台筛选和对话确认后的候选视图条件 -> 进入 `planningState.candidateViewState`
- 草稿变化 -> 排序、审查失效
- 排序变化 -> 审查失效

进一步约束如下：

- 软意向变化
  - 应打脏 `recommendationOverlay / initialRecommendation / planAdjustment / orderedPlan / review`
- 硬约束变化
  - 应更新 `candidateViewState`
  - 应打脏 `recommendationOverlay / initialRecommendation / planAdjustment / orderedPlan / review`
  - 不应打脏 `candidatePool`
- `candidateViewState` 变化
  - 默认打脏 `initialRecommendation / planAdjustment`
  - 不应自动推翻已有正式方案
- 草稿变化
  - 打脏 `orderedPlan / planAdjustment / review`
- 排序变化
  - 打脏 `planAdjustment / review`

补充约束：

- `futureDevelopment` / `careerTypes` 归类为软意向层
- 它可以影响 `recommendationOverlay / initialRecommendation / orderedPlan / review`
- 它不应直接打脏 `candidatePool`
- 若用户仅表达“想去体制内 / 想考公 / 更看重稳定”等未来发展诉求，系统应优先解释其对当前方案承接方向的影响，而不是直接修改候选基础池

### 3.3 候选基础池与推荐覆盖层的数据边界

为降低改造风险，建议后续沿现有 `CandidatePoolStateDTO` / `CandidateItemDTO` 逐步演进，而不是一次性推翻。

#### A. `candidatePoolState`

建议只保留基础候选池语义相关字段：

- `generatedAt`
- `sourceVersion`
- `requiredCount`
- `requiredTierCounts`
- `requiredMajorCount`
- `userScore`
- `batchScore`
- `sourceProvinceName`
- `volunteerModel`
- `items`
- `summary`

其中 `items` 建议只承载基础候选成员信息，例如：

- `volunteerId`
- `tier`
- `subTier`
- `planSchoolDataId`
- `schoolId`
- `schoolName`
- `provinceName`
- `cityName`
- `majorId`
- `majorName`
- `planNum`
- `duration`
- `tuitionPerYear`
- `admissionRatio`
- `mustSubjects`
- `riskFlags`
- 历年分数线、院校基础标签、专业基础标签

原则：

- 这些字段由全量志愿数据、录取概率、基础规则和硬约束决定
- 不因软意向变化而改变成员集合

#### B. `recommendationOverlayState`

建议新增一层推荐覆盖状态，至少包含：

- `generatedAt`
- `sourceVersion`
- `profileVersion`
- `items`
- `summary`

其中 `items` 可按 `volunteerId` 建立映射，建议字段：

- `volunteerId`
- `baseScore`
- `intentScore`
- `finalScore`
- `rankInTier`
- `preferred`
- `reasonCodes`
- `schoolRankTags`
- `majorRankTags`
- `preferenceTags`

原则：

- 这层承接现有 rank 的推荐系数和“专家优选组合”结果
- 由软意向和专家规则决定
- 原则上不直接改动基础候选成员

#### C. `CandidateItemDTO` 的最小兼容策略

为兼容前端现状，第一阶段不强制拆分查询返回结构，可以采用：

- `candidatePoolState.items` 继续存现有 `CandidateItemDTO`
- 但内部语义上把字段拆成：
  - 基础字段
  - 覆盖字段
- 查询接口返回时再拼装成当前前端需要的单条候选项

这样可以先改状态流转和失效语义，再逐步推进 DTO 正式拆分。

### 3.4 `candidateViewState`

`sessionDetailV2` 当前需要把“界面上实际生效的候选筛选/排序视图”作为独立状态持久化，而不是继续只放在前端本地态。

建议字段：

- `filters`
  - `tiers`
  - `provinceNames / negativeProvinceNames`
  - `cityNames / negativeCityNames`
  - `schoolKeywords / negativeSchoolKeywords`
  - `majorKeywords / negativeMajorKeywords`
  - `schoolTags / negativeSchoolTags`
  - `majorTags / negativeMajorTags`
- `sort`
  - `field`
  - `order`
- `expertPreferredOnly`

职责边界：

- `candidatePoolState`
  - 表示由分数、省份、批次、基础供给计算出来的大候选池
- `candidateViewState`
  - 表示当前工作台或对话确认后实际生效的筛选与排序视图
- `candidate-pool/query`
  - 当前由前端先读取 `candidateViewState` 回灌筛选栏，再携带完整 query 参数查询最终展示结果

当前约束：

- 画像初始化产生的地域/专业初始意向，可下沉为默认 `candidateViewState`
- 用户在筛选栏手动修改筛选条件，只更新 `candidateViewState`
- 对话中确认的硬约束，也先落到 `candidateViewState`，不自动重建基础池
- `candidateViewState` 的更新不应打脏 `candidatePool`

### 3.5 临时筛选参数与持久筛选状态

当前 `CandidatePoolQueryReq` 已具备：

- `tiers`
- `provinceNames`
- `negativeProvinceNames`
- `schoolKeywords`
- `negativeSchoolKeywords`
- `majorKeywords`
- `negativeMajorKeywords`
- `schoolTags`
- `negativeSchoolTags`
- `majorTags`
- `negativeMajorTags`
- `sort.field`
- `sort.order`

对应文件：

- [CandidatePoolQueryReq.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/model/dto/planning/CandidatePoolQueryReq.java)
- [tag-governance.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/tag-governance.md)

后续建议按以下口径使用：

- `tiers`
  - 普通类筛选
- `provinceNames`
  - 地域筛选
  - 当前口径固定为“省份名称”
  - 不混入城市或区县
- `negativeProvinceNames`
  - 地域排除筛选
- `schoolKeywords`
  - 院校名称关键词筛选
- `negativeSchoolKeywords`
  - 院校名称关键词排除
- `majorKeywords`
  - 专业名称关键词筛选
- `negativeMajorKeywords`
  - 专业名称关键词排除
- `schoolTags`
  - 院校属性枚举筛选
- `negativeSchoolTags`
  - 院校属性枚举排除
- `majorTags`
  - 专业属性枚举筛选
- `negativeMajorTags`
  - 专业属性枚举排除
- `sort.field` / `sort.order`
  - 仅影响当前候选查看顺序

筛选语义固定为：

- 不同属性之间做 `且`
  - 地域 + 院校属性 + 专业属性 + 关键词
- 同一属性内部做 `或`
  - 例如 `schoolTags=[公办, 双一流]` 表示命中任一即可

筛选项来源固定为：

- 前端不从当前已加载候选中自行推导
- 统一由 backend `candidate-pool/filter-options` 返回全量枚举型筛选项
- 数值型信息不进入筛选枚举
  - 如排名、录取率、保研率、升学率、学费、计划数、人数、位次等
  - 这些字段统一走排序能力，不走标签筛选

原则：

- 前端工作台常驻筛选条件应优先写入 `planningState.candidateViewState`
- `queryCandidatePool(...)` 的查询参数仍可用于临时查看行为
- 临时 query 参数不回写 `planningState.profileState`
- 临时 query 参数不直接触发 `staleFlags`

### 3.6 推荐覆盖层的消费原则

为避免“候选面板看到的是新推荐，排序/审查还是旧推荐”的链路割裂，后续所有依赖推荐分、专家优选组合或推荐理由的能力都应遵循同一原则：

- 候选基础成员判断：只看 `candidatePoolState`
- 推荐分、专家优选、推荐理由读取：优先看 `recommendationOverlayState`
- 对外提供排序、补偿、审查等能力时：使用“基础候选池 + 推荐覆盖层”的合并结果
- 若 `recommendationOverlay=true` 且当前接口有 `tenantId`，应先刷新 overlay，再继续本次编排

这样可以保证：

- 软偏好变化只刷新推荐层，不误伤基础池成员
- 默认排序、补偿优先级和候选展示保持一致
- 后续 agent / frontend / backend 三端不会出现不同口径的“专家优选组合”

## 4. 已实现能力映射

### 4.1 画像层

已实现：

- 显式画像更新
- 潜在画像更新
- 身体条件更新

设计要求：

- 不再把潜在画像强塞到 `UserProfileData`
- 统一沉淀到 `planningState.profileState`

### 4.2 约束层

已实现：

- 从潜在画像推导 `derivedPreferences`

待增强：

- 风险偏好推导
- 地域依赖、就近需求等推导
- 与 physical constraints 联动形成硬限制

### 4.3 候选池层

已实现：

- 复用 `VolunteerBizService.recommendVolunteerList(...)`
- 打平冲、稳、保结果
- 候选池查询筛选与排序

待增强：

- 将候选基础池与专家推荐覆盖层拆分
- 明确只让硬约束参与候选基础池成员生成
- 候选项补充录取概率、收费标签、限制报考标签、特殊类型标签
- 支持更强的 explain 字段

补充约束：

- 候选池查询时的标签筛选、关键词筛选、排序字段切换，默认视为临时交互动作
- 临时交互动作不应回写 `profileState`
- 临时交互动作不应直接触发候选基础池整体失效

### 4.4 专家推荐覆盖层

建议新增独立语义层，用于承接软意向变化后的重算结果。

建议负责：

- 推荐系数重算
- 专家优选组合标记重算
- 推荐理由标签更新
- 默认展示顺序更新

约束：

- 不直接改变候选基础池成员
- 可被草稿、排序、审查继续消费

建议的最小落地步骤：

1. 先新增 `recommendationOverlay` 的失效语义
2. 再把软意向更新从 `candidatePool stale` 切换到 `recommendationOverlay stale`
3. 保持当前查询接口返回结构不变，由 service 在查询时把基础池和覆盖层合并
4. 最后再考虑是否正式拆 DTO 和接口响应

### 4.5 草稿层

已实现：

- 选入草稿
- 移出草稿
- 锁定
- 禁用

待增强：

- 记录更多来源信息
- 支持批量系统补偿标记

### 4.6 排序层

已实现：

- 生成排序
- 按冲稳保重组
- 手动移动
- 固定位置 / 取消固定
- 基础摘要

待增强：

- 更细的区间内部梯度策略
- 锁定项不可越位策略
- 基于录取概率和 rank 分的综合排序策略

## 5. 后续开发分期

## Phase 1

目标：

- 建立状态骨架并打通画像 -> 候选 -> 草稿 -> 排序链路

当前状态：

- 已完成

交付内容：

- 状态持久化
- 基础 controller
- service 层状态流转
- 单元测试

验证：

- `PlanningStateServiceTest`
- `mvn -q -DskipTests compile`

## Phase 2

目标：

- 落地 `reviewState`
- 把 `risk_management` 和数量校验变成可执行规则

交付内容：

- `GET /session/review`
- `POST /session/review/run`
- `POST /session/review/ack`
- 规则结果结构化输出

当前最小闭环优先顺序：

- 区间配比
- 兜底安全
- 倒挂
- 梯度断层
- 数量校验

计划纳入的规则：

- 区间配比合理性
- 兜底安全性
- 倒挂现象
- 梯度断层
- 中外合作办学提示
- 高收费专业提示
- 限报要求提示
- 特殊类型招生提示
- 边缘分数提示
- 固定提示项
- 数量校验

验证：

- 每条规则最少 1 个命中用例 + 1 个未命中用例
- 多条规则叠加用例
- 排序变化后 review stale 校验

## Phase 3

目标：

- 落地补偿能力

交付内容：

- `POST /session/compensation/preview`
- `POST /session/compensation/apply`
- 自动补偿动作记录

当前最小闭环优先顺序：

- 总数量不足补齐
- 本省保底不足补齐
- 保区占比失衡补齐

补偿场景：

- 区间数量不足
- 本省保底不足
- 梯度断层
- 数量校验不足

验证：

- 补偿前后数量变化测试
- 锁定项不被破坏测试
- 硬约束不被突破测试

## Phase 4

目标：

- 支撑 PC 前端和 v3 agent 的统一操作回流

交付内容：

- 更细粒度操作接口
- 操作日志
- 前端手动动作回写
- agent 自动动作回写

验证：

- 接口契约测试
- 状态一致性测试

## 6. reviewState 设计建议

建议在 backend 中将 review 结果标准化为：

- `code`
- `level`
- `passed`
- `summary`
- `detail`
- `suggestedAction`
- `affectedVolunteerIds`

建议 `level`：

- `info`
- `warn`
- `risk`

建议 `code`：

- `ratio_distribution`
- `safety_guard`
- `probability_inversion`
- `probability_gap`
- `cooperative_program`
- `high_tuition`
- `admission_limit`
- `special_enrollment`
- `edge_score`
- `plan_update_notice`
- `adjustment_notice`
- `count_validation`

## 7. 数量校验在 backend 的建模建议

数量校验需要引入显式上下文：

- `fillMode`
  - `major_group`
  - `major`
  - `school`
- `province`
- `batch`
- `requiredCount`
- `requiredMajorCountPerUnit`

建议校验输出：

- 当前数量
- 官方要求数量
- 是否不足 / 满足 / 过多
- 命中的院校或专业组
- 建议动作

## 8. 与其它模块的接口约定

### 与 PC 前端

前端应优先读写 `planningState` 接口，而不是依赖一次性推荐结果。

### 与 v3 agent

agent 初始化时应拉取：

- `profileState`
- `constraintState`
- `draftPlanState`
- `orderedPlanState`
- `reviewState`

### 与 rank

rank 需要为后续 review 和 compensation 提供更多结构化字段：

- 录取概率
- 高收费标签
- 限报标签
- 特殊类型标签
- 本省 / 外省属性

## 9. 测试策略

backend 每个阶段都要补三类测试：

- service 单元测试
- controller / 接口测试
- 状态流转回归测试

建议最小覆盖清单：

1. 初始空状态加载
2. 画像更新后的 stale flags
3. 候选池生成和查询
4. 草稿增删锁禁
5. 排序生成、移动、固定
6. review 规则命中与未命中
7. compensation 不破坏锁定项

## 10. 当前建议下一步

backend 代码下一步建议直接进入：

1. `reviewState` DTO 与接口
2. 审查规则 service
3. 数量校验 service
4. `PlanningStateServiceTest` 扩充 review 场景
