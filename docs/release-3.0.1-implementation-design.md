# Release 3.0.1 Implementation Design

本文档是 `3.0.1` 稳定修复版的实施设计，承接 `docs/release-3.0.1-stability-plan.md`。

文档职责：

- `stability plan` 负责版本范围、优先级和发布准入，是是否进入 `3.0.1` 的唯一来源。
- 本文只描述已经进入 `3.0.1` 的事项如何落地，包括后端状态、接口、前端交互、测试和技术取舍。
- 新增反馈先进入 `stability plan` 或 backlog，确认优先级后再补充到本文。

## 1. 后端设计

### 1.1 导出序号连续

现状：

- 新版导出入口为 `PlanningStateController.exportOrderedPlan`。
- 服务层入口为 `PlanningStateService.exportOrderedPlan`。
- 导出内容由 `PlanningExcelExportBuilder.build` 转成 `ExcelUtil.VolunteerExcelData`。

设计：

- 导出时以 `orderedPlanState.items` 当前有效顺序为准重新编号。
- 不信任历史 `position`、迁移源文件序号或前端传入序号。
- `major` 模式按志愿条目连续编号。
- `majorGroup` 模式按专业组 unit 连续编号；组内专业行如果导出为多行，需要保持同一个组序号或明确使用组内序号，不能出现主序号跳号。

验收：

- 新建方案、迁移 `_final` 方案、迁移 `_temp` 方案、手动移动后方案导出序号均从 1 连续递增。
- 页面顺序和导出顺序一致。

### 1.2 空候选和少候选状态

现状：

- `generateInitialPlan` 会在候选池为空或过期时调用 `generateCandidatePool`。
- 生产样本出现过专项过滤后候选为 0，但流程表现为“成功生成空方案”。

设计：

- `generateCandidatePool` 完成候选平铺后增加结果质量判断：
  - `candidate_pool_empty`：冲/稳/保全部为空，或有效候选总数为 0。
  - `candidate_pool_low_count`：有效候选数低于目标数量，或低于可配置阈值。
- 状态需要进入规划状态，供工作台接口返回；建议新增轻量字段 `candidatePoolState.statusCode/statusMessage/riskHints`，避免只靠异常文本。
- `generateInitialPlan` 遇到 empty 状态时不继续生成空方案。
- 对 low count 状态允许继续生成，但前端必须展示风险提示。
- 提示原因优先来自实际过滤上下文：专项资格、批次、分数线、专业/地域偏好、身体条件限制。

验收：

- 空候选时页面看到可理解原因，不显示“生成成功但没有方案”。
- 少候选时生成结果可见，同时提示“候选偏少，方案选择空间有限”。
- 专项过滤、分数线边界、偏好过窄至少各有一个测试样本。

### 1.3 方案状态和审查状态

现状：

- 前端能看到“区间顺序合理”“待调整”等结果，但这些文案没有形成清晰状态机。
- 审查结果数据已经进入工作台面板，但缺少用户主动触发审查的入口。

设计：

- 后端工作区状态需要稳定输出以下用户侧状态域：
  - `candidateStatus`：候选池是否已生成、为空、偏少、异常。
  - `planStatus`：方案是否为空、已选择、已生成、待更新、历史只读。
  - `reviewStatus`：未审查、审查中、通过、有风险、审查失败。
  - `exportStatus`：未导出、已导出、最近导出时间。
- 状态域由后端根据 planning state 派生，前端只负责展示，不自行拼接业务结论。
- `draftPlanState` 可以继续作为后端内部数据结构或兼容字段存在，但不作为用户侧状态，不在前端文案中展示“草稿”。
- 保留现有 review 接口，前端新增“执行审查/重新审查”按钮触发 `runReview`。
- 审查结果不自动修改方案顺序；如需要调整，必须进入明确的调整动作。

验收：

- 新建方案、迁移方案、手动调整后方案都能得到稳定状态。
- 用户能直接触发审查并看到结果刷新。
- 状态文案能区分“方案未生成”“方案已生成待审查”“审查有风险”“有待确认调整”。

### 1.4 状态值和状态转换

后端工作区接口需要返回统一的 `workflowStatus`，前端以该字段作为主展示依据。已有的 `phase/staleFlags/candidatePoolState/draftPlanState/orderedPlanState/reviewState` 继续保留，但只作为状态计算来源，不再要求前端自行拼接总状态。

产品口径：

- 用户侧不再出现“草稿”概念。
- 候选列表下方的篮子直接叫“方案”或“当前方案”，含义是“已经加入方案、待系统排序或已形成排序方案的志愿集合”。
- 新版本没有“提交状态”。历史版本兼容的已提交方案只作为 `legacySubmitted=true` 或“历史已确认方案”提示，不进入新版本主状态机。

建议结构：

```json
{
  "candidateStatus": "ready",
  "candidateMessage": "候选池已生成",
  "planStatus": "pending_review",
  "planMessage": "方案已生成，待审查",
  "legacySubmitted": false,
  "legacyMessage": null,
  "reviewStatus": "not_reviewed",
  "reviewMessage": "方案尚未审查",
  "exportStatus": "not_exported",
  "exportMessage": "方案尚未导出",
  "lastExportedAt": null
}
```

#### 1.4.1 候选状态 `candidateStatus`

| 状态值 | 含义 | 进入条件 | 下一步 |
| --- | --- | --- | --- |
| `not_generated` | 候选池尚未生成 | 无 `generatedAt`，且无候选 summary | 触发候选生成 |
| `generating` | 候选生成中 | 后端开始生成候选但未完成，若当前链路同步执行可暂不落库 | 等待完成 |
| `ready` | 候选池可用 | 有有效候选，且候选数量达到目标或可正常生成方案 | 加入方案或生成方案 |
| `low_count` | 候选偏少 | 有候选，但有效数量低于目标数量或配置阈值 | 允许继续生成，同时提示风险 |
| `empty` | 无可用候选 | 有生成结果，但有效候选数为 0 | 阻止继续生成空方案，提示调整条件 |
| `failed` | 候选生成失败 | 推荐接口异常、数据解析异常或业务失败 | 提示稍后重试或联系排查 |

候选状态计算规则：

- `effectiveCandidateCount = candidatePoolState.summary.total`，专业组模式可同时参考 `summary.unitTotal`。
- `requiredCount` 优先取 `candidatePoolState.requiredUnitCount` 或 `requiredCount`，具体按 `volunteerModel` 区分。
- `empty` 优先级高于 `low_count`。
- `low_count` 只是风险提示，不阻断后续生成。
- `empty` 必须阻断 `generateInitialPlan` 后续步骤，不能继续写入空方案。

用户文案：

- `not_generated`：候选池尚未生成。
- `ready`：候选池已生成。
- `low_count`：当前条件下可用候选偏少，方案选择空间有限。
- `empty`：当前条件下没有可用志愿候选，请检查专项资格、批次、分数线或筛选条件。
- `failed`：候选生成失败，请稍后重试。

#### 1.4.2 方案状态 `planStatus`

| 状态值 | 含义 | 进入条件 | 下一步 |
| --- | --- | --- | --- |
| `empty` | 方案为空 | 内部 `draftPlanState.items` 和 `orderedPlanState.items` 均为空 | 从候选加入或生成初始方案 |
| `selected` | 已加入方案，待生成顺序 | 内部 `draftPlanState.items` 有内容，但 `orderedPlanState.items` 为空 | 生成方案顺序 |
| `ready` | 方案已生成 | 排序方案有条目，未过期 | 审查、调整、导出 |
| `dirty` | 方案有调整，待更新 | 用户从候选加入、删除或调整后设置 `staleFlags.orderedPlan=true` | 更新方案 |
| `pending_review` | 方案已生成，待审查 | 方案有条目，`staleFlags.review=true` 或无 `reviewedAt` | 执行审查 |
| `legacy_readonly` | 历史已确认方案，只读查看 | `generationMode=legacy_submitted` 或历史导入条目锁定 | 只读查看或重新生成新方案 |

方案状态计算规则：

- 用户侧不暴露“草稿”，内部 `draftPlanState` 只参与判断方案是否已有选择、是否待更新。
- `legacy_readonly` 只用于历史兼容，不表示新版本有“提交状态”。
- `dirty` 优先级高于 `pending_review`，因为方案本身需要先更新。
- 若方案有条目且 review 过期，返回 `pending_review`。
- “区间顺序合理”“梯度断层”等不作为总状态，只进入 review checks。

用户文案：

- `empty`：当前方案为空。
- `selected`：已加入方案，待生成顺序。
- `ready`：方案已生成。
- `dirty`：方案有待更新调整。
- `pending_review`：方案已生成，待审查。
- `legacy_readonly`：历史已确认方案，建议只读查看。

#### 1.4.3 审查状态 `reviewStatus`

| 状态值 | 含义 | 进入条件 | 下一步 |
| --- | --- | --- | --- |
| `not_reviewed` | 尚未审查 | 无 `reviewedAt`，或无 review checks | 点击执行审查 |
| `running` | 审查中 | 审查接口执行中，前端本地 loading；若后端改异步可落库 | 等待结果 |
| `passed` | 审查通过 | 有审查结果，risk/warn 数量均为 0 | 可导出 |
| `has_warning` | 有提醒 | warn > 0，risk = 0 | 查看提醒，可继续导出 |
| `has_risk` | 有风险 | risk > 0 | 查看风险，建议调整后复审 |
| `stale` | 审查已过期 | `staleFlags.review=true` 且已有旧审查结果 | 重新审查 |
| `failed` | 审查失败 | 审查接口异常或业务失败 | 稍后重试 |

审查状态计算规则：

- `stale` 优先于旧的 `passed/has_warning/has_risk` 展示。
- `risk > 0` 返回 `has_risk`。
- `warn > 0` 返回 `has_warning`。
- 只有 risk/warn 都为 0 时返回 `passed`。
- 审查不自动修改方案，只提供风险说明和调整建议。
- 当前端看到 `stale` 时，旧审查结果已经不适用于当前方案顺序；方案区不再展示旧风险/提醒惊叹号 tooltip，只保留“审查”按钮引导重新审查。

用户文案：

- `not_reviewed`：方案尚未审查。
- `running`：正在审查方案。
- `passed`：审查通过，暂无明显风险。
- `has_warning`：审查有提醒，建议查看。
- `has_risk`：审查发现风险，需要查看。
- `stale`：方案已调整，建议重新审查。
- `failed`：审查暂未完成，请稍后重试。

#### 1.4.4 导出状态 `exportStatus`

| 状态值 | 含义 | 进入条件 | 下一步 |
| --- | --- | --- | --- |
| `not_exported` | 尚未导出 | 无导出事件或导出时间 | 可导出 |
| `exporting` | 导出中 | 前端导出请求进行中；同步链路可只做前端 loading | 等待完成 |
| `exported` | 已导出 | 服务端成功生成导出文件并记录事件 | 可继续调整或再次导出 |
| `stale` | 导出后方案又变化 | 最近导出版本低于当前方案版本 | 重新导出 |
| `failed` | 导出失败 | 导出接口异常或业务失败 | 稍后重试 |

导出状态计算规则：

- 服务端成功导出后记录 `plan_export` 行为事件，作为导出状态来源。
- `exported` 不等同于真实填报结果，只代表用户对当前方案有较强认可。
- 若导出后发生加入、删除、排序、移动等方案操作，导出状态转为 `stale`。

用户文案：

- `not_exported`：方案尚未导出。
- `exporting`：正在导出方案。
- `exported`：方案已导出。
- `stale`：方案已调整，建议重新导出。
- `failed`：导出失败，请稍后重试。

#### 1.4.5 主流程状态转换

标准新建会话：

```text
candidate.not_generated
  -> generateCandidatePool
candidate.ready / candidate.low_count / candidate.empty
  -> generateInitialPlan
plan.selected
  -> generateOrderedPlan / reorderDraftPlan
plan.ready + review.not_reviewed
  -> runReview
review.passed / review.has_warning / review.has_risk
  -> exportOrderedPlan
export.exported
```

空候选分支：

```text
candidate.not_generated
  -> generateCandidatePool
candidate.empty
  -> stop
plan.empty
review.not_reviewed
export.not_exported
```

用户调整分支：

```text
plan.ready + review.passed/export.exported
  -> add/remove/move/pin
plan.dirty
review.stale
export.stale
  -> regenerate/reorder
plan.pending_review
  -> runReview
```

历史迁移分支：

```text
legacy_final
  -> plan.legacy_readonly
  -> review.not_reviewed 或 review.stale

legacy_temp
  -> plan.ready
  -> review.not_reviewed 或 review.stale
```

#### 1.4.6 状态优先级

同一层状态存在多个条件时，按以下优先级计算：

- 候选：`failed > empty > low_count > ready > generating > not_generated`
- 方案：`legacy_readonly > dirty > empty > selected > pending_review > ready`
- 审查：`failed > stale > has_risk > has_warning > passed > running > not_reviewed`
- 导出：`failed > stale > exported > exporting > not_exported`

#### 1.4.7 前端展示原则

- 顶部总状态只展示用户可理解的组合文案，不直接展示枚举值。
- 审查项里展示“区间顺序合理”“梯度断层”等专业判断，不再把它们作为方案总状态。
- 前端不展示“草稿”“排序区”“提交”等系统概念；候选下方篮子文案统一为“方案”。
- 新版本不展示提交状态；历史兼容只展示“历史已确认方案，建议只读查看”。
- 主按钮按状态变化：
  - `candidate.empty`：展示“调整条件”，不展示导出主按钮。
  - `plan.pending_review/review.not_reviewed`：展示“执行审查”。
  - `review.stale`：展示“重新审查”。
  - `plan.dirty`：展示“更新方案”。
  - `review.passed/has_warning/has_risk` 且 plan ready：允许导出。

### 1.5 指定目标位置移动

现状：

- 后端已有 `ordered-plan/move`，请求体包含 `volunteerId` 和 `targetPosition`。
- 当前能力本质上已经支持移动到目标位置，前端需要暴露更高效的输入和快捷动作。

设计：

- 保留现有接口，补齐边界测试。
- 服务端继续负责位置归一化、固定项边界、position 重建。
- 前端增加确认式“移动到第 N 位”，并提供“移到顶部”“移到底部”快捷动作。
- 操作成功后消费后端轻量动作响应合并排序态，不在前端本地猜测最终顺序。
- 单条移动与方案排序一致，成功后将 `review` 和 `planAdjustment` 标记为过期，前端展示为“待重新审查”。

验收：

- 移动后 position 连续。
- 固定项不可被越过或破坏；旧草稿锁定仅作为历史兼容字段，不作为新版前端方案调整入口。
- 目标位置越界时服务端按合法边界处理或返回明确错误。
- 移动后审查状态不再沿用旧方案顺序下的结论。

### 1.6 历史方案候选详情解析

现状：

- 新版本正常创建的方案项会沿用候选池的 `volunteerId`，候选、方案、排序区 ID 一致。
- 部分历史兼容/迁移会话中，排序方案项保存的 `volunteerId` 第三段来自旧版 `majorId`，而候选池当前 `volunteerId` 第三段来自 `planMajorDataId`，导致直接按 `volunteerId` 匹配失败。
- `/session/workspace-state` 为了减小响应体，只返回当前工作区引用的候选明细；如果按 ID 过滤失败，前端刷新后无法补齐方案卡片的录取率、推荐系数、院校排名标签等字段。
- 方案排序按院校层次、录取率、推荐系数取值时也依赖候选明细；历史 ID 不一致会导致排序字段为空，排序退化为原始顺序。

设计：

- 后端新增统一候选解析器，用于工作区轻量状态和方案排序。
- 匹配优先级：
  - 精确 `volunteerId`，保障新版本新会话主链路不受影响。
  - 兼容旧 ID 前两段，即 `planSchoolDataId + planMajorDataId` 一致时可解析到当前候选。
  - `schoolName + majorName` 唯一匹配兜底，只在无歧义时生效。
- `/session/workspace-state` 继续保持轻量，不恢复全量 `candidatePoolState.items`，但必须返回当前草稿/方案引用到的候选明细。
- 方案排序的比较器使用同一解析器取 `schoolRank/admissionRatio/finalScore`，避免展示和排序使用两套匹配口径。
- 方案排序是实际改写方案顺序的操作，成功后需要将 `review` 和 `planAdjustment` 标记为过期；若已有审查结果，工作区状态应展示为“待重新审查”。
- 前端不做模糊匹配，不依赖候选分页加载顺序修复方案卡片字段。

验收：

- 新版本新会话方案项与候选项精确 ID 匹配时行为不变。
- 历史迁移会话中，方案 `volunteerId` 与候选 `volunteerId` 第三段不一致时，工作区刷新后仍能展示录取率、推荐系数、院校排名标签。
- 历史迁移会话按院校层次排序时，能实际按院校排名升序，并继续按录取率、推荐系数做二三级排序。
- 专业+大学和院校专业组模式都不能因为兼容解析导致重复候选或误匹配。

### 1.7 专业组组级删除和移动

现状：

- `majorGroup` 模式下 `orderedPlanState.units` 已能表达组级结构。
- 现有移动接口以 `volunteerId` 为主，不足以表达按组操作。

设计：

- 新增组级操作接口，或扩展现有请求增加 `unitId` 和 `operationScope=unit`。
- 推荐新增接口，减少兼容风险：
  - `POST /session/ordered-plan/unit/move`
  - `POST /session/ordered-plan/unit/remove`
- 组级移动时，以 unit 为单位移动，组内 item 顺序不变。
- 组级删除时，删除 unit 下所有 item，并重建 `orderedPlanState.items/units/summary`。
- 非 `majorGroup` 模式调用组级接口时返回明确业务错误。

验收：

- 删除专业组不会残留孤立专业。
- 移动专业组不会打散组内专业。
- 组级操作后导出序号连续。

### 1.8 行为反馈事件

现状：

- `PlanningStateDTO.operationLogs` 只有 `type/operator/detail/createdAt/volunteerIds`，适合用户可读操作日志。
- 该结构缺少位置、概率、模式、方案来源、快照关联等字段，不适合作为算法优化数据。

设计：

- 新增结构化行为事件，建议命名为 `PlanningBehaviorEventDTO`，与 `OperationLogDTO` 分离。
- 存储优先级：
  - 首期可随 planning state JSON 存储，降低数据库变更风险。
  - 若生产需要跨会话统计，后续迁移到独立表或日志管道。
- 每次服务端成功完成方案操作后记录事件；前端不单独上报“意图事件”作为主依据。
- 导出成功后记录 `plan_export`，并关联导出时的方案版本和快照摘要。
- 记录失败不能阻断用户主流程；事件写入异常只打 warning 日志。

事件类型：

| 事件 | 触发时机 | 反馈含义 |
| --- | --- | --- |
| `candidate_add_to_plan` | 候选加入方案成功 | 用户认可候选进入方案 |
| `plan_item_remove` | 从方案删除成功 | 用户否定或暂不需要该志愿 |
| `plan_item_move` | 单条移动成功 | 用户调整排序偏好 |
| `plan_unit_move` | 专业组移动成功 | 用户调整组级排序偏好 |
| `plan_unit_remove` | 专业组删除成功 | 用户否定或暂不需要该专业组 |
| `plan_sort_apply` | 应用排序结果成功 | 用户认可某种排序规则 |
| `plan_export` | 导出成功 | 强正反馈，但不等同真实填报 |

核心字段：

- `eventId`
- `chatSessionId`
- `tenantId`
- `eventType`
- `mode`: `major` 或 `majorGroup`
- `planVersion`
- `generationMode`
- `source`: `new_session`、`legacy_final`、`legacy_temp`、`external_initialize`
- `volunteerIds`
- `unitIds`
- `fromPositions`
- `toPositions`
- `tier`
- `admissionRatio`
- `schoolName`
- `majorName`
- `sortKey`
- `positiveFeedback`
- `snapshotDigest`
- `createdAt`

验收：

- 添加、删除、移动、组级移动/删除、应用排序、导出均能查到结构化事件。
- 导出事件能定位到当时方案版本或快照摘要。
- 事件写入失败不影响方案操作成功。

## 2. 前端 Web 设计

### 2.0 桌面端工作区布局

设计：

- `sessionDetailV2` 桌面端双栏兼顾对话阅读和工作面板操作。
- 标准视图比例调整为：左侧对话约 43%，右侧工作面板约 57%。
- 移动端继续保持单栏对话主视图和工作台抽屉，不随本项调整。

验收：

- 桌面端方案、候选、排序、审查操作拥有稳定横向空间。
- 对话区仍能完整承载消息阅读和输入，不因过窄影响会话体验。
- 移动端布局不受影响。

### 2.1 返回会话列表

设计：

- 在 `sessionDetailV2` 主界面顶部增加明显的“返回会话列表”。
- 默认跳转 `/assistant-pc/session`。
- 后续如需要从客户详情页返回，可通过 query 传 `returnTo`，本期不强依赖。
- `sessionDetailLegacy` 不再补新入口或新交互，后续统一迁到新版页面。

验收：

- 用户不依赖浏览器返回按钮即可返回列表。
- `/sessionDetailV2` 不出现导航断点。

### 2.2 状态管理和审查入口

设计：

- 方案面板顶部展示组合状态，而不是散落展示弱文案：
  - 方案生成状态。
  - 方案调整状态。
  - 审查状态。
  - 最近导出状态。
- “区间顺序合理”这类技术判断需要归入审查项或风险项，不能作为唯一总状态。
- 在审查状态旁提供“执行审查/重新审查”按钮。
- 审查中显示 loading，成功后刷新 workspace state，失败时提示“审查暂未完成，请稍后重试”。
- 不再展示“草稿”。候选下方篮子直接展示为“方案”，状态文案使用“已加入方案，待生成顺序”或“方案有调整，待更新”。

验收：

- 用户能理解当前是否已有方案、是否需要审查、是否有待处理调整。
- 审查入口在方案面板内可见，且触发后结果刷新。

### 2.3 方案排序

设计：

- 方案区增加排序控件，默认“当前顺序”。
- 支持查看排序：录取率、院校层次、推荐系数。
- 不再提供冲稳保、专业名、学校名、分数/位次排序入口。
- 查看排序不改写服务端方案顺序。
- 如果需要把当前排序应用为方案顺序，必须点击明确的“应用到方案顺序”，并记录 `plan_sort_apply`。
- 本节只约束方案列表排序，不影响候选列表排序。候选列表仍保留推荐系数、录取率、院校层次、区间位次、专业热度、薪酬指数、学费等更多筛选浏览维度。
- 方案排序使用稳定的多级规则：
  - 录取率：录取率升序 -> 院校排名升序 -> 推荐系数降序。
  - 院校层次：院校排名升序 -> 录取率升序 -> 推荐系数降序。
  - 推荐系数：推荐系数降序 -> 录取率升序 -> 院校排名升序。
- 方案卡片展示候选侧已有的院校排名标签，辅助用户理解“院校层次”排序依据。

验收：

- 切换排序后可恢复当前顺序。
- 未应用时导出仍按服务端方案顺序。
- 候选页排序字段不因方案排序收口而减少。
- 一级排序值相同时，排序结果不再随机打散，而是继续按约定的二、三级字段稳定排序。

### 2.4 历史分数展示

设计：

- 方案和候选行展示近三年分数/位次摘要。
- 数据优先使用已有 `schoolHistoryScores / majorHistoryScores`。
- 缺失显示“暂无”，不显示内部占位值。
- 专业组模式默认展示组级摘要，展开后展示组内专业明细。
- `salaryAvg` 在前端统一展示为“薪酬指数”，表示相对水平，不等同于实际工资。
- 方案区标签收敛为决策必要信息：院校/专业组标题后仅保留“院校排名”和“录取率”，不展示“意向省份”“优选”“系统初排”“已调整”等标签；冲稳保不在标题区重复展示，避免挤压学校/专业组名称和操作按钮。

验收：

- 信息不撑破列表布局。
- 专业组模式不把单个专业分数误写成整个专业组承诺。
- 专业+大学和院校专业组模式下，方案卡片标题区都不再被非必要标签挤压。

### 2.5 移动和组级操作

设计：

- 单条志愿菜单增加：
  - 移动到第 N 位。
  - 移到顶部。
  - 移到底部。
- `majorGroup` 模式下，组标题区域增加组级操作：
  - 移动专业组到第 N 位。
  - 删除专业组。
- 成功后统一刷新工作区状态。

验收：

- 操作按钮不挤压学校名和概率展示。
- 失败时提示用户可理解原因。

### 2.6 页面空间、方案篮子和长列表定位

设计：

- 前端不再露出草稿概念，候选 tab 内的篮子直接命名为“方案”。
- “加入方案”“已加入方案”“当前方案”作为主要文案，不使用“加入草稿”“已选草稿”。
- 候选 tab 内方案篮子优先展示 `orderedPlanState.items`，确保方案页排序、移动和固定后的顺序能同步呈现；没有排序方案时才回退内部 `draftPlanState.items`。
- 新版前端不再展示旧草稿 `lock/unlock` 操作，也不展示“已锁定”标签；用户侧位置固定统一使用方案区 `pin/unpin`。
- 后端删除方案项时不再使用旧 `draftItem.locked` 字段阻断删除，避免历史锁字段在新版界面不可见但仍影响用户操作。
- 方案篮子使用独立色系，避免与候选志愿条目的红色风险/冲刺标签混在一起。
- 方案篮子色系建议使用蓝色或中性色，含文字标识；不要只靠颜色区分。
- 顶部数字概览支持折叠。
- 冲稳保颜色统一：冲=红，稳=橙，保=绿。
- 方案和候选列表各自增加回到顶端。
- 方案和候选长列表增加滑杆或快速定位控件：
  - 优先使用当前滚动容器的原生滚动条增强样式，避免额外复杂虚拟滚动改造。
  - 如已有虚拟列表，使用列表组件提供的 scrollTo 能力。
  - 快速定位至少支持回到顶部、到底部；如成本可控，可补按序号定位。
- 候选筛选标签优化：
  - 城市类标签默认只展示有限数量，超出部分折叠到“更多”。
  - 城市数量较多时提供关键词搜索，支持按城市名快速过滤。
  - 如筛选项天然有省/市层级，优先按省份或区域分组展示。
  - 当前已选标签始终前置或固定展示，避免折叠后用户不知道已选条件。
  - 筛选区默认高度可控，不挤压候选列表主体。

验收：

- 用户不需要理解草稿概念，只需要理解候选可以加入方案。
- 方案篮子与候选志愿条目有明显区分。
- 折叠概览后方案可视空间增加。
- 长列表可以快速移动和定位，不需要大量滚轮操作。
- 城市标签默认展开不会占满筛选区，用户能通过搜索、更多或分组快速定位目标城市。
- 已选城市标签清晰可见，折叠和搜索不会丢失已选状态。

## 3. 接口变更草案

### 3.1 新增组级移动

```http
POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/unit/move?chatSessionId={chatSessionId}
Content-Type: application/json

{
  "unitId": "group-xxx",
  "targetPosition": 12
}
```

返回沿用 `OrderedPlanActionRes`。

落地状态：

- 后端已新增接口，移动时按 `unitId` 整组搬迁，组内专业顺序保持不变。
- 操作成功后重建 `orderedPlanState.items/units`，并将 `review` 与 `planAdjustment` 标记为过期。
- 成功操作记录 `plan_unit_move` 行为事件，包含 `unitIds` 和组内 `volunteerIds`。

### 3.2 新增组级删除

```http
POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/unit/remove?chatSessionId={chatSessionId}
Content-Type: application/json

{
  "unitIds": ["group-xxx"]
}
```

返回沿用工作区轻量状态或 `OrderedPlanActionRes`，详细实现阶段二选一，优先减少前端刷新次数。

落地状态：

- 后端已新增接口，删除时同步移除 `draftPlanState.items/units` 与 `orderedPlanState.items/units` 中对应专业组，避免候选页方案篮和方案页不一致。
- 操作成功后重算 draft / ordered summary，并将 `review` 与 `planAdjustment` 标记为过期。
- 成功操作记录 `plan_unit_remove` 行为事件，包含 `unitIds` 和组内 `volunteerIds`。

### 3.3 行为事件查询

```http
GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/behavior-events?chatSessionId={chatSessionId}
```

用途：

- 本地验证和运维排查。
- 后续策略分析导出。

生产前端默认不需要展示该接口。

## 4. 测试计划

### 4.1 后端测试

- 导出序号连续：
  - `major` 新建方案。
  - `majorGroup` 新建方案。
  - legacy `_final` 已提交方案。
  - legacy `_temp` 未提交方案。
  - 手动移动后导出。
- 空候选/少候选：
  - 专项过滤为空。
  - 分数线边界候选少。
  - 偏好过滤过窄。
- 移动：
  - 移到顶部。
  - 移到底部。
  - 移到中间位置。
  - 锁定项边界。
- 专业组：
  - 组级移动。
  - 组级删除。
  - 删除后导出。
- 行为事件：
  - 每类事件成功记录。
  - 事件写入失败不阻断主流程。

### 4.2 前端测试

- `yarn build` 通过。
- 桌面宽屏和常规笔记本宽度截图验证。
- 返回会话列表入口可见且可点击。
- 方案状态展示清晰，审查入口可触发并刷新结果。
- 排序查看和恢复当前顺序。
- 排序入口只包含录取率、院校层次、推荐系数。
- 应用排序前后导出顺序符合预期。
- 移动到指定位置交互。
- 专业组组级操作。
- 顶部概览折叠、回到顶端、长列表滑杆或快速定位、颜色统一。
- 候选 tab 内方案篮子与候选志愿条目视觉区分。
- 候选筛选城市标签折叠、搜索或分组后仍能正确筛选。

### 4.3 准生产回归

沿用本地准生产拓扑：

- Web：`3088 -> 28688`
- Backend：`8090`
- Agent：`8091 -> 8009`
- Rank：`8092 -> 5001`

必须覆盖：

- `/assistant-pc/session`
- `/assistant-pc/sessionDetailV2`
- 新建 `major` 会话。
- 新建 `majorGroup` 会话。
- 外部授权初始化会话。
- legacy 迁移会话。
- 方案调整、导出、行为事件查询。

## 5. Changelog 要求

实现阶段必须同步更新：

- `zhiyuan-server/docs/CHANGELOG.md`
- `zhiyuan-web/docs/CHANGELOG.md`

如 Agent 未改代码，不更新 Agent changelog。

## 6. 开放问题

1. 行为事件首期是否随 planning state JSON 保存，还是直接落独立表。
2. 行为事件保留周期和脱敏要求。
3. 专业组历史分数展示以组最低分、代表专业还是组内专业列表为主。
4. 方案排序“应用到方案顺序”是否进入 3.0.1 首版，还是先只做临时查看排序。
5. 顶部数字概览 PC 端默认展开还是默认折叠。
6. 长列表快速定位首版是只做顶部/底部，还是支持输入序号定位。
7. 候选城市筛选首版优先做“更多折叠”，还是同步做关键词搜索和省份分组。
8. `salaryAvg` 展示文案已收敛为“薪酬指数”，是否还需要在排序项、tooltip 和导出文案里继续统一口径。
