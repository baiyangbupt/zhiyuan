# 一期规划状态落地说明

更完整的整体方案与分期说明见：

- [planning-state-roadmap.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/planning-state-roadmap.md)
- [planning-recommendation-current-state.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/planning-recommendation-current-state.md)
- [planning_state_full_design.md](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/planning_state_full_design.md)

## 背景

当前系统已经具备较强的自动生成志愿方案能力，但用户对方案的可干预性不足。为支持后续的候选池、草稿、排序、审查与补偿闭环，一期先在 backend 落地统一的 `planningState` 状态骨架。

## 一期已落地内容

### 1. 规划状态聚合对象

新增 `planningState` 聚合状态，使用 `ChatSessionExtraDataConstants.PLANNING_STATE_KEY` 持久化到 `assistant_chat_session_extra_data`。

状态结构当前包含：

- `sessionId`
- `version`
- `phase`
- `staleFlags`
- `profileState`
- `constraintState`
- `candidatePoolState`
- `draftPlanState`
- `orderedPlanState`
- `reviewState`
- `pendingActions`

### 2. 扩展画像

`profileState` 当前支持以下三部分：

- `explicitProfile`
  - 显式专业、院校、地域偏好
  - 优势学科
- `latentProfile`
  - `futureDevelopment`
  - `interestPersonality`
  - `familyContext`
- `physicalConstraints`
  - 视力
  - 色觉
  - 身高
  - 其他限制

### 3. 已提供接口

新增内网接口：

- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/state`
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/summary`
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/profile`
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/constraints`
- `PATCH /gaotu-assistant-bot/inner/planning/{tenantId}/session/profile/explicit`
- `PATCH /gaotu-assistant-bot/inner/planning/{tenantId}/session/profile/latent`
- `PATCH /gaotu-assistant-bot/inner/planning/{tenantId}/session/profile/physical`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/constraints/derive`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/generate`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/query`

### 4. 状态失效规则

本期先统一实现画像更新后的失效标记：

- 更新显式画像：`candidatePool=true`、`orderedPlan=true`、`review=true`
- 更新潜在画像：`candidatePool=true`、`orderedPlan=true`、`review=true`
- 更新身体条件：`candidatePool=true`、`orderedPlan=true`、`review=true`

### 5. 新增派生偏好与候选池

本轮补充了两项能力：

- `constraints/derive`
  - 从潜在画像中推导 `derivedPreferences`
  - 当前推导包括推荐专业簇、就业倾向、学费弹性
- `candidate-pool/generate` / `candidate-pool/query`
  - 复用现有志愿推荐链路生成候选池
  - 将冲、稳、保结果打平成候选项列表
  - 支持按层级、省份、学校关键词、专业关键词、标签进行内存筛选

### 6. 新增草稿状态

本轮继续补充了草稿层：

- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/draft`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/draft/select`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/draft/remove`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/draft/lock`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/draft/ban`

草稿状态当前支持：

- 候选加入草稿
- 草稿项移除
- 草稿项锁定
- 候选项禁用
- 草稿总数与冲稳保统计

草稿变更后统一标记：

- `orderedPlan=true`
- `review=true`

### 7. 新增排序状态

本轮继续补充了排序层：

- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/generate`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/move`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/pin`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/unpin`

排序状态当前支持：

- 基于草稿生成初始排序结果
- 按草稿顺序或按冲稳保分层生成
- 手动上下移动排序项
- 固定指定志愿的位置并在重排时保留
- 输出总数、冲稳保统计、梯度检查、保底检查

排序变更后统一标记：

- `orderedPlan=false`
- `review=true`

### 8. 推荐覆盖层联动补强

为对齐“临时查看 / 软偏好 / 硬约束”三类语义，本轮对推荐覆盖层补充了后续链路联动：

- `candidatePoolState` 继续承载基础候选成员
- `recommendationOverlayState` 承载推荐分、专家优选组合、推荐理由等可随软意向变化的覆盖信息
- 候选查询、排序生成、审查执行、补偿预览/应用均改为优先消费“基础候选池 + 推荐覆盖层”的合并结果
- 当 `recommendationOverlay=true` 时，这些接口会按需刷新 overlay，而不会直接重建基础候选池

这样可以保证：

- 软意向变化会影响默认推荐顺序和“专家优选组合”
- 不会把整个候选基础池误判为失效
- 后续草稿、排序、审查、补偿与候选面板口径一致

## 后续迭代方向

### 二期接口

- `constraints/derive`
- `candidate-pool/generate`
- `candidate-pool/query`
- `draft/select`
- `draft/remove`
- `ordered-plan/generate`
- `review/run`

### 二期规则纳入

后续将把 `risk_management` 和数量校验中的规则配置化，纳入 `reviewState`：

- 区间配比合理性
- 兜底安全性
- 倒挂现象
- 梯度断层
- 高收费提示
- 限报要求提示

## 测试

本期已新增 `PlanningStateServiceTest`，覆盖：

- 无状态时默认初始化
- 潜在画像写入持久化
- stale flags 更新
- version 递增
- 派生偏好生成
- 候选池生成与查询
- 草稿的加入、删除、锁定
- 排序方案生成、移动、固定/取消固定
