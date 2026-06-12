# Release 3.1.0 Data Freshness And Impact Notification Design

本文记录 3.1.0 阶段对“高途招生计划数据持续变化”的设计方案。目标是在不改变当前一次性拉取、落盘、按会话生成工作区的总体机制下，让系统具备数据刷新感知、变化影响分析和分层通知能力。

## 1. 背景

当前创建会话时会一次性拉取高途全量志愿数据，清洗后写入会话快照文件，并以该快照生成候选池、方案和工作区状态。此模式的优点是稳定、可追溯，但缺点是：

- 高途招生计划、录取率、位次等数据后续可能继续更新。
- 当前系统无法主动感知“原始快照是否过期”。
- 已生成的候选池和方案不会主动提示用户数据变化。

3.1.0 需要补齐的是“变化感知”和“变化通知”，而不是把整个链路改成实时查询。

## 2. 目标

- 保持现有创建会话主流程不变。
- 为每个会话建立可比较的数据快照元信息。
- 在数据变化时生成影响分析结果。
- 在对话层和工作区层分别给出明确提示。
- 仅对受影响条目做标记或建议，不自动覆盖用户已确认的方案。

## 3. 非目标

- 不把高途数据改成实时查询模式。
- 不自动重排或覆盖用户方案。
- 不自动删除已存在方案条目。
- 不改变当前候选池/方案生成的主体算法。

## 4. 数据快照模型

每次创建会话或刷新时，落一份快照元信息：

- `chatSessionId`
- `source`：gaotu
- `fetchTime`
- `examYear`
- `prepareType`
- `province`
- `batch`
- `subjectType`
- `score`
- `requestHash`
- `dataHash`
- `dataVersion`
- `sourceDataHash`
- `latestSourceDataHash`
- `lastCheckedAt`
- `nextCheckAt`
- `checkIntervalMinutes`
- `checkSource`：scheduler / open_session / manual

其中：

- `requestHash` 用于标识“请求参数是否相同”。
- `dataHash` 用于标识“候选池可见字段是否变化”。
- `sourceDataHash` 用于标识“高途清洗后原始招生计划快照是否变化”。
- `latestSourceDataHash` 记录最近一次检查到的上游源数据摘要。
- `dataVersion` 用于兼容历史版本，后续不再作为唯一变化判断依据。
- `nextCheckAt/checkIntervalMinutes` 用于后台巡检调度和对外可观测。

如果上游没有独立版本号，就以 `sourceDataHash` 作为后台轻量检查主依据，以 `dataHash` 作为手动完整影响分析依据。

## 5. 刷新触发

建议支持三种触发方式：

1. 后台定时巡检：主触发方式，按省份和会话创建时间分散执行，单会话最长 5 小时内完成一次检查。
2. 打开会话详情或工作区时触发兜底异步检查：仅当该会话超过允许检查间隔时入队，不做页面高频轮询。
3. 用户手动点击“检查更新 / 刷新候选”：手动触发完整影响分析或确认后同步数据。

刷新原则：

- 只刷新 `prepareType=VOLUNTEER` 的智能填报会话。
- 优先刷新 `GOING`、近期开启或正在编辑的会话；已完成或明显过期会话只在用户访问时兜底。
- 对同一 `chatSessionId` 做互斥锁，避免重复刷新。
- 后台检查只更新快照和通知状态，不直接覆盖候选池、排序方案或用户确认结果。

## 6. 变化影响分析

变化类型分四级：

### 6.1 无变化

- `dataHash` 相同。
- 不通知用户。
- 只更新检查时间。

### 6.2 轻微变化

典型变化：

- 招生计划说明调整。
- 计划数细微变化。
- 历年分数补充更新。

业务动作：

- 更新候选池明细。
- 标记快照已刷新。
- 不影响当前方案结构。

通知建议：

- 对话层：`招生计划数据已更新，当前方案未受明显影响。`
- 工作区层：展示更新时间和变更数量。

### 6.3 中等变化

典型变化：

- 录取率变化。
- 位次区间变化。
- 计划数变化影响冲稳保判断。

业务动作：

- 候选池重新计算。
- 方案审查状态标记为 stale。
- 排序建议标记为 stale。

通知建议：

- 对话层：`部分院校/专业组数据已更新，建议重新审查当前方案。`
- 工作区层：列出受影响学校/专业组和变化摘要。

### 6.4 重大变化

典型变化：

- 当前方案条目下线。
- 招生计划为 0。
- 选科、体检、批次归属等约束变化。

业务动作：

- 当前方案条目标记异常或失效。
- 不自动删除。
- 生成风险提醒和待处理项。

通知建议：

- 对话层：`当前方案中有志愿已受招生计划变化影响，请尽快处理。`
- 工作区层：高亮受影响条目并提供调整入口。

## 7. 通知分层

### 7.1 对话层

对话层只输出摘要，负责回答：

- 有没有变化。
- 变化严不严重。
- 是否建议重新审查。

### 7.2 工作区层

工作区新增“通知区/变化区”，负责展示：

- 数据更新时间。
- 受影响范围。
- 变化条数。
- 变化明细。
- 操作按钮。

建议按钮：

- `查看变化详情`
- `重新审查`
- `刷新候选池`
- `稍后处理`

## 8. 差异匹配规则

建议以稳定 key 做 diff：

- `province + batch + schoolCode + majorGroupCode + majorCode`

匹配后的处理：

- 条目存在且字段变化：更新展示字段。
- 条目存在但计划为 0：标记失效。
- 条目不存在：标记下线。
- 条目新增：标记新增。

## 9. 后端落点

建议增加以下能力：

- `VolunteerDataSnapshot`
- `refreshVolunteerData(chatSessionId)`
- `detectVolunteerDataDiff(oldSnapshot, newSnapshot)`
- `buildChangeSummary(diff)`
- `markWorkspaceStale(chatSessionId)`

## 10. 前端落点

建议前端至少增加：

- 会话详情顶部提示条。
- 工作区通知区。
- 变化明细弹层或抽屉。
- 重新审查按钮。

## 11. 3.1.0 推荐实施顺序

1. 先落快照元信息和 hash。
2. 再实现刷新检查。
3. 再实现差异分析。
4. 再补对话层摘要通知。
5. 最后补工作区变化区和操作入口。

## 12. 风险与约束

- 不能自动重写用户确认过的方案。
- 刷新必须可追溯，可回看历史版本。
- 变化通知必须分层，避免打扰主对话。
- 刷新频率要限流，避免放大高途接口压力。

## 13. 结论

3.1.0 适合把“高途招生计划持续变化”做成数据快照与影响分析能力，而不是改成实时查询。这样可以在保持当前架构稳定的前提下，让系统感知变化、精准通知用户，并把风险控制在候选池和方案审查层面。

## 14. 专业组模式院校筛选优化方案

### 14.1 问题描述

当前专业组模式下，工作区筛选面板中的“院校名称”筛选不够灵活。页面表现为筛选项更接近专业组展示名称，用户希望按真实院校维度筛选。例如同一院校下存在多个专业组时，应能通过院校名称一次筛出该院校相关专业组，而不是只能命中某个专业组展示项。

### 14.2 已定位代码链路

后端筛选项入口：

- `PlanningStateService#getCandidateFilterOptions`
- `PlanningStateService#buildCandidateFilterGroups`
- 当前“院校名称”分组为 `groupCode=school.name`，`filterField=schoolKeywords`
- `schoolKeywords` 当前从 `CandidateItemDTO#getSchoolName` 提取

后端候选池查询过滤：

- `PlanningStateService#queryCandidatePool`
- `PlanningStateService#matchesSchoolKeyword`
- 当前正向和反向筛选都只匹配 `CandidateItemDTO#getSchoolName`

候选项字段映射：

- `PlanningStateService#flattenCandidates`
- `PlanningStateService#fillSchoolFields`
- `fillSchoolFields` 将高途返回的 `VolunteerSchool.school_name` 写入 `CandidateItemDTO.schoolName`

前端筛选面板：

- `WorkspacePanel#index.tsx`
- `FilterTokenField` 支持 `schoolKeywords`
- `FILTER_FIELD_META.schoolKeywords` 展示为“院校名称”
- 前端优先使用后端返回的 `candidateFilterOptions.groups`，无 `groups` 时 fallback 构造 `schoolKeywords`
- 前端提交候选池查询时仍回传 `filters.schoolKeywords`

### 14.3 初步原因判断

代码语义上 `schoolKeywords` 已经被设计为院校名称筛选，但专业组模式下如果页面实际展示为专业组名称，原因应在数据语义混用：

- 上游高途返回的 `school_name` 在专业组模式下可能已经是专业组展示名，而不是真实院校名。
- 或者本系统专业组聚合时，为了展示专业组，把 `schoolName` 当作专业组名使用。
- 当前 `schoolName` 同时承担“真实院校名”“专业组展示名”“分组展示名”“筛选匹配字段”多个职责，导致筛选语义不稳定。

因此不建议只在前端改 label 或做字符串截断。应在后端数据模型层明确拆分“真实院校名”和“专业组展示名”。

### 14.4 推荐设计

推荐在 3.1.0 中将筛选语义收敛为：

- `schoolName`：真实院校名称，用于院校筛选、院校标签、导出、审查中的院校维度。
- `majorGroupName` 或 `unitName`：专业组展示名称，用于专业组卡片标题和专业组移动、删除、排序等工作区展示。
- `schoolKeywords`：继续作为兼容字段，值必须来自真实院校名称。
- 如需保留专业组筛选，另增 `majorGroupKeywords`，展示为“专业组名称”，不复用 `schoolKeywords`。

兼容策略：

- 对前端已有 `schoolKeywords` 请求字段保持不变，避免破坏候选池查询、视图状态保存和历史筛选状态。
- 后端 `matchesSchoolKeyword` 继续读取 `filters.schoolKeywords`，但匹配真实院校名称。
- 专业组模式可新增可选筛选组 `groupCode=major_group.name`、`filterField=majorGroupKeywords`，前端不支持时不会影响现有功能；若本期不做专业组名称筛选，可以先不新增。
- 历史会话加载时，如果已有候选快照缺少真实院校名，应通过 `schoolId`、`planSchoolDataId` 或快照中的原始字段尽量回填；无法回填时保留当前值并记录兼容标记。

### 14.5 后端实施点

1. 检查 `VolunteerRecommendListResponse.VolunteerSchool` 是否存在真实院校名与专业组名的独立字段。
2. 若存在独立字段：
   - `fillSchoolFields` 中将真实院校名写入 `CandidateItemDTO.schoolName`。
   - 将专业组展示名写入新增字段 `majorGroupName` 或 `unitName`。
3. 若不存在独立字段：
   - 从 `schoolId` / `schoolUnitCode` / 院校基础库补齐真实院校名。
   - 原 `school_name` 若为专业组展示名，则写入 `majorGroupName`。
4. `getCandidateFilterOptions` 中 `schoolKeywords` 必须按真实院校名去重。
5. `matchesSchoolKeyword` 按真实院校名匹配；如存在历史数据兼容需要，可短期 fallback 匹配旧 `schoolName`，但不应扩大为专业名或专业组名泛匹配。
6. 专业组聚合方法中，卡片展示优先使用 `majorGroupName/unitName`，院校维度逻辑继续使用 `schoolName`。

### 14.6 前端实施点

1. 保持现有 `schoolKeywords` token、chip、请求体字段不变。
2. 筛选面板“院校名称”继续展示真实院校列表。
3. 专业组卡片标题如需要展示专业组名称，应改用后端新增的 `majorGroupName/unitName`。
4. 如新增 `majorGroupKeywords`：
   - 扩展 `FilterTokenField`。
   - 增加 `FILTER_FIELD_META.majorGroupKeywords`。
   - 请求体和候选池查询 DTO 增加对应正反向字段。
   - 作为独立筛选项展示“专业组名称”，不要替代“院校名称”。

### 14.7 影响面

需要重点回归：

- 专业组模式候选池筛选：按院校名称筛选后，同一院校下多个专业组应同时命中。
- 专业模式候选池筛选：原“院校名称”筛选行为不变。
- 专业组工作区展示：卡片标题、组内专业展示、移动、删除、排序不受影响。
- 方案区导出：院校名、专业组名、组内专业字段语义正确。
- 审查和修复：专业组安全垫、冲稳保断层、补位推荐仍按专业组单元处理。
- 历史迁移会话：旧快照可打开、可筛选；无法回填真实院校名的条目不应导致页面异常。

### 14.8 验收标准

- 专业组模式下，“院校名称”筛选项展示真实院校名，不展示专业组组合名。
- 选择某个院校后，候选区返回该院校下所有符合条件的专业组/专业项。
- 反向“不看某院校”能排除该院校所有专业组。
- 专业模式原筛选结果与修改前一致。
- 新建会话和历史迁移会话均可正常加载、筛选、导出、审查、排序。

### 14.9 待确认问题

- 高途专业组模式原始返回中，真实院校名和专业组名分别对应哪个字段。
- 当前生产快照中是否存在可回填真实院校名的字段。
- 是否需要在 3.1.0 同时提供“专业组名称”独立筛选，还是本期只修正“院校名称”筛选语义。


## 15. 2026-06-12 落地记录：数据新鲜度最小闭环

本阶段先落「状态感知与通知」闭环，不把数据刷新改造成实时查询，也不自动改方案。

已实现范围：

- 后端 `PlanningStateDTO` / `PlanningWorkspaceStateRes` 增加 `dataFreshnessState`。
- 候选池生成和历史方案导入时，基于候选池稳定字段生成 `requestHash` / `dataHash` 快照。
- 新增 `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/data-freshness/check`：
  - 不传外部 hash 时，只回填/检查当前会话快照。
  - 传入外部 `dataHash/dataVersion/changeLevel` 且与当前快照不同，则标记数据变化。
  - `minor` 变化只提示刷新候选池，不强制审查 stale。
  - `medium/major` 变化会标记候选、推荐、方案调整和审查 stale。
- 前端工作区增加招生计划更新提示条，展示变化级别、影响数量、检查时间，并提供「检查更新」「刷新候选」「重新审查」入口。
- Agent `query_state` 状态概览会读取 `dataFreshnessState`，只做摘要提示和下一步建议，不自动触发方案调整。

与复合 action plan 的关系：

- 数据新鲜度状态只作为外部事实输入，不作为复合 action plan 的一个执行步骤。
- 当前不自动生成“刷新候选 -> 重排 -> 审查 -> 替换失效项”的多动作事务。
- 后续复合 action plan 稳定后，可以把 `dataFreshnessState.requiresCandidateRefresh/requiresReview/affectedVolunteerIds` 作为 planner 输入，生成可确认的多步骤处理预览。
- 在此之前，刷新候选池和重新审查仍由用户点击或明确指令触发，避免外部数据变化直接改动用户方案。

### 15.1 2026-06-12 补充：手动重拉与确认后同步

本次在最小闭环基础上补齐“能感知最新高途数据、并在用户确认后使用新数据刷新候选”的链路。

后端实现：

- 新增 `VolunteerSourceDataSyncService`，复用建会话时的 `queryAllProgramData -> cleanJsonDataWithStringProcessing -> session_volunteer` 规则，保证重拉数据结构与初始会话一致。
- `DataFreshnessCheckReq` 增加 `fetchLatest` / `syncSourceData`：
  - `fetchLatest=true`：按当前会话成绩、批次、选科、年份、prepareType 重新请求高途全量招生计划，只做内存态比对。
  - `syncSourceData=true`：在重拉后覆盖本机 `session_volunteer` 原始文件，并异步上传 OSS；该开关只在用户确认刷新候选时使用。
- `checkDataFreshness(tenantId, chatSessionId, req)` 在 `fetchLatest=true` 时会用最新源数据重新跑推荐流水线，但不保存候选池、不重排方案、不修改用户方案。
- 比对维度基于候选志愿稳定 key 和候选核心字段，输出 `addedCount/removedCount/updatedCount/invalidCount/affectedVolunteerIds/affectedUnitIds/changeLevel`。
- 数据变化后：
  - `minor`：标记候选池、初始推荐、方案调整 stale，不强制审查 stale。
  - `medium/major`：标记候选池、推荐 overlay、初始推荐、排序方案、方案调整、审查 stale。
- `CandidatePoolGenerateReq` 增加 `refreshSourceData`。用户点击工作区「刷新候选」时传 `refreshSourceData=true`，先同步最新 `session_volunteer`，再重新生成候选池。
- 空请求且没有外部 hash 时不会清除已有 `changed` 提示，避免前端误把未检查当作已恢复。

前端实现：

- 工作区「检查更新」调用 `data-freshness/check` 时传 `{ fetchLatest: true }`，展示最新比对结果。
- 数据更新提示条中的「刷新候选」调用候选池生成接口时传 `refreshSourceData=true`，确保后续候选池使用最新高途数据。
- 普通候选池刷新和其他历史入口不传 `refreshSourceData`，保持原行为。

Agent 影响：

- Agent 仅读取 `dataFreshnessState` 作为状态事实，回复中解释“外部招生计划数据变化、当前不自动改方案、建议刷新候选或重新审查”。
- 复合 action plan 后续可以消费 `requiresCandidateRefresh/requiresReview/affectedVolunteerIds`，但本次不把源数据同步变成自动执行步骤。

后续待接入：

- 定时任务或会话打开时异步检查活跃会话，避免完全依赖用户手动点击。
- 更细粒度 diff：院校/专业组下线、计划数变化、录取率变化、选科/体检/批次变化分别对应不同通知文案和操作建议。
- 工作区变化明细抽屉和受影响条目高亮。
- 刷新候选后的“旧方案受影响项”可视化审查，供复合 action plan 生成可确认的多步骤处理预览。

### 15.2 高频变化字段与开销边界补充

本次将高频变化字段纳入候选数据指纹，覆盖常见的院校属性、专业属性和招生计划变化。

纳入 `dataHash` 的主要字段：

- 志愿身份与单元：`volunteerId`、`unitId`、`tier`、`subTier`、`rankInTier`。
- 院校/专业组信息：`planSchoolDataId`、`schoolId`、`schoolUnitCode`、`schoolName`、`provinceName`、`cityName`、`schoolBatch`、`schoolLevel`、`schoolNature`、`schoolCategory`。
- 院校属性：`schoolRank`、`schoolEnrollRatio`、`baoyanRatio`、`upgradeRatio`、`masterCount`、`doctorCount`。
- 院校标签与历史分数摘要：`schoolRankTags`、`schoolBasicTags`、`schoolPopupTags`、`schoolHistoryScores(year/score/pos/planNum/enrollNum)`。
- 专业信息：`majorId`、`majorName`、`majorCode`、`majorCategoryId`、`majorSubCategoryId`、`majorLevel`、`majorDiscipline`、`majorCategory`、`majorTier`。
- 招生计划与专业属性：`planNum`、`duration`、`tuitionPerYear`、`admissionRatio`、`mustSubjects`。
- 专业标签与历史分数摘要：`majorRankTags`、`majorPlanTags`、`majorHistoryScores(year/score/pos/planNum/enrollNum)`。
- 排序/推荐相关轻量字段：`baseScore`、`intentScore`、`finalScore`、`futureDevelopmentScore`、`hotIndex`、`salaryAvg`、`reasonCodes`、`riskFlags`。

兼容策略：

- 历史会话中已有的 `dataHash` 可能由旧字段集生成。检查时会优先用当前候选池按最新字段集重新计算基线 hash，避免字段集扩展导致老会话第一次检查时误报变化。
- 无变化时会把 `dataFreshnessState.dataHash` 迁移为最新字段集 hash。
- 不把高途原始大对象整体放入 hash，只使用候选条目上的轻量字段和历史分数摘要。

开销边界：

- 字段扩展本身只增加候选条目遍历时的 `row.put` 和 JSON 序列化长度，通常不是主要开销。
- 当前链路的主要开销分两类：后台检查侧的高途全量招生计划拉取、JSON 清洗和 `sourceDataHash` 计算；用户确认刷新侧的推荐过滤排序流水线和候选池重新生成。
- 后台巡检只能做源数据 hash 级检查、状态更新和通知标记，不执行推荐流水线，不生成候选池，不改动方案。
- 完整影响分析、候选池重新生成、排序和审查仍由用户点击「检查更新 / 刷新候选 / 重新审查」或明确指令触发。
- 定时任务必须限制会话范围、批量大小、并发数、超时时间和重试次数，避免与线上主链路争抢 CPU、网络和高途接口额度。

### 15.3 更新触发策略补充：后台巡检优先，5 小时封顶

仅靠用户主动点击「检查更新」不够；但当前“轻量检查”仍需要调用高途全量招生计划接口并计算 `sourceDataHash`，网络 IO 不适合在用户打开页面后高频轮询。本阶段触发策略调整为后台巡检优先，页面访问只做兜底。

后台巡检目标：

- 只处理 `prepareType=VOLUNTEER` 的智能填报会话。
- 单会话最长检查间隔不超过 5 小时，即任一纳入巡检范围的会话在 5 小时内必须完成一次源数据检查。
- 可以做阶梯调度，但 `checkIntervalMinutes` 必须小于等于 300。
- 后台检查只做源数据 hash 级变化感知，不自动刷新候选池、不自动重排、不自动修改方案。

建议调度阶梯：

- 创建 24 小时内或最近 24 小时访问过：2 小时检查一次。
- 创建 1-7 天且仍为 `GOING`：3 小时检查一次。
- 创建 7 天以上但仍在智能填报范围内：5 小时检查一次。
- 已完成、已归档或超过业务保留期的会话：默认不进入后台巡检，仅在用户访问时按兜底策略检查。

负载均衡策略：

- 按 `provinceCode + createTime` 分片取任务，避免同一省份、同一时间段集中请求高途。
- 单批只取少量会话，例如 5-10 个；单机并发建议 1-2。
- 高途请求失败时记录 `failCount/lastError/lastFailedAt`，按失败次数退避，但不能让仍有效的会话永久超过 5 小时未检查；达到熔断阈值时应暴露巡检异常状态。
- 同一 `chatSessionId` 加互斥锁，避免后台巡检、用户打开兜底和手动检查同时重拉。
- 后台任务不使用调度线程池直接大并发打高途，应使用独立小线程池或令牌桶限流。

页面访问兜底：

- 工作区加载时优先读取 `dataFreshnessState` 和巡检状态，不做页面高频轮询。
- 如果 `nextCheckAt` 已过期或 `lastCheckedAt` 距今超过 5 小时，可以异步入队一次轻量检查。页面先返回已有状态，不阻塞首屏。
- 同一浏览器会话仍可保留短暂冷却，避免用户频繁进出同一页面造成重复入队；冷却时间必须服从后台 5 小时封顶策略。

### 15.4 巡检状态查询接口

需要提供接口让运维或前端查看每个会话的检查间隔和调度状态。建议新增：

- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/data-freshness/schedule?chatSessionId={chatSessionId}`
- 返回单会话巡检状态：`chatSessionId`、`prepareType`、`provinceCode`、`provinceName`、`createTime`、`lastCheckedAt`、`nextCheckAt`、`checkIntervalMinutes`、`lastCheckSource`、`lastCheckStatus`、`lastSourceDataHash`、`latestSourceDataHash`、`failCount`、`lastError`。
- 管理侧后续可补列表接口：按 `provinceCode/status/nextCheckAt` 分页查看巡检积压和失败情况。

接口语义：

- `lastCheckStatus=current`：最近一次源数据 hash 未变化。
- `lastCheckStatus=changed`：源数据 hash 已变化，已通知用户，但尚未确认刷新候选。
- `lastCheckStatus=failed`：最近一次后台检查失败，需要重试或人工排查。
- `nextCheckAt` 是调度计划时间，不代表一定精确执行；但有效会话的实际检查完成时间不得晚于上一次成功检查后的 5 小时窗口。

数据落地建议：

- 短期可以复用 `dataFreshnessState` 保存单会话检查时间、源 hash 和状态。
- 为避免批量扫描解析大 JSON，建议新增轻量索引表或 extra-data 索引记录：`chatSessionId/tenantId/prepareType/provinceCode/createTime/lastCheckedAt/nextCheckAt/checkIntervalMinutes/status/failCount`。
- 索引在创建会话、刷新候选、后台检查完成时同步更新。

### 15.5 实施拆分与验收标准

建议把后台数据更新感知拆成以下实施单元：

1. 巡检状态模型：补齐 `lastCheckedAt`、`nextCheckAt`、`checkIntervalMinutes`、`lastCheckSource`、`lastCheckStatus`、`failCount`、`lastError`、`sourceDataHash`、`latestSourceDataHash`。
2. 轻量索引：为后台任务提供可分页扫描的索引，避免每轮巡检解析所有会话的大 JSON。
3. 调度器：定期扫描到期的 `VOLUNTEER` 会话，按 `provinceCode + createTime` 分散取数，单批 5-10 个，单机并发 1-2。
4. 间隔计算：按会话创建时间、最近访问时间、状态计算 2 小时、3 小时、5 小时阶梯，但最终写入的 `checkIntervalMinutes` 不得超过 300。
5. 执行锁与限流：同一 `chatSessionId` 同时只允许一个检查任务；后台巡检、打开会话兜底、手动检查共享互斥和限流。
6. 检查执行：只重拉并清洗高途源数据，计算 `sourceDataHash`，记录是否变化；不刷新候选池、不重排、不修改方案。
7. 通知写入：源数据变化时更新 `dataFreshnessState` 和工作区通知状态，由用户决定是否刷新候选或重新审查。
8. 查询接口：提供单会话巡检状态查询，后续再补管理侧列表查询。

验收标准：

- 正常情况下，任一纳入巡检范围的 `VOLUNTEER` 会话距离上次成功检查不超过 5 小时。
- 后台巡检不会触发候选池重建、推荐系数重算、方案排序、方案删除或方案替换。
- 页面打开只读取状态并在过期时异步入队，不做高频同步轮询，不阻塞工作区首屏。
- 巡检状态接口能看到当前会话的 `lastCheckedAt`、`nextCheckAt`、`checkIntervalMinutes`、检查来源、检查结果和失败原因。
- 当高途源数据变化时，对话层和工作区只提示变化范围和建议动作，用户确认前不自动覆盖任何已生成方案。
- 高途接口失败、超时或熔断时记录失败状态，并在状态接口中可见；恢复后按调度策略继续检查。

### 15.6 2026-06-12 实现补充：后台巡检索引与默认关闭开关

本次在设计基础上补齐后台巡检的代码骨架，保持生产风险可控：

- 新增轻量索引表 `assistant_planning_data_freshness_schedule`，用 `chatSessionId` 唯一索引保存巡检状态，避免后台任务扫描和解析完整 `planningState` 大 JSON。
- 新增巡检状态接口：`GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/data-freshness/schedule?chatSessionId={chatSessionId}`。
- 工作区状态返回时会合并轻量索引中的 `changed/failed/nextCheckAt/checkIntervalMinutes`，让前端能展示后台巡检发现的变化。
- 后台巡检任务默认关闭：`planning.data-freshness.schedule.enabled=false`。上线后需要明确开启配置才会开始请求高途。
- 后台任务每轮先小批量补建索引，再按 `nextCheckAt/lastCheckedAt` 取到期会话执行轻量检查；单轮执行量由 `batch-size` 和 `max-consecutive-tasks` 控制。
- 轻量检查只重拉并清洗高途源数据，计算 `sourceDataHash` 并写入索引；不生成候选池、不重新排序、不覆盖用户方案。
- 前端取消工作区打开后的自动静默检查，保留用户手动「检查更新」入口。

生产部署注意：

- 生产长期关闭 Flyway 时，需要在升级前手动执行 `V6__add_planning_data_freshness_schedule.sql`。
- 首次打开后台巡检建议保守配置：`batch-size=5`、`max-consecutive-tasks=1`、`fixed-delay-ms=300000`，观察高途接口耗时、失败率和机器负载后再调整。
- 如果短期只需要状态可查但不希望后台自动打高途，保持 `enabled=false`，接口仍可查看/补建单会话索引。

### 15.7 待验证项与投产前检查清单

本阶段代码已完成后台巡检骨架，但生产启用前仍需要按以下清单逐项验证，避免对线上高途接口、数据库和用户工作区产生额外影响。

数据库与开关：

- 确认生产库已执行 `V6__add_planning_data_freshness_schedule.sql`，并检查 `assistant_planning_data_freshness_schedule` 表、`uk_chat_session_id` 唯一索引、`idx_enabled_next_check` 和 `idx_status_next_check` 索引存在。
- 先以 `planning.data-freshness.schedule.enabled=false` 部署，确认服务启动后没有后台巡检日志、没有新增高途全量方案拉取请求。
- 确认 Flyway 关闭的生产环境不会因为新增 migration 文件影响启动；如果生产 Flyway 仍关闭，以手工 SQL 为准。

单会话接口：

- 用已知 `VOLUNTEER` 会话调用 `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/data-freshness/schedule?chatSessionId={chatSessionId}`，确认返回 `prepareType=VOLUNTEER`、`provinceCode`、`enabled=true`、`checkIntervalMinutes<=300`、`nextCheckAt`。
- 用 `PREDICT` 或已结束会话调用同一接口，确认不会被纳入后台巡检，`enabled=false` 或无有效 `nextCheckAt`。
- 对不存在或无工作区数据的会话调用接口，确认返回可理解的错误或空状态，不触发异常堆栈和重复重试。

工作区展示：

- 在巡检索引中模拟 `lastCheckStatus=changed`，打开工作区确认会展示数据更新提示，但不会自动刷新候选池、不会修改方案、不会重新排序。
- 在巡检索引中模拟 `lastCheckStatus=failed`，确认工作区能展示检查失败或稍后重试提示，不阻塞用户继续查看和编辑方案。
- 确认前端打开工作区时只读取状态，不再发起自动静默全量检查。

手动刷新链路：

- 点击「检查更新」验证仍走完整影响分析，能展示变化范围，并由用户确认是否刷新候选或重新审查。
- 用户确认刷新前，候选池、排序区、方案区和导出结果不应被后台巡检改写。
- 用户确认刷新后，巡检索引中的 `lastSourceDataHash/latestSourceDataHash/lastCheckedAt/nextCheckAt` 应随刷新结果同步更新。

后台巡检小流量验证：

- 只在 SQL、接口和默认关闭验证通过后开启后台巡检。
- 首次启用建议配置 `batch-size=5`、`max-consecutive-tasks=1`、`fixed-delay-ms=300000`，观察至少一个调度周期。
- 观察 CPU、内存、数据库慢查询、高途接口耗时和失败率，确认没有影响创建会话、工作区加载、对话发送等主链路。
- 抽查到期会话被处理后，`lastCheckedAt` 更新，`nextCheckAt` 后移，`checkIntervalMinutes` 不超过 300 分钟。

5 小时封顶与失败退避：

- 人工构造 `next_check_at` 已过期的 `VOLUNTEER` 会话，确认下一轮调度会优先处理。
- 人工构造创建时间不同的会话，确认阶梯间隔符合 2 小时、3 小时、5 小时策略，且最终不会超过 300 分钟。
- 模拟高途接口失败，确认 `lastCheckStatus=failed`、`failCount`、`lastError`、`lastFailedAt` 被记录，下一次重试时间仍在 5 小时封顶范围内。
- 连续失败时确认任务不会无限密集重试，也不会阻塞其他省份或其他会话的检查。

无副作用确认：

- 后台巡检只允许写巡检索引和工作区数据更新状态，不允许触发候选池重建、推荐系数重算、方案排序、方案删除、方案替换或导出数据改写。
- 抽查巡检前后的方案版本、志愿单元数量、专业组内专业数量、排序区顺序和用户已编辑内容，确认保持不变。
- 确认专业模式和专业组模式都只产生通知状态，不产生结构变更。

回滚方式：

- 如发现负载异常或高途接口异常，第一时间将 `planning.data-freshness.schedule.enabled=false` 并重启新版本服务或热更新配置。
- 回滚不需要删除 `assistant_planning_data_freshness_schedule` 表；保留索引数据便于后续排查。
- 如需完全停止影响，除关闭开关外，应确认没有人工或定时任务继续调用手动「检查更新」批量接口。
