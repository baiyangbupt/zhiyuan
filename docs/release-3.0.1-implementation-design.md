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
- 导出回填院校和专业明细时必须复用历史 ID 兼容解析口径：
  - 优先按 `volunteerId` 精确匹配候选。
  - 精确匹配失败时，按旧版 `planSchoolDataId_schoolId_*` 前缀兜底，解决迁移方案中第三段专业 ID 与新版候选 ID 不一致的问题。
  - 仍失败时，按学校名 + 专业名兜底，避免导出文件只剩序号和空行。

验收：

- 新建方案、迁移 `_final` 方案、迁移 `_temp` 方案、手动移动后方案导出序号均从 1 连续递增。
- 页面顺序和导出顺序一致。
- 历史兼容方案即使 `orderedPlanState.items` 或 `orderedPlanState.units.majorItems` 的 `volunteerId` 与候选池第三段 ID 不一致，也能导出院校代码、学校名、专业代码、专业名、计划、学费、学制、选科和历史分数。

#### 1.1.1 导出空数据问题复盘

触发反馈：

- 页面点击“导出”后可以下载 Excel，但表内志愿明细大量为空。
- 从用户视角看像是“导出功能被破坏”，实际问题集中在新导出链路回填候选明细失败。

定位过程：

- 前端导出入口调用 `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/export?chatSessionId={chatSessionId}`。
- 后端 `PlanningStateService.exportOrderedPlan` 读取当前 `planningState.orderedPlanState`，再由 `PlanningExcelExportBuilder.build` 转成 `ExcelUtil.VolunteerExcelData`。
- `ExcelUtil.createDataRows` 会跳过 `majorList` 为空的志愿行，因此只要导出构建器无法从方案项解析到候选专业，最终 Excel 就会表现为空或只剩很少字段。
- 排查发现 `PlanningExcelExportBuilder` 原实现只通过 `candidateMap.get(orderedItem.volunteerId)` 精确匹配候选。
- 但历史迁移方案中，排序方案项保存的 `volunteerId` 第三段可能来自旧版 `majorId`，候选池当前 `volunteerId` 第三段来自新版 `planMajorDataId`。两者前两段一致，第三段不一致。
- 该 ID 不一致问题此前已经在工作区轻量状态和方案排序中通过 `CandidateResolver` 兜底修复，但导出构建器没有同步这套解析口径。

修复方案：

- `PlanningExcelExportBuilder` 新增导出专用候选解析器 `CandidateExportResolver`。
- 解析顺序：
  - 第一优先：按 `volunteerId` 精确匹配。
  - 第二优先：按旧版 `planSchoolDataId_schoolId_*` 前缀匹配，覆盖历史迁移 ID 第三段不一致。
  - 第三优先：按学校名 + 专业名匹配，作为候选明细回填兜底。
- `major` 模式导出时，按 `OrderedItemDTO` 解析候选。
- `majorGroup` 模式导出时，按 `OrderedUnitDTO.schoolName + PlanningUnitMajorDTO.majorName` 结合 unit 内专业 ID 解析候选，避免 unit 里的专业 ID 不一致导致组内专业列表为空。
- 该修复只影响导出明细回填，不改变方案顺序、候选池、排序结果和页面展示。

回归测试：

- `PlanningExcelExportBuilderTest.shouldResolveLegacyMajorSchoolVolunteerIdWhenExporting`
  - 覆盖专业+大学模式下 `orderedPlanState.items.volunteerId` 第三段与候选池不一致。
  - 断言院校代码、学校名、专业代码、专业名可以正常导出。
- `PlanningExcelExportBuilderTest.shouldResolveLegacyMajorGroupVolunteerIdWhenExportingUnits`
  - 覆盖院校专业组模式下 `orderedPlanState.units.majorItems.volunteerId` 第三段与候选池不一致。
  - 断言专业组、专业明细和专业录取率可以正常导出。

验证命令：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningExcelExportBuilderTest,PlanningStateServiceTest#shouldReturnCandidateFilterOptionsFromBackend test
```

本地服务验证：

```bash
# 后端
cd zhiyuan-server
mvn spring-boot:run -Dspring-boot.run.profiles=local -q

# 前端
cd zhiyuan-web
npx env-cmd -f .env.dev next dev -p 3001
```

页面验证：

- 打开 `http://localhost:3001/assistant-pc/session`。
- 进入已有排序方案的会话详情。
- 切换到“方案”页，点击“导出”。
- 检查下载 Excel：
  - 院校代码、院校、专业代码、专业名不为空。
  - 计划、学费、学制、选科、近三年分数/位次能按候选数据回填。
  - 序号从 1 连续递增。

接口验证：

```bash
curl -X POST -L \
  "http://localhost:8080/gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/export?chatSessionId={chatSessionId}" \
  -o /tmp/ordered-plan.xlsx
```

本地重启注意事项：

- `scripts/start.sh` 依赖 `.pids` 判断服务是否已运行；如果 `.pids` 里是旧 PID，可能误判。
- 本次验证中出现过 `.pids` 显示旧服务已退出，但端口仍被实际 `java/node` 进程占用的情况。
- 处理方式：
  - 用 `lsof -nP -iTCP:8080 -sTCP:LISTEN` 和 `lsof -nP -iTCP:3001 -sTCP:LISTEN` 确认真实监听进程。
  - 必要时停止端口上的实际进程后，再以前台长驻方式启动，便于直接观察日志。

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
- 服务端继续负责位置归一化、历史锁定兼容边界、position 重建。
- 前端增加确认式“移动到第 N 位”，并提供“移到顶部”“移到底部”快捷动作。
- 操作成功后消费后端轻量动作响应合并排序态，不在前端本地猜测最终顺序。
- 单条移动与方案排序一致，成功后将 `review` 和 `planAdjustment` 标记为过期，前端展示为“待重新审查”。

验收：

- 移动后 position 连续。
- 历史锁定兼容字段不可在新版界面不可见时阻断正常移动；旧草稿锁定不作为新版前端方案调整入口。
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
- 工作区轻量状态收集候选引用时不能只收集 `volunteerId` 字符串，必须同时保留 `schoolName + majorName` 上下文：
  - `major` 模式来自 `DraftItemDTO/OrderedItemDTO`。
  - `majorGroup` 模式来自 `DraftUnitDTO/OrderedUnitDTO.schoolName + majorItems.majorName`。
  - 返回给前端的候选副本仍使用工作区方案里的 `volunteerId`，保证前端 `candidateItemMap` 可以按方案 ID 精确命中。
- 方案排序的比较器使用同一解析器取 `schoolRank/admissionRatio/finalScore`，避免展示和排序使用两套匹配口径。
- 方案排序是实际改写方案顺序的操作，成功后需要将 `review` 和 `planAdjustment` 标记为过期；若已有审查结果，工作区状态应展示为“待重新审查”。
- 前端不做模糊匹配，不依赖候选分页加载顺序修复方案卡片字段。

验收：

- 新版本新会话方案项与候选项精确 ID 匹配时行为不变。
- 历史迁移会话中，方案 `volunteerId` 与候选 `volunteerId` 第三段不一致时，工作区刷新后仍能展示录取率、推荐系数、院校排名标签。
- 专业组历史会话中，即使同一专业组下多个专业共享旧 ID 前缀，仍可通过专业组名 + 专业名唯一兜底回填候选明细；本地 session 16 验证 `/session/workspace-state` 返回 185 个引用候选、48 个专业组，候选评分字段缺失数为 0。
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
- 方案区优先展示专业级 `majorHistoryScores`，与候选专业表格保持同一口径：近三年录取人数、最低分数、最低位次。
- 方案区专业明细表格照搬候选专业表格结构：专业、2025 招生计划、数据类型、近三年年份列、表格下方推荐系数等参数。
- 方案区不再展示候选右侧的“冲稳保 + 录取率”长条；该位置替换为实体操作按钮，保留上移、下移、移动到指定位置、删除等操作，暂不展示固定 pin 操作，避免操作列拥挤。
- 方案标题区的录取率标签使用短文案“录取率 xx%”，不再展示“专业组录取率/专业录取率”等长前缀；专业组标题使用专业组层录取率，专业+大学标题使用专业层录取率。
- 方案标题区与候选标题区对齐：专业组模式和专业+大学模式都使用“序号 + 学校/专业组名称 + 院校排名标签 + 录取率标签”的标题行，标题下方统一展示院校基础标签或地域/批次/性质等基础信息。
- 专业录取率放在表格最左侧专业名下方，用带底纹标签展示；表格底部参数区不再重复展示专业录取率，降低查找成本。
- 专业级操作按钮使用更小尺寸，保证上移、下移、移动到指定位置、删除四个按钮尽量保持单行展示。
- 专业组模式下，专业组标题和整组操作常驻，组内专业列表支持展开/折叠；默认只展开第一条专业组，其余折叠，点击专业组名称/学校名称周边空白区域切换展开状态，不额外占用独立横条。折叠只影响前端展示，不改变方案顺序和后端状态。
- 专业+大学模式下，方案条目也复用专业组模式的明细表格、浅色外框和展开/折叠交互；默认只展开第一条，其余折叠，折叠态保留标题、院校标签、录取率和移动/删除操作。

#### 2.4.1 专业组托底专业排查记录

- 本地 session 16 中，`郑州工商学院第102组(普通组)` 的专业组录取率为 18%。
- 全量候选池中该组共有 6 个专业，其中 `网络工程(网络安全)(第一年在兰考校区培养，第二至四年在郑州校区培养)` 的专业录取率为 18%，等于专业组录取率，可作为组内托底专业。
- 当前方案/workspace-state 中该组只引用了 5 个专业，包含 10% 和 14% 的专业，没有引用该 18% 托底专业。
- 因此该现象不是候选池缺失或轻量工作区详情回填失败，而是当前排序方案没有选入候选池中的托底专业。可能来源包括历史迁移方案、人工调整、或当前方案生成/重建时未强制保留托底专业；后续如要修复，应在专业组方案生成、重排和兼容迁移链路中统一校验“组内至少包含一个专业录取率不低于专业组录取率的专业”。
- 后端链路审计结论：
  - 正常初始推荐的组内专业选择会优先挑选 `admissionRatio >= schoolEnrollRatio` 的专业作为托底专业，然后再按组内推荐排序补足数量。
  - `replaceDraftWithInitialRecommendation` 会把初始推荐 unit 的 `majorItems` 原样落到草稿，因此正常新建方案理论上可以继承托底专业。
  - 排序、整组移动和单条移动只改变顺序，不会主动删除托底专业。
  - 人工删除单个专业、老方案迁移、历史方案兼容导入、或从已有草稿重新生成排序方案时，如果草稿/排序里已经缺失托底专业，当前 `buildOrderedUnitsFromOrderedItems` 只按现有排序项重建 unit，不会自动从候选池补回托底专业。
  - `reviewGroupInnerSafetyGuard` 已存在，但当前 `runReview` 主审查列表没有接入该检查；自动补偿也只从未选专业组里补组，`buildAvailableCompensationUnits` 会排除已选专业组，不能对已选组补一个缺失的托底专业。因此这里存在审查不可见、自动修复不可闭环的逻辑漏洞。
  - 建议后续修复分两步：先把 `group_inner_safety_guard` 接入 `runReview`，让风险在审查和工作台中可见；再新增“组内补托底专业”的补偿动作，允许对已选专业组追加或替换一个托底专业，并补充专业+大学与院校专业组两种模式的回归测试，确保普通专业模式不受影响。
- 专业组模式在组内专业行展示该专业近三年数据，不把单个专业分数误写成整个专业组承诺；组标题仍只保留院校排名和录取率。
- `salaryAvg` 在前端统一展示为“薪酬指数”，表示相对水平，不等同于实际工资。
- 方案区标签收敛为决策必要信息：院校/专业组标题后仅保留“院校排名”和“录取率”，不展示“意向省份”“优选”“系统初排”“已调整”等标签；冲稳保不在标题区重复展示，避免挤压学校/专业组名称和操作按钮。

验收：

- 信息不撑破列表布局。
- 专业组模式不把单个专业分数误写成整个专业组承诺。
- 专业+大学和院校专业组模式下，方案卡片标题区都不再被非必要标签挤压。
- 刷新历史/迁移会话后，只要轻量候选详情回填成功，方案区也能显示近三年专业分数表格。

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
- 候选 tab 内方案篮子优先展示 `orderedPlanState.items`，确保方案页排序、移动后的顺序能同步呈现；没有排序方案时才回退内部 `draftPlanState.items`。
- 新版前端不再展示旧草稿 `lock/unlock` 操作，也不展示“已锁定”标签；3.0.1 用户侧不再提供方案 `pin/unpin` 入口。
- 后端删除方案项时不再使用旧 `draftItem.locked` 字段阻断删除，避免历史锁字段在新版界面不可见但仍影响用户操作。
- 方案篮子使用独立色系，避免与候选志愿条目的红色风险/冲刺标签混在一起。
- 方案篮子色系建议使用蓝色或中性色，含文字标识；不要只靠颜色区分。
- 顶部数字概览支持折叠。
- 工作面板首次向下滚动时自动折叠顶部数字概览，只保留“方案/候选”大 tab 作为固定首行；用户在主体列表滚回顶部后，继续向上滚动或上拉时才恢复概览，避免刚触顶就弹出概览。
- 切换“方案/候选”时回到当前 tab 顶部，但不强制展开概览，保持用户当前的空间状态。
- 冲稳保颜色统一：冲=红，稳=橙，保=绿。
- 候选专业组右侧“录取率 / 冲稳保 / 专业数量”方块也需要按冲稳保三色展示，不只调整专业表格内录取率标签。
- 方案和候选列表各自增加回到顶端。
- 方案和候选长列表增加滑杆或快速定位控件：
  - 先保留当前已有的“回到顶部”能力。
  - 滑杆/快速定位控件本轮暂缓，前端验证中发现位置和交互稳定性不足，后续需要单独设计后再落地。
  - 不引入额外虚拟滚动改造，不影响候选页原有下滑加载更多逻辑。
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
- 概览折叠不影响候选分页下滑加载、回到顶部、方案移动和导出操作。
- 长列表可以快速移动和定位，不需要大量滚轮操作。
- 城市标签默认展开不会占满筛选区，用户能通过搜索、更多或分组快速定位目标城市。
- 已选城市标签清晰可见，折叠和搜索不会丢失已选状态。

### 2.7 候选筛选链路和标签来源

当前实现梳理：

- 候选筛选默认状态由前端 `createDefaultFilters` 和后端 `buildDefaultCandidateViewState` 共同兜底，当前均为空筛选，只保留默认排序 `finalScore desc`。
- 新建会话不应再把采集画像中的地域、专业、院校偏好作为候选默认筛选条件。用户画像用于候选生成、推荐打分和对话理解，不等同于工作台筛选条件。
- 前端进入工作台后从 `planningState.candidateViewState` 恢复用户上次主动设置的筛选和排序，并通过 `PATCH /session/candidate-view-state` 持久化。
- 候选筛选项优先来自后端 `/session/candidate-pool/filter-options`。后端基于当前会话候选池实际条目生成省份、城市、院校标签、专业门类、专业大类、招生类型和限报要求等可选项。
- 前端只有在后端未返回结构化 `groups` 时，才从已缓存候选条目中兜底拼出筛选项。该兜底只能覆盖已分页加载的候选，不应作为长期主路径。
- Agent 的约束型意图会把“只看北京”“不去上海”“不学护理”等硬条件规范化成 `candidateFilters`，通过 `planningWorkspaceAction` 联动候选面板并切换到候选视图。该动作只是设置筛选条件，不重新生成候选池。
- Rank 模块负责生成候选和推荐分，不直接提供前端筛选项。Backend 会从 rank/legacy 推荐结果中补齐候选结构化字段，再派生工作台筛选标签。
- Backend `CatalogService` 提供院校标签、招生类型、限报要求和专业目录等规范字典，Agent 的 `code_enrichment` 会优先使用后端 catalog 规范化，保留本地静态字典作为兜底。

当前前端展示层级：

- 后端原始分组中，地域是两个平级组：`region.school_province / 院校省份` 和 `region.school_city / 院校城市`。
- 前端不会直接平铺这两个组，而是重组为一个 `院校地域` 树：
  - 一级展示 `院校地域`，一级标题可折叠，不额外加底色。
  - 二级直接展示省份名称，对应筛选字段 `provinceNames`，右侧支持 `筛选/排除`。
  - 三级直接展示城市名称，对应筛选字段 `cityNames`，右侧支持 `筛选/排除`，通过缩进表达归属省份。
  - 不再展示 `全省/全市`、`城市`、`其他城市` 这类中间文案，避免把结构辅助词误当成筛选条件。
- 专业相关后端原始分组主要有三类：
  - `major.discipline / 专业门类`，字段是 `majorTags`，来源于候选项 `majorDiscipline` 或专业字典一级类目。
  - `major.category / 专业大类`，字段是 `majorKeywords`，来源于候选项 `majorCategory` 或专业字典二级类目。
  - `major.tag / 专业标签` 已从后端筛选分组中移除，不再作为用户侧筛选入口。
- 前端会把专业相关分组重组为一个 `专业` 树：
  - 一级展示 `专业`，一级标题可折叠，不额外加底色。
  - 二级按 `专业门类` 建节点，对应筛选字段 `majorTags`，右侧支持 `筛选/排除`。
  - 三级展示 `专业大类`，对应筛选字段 `majorKeywords`，右侧支持 `筛选/排除`，通过缩进表达归属门类。
  - 将 `专业大类` 按 `MAJOR_CATEGORY_TO_DISCIPLINES` 或候选项中的 `majorCategory -> majorDiscipline` 关系挂到对应门类下。
  - 无法归属门类的大类进入 `其他专业大类`。
  - `招生类型`、`限报要求` 继续作为专业树下的补充分组追加。
- 当前看到类似“专业标签-意向专业类”的内容，实际是后端 `major.tag / 专业标签` 中的候选专业标签值。它可能来自候选项的 `majorRankTags` 或 `majorPlanTags`，不一定代表用户主动设置的“意向专业”。命名上容易让用户误解，应在后续交互优化中区分“专业大类/门类”和“专业标签/推荐标签”的语义。
- `意向专业类` 的直接链路已经确认：
  - Rank 在推荐打分时读取用户画像 `major_intent` / `negative_major_intent`。
  - 当候选专业所属二级专业类命中用户正向专业类意向时，rank 写入 `major_remark = 意向专业类`；命中具体专业时写入 `意向专业`，负向命中则写入 `非意向专业/非意向专业类`。
  - Rank 返回结果中的专业备注进入 `VolunteerRecommendListResponse.VolunteerMajor.planTagList`。
  - Backend 在构建候选项时把 `planTagList` 写入 `CandidateItemDTO.majorPlanTags`。
  - 历史实现里 `collectMajorFilterTags` 会把 `majorPlanTags` 纳入专业筛选标签，因此前端最终在 `专业标签` 下看到 `意向专业类`。
  - 这说明 `意向专业/意向专业类/非意向专业/非意向专业类` 是推荐解释标签，不是用户主动筛选条件。3.0.1 从筛选项里移除这些解释标签，并移除用户侧 `专业标签` 分组，避免用户误以为点击它是在选择某个专业类或负向专业类。
- `其他城市` 的直接原因也已确认：后端 `filter-options` 当前只返回平级 `provinceNames` 和 `cityNames`，没有返回完整的 `province -> cities` 映射。前端为了展示省市树，只能从当前已加载候选缓存里临时统计 `provinceName -> cityName`；未加载页里的城市虽然存在于后端 `cityNames`，但前端不知道归属省份，于是落入 `其他城市`。
- 当前前端推断省份和城市的方式不够合理。原因是筛选项来自后端全量候选池，但省市归属来自前端已加载分页缓存，二者数据范围不一致；分页未加载到的城市会被错误放进 `其他城市`。
- `其他城市` 可以归到省份。3.0.1 已在 `/session/candidate-pool/filter-options` 中新增兼容字段 `regionTree`，由后端基于当前候选池的 `provinceName/cityName` 聚合当前会话实际命中的省市树；前端优先消费 `regionTree`，没有该字段时才回退旧的分页候选缓存推断。
- 省市源头链路：
  - Rank 推荐结果中的院校对象携带 `province_name/city_name`。
  - Backend 在 `fillSchoolFields` 中把它们写入 `CandidateItemDTO.provinceName/cityName`。
  - `getCandidateFilterOptions` 从当前候选池聚合 `provinceNames/cityNames`，同时构建 `regionTree`。
  - 前端候选筛选面板消费 `regionTree` 生成 `院校地域 -> 省份 -> 城市` 层级。

设计原则：

- 用户偏好和候选筛选分离。偏好可以影响生成和解释，但不应默认缩小候选面板结果，避免用户误以为系统“少推荐”或“漏推荐”。
- 筛选项以当前候选池可命中的枚举为准，避免展示全局字典里当前会话没有结果的标签。
- 用户主动筛选导致结果为空时，只展示“当前筛选无结果”类空态，不提示“候选不足”。候选不足只针对候选池生成质量，不针对用户筛选后的子集。
- 约束型对话筛选必须可见、可撤销，并与用户手动筛选共用同一套 `candidateViewState`，避免对话里生效了隐藏条件。
- 后端结构化 `filter-options.groups` 是筛选面板主协议。前端分页缓存兜底只能用于临时兼容，后续不应新增依赖。

后续落地建议：

- 城市筛选默认按省份折叠，省份行和城市行均直接提供 `筛选/排除` 操作；城市数量较多时通过省份节点内部展开和搜索定位。
- 搜索时同时匹配省份、城市、院校标签、专业门类和专业大类；匹配到子项时保留父级路径，避免用户看不懂标签来源。
- 已选筛选条件在筛选入口摘要或面板顶部固定展示，支持单项移除和一键清空。
- 若后端 `filter-options` 获取失败，前端可以展示已加载候选的有限兜底项，但需要避免把兜底结果误表现为完整筛选集合。
- Backend 和 Agent 的标签规范应逐步收敛到 `CatalogService`，减少 Agent 本地静态字典与后端白名单漂移。
- 将 `意向专业/意向专业类/非意向专业/非意向专业类` 从普通 `专业标签` 中拆出或隐藏：
  - 如果保留，应作为“推荐解释”或“匹配偏好”只读标签，不作为主要筛选项。
  - 如果要支持筛选，应单独命名为“偏好匹配”，并明确这是系统根据画像计算出的匹配结果。
- TODO：重新对齐 Agent 与 Backend 的“意向”语义。Agent 侧实际已经区分软偏好和硬要求，两者都会被组织在意向/约束工具链里；Backend 和历史 rank 标签仍更接近旧版“泛泛意向”定义。后续需要明确：
  - 软偏好用于生成、打分、解释和可选推荐。
  - 硬要求用于筛选、排除、合规约束和对话联动筛选。
  - 推荐解释标签、用户主动筛选条件、用户画像意向三者不能继续混用同一组“意向”文案。
- `filter-options` 地域结构已扩展为 `regionTree`：
  - 每个省份节点包含当前候选池实际命中的城市。
  - 城市归属优先使用候选项自带 `provinceName/cityName`。
  - 前端仍保留 `provinceNames/cityNames` 和分页缓存推断作为兼容兜底，但省市展示以结构化树为准。

验收：

- 新建 `major` 和 `majorGroup` 会话进入候选页时，不默认带入画像地域、专业或院校筛选。
- 刷新页面后，用户主动设置过的候选筛选和排序可以恢复。
- 对话触发约束筛选后，候选面板可见对应筛选条件，用户可以清空或逐项撤销。
- 后端返回的筛选项均能命中当前候选池；不会展示大量当前会话无结果的全局标签。
- 用户筛选到空结果时展示空态，不触发候选池偏少或生成异常提示。
- 城市不再因为候选分页缓存未加载而进入 `其他城市`；只有省市字典也无法识别时才允许出现兜底分组。
- `意向专业/意向专业类/非意向专业/非意向专业类` 不再以普通专业筛选项展示，用户侧不再出现 `专业标签` 筛选分组。

### 2.8 Agent 和对话驱动整合

目标：

- 3.0.1 用户侧不再暴露“草稿”。Agent 回复、确认预览、pending 动作、工作台事件和前端展示统一称为“方案”。
- 底层 `draftPlanState` 继续作为 backend 兼容结构存在，但只在服务端和工具内部使用，不进入用户话术。
- 对话触发的方案操作必须与新版工作台一致，避免出现“对话能做、前端看不到”或“前端有按钮、对话不能联动”的分裂。

P0 工作项：

1. 收口 Plan 工具入口。
   - ChatAgent 面向模型只保留 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` 主链。
   - `planning_router_tool.handle_planning_request` 仅作为兼容工具保留，不再出现在新指令和新设计中。
   - 文案和测试不得再要求调用 `handle_planning_request`。
   - `planning_workflow_tool` 不是模型入口，但当前仍被 handlers 和查询工具大量复用，不能直接删除；本期只做依赖梳理和拆分准备。

2. 去草稿用户语义。
   - Agent 方案查询、加入、删除、补入、生成、重排等回复统一使用“方案”。
   - `draft_snapshot/query_draft` 仍可作为内部 fallback，但面向用户表达为“已加入方案，待生成顺序”或“当前方案”。
   - 清理“加入草稿”“草稿志愿”“锁定草稿”等用户可见文案。

3. 冻结 pin/lock 用户入口。
   - 3.0.1 不让对话触发 `pin_unit/unpin_unit/lock_draft/unlock_draft`。
   - 如果用户说“锁定/固定”，Agent 应解释当前新版工作台暂不提供固定入口，并建议使用移动到指定位置或排序后人工确认。
   - service 层不再为 pin/unpin 生成工作台刷新 pending。

4. 对话触发方案排序。
   - 用户说“按录取率排序”“按院校层次排序”“按推荐系数排序”时，规划为 `sort_ordered_plan` 类动作，而不是旧 `regenerate_order`。
   - 排序是实际改写方案顺序的高副作用动作：先 preview，用户确认后调用 backend `ordered-plan/sort`。
   - 排序成功后刷新方案视图，并让审查状态进入待重新审查。
   - 普通“帮我顺一下/重新排一下”仍可继续走整体重排/重新生成排序，但需要与指定字段排序分开。

5. 工作台事件协议收口。
   - 只读 `query_state/query_ordered` 默认不发无联动卡片。
   - 会改变状态或需要用户关注工作台变化的动作才发送 `planningWorkspaceAction`。
   - 候选筛选联动必须写入可见、可撤销的 `candidateViewState`，不允许隐藏筛选。

6. Router / workflow 依赖整理。
   - `planning_router_tool` 当前没有注册到 `ChatAgent.tools`，线上主链路不会由模型直接调用；直接依赖主要来自 `tests/unit/test_planning_router_tool*.py` 和部分历史 scenario 测试。
   - 3.0.1 将 `planning_router_tool` 标记为 deprecated compatibility wrapper；新增能力不得继续接入这里。
   - 迁移步骤：先把依赖 `handle_planning_request` 的测试改为覆盖 Plan 主链，再删除 router 测试，最后移除模块或保留极薄 shim。
   - `planning_workflow_tool` 当前仍被 `handlers/query_handlers.py`、`handlers/mutation_handlers.py`、`handlers/generate_handler.py`、`handlers/analysis_handlers.py`、`handlers/compensation_handlers.py`、`plan_execution_tool.py`、`plan_context_tool.py`、`plan_query_tool.py`、`major_info_tool.py` 直接复用，不能裸删。
   - 后续拆分目标：把 `planning_workflow_tool` 拆成内部 helper 模块，如 `planning_formatters.py`、`planning_state_readers.py`、`planning_mutations.py`、`planning_review_helpers.py`、`planning_compensation_helpers.py`。
   - 测试夹具需要同步迁移到 handler 实际调用位置，避免 patch 旧 workflow wrapper 后仍误连真实 backend。

验收：

- Agent 和前端不再向用户展示“草稿”。
- 对话排序和前端排序能力一致。
- 对话不会触发前端不可见的 pin/lock 状态。
- 高副作用动作均有 preview 和确认。
- 专业+大学、院校专业组两种模式均有端到端 examples 覆盖。
- 新指令中不再出现 `handle_planning_request`，router 仅作为兼容层存在。

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
  - 历史锁定兼容边界。
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
- 候选筛选默认值：
  - 新建 `major` 会话不默认带入画像地域、专业或院校筛选。
  - 新建 `majorGroup` 会话不默认带入画像地域、专业或院校筛选。
  - 刷新页面后可以恢复用户主动设置过的筛选和排序。
  - 对话触发约束筛选后，候选面板可见对应筛选条件且可撤销。
  - 用户筛选到空结果时只展示筛选空态，不展示候选池偏少提示。

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
4. 已关闭：方案排序进入 3.0.1，按确认后实际改写当前方案顺序实现。
5. 顶部数字概览 PC 端默认展开还是默认折叠。
6. 长列表快速定位首版是只做顶部/底部，还是支持输入序号定位。
7. 候选城市筛选首版优先做“更多折叠”，还是同步做关键词搜索和省份分组。
8. `salaryAvg` 展示文案已收敛为“薪酬指数”，是否还需要在排序项、tooltip 和导出文案里继续统一口径。
