# 老版本到 V2 升级迁移方案

本文档用于指导当前线上老版本系统平滑升级到新版本 V2 工作台。目标是在尽量用户无感的前提下，保留老用户已有数据，尤其是已经生成或提交过的优选志愿方案，并让这些方案能在新版本工作台中继续展示和操作。

## 1. 现状结论

当前目录 `/root/dev/zhiyuan` 是新版本，父目录 `/root/dev/zhiyuan.old` 是线上运行的老版本代码。两套系统模块对应关系如下：

| 能力 | 老版本目录 | 新版本目录 |
| --- | --- | --- |
| 前端 | `gaokao-volunteer-pc/` | `zhiyuan-web/` |
| 后端 | `gaotu-assistant-backend/` | `zhiyuan-server/` |
| Agent | `gaotu-zy-agent-plus/` | `zhiyuan-agent/` |
| 排序服务 | `gaokao-volunteer-rank-service/` | `zhiyuan-rank/` |

基础数据库表基本保持兼容，核心表仍是：

- `assistant_user_base`
- `assistant_user_credential`
- `assistant_user_auth`
- `assistant_chat_session`
- `assistant_chat_message`
- `assistant_chat_session_extra_data`

新版本 V2 工作台没有新增独立规划表，目前把统一规划状态存储在 `assistant_chat_session_extra_data`：

- `data_key = 'planningState'`
- `data_value = PlanningStateDTO JSON`
- `data_version = 0`

新版本已经能在缺少 `planningState` 时创建空规划状态，并从老的 `userScoreDetail`、`userprofile` 回填画像。但它不会自动把老版本已经生成的优选志愿方案转成 V2 的 `candidatePoolState`、`draftPlanState`、`orderedPlanState`。这就是迁移的核心缺口。

## 2. 老数据分布

老版本线上需要保留和兼容的数据主要有四类。

### 2.1 用户和会话数据

在 MySQL 中：

- 用户：`assistant_user_base`
- 登录凭证：`assistant_user_credential`
- 第三方认证：`assistant_user_auth`
- 会话：`assistant_chat_session`
- 消息：`assistant_chat_message`

这些表可以直接复用，不建议重新导入到新库，除非线上部署必须换库。

### 2.2 会话 extra_data

在 `assistant_chat_session_extra_data` 中：

| data_key | 含义 | V2 处理方式 |
| --- | --- | --- |
| `userScoreDetail` | 成绩、选科、省份、批次、策略等填报基础信息 | 直接复用，并回填到 V2 profile/constraints |
| `userprofile` | 对话沉淀出的用户意向画像 | 直接复用，并回填到 V2 profile |
| `userInitProfile` | 初始推导画像 | 保留，按现有逻辑读取 |
| `sessionSituation` | 会话情况摘要 | 保留 |
| `planEditCache` | 方案/意向变更缓存 | 不直接迁移为最终方案，仅作为“待确认变更”提示或继续由 Agent 消费 |
| `messageAnalyzeProgress` | 消息分析进度 | 保留 |
| `userProgram3MajorSummary` | 老方案专业总结 | 保留，短期可继续兼容查询 |
| `userProgramAreaSummary` | 老方案地区总结 | 保留，短期可继续兼容查询 |
| `planningState` | V2 工作台统一规划状态 | 新增或懒迁移生成 |

### 2.3 老方案文件

老版本会把推荐结果保存为方案文件，常见形式：

- `session_volunteer_{chatSessionId}_temp.json`
- `session_volunteer_{chatSessionId}_temp_summary.json`
- `session_volunteer_{chatSessionId}.json`

其中：

- `_temp.json` 通常是当前推荐/临时方案。
- 无 `_temp` 的 JSON 通常是提交后的最终方案。
- summary 文件可用于老 Agent 总结，但不能替代完整方案迁移。

V2 迁移应优先读取最终方案，其次读取临时方案，最后才重新生成。

### 2.4 老推荐接口

老接口仍存在于新后端，短期内应保留：

- `GET /gaotu-assistant-bot/chat/{tenantId}/volunteer/recommend-list?chatSessionId=...`
- `POST /gaotu-assistant-bot/chat/{tenantId}/volunteer/export?chatSessionId=...`
- `POST /gaotu-assistant-bot/chat/{tenantId}/volunteer/submit?chatSessionId=...`

这些接口可以作为兼容和回滚兜底，不建议上线 V2 时立即移除。

## 3. 迁移目标

升级后应满足：

1. 老用户账号、会话列表、历史消息不丢失。
2. 老用户进入 V2 会话详情时，能看到原来的优选志愿方案。
3. 已提交的方案保持提交时的顺序和内容，不被自动重算覆盖。
4. 未提交的临时方案优先保留原来的“优报/候补”划分。
5. 新用户直接走 V2 流程，生成 `planningState`。
6. 若迁移失败，用户仍可回退到旧会话详情页或旧志愿接口。

## 4. 推荐迁移策略

采用“兼容读 + 懒迁移 + 灰度切换”。

不建议首次上线就对全量历史 session 批量重算或批量写入 `planningState`，原因：

- 历史方案可能已经提交，重算会造成内容变化。
- 一次性处理大量大 JSON，数据库和 OSS 压力高。
- 迁移失败影响面大，不利于回滚。

推荐策略：

1. 保留老表和老方案文件。
2. 后端新增 legacy plan import 逻辑。
3. 用户首次打开 V2 工作台时，如果没有 `planningState`，自动从老数据生成。
4. 成功后写入 `assistant_chat_session_extra_data(data_key='planningState')`。
5. 后续访问都读 V2 状态。
6. 上线前可对活跃会话做小批量预热迁移，但不是唯一入口。

## 5. 后端改造方案

### 5.1 入口

建议在 `PlanningStateService.loadPlanningState(Long chatSessionId)` 中接入懒迁移：

```java
private PlanningStateDTO loadPlanningState(Long chatSessionId) {
    ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
            chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);

    if (extraData != null && extraData.getDataValue() != null) {
        return parseAndBackfill(extraData.getDataValue(), chatSessionId);
    }

    PlanningStateDTO state = tryImportLegacyPlanningState(chatSessionId);
    if (state != null) {
        savePlanningState(chatSessionId, state);
        return state;
    }

    state = new PlanningStateDTO();
    state.setSessionId(chatSessionId);
    backfillLegacyProfileState(chatSessionId, state);
    return state;
}
```

注意：实际代码应沿用现有 `loadPlanningState` 中的默认对象初始化逻辑，不要直接替换。

### 5.2 老方案读取顺序

`tryImportLegacyPlanningState` 建议按以下顺序查找方案：

1. 如果 `assistant_chat_session.session_status = FINISHED`，优先读取最终提交方案。
2. 读取 `session_volunteer_{chatSessionId}.json`。
3. 读取 `session_volunteer_{chatSessionId}_temp.json`。
4. 如本地文件没有，按现有 `VolunteerFilePathUtil` 查 OSS。
5. 仍不存在时，调用 `volunteerBizService.recommendVolunteerList(tenantId, chatSessionId, false, false)` 生成当前候选，但要标记为“系统重新生成”，不要伪装为用户历史最终方案。

### 5.3 旧方案到 V2 DTO 映射

老方案结构主要是 `VolunteerRecommendListResponse`：

- `sprints`
- `safes`
- `protects`
- `baseData`

V2 结构主要是：

- `CandidatePoolStateDTO`
- `DraftPlanStateDTO`
- `OrderedPlanStateDTO`
- `ReviewStateDTO`

映射建议如下：

| 老字段 | 新字段 |
| --- | --- |
| `sprints` | `tier = 冲` |
| `safes` | `tier = 稳` |
| `protects` | `tier = 保` |
| `school.planSchoolDataId + major.planMajorDataId` | `CandidateItemDTO.volunteerId` |
| `school.schoolId` | `CandidateItemDTO.schoolId` |
| `school.school_name` | `CandidateItemDTO.schoolName` |
| `school.area.data` | `CandidateItemDTO.provinceName` |
| `school.city.data` | `CandidateItemDTO.cityName` |
| `school.type.data` | `CandidateItemDTO.schoolNature` |
| `school.rankTagList` | `CandidateItemDTO.schoolRankTags` |
| `school.basicTagList` | `CandidateItemDTO.schoolBasicTags` |
| `school.popTagList` | `CandidateItemDTO.schoolPopupTags` |
| `major.majorId` | `CandidateItemDTO.majorId` |
| `major.major_name` | `CandidateItemDTO.majorName` |
| `major.majorUnitCode` | `CandidateItemDTO.majorCode` |
| `major.planNum` | `CandidateItemDTO.planNum` |
| `major.planMoney` | `CandidateItemDTO.tuitionPerYear` |
| `major.enroll_ratio` | `CandidateItemDTO.admissionRatio` |
| `major.must_subject` | `CandidateItemDTO.mustSubjects` |
| `major.history_score_list` | `CandidateItemDTO.majorHistoryScores` |
| `school.rank_in_tier` | `CandidateItemDTO.rankInTier` |
| `school.is_preferred` | `CandidateItemDTO.preferred` |
| `school.algTagMap.volunteer_score` | `CandidateItemDTO.finalScore` |
| `school.algTagMap.college_score_new` | `CandidateItemDTO.baseScore` |
| `major.algTagMap.major_score_new` | `CandidateItemDTO.intentScore` |

新版本已有 `flattenCandidates(...)` 可复用，它已经能从 `VolunteerRecommendListResponse.VolunteerSchool` 生成 `CandidateItemDTO`。迁移代码应优先复用该逻辑，避免维护两套字段映射。

### 5.4 优报和候补处理

老版本优报识别字段：

- `school.is_preferred = true`
- `school.rank_in_tier` 表示区间内排名

迁移规则：

1. 所有老方案项进入 `candidatePoolState.items`。
2. `is_preferred = true` 的项进入 `draftPlanState.items`。
3. `is_preferred = true` 的项按“冲 -> 稳 -> 保 + 原列表顺序或 rank_in_tier”进入 `orderedPlanState.items`。
4. `is_preferred = false` 的项作为候补保留在候选池，不进入最终排序方案。
5. 如果老数据没有 `is_preferred`，按 `baseData.three_target_count_map` 和区间内排名补算。

已提交会话建议：

- `orderedPlanState.items[].locked = true`
- `orderedPlanState.generationMode = "legacy_submitted"`
- `phase = "ordered"`
- 工作台展示“已提交方案”状态，避免用户误改。

未提交会话建议：

- `draftPlanState.items[].source = "legacy_preferred"`
- `orderedPlanState.items[].source = "legacy_preferred"`
- `orderedPlanState.generationMode = "legacy_import"`
- `phase = "ordered"`，如果没有足够优报项则为 `draft_ready`。

### 5.5 Summary 回填

迁移时需要同步回填 summary：

`candidatePoolState.summary`：

- 总候选数
- 冲稳保候选数
- 目标数量

`draftPlanState.summary`：

- `total`
- `unitTotal`
- `targetCount`
- `targetUnitCount`
- `tierCounts`
- `unitTierCounts`

`orderedPlanState.summary`：

- `total`
- `unitTotal`
- `targetCount`
- `targetUnitCount`
- `tierCounts`
- `unitTierCounts`
- `sequenceOk`
- `gradientOk`
- `safetyOk`

如果已有 `PlanningStateService` 内部 summary 计算方法，应抽取复用，不要在迁移方法里散落重复统计逻辑。

### 5.6 planEditCache 处理

`planEditCache` 不应自动合并进最终方案。它只是对话中的意向变更缓存，可能还没有被用户确认。

建议：

- 保留原 dataKey。
- V2 初始化时检测是否存在非空 `planEditCache`。
- 如果存在，在 `pendingActions` 或 `operationLogs` 中记录“存在待确认意向变更”。
- 由 Agent 后续继续引导用户确认。

## 6. 数据库升级步骤

上线前执行：

```sql
show columns from assistant_user_base;
show columns from assistant_user_credential;
```

确认以下字段是否存在：

- `assistant_user_base.limit_settings`
- `assistant_user_base.channel`
- `assistant_user_base.expired_date`
- `assistant_user_base.user_level`
- `assistant_user_credential.channel`

如果不存在，再执行对应增量 SQL。

注意：

- 不要重复执行 `ALTER TABLE ADD COLUMN`。
- 不要清空 `assistant_chat_session_extra_data`。
- 不要批量删除老方案文件。
- 不要把 `planningState` 作为必须预置数据，懒迁移会自动生成。

建议给 `assistant_chat_session_extra_data` 保持唯一索引：

```sql
unique (chat_session_id, data_key, data_version)
```

该索引用于保证每个会话每个 dataKey 只有一份当前版本数据。

## 7. 移动端适配方案

当前 `sessionDetailV2` 页面已经有移动端“对话/工作台”切换，但 `WorkspacePanel` 内部仍有桌面化组件。

### 7.1 已有基础

页面层已有：

- `useMediaQuery(768)`
- 移动端 tab：`对话` / `工作台`
- 移动端点击对话卡片动作时自动切到工作台

### 7.2 需要补齐

工作台移动端建议补以下样式和交互：

1. 顶部指标区 `metricsGrid`
   - PC：4 列
   - 移动端：2 列，或改成横向滚动摘要

2. 筛选区 `filtersRow`
   - PC：多列 grid
   - 移动端：拆成两行
   - 第一行：冲/稳/保 tab
   - 第二行：筛选按钮、排序按钮、升降序按钮

3. 筛选弹层
   - 当前宽度约 360px
   - 移动端改为 `width: calc(100vw - 24px)`
   - 最大高度改为 `70vh`

4. 专业详情表
   - 当前主要依赖横向滚动
   - 移动端建议改成卡片式字段展示
   - 至少要保证横向滚动容器有明显边界，不撑破页面

5. 排序方案操作按钮
   - 上移、下移、固定、取消固定、删除等按钮移动端容易挤压标题
   - 建议收进更多菜单，或固定在卡片底部操作栏

6. 工作台高度
   - 保持 `height: 100%` 和内部滚动
   - 避免 body 页面整体滚动和工作台内部滚动互相抢焦点

## 8. 平滑部署方案

### 8.1 部署原则

1. 后端先兼容，前端再切换入口。
2. 新旧接口并存至少 1-2 周。
3. V2 只对白名单或小流量用户开放。
4. 每个阶段都保留回滚路径。

### 8.2 推荐上线顺序

#### 阶段 0：备份

上线前备份：

- MySQL 全量备份
- 老方案文件目录
- OSS 中方案 JSON
- 当前前端镜像 tag
- 当前后端 JAR
- 当前 Agent 镜像 tag
- 当前 Rank 镜像 tag

#### 阶段 1：后端兼容上线

先上线包含以下能力的新后端：

- 保留旧 `/volunteer/*` 接口。
- 新增或完善 `/inner/planning/*` 接口。
- 加入 legacy plan import 懒迁移。
- 加迁移日志。

迁移日志建议至少包含：

- `chatSessionId`
- 是否已有 `planningState`
- 老方案来源：submitted/temp/regenerated/none
- 导入候选数
- 导入优报数
- 冲稳保数量
- 是否保存成功
- 异常原因

#### 阶段 2：内部白名单验证

只让内部账号进入 `/sessionDetailV2`。

验证样本应覆盖：

- 未生成方案的新会话
- 已生成未提交的老会话
- 已提交的老会话
- 有 `planEditCache` 的会话
- 专业优先模式
- 院校专业组模式
- 方案数量很大的会话

#### 阶段 3：小流量灰度

按用户或渠道灰度：

- 5%
- 20%
- 50%
- 100%

每个阶段观察：

- V2 工作台空白率
- `planningState` 懒迁移失败率
- 方案数量不一致率
- 导出失败率
- Agent WebSocket 错误率
- 后端接口 P95/P99
- MySQL `max_allowed_packet` 和慢 SQL

#### 阶段 4：默认入口切换

确认稳定后：

- 会话详情默认跳 V2。
- 保留旧页入口，如 `/sessionDetail?legacy=1`。
- 客服或运营可手动回退单个用户到旧页。

#### 阶段 5：收尾

观察 1-2 周后：

- 再决定是否批量预迁移剩余历史 session。
- 再决定是否下线旧页。
- 旧接口不建议立刻删除，可先只隐藏入口。

## 9. 验证清单

### 9.1 数据验证

对同一个 `chatSessionId` 对比：

- 老页面优报总数 = V2 ordered 总数
- 老页面冲/稳/保优报数 = V2 ordered 冲/稳/保数
- 老页面候补数 = V2 candidate 中非 preferred 数
- 已提交方案顺序保持一致
- 导出 Excel 主要字段一致
- 用户画像字段能在 V2 profile 中看到

### 9.2 接口验证

必须验证：

- `GET /gaotu-assistant-bot/chat/{tenantId}/volunteer/recommend-list`
- `POST /gaotu-assistant-bot/chat/{tenantId}/volunteer/export`
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/workspace-state`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/query`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/move`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/export`

### 9.3 前端验证

PC：

- 对话和工作台左右布局正常
- 工作台刷新不拉取超大完整 state
- 排序、固定、取消固定正常
- 筛选候选正常
- 导出正常

移动端：

- 默认进入对话 tab
- 点击“看看现在的方案”能切到工作台
- 工作台顶部不遮挡
- 筛选弹层不超出屏幕
- 专业表格或卡片不撑破页面
- 排序操作按钮可点击

## 10. 回滚方案

### 10.1 前端回滚

最快回滚：

- 将会话详情入口切回旧 `sessionDetail`
- 保留 V2 页面但不再默认进入

如果只是移动端问题：

- PC 继续 V2
- 移动端强制旧页或只开放对话 tab

### 10.2 后端回滚

如果新后端问题严重：

- 回滚旧后端 JAR 或容器
- 因为老接口和老 dataKey 没有被破坏，老版本可继续读原数据

注意：

- 新增的 `planningState` dataKey 对老版本无影响。
- 不要在迁移中修改或删除老方案 JSON。

### 10.3 单会话回滚

如果某个 session 的 V2 状态导入错误：

```sql
delete from assistant_chat_session_extra_data
where chat_session_id = ?
  and data_key = 'planningState'
  and data_version = 0;
```

然后：

- 用户可回旧页继续使用。
- 或修复导入逻辑后重新进入 V2 触发懒迁移。

## 11. 风险点

### 11.1 方案重算导致用户感知变化

风险：如果迁移时重新调用推荐接口，结果可能和用户之前看到的不一致。

控制：

- 优先读取最终/临时方案文件。
- 只有文件不存在时才重算。
- 重算生成的状态要记录 `generationMode = "legacy_regenerated"`。

### 11.2 大 JSON 写入失败

风险：`planningState` 可能达到十几 MB，MySQL `max_allowed_packet` 过小会失败。

控制：

- 上线前确认 MySQL `max_allowed_packet`。
- 优先使用 `workspace-state` 轻量接口。
- 中长期拆分 `planningState`，例如 `planning_state_meta`、`candidate_pool_state`、`ordered_plan_state`。

### 11.3 已提交方案被误改

风险：用户已经提交的方案被 V2 当成可编辑方案。

控制：

- 已提交 session 导入时加 locked/pinned 或只读态。
- 前端展示“已提交方案”。

### 11.4 planEditCache 污染当前方案

风险：把未确认意向自动应用到最终方案。

控制：

- `planEditCache` 只提示，不直接改 `orderedPlanState`。

### 11.5 移动端工作台过重

风险：移动端表格、筛选、排序操作体验差。

控制：

- 优先保证方案查看和导出。
- 复杂编辑能力可逐步开放。
- 筛选和专业详情做移动端卡片化。

## 12. 建议开发任务拆分

### P0

- 后端新增 legacy plan import 懒迁移。
- 导入优报项到 `draftPlanState` 和 `orderedPlanState`。
- 保留候补项在 `candidatePoolState`。
- 已提交方案只读/锁定。
- 增加迁移日志。
- 增加 5 类迁移单测。

### P1

- 前端 V2 工作台移动端关键样式修复。
- 前端增加“已提交方案”状态展示。
- 前端迁移失败兜底提示和旧页入口。
- 管理端或脚本支持按 sessionId 重置 `planningState`。

### P2

- 离线预迁移活跃 session。
- 拆分大 `planningState` 存储。
- 下线旧页和旧接口。

## 13. 最小上线判断

满足以下条件后，可以开始小流量灰度：

- 老用户会话列表可正常打开。
- 至少 20 个真实历史 session 迁移成功。
- 已提交方案和老页面顺序一致。
- 未提交方案优报/候补数量一致。
- 移动端能查看方案，不出现横向撑破页面。
- 一键删除 `planningState` 后可回旧页。
- 后端日志能定位每次迁移来源和数量。

