# Planning Workspace Light Refresh Design

记录 `sessionDetailV2` 工作台点击刷新时的轻量化设计。背景问题来自 2026-05-05 线上 session 59：完整 `/session/state` 响应约 20MB，公网传输和浏览器 JSON 解析会造成明显等待。

## 问题

当前工作台刷新调用：

```text
GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/state?chatSessionId={id}
```

该接口返回完整 `PlanningStateDTO`，包含：

- `candidatePoolState.items / units`
- `recommendationOverlayState`
- `initialRecommendationState`
- `planAdjustmentState`
- `draftPlanState`
- `orderedPlanState`
- `reviewState`

其中候选池和推荐覆盖层是主要体积来源。对右侧工作台来说，刷新首屏只需要摘要、草稿、方案、审查和候选分页入口，不需要一次性拿完整候选明细。

## 目标

- 点击工作台刷新时不再传输完整 `PlanningStateDTO`。
- 保留候选列表的分页查询能力，候选 tab 只拉当前页。
- 不改变现有完整 `/session/state`，避免影响 agent、旧页面和调试入口。
- 第一阶段只做返回结构轻量化，不改数据库存储，降低风险。

## 新接口

新增：

```text
GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/workspace-state?chatSessionId={id}
```

返回 `PlanningWorkspaceStateRes`：

```ts
{
  sessionId,
  version,
  phase,
  staleFlags,
  planGenerationState,
  candidatePoolState: {
    generatedAt,
    sourceVersion,
    requiredCount,
    requiredTierCounts,
    requiredMajorCount,
    userScore,
    batchScore,
    sourceProvinceName,
    volunteerModel,
    summary
  },
  candidateViewState,
  draftPlanState,
  orderedPlanState,
  reviewState,
  pendingActions,
  operationLogs
}
```

明确不返回：

- `candidatePoolState.items`
- `candidatePoolState.units`
- `recommendationOverlayState`
- `initialRecommendationState`
- `planAdjustmentState`
- `profileState`
- `constraintState`

## 前端刷新策略

`WorkspacePanel.fetchPlanningState()` 改为 `fetchWorkspaceState()`：

1. 页面初始化拉 `workspace-state`。
2. 如果当前处于候选 tab，或需要刷新候选展示，再调用 `candidate-pool/query` 拉第一页。
3. 方案 tab 的刷新只更新摘要、草稿、方案和审查，不拉候选明细。
4. 方案上移、下移、固定、取消固定继续消费 `OrderedPlanActionRes`，不回退全量 state。

候选列表继续使用：

```text
POST /session/candidate-pool/query
```

## 后续存储优化

本设计第一阶段仍会在后端读取完整 JSON，再裁剪响应，因此主要解决公网传输和前端解析慢。

下一阶段应拆分存储：

- `planning_state_meta`
- `candidate_pool_state`
- `recommendation_overlay_state`
- `draft_plan_state`
- `ordered_plan_state`
- `review_state`

这样才能进一步减少后端从 MySQL 读取、反序列化和更新 20MB JSON 的成本。
