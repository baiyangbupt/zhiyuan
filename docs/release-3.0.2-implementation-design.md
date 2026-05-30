# Release 3.0.2 Implementation Design

本文档承接 `docs/release-3.0.2-stability-plan.md`，记录已经确认进入 `3.0.2` 的事项如何落地。新增需求先进入 stability plan，确认范围后再补充到本文。

## 1. 外部初始化会话学员姓名展示

### 1.1 目标

外部系统通过初始化接口直接创建会话时，可以传入当前被服务学员姓名。用户打开返回的详情页后，页面顶部在填报类型前展示姓名，例如：

```text
高翔  模拟填报  进行中
```

姓名缺失时不展示空标签，页面保持现有样式。

### 1.2 后端设计

现有链路：

- 外部初始化接口复用 `ExternalSessionInitializeReq.createSession`。
- `CreateSessionReq.userName` 已写入 `assistant_chat_session.user_name`。
- `GET /gaotu-assistant-bot/chat/{tenantId}/session/detail` 返回 `ChatSessionVo.userName`。

本次补充：

- `ExternalSessionInitializeRes` 增加只读展示字段 `studentName`。
- `IntegrationSessionService.buildResponse` 从 `createSession.userName` 派生 `studentName`，并做 trim；空字符串返回 `null`。
- 新增版本化稳定路径：
  - `POST /gaotu-assistant-bot/chat/{tenantId}/integration/v1/session/initialize`
- 既有路径继续保留：
  - `POST /gaotu-assistant-bot/chat/{tenantId}/integration/session/initialize`
- 两个路径调用同一个 service，不分叉业务逻辑。

边界：

- `studentName` 只用于展示，不参与授权、幂等用户身份或权限判断。
- 授权身份仍以 `tk/pf` 登录态为准。
- 幂等命中时，因为 request hash 要求请求体一致，`studentName` 与首次成功创建请求保持一致。

### 1.3 前端设计

`sessionDetailV2` 已在进入页面后调用会话详情接口。新增：

- 增加 `studentName` state。
- `fetchSessionDetail` 读取 `data.userName`，trim 后写入 `studentName`。
- header meta 中在 `prepareTypeDesc` 前展示 `studentName` 标签。
- `studentName` 为空时不渲染。

样式：

- 复用 `metaBadge` 的紧凑标签样式。
- 姓名标签可加轻微强调，避免和状态标签混淆，但不扩大头部高度。

### 1.4 测试

后端：

- controller 覆盖无版本路径和 `v1` 路径。
- service 覆盖 `createSession.userName` 到 `studentName` 的响应映射。
- service 覆盖空白姓名返回 `null`。

前端：

- 当前先做静态类型和构建级验证。
- 后续补页面测试时覆盖有姓名、无姓名、外部 `sessionUrl` 进入和会话列表进入。

### 1.5 验收

- 外部调用传 `createSession.userName="高翔"` 后，初始化响应返回 `studentName="高翔"`。
- 打开 `sessionUrl` 后，详情页顶部在“模拟填报”前展示“高翔”。
- 未传姓名时不展示姓名标签。
- `v1` 路径和旧路径行为一致。

### 1.6 生产反馈兼容修复

线上 `3.0.1` 已有外部系统按无版本路径完成对接，因此 `3.0.2` 不要求调用方切换路径。后端需要同时保留：

- `POST /gaotu-assistant-bot/chat/{tenantId}/integration/session/initialize`
- `POST /gaotu-assistant-bot/chat/{tenantId}/integration/v1/session/initialize`

两个路径仍共用同一个 controller 和 service，不引入分叉实现。

本次反馈还暴露了外部请求字段缺省后的稳定性问题：

- `sex` 不再作为外部初始化的强必填字段。缺失或 `code` 为空时，后端归一化为 `{code:"female", name:"女"}`，口径对齐前端采集流默认值。
- `strategyType` 不再作为外部初始化的强必填字段。缺失或 `code` 为空时，后端归一化为 `{code:"cautious", name:"稳妥型"}`，口径对齐前端采集流默认策略。
- 外部如果按 snake_case 传 `strategy_type`，后端同样映射到 `strategyType`；推荐字段名仍为 `strategyType`。
- 幂等 hash 仍在默认值归一化前按原始请求体计算，保持外部重试语义不变。

`strategyType` 缺失时的更大风险在方案目标数量计算：旧逻辑拿不到策略后可能回退到 `three_target_count_map / sprints_count / safes_count / protects_count`，而这些字段在部分推荐响应里更接近候选池规模，可能把排序方案放大到候选数量级。修复口径：

1. 优先使用 `baseData.need_count` 作为目标方案数量。
2. 若 `need_count` 缺失，再按 `volunteerCount` 和 `volunteerModel` 取当前模式的目标数量。
3. 若仍缺失，兜底为 `45`。
4. 如果用户成绩信息里有显式 `strategyType`，按该策略重新计算 `requiredTierCounts`。
5. 如果没有显式策略，但 `three_target_count_map` 三项之和等于目标方案数量，认为它是可信的旧版目标分布，继续沿用。
6. 如果没有显式策略，且 `three_target_count_map` 三项之和明显大于目标方案数量，认为它更像候选池规模，忽略该 map，按默认稳妥型 `3:3:4` 计算。
7. 只有上述计算完全失败时，才回退旧的散字段 `sprints_count / safes_count / protects_count`。

测试覆盖：

- controller 覆盖无版本路径和 `v1` 路径。
- controller 覆盖 `strategy_type` 入参别名。
- service 覆盖外部初始化创建前会执行默认值归一化。
- planning 覆盖缺 `strategyType`、缺 `need_count` 时不会把候选规模当作排序目标数量。

## 2. 登录后默认进入会话列表

### 2.1 目标

用户登录后优先看到会话列表，而不是直接进入最近一次会话详情。这样 B 端或服务人员能先确认当前服务对象，再进入具体会话。

### 2.2 当前逻辑

- 普通账号密码/手机号登录：
  - `isCustomer=true` 跳转 `/customer`
  - `isCustomer=false` 跳转 `/session`
- token 静默登录：
  - 同样按 `isCustomer` 跳转。
- `/customer` 页面默认打开会话列表抽屉，不再自动跳转最新会话详情。
- `/customer?openSessionList=1` 作为显式打开会话列表的兼容入口保留。

### 2.3 实施方案

本次不重写 `/customer` 页面，只复用已有 `openSessionList=1` 入口：

- 登录后如果 `isCustomer=true`，跳转 `/customer?openSessionList=1`。
- 登录后如果 `isCustomer=false`，继续跳转 `/session`。
- `source=minip` 仍由 router 工具自动透传。
- 采集页创建成功后也必须回到会话列表，而不是进入新建会话详情；C 端回到 `/customer?openSessionList=1`，B 端回到 `/session`。

### 2.4 验收

- token 登录、账号密码登录、手机号登录三个入口行为一致。
- C 端用户进入 `/customer` 时默认打开会话列表，不再自动跳最近会话。
- B 端用户仍进入 `/session` 会话列表。
- 外部深链路不在本次修改范围；如果后续增加 `redirectUrl/sessionUrl`，需要优先保留深链路。

## 3. 前置信息采集缓存

### 3.1 目标

用户在创建会话前会完成高考信息、个人信息、专业意向、区域意向和志愿策略采集。`3.0.2` 先解决“刷新或短时间离开后需要整轮重填”的问题：

- 每个步骤点击“确认提交”成功后，就缓存已经确认过的结构化采集结果；对于个人信息这类包含多个内部小表单的步骤，每个小表单确认后都会更新缓存。
- 页面刷新或重新打开采集入口时，恢复到上次未完成的步骤，并带回之前步骤的结构化结果；用户点击“上一步”回看时，已确认字段需要回填到对应表单/选择控件。
- 创建会话成功后清理缓存，避免下一次创建误带入旧信息。
- 本期不再提供单独“重新开始”入口，避免和“上一步”修正流程混淆；缓存清理依赖创建会话成功、缓存过期或非法缓存自动清理。

第一阶段不缓存用户在单个表单内尚未点击“确认提交”的半填写字段。原因是各步骤内部存在较多派生字段和接口联动，例如总分、位次、批次线、专业推荐结果；直接做字段级 autosave 容易恢复到不一致状态。后续如继续优化，可在每个步骤组件内按字段补充受控 autosave。

### 3.2 缓存结构

缓存只存在浏览器本地，作为创建会话前的临时草稿，不进入正式用户画像、方案或后端 planning 状态。

```json
{
  "version": 1,
  "tenantId": "default",
  "botId": "xxx",
  "userKey": "12345",
  "currentStep": 3,
  "values": {
    "province": {},
    "batch": {},
    "majorList": [],
    "preferredRegions": []
  },
  "updatedAt": 1710000000000
}
```

缓存 key：

```text
customer_detail_draft:{tenantId}:{botId}:{userKey}
```

`userKey` 优先使用登录用户 ID；缺失时使用采集用户基础信息中的低敏标识兜底，避免不同租户、bot 或用户之间串缓存。

过期策略：

- TTL 为 7 天。
- 读取时发现版本不一致、租户/bot 不一致、步骤非法或过期，则直接忽略并清理。

### 3.3 入口覆盖

当前存在两个采集入口：

- `CustomerDetailFlow`：新版详情页抽屉、C 端首页抽屉等复用入口。
- `/customerDetail`：旧的独立采集页。

本次两处都接入同一套缓存工具，避免同一用户从不同入口进入时行为不一致。

### 3.4 状态流转

| 时机 | 行为 |
| --- | --- |
| 进入采集页 | 读取有效缓存，恢复 `currentStep` 和 `createSessionValues` |
| 渲染具体步骤 | 将 `createSessionValues` 传入步骤组件，并从结构化业务字段反向映射到表单控件字段 |
| 点击确认提交 | 合并当前已确认结构化值，缓存当前步骤号和累计值 |
| 点击下一步 | 缓存下一步步骤号和累计值 |
| 点击上一步 | 保留累计值并缓存回退后的步骤号 |
| 最终提交前 | 缓存当前最终步骤值，避免创建接口失败后丢失 |
| 创建会话成功 | 清理缓存 |
| 缓存过期/非法 | 清理缓存并按新流程开始 |

### 3.4.1 字段回填边界

缓存内保存的是创建会话接口使用的结构化业务字段，而不是每个表单组件内部的临时控件字段。因此恢复时需要做反向映射：

- 高考信息：`examYear`、`province.code` 回填到考试年份和考试省份。
- 个人信息：`subjectList / subjectScoreList / strengthSubjectList / batch / sex / height / visionAbility / ethnicity / colorSituation / specialPlan / politicalStatus` 回填到两段个人信息表单，兼容旧字段 `colorSistuation`。
- 专业意向：`preferredMajors / unacceptableMajors / acceptForeignSchool / tuitionRange` 回填到专业选择、排除专业、是否接受中外合作和学费区间。
- 区域意向：`preferredRegions` 回填到区域选择。
- 志愿策略：`strategyType.code` 回填到策略卡片。

第一阶段仍不缓存“用户正在当前表单中输入但还没有点击确认提交”的字段。也就是说，已确认步骤必须能恢复和回填；当前步骤里未确认的半填写内容暂不保证恢复，后续如继续优化再做字段级 autosave。

补充实现约束：

- 个人信息采集页内部的分数填写和身体情况填写使用各自独立的表单实例与总结锚点，避免一个子表单的确认操作把页面滚动或表单状态带回到另一段。
- 分数子步骤点击确认后，页面应自动滚到下一子步骤的起始位置，让用户能直接看到身体信息区域出现，而不是只停留在当前总结锚点附近。
- 分数计算、位次查询与批次联动只绑定分数子表单；身体情况确认只更新当前子表单的缓存和总结态，不会重新触发分数段的计算逻辑。
- 视力情况、分数列表这类组合字段的必填校验要落在内部真实输入项上，外层容器只负责展示和布局，避免明明填了 4.3 / 4.3 却仍被当成未填。
- 个人信息任一子步骤如果已经从缓存恢复为“已确认”，必须同时恢复总结区和“了解完成，继续下一步”入口；不能出现只展示“确认提交”气泡、但仍要求用户再次提交一次才可继续的中间态。
- 个人信息子步骤只有在缓存中存在真实业务字段时才恢复为“已确认”。仅由表单结构反推出来的空选科数组、空擅长学科或空身体信息不能触发恢复态，也不能覆盖后端/用户信息提供的默认选科；否则首次进入选科成绩环节会出现未点击确认就展示“确认提交”反馈、选科默认值丢失的问题。
- 批次字段来自异步批次线接口。表单初始化不能用配置里的空 `defaultValue` 覆盖已经加载出的默认批次线；初始化值应优先使用已缓存批次，其次保留当前有效批次，再兜底批次线列表第一项，确保老版本已有的自动填入批次线能力不回退。
- 选科成绩、总分、批次线和成绩排名是同一条派生链路：初始化/缓存恢复、批次线异步加载、用户修改分数或批次时，都必须调用统一的分数派生刷新逻辑。不能只依赖 `onValuesChange`，否则断点续填或接口异步回填不会触发总分计算和位次查询。
- 新高考 `WL/LS` 模式会把 `subjectList` 拆为 `subjectList_first` 和 `subjectList_second`。提交创建会话时需要从所有 `mutiSelectType=subjectList` 字段收集选科，不能只找原始 `subjectList` 字段。
- 个人信息提交时的字段解析必须使用渲染后的 `processedStepsData`，而不是原始 `stepsData`。否则 `subjectList_first/second` 拆分字段只存在于渲染结构里，最终创建请求会出现选科丢失。
- 采集缓存恢复不能只恢复结构化值，还要恢复对应步骤的确认态和总结态。高考信息、专业意向、区域意向和志愿策略在缓存命中后应直接显示已确认后的总结区；否则用户刷新后会误以为还没确认，重复看到“确认提交”按钮。
- 采集页在没有任何有效缓存时必须显式重置上一个会话残留的确认态、总结态和本地表单值，避免用户切换到新会话后沿用旧会话的恢复结果。
- `/customerDetail` 页面入口和弹窗/复用入口 `CustomerDetailFlow` 必须保持同一套缓存恢复契约。修复时不能只改复用组件；实际页面入口也要在无有效缓存时重置步骤和累计值，并在用户省份变化时重新拉取或清空选科策略。
- 专业意向页中“以下专业类，哪些是明确排斥不想选的？”必须展示后端按选科和批次动态注入的 `bachelorMajors / associateMajors` 冷门/排斥专业类；批次暂时未恢复或动态字段缺失时，不能回退到静态 `options` 里的具体专业列表，避免把“建筑学、计算机科学与技术”等普通专业误展示为排斥专业类。
- 专业意向页中的负意向专业类不再只靠 `collect-flow` 的初始注入结果；应以当前表单里的选科和批次调用 `base-data/unacceptable-majors` 重新取一次动态列表，确保不同选科和不同批次看到的排斥专业类保持一致。
- 志愿填报策略是最后一步，但交互仍沿用旧流程：策略表单内部只有单个“确认提交”用于确认选择；确认后底部展示浅红底“了解完成，继续下一步”按钮，由该按钮触发 `finalSubmit` 创建会话。不能把底部动作改成小号“上一步 / 确认提交”按钮组，避免用户误以为还只是普通表单提交。
- 志愿填报策略的最终按钮只触发创建会话，不再追加一条同文案的用户气泡；否则用户会看到重复的“了解完成，继续下一步”。
- 个人信息里的批次字段属于创建会话必填结构化字段。批次控件值需要从当前分数表单实例和异步批次列表中解析为 `CreateSessionReq.batch`，缓存恢复或 id 类型变化时要用已缓存批次兜底，不能让最终 payload 中 `batch` 丢失。最终创建前如果遇到历史缓存已进入最后一步但仍缺少批次，需要按当前用户省份、选科和默认批次列表再做一次异步补齐；仍无法补齐时，前端展示“请选择批次后再创建会话”并停止提交。
- 后端创建会话入口需要在保存 session 前校验 `batch / province / subjectType / subjectScoreList / totalScore` 等核心字段，缺失时返回用户可理解的业务错误，不能让空指针透出为“系统错误”。

### 3.5 验收

- 用户完成前两步后刷新页面，能回到下一步并保留前两步结果。
- 用户完成到区域意向后短时间离开，再进入不需要重新填写成绩、批次、专业意向。
- 用户恢复后点击“上一步”，之前已确认的高考信息、个人信息、专业意向和区域意向会回填到表单控件里，而不是只恢复步骤号。
- 用户进入志愿填报策略，表单内点击“确认提交”后底部只出现一个“了解完成，继续下一步”；点击后创建会话请求包含完整 `batch`。
- 如果采集链路异常导致批次缺失，后端返回“请选择批次后再创建会话”，前端展示该提示，不再只显示“系统错误”。
- 创建会话成功后，再次新建不会恢复旧缓存。
- 缓存只保存已确认的采集结构化值，不保存 API key、token 或正式方案数据。

## 4. 候选筛选已选条件快捷移除

### 4.1 目标

候选筛选支持正向筛选和排除筛选。长列表下用户选中多个条件后，如果需要撤销某个条件，不应必须回到原筛选层级里反向点击。

本次先补充已选条件条：

- 在候选筛选工具栏下方展示当前已选筛选/排除条件。
- 每个条件右侧提供 `x` 移除入口。
- 排除条件视觉上与正向筛选区分。
- 移除单个条件时不影响其他正向/排除条件。

### 4.2 当前状态

`WorkspacePanel` 已有三层结构：

- `filters`：真实筛选状态，包含 `provinceNames / negativeProvinceNames / cityNames / negativeCityNames / schoolKeywords / negativeSchoolKeywords / majorKeywords / negativeMajorKeywords / schoolTags / negativeSchoolTags / majorTags / negativeMajorTags / expertPreferredOnly`。
- `selectedAttributeFilterTokens`：筛选面板内部用于判断每个选项的选中态。
- `activeFilterChips`：已把当前筛选状态格式化成用户可读标签，但此前只用于生成下拉按钮摘要文案。

### 4.3 实施方案

复用 `activeFilterChips`，在候选工具栏下方渲染 chip 列表：

- `positive` 使用浅蓝/浅绿类样式。
- `negative` 使用浅红/橙红样式，并保留“不看/不去”等用户侧语言。
- 点击 `x` 后按 `chip.field + chip.polarity + chip.value` 精确删除对应数组项。
- `expertPreferredOnly` 是布尔筛选，删除时置为 `false`。

不改变：

- 不改候选查询接口。
- 不改后端 `candidateViewState` 保存结构。
- 不恢复之前已去掉的意向专业类、负向专业标签等解释性标签。

### 4.4 验收

- 同时选择一个正向筛选和一个排除筛选后，能分别单独移除。
- 移除排除条件时，正向筛选仍保留。
- 移除正向筛选时，排除条件仍保留。
- 清空按钮仍可一次清掉全部条件。
- `major` 和 `majorGroup` 两种模式下候选数量随条件变化刷新。

### 4.5 交互修正

- 筛选分组的自动展开只保留给搜索态。
- 已选筛选项不再强制锁定父级分组展开状态；例如选择“院校地域 > 上海”后，用户仍可手动收起“院校地域”。
- 已加入方案的候选在学校/专业组标题和专业条目上展示“已选择”标签，按钮继续展示“已加入方案”并保持不可重复加入。

### 4.6 候选已加入状态修正

本地会话 17 暴露出一个身份口径问题：专业+大学模式下，候选池查询返回的 `volunteerId` 可能是 `planSchoolDataId + planMajorDataId`，而初始方案/历史方案中已选条目使用的是 `planSchoolDataId + majorId`。工作区详情接口此前通过兼容解析能展示方案信息，但候选查询和“加入方案”仍按原始候选 ID 判断，导致同一个志愿看起来还可以再次加入。

修正原则：

- 后端是主修复点：在专业+大学模式下，候选查询、加入方案、方案同步统一使用 `planSchoolDataId + majorId` 作为候选身份。
- 专业组模式不改口径，继续保留 `planSchoolDataId + planMajorDataId`，避免破坏组内专业定位。
- “已加入”判断不能只依赖精确 ID；后端需用兼容解析防止旧 ID、脏 ID 再次加入同一候选。
- 前端可保留选中态兜底，但不能用前端兜底掩盖后端 ID 漂移。

验收：

- 会话 17 候选列表第一屏已在方案中的条目展示“已选择/已加入方案”，按钮不可重复点击。
- 点击旧格式候选 ID 也不会把同一志愿重复追加到方案。
- `majorGroup` 会话候选 ID 不被改写，专业组内专业仍可按原 ID 展示和操作。

## 5. 候选筛选支持院校名和三级专业

### 5.1 目标

候选筛选不只支持地域、院校属性、专业门类和专业大类，还要让用户能直接按具体院校名、具体专业名筛选：

- 用户知道目标院校时，可以在筛选面板里搜索或选择院校名称。
- 用户知道具体专业时，可以沿“专业门类 -> 专业大类 -> 专业名”定位。
- 正向筛选和排除筛选都可用。

### 5.2 后端设计

现有查询接口已经具备对应语义：

- `CandidatePoolQueryReq.filters.schoolKeywords`：按 `schoolName` 包含匹配。
- `CandidatePoolQueryReq.filters.majorKeywords`：按 `majorName / majorCategory / majorDiscipline` 包含匹配。

本次不新增查询字段，只补充 filter-options 输出：

- `schoolKeywords`：候选池内可选院校名称去重列表。
- `majorTree`：候选池内可选专业层级树。
  - 第一层：专业门类，对应筛选字段 `majorTags`。
  - 第二层：专业大类，对应筛选字段 `majorKeywords`。
  - 第三层：专业名称，对应筛选字段 `majorKeywords`。
- `groups` 追加：
  - `school.name / 院校名称 / schoolKeywords`
  - `major.name / 专业名称 / majorKeywords`

专业名称做轻量归一化：优先取括号前的主体名称，例如 `会计学(办学地点...)` 暴露为 `会计学`。查询侧仍是包含匹配，因此主体专业名能命中带备注的候选。

边界：

- 同一字段内多个值保持现有 OR 语义，例如同时选多个院校名表示“这些院校都可以”。
- 专业大类和专业名同属 `majorKeywords`，同时选择时也是 OR，不在本期改为 AND；后续如果需要更严格的层级筛选，可新增独立 `majorNames` 字段。
- 不把用户前置信息里的意向专业重新塞回筛选默认值。

### 5.3 前端设计

筛选面板调整：

- `FilterTokenField` 增加 `schoolKeywords`。
- 院校名称作为“院校名称”分组展示，支持搜索、筛选和排除。
- 专业分组优先使用后端 `majorTree` 渲染为三层：
  - 专业门类
  - 专业大类
  - 专业名称
- 兼容旧后端：如果没有 `majorTree`，继续使用现有 groups + 已加载候选项推导门类/大类。
- 已选条件条继续复用 `activeFilterChips`，院校名和专业名可从筛选框外直接移除。

### 5.4 验收

- 筛选面板能搜索并选择具体院校名，候选列表只保留该院校。
- 筛选面板能在专业下展开到具体专业名，候选列表只保留匹配专业。
- 院校名和专业名都支持排除。
- `major` 和 `majorGroup` 两种模式都能返回稳定的筛选选项。
- 已选条件快捷移除后，候选列表恢复对应结果。

### 5.5 专业编码缺失治理

本地会话 17 的候选池里，部分“职业本科/技术类”专业被归到“其他专业”。抽样确认不是前端渲染问题：

- 原始候选文件 `zhiyuan-server/data/tmp/session_volunteer_17.json` 中，`软件工程技术`、`云计算技术`、`人工智能工程技术` 等条目的 `majorId/categoryId/subCategoryId` 已经是 `0`。
- 当前服务端转换链路是透传字段：
  - `ProgramPageDTO.SchoolDetail/MajorVO` -> `VolunteerMajor`
  - `VolunteerMajor` -> `VolunteerRecommendListResponse.VolunteerMajor`
  - `VolunteerRecommendListResponse.VolunteerMajor` -> `CandidateItemDTO`
- `PlanningStateService` 只在已有 `majorSubCategoryId` 时通过 `MajorExtraDataManager` 解析门类/大类；编号为 `0` 且目录查不到名称时，只能归入“其他专业”。
- `MajorMappingManager` 当前加载 `bizdata/major_bachelor.json` 和 `bizdata/major_associate.json`；抽样名称未命中本科目录，专科目录也只存在相近名称，例如 `云计算技术应用`，不能直接等同为 `云计算技术`。
- rank 侧结果中这类条目已经带有 `major_remark:未知专业减分`，说明算法侧也没有识别到专业目录，而不是仅筛选树缺失。

字段口径：

- `majorId`：专业目录中的三级专业 ID，用于具体专业匹配、意向专业匹配和筛选。
- `categoryId`：一级门类 ID。
- `subCategoryId`：二级专业类 ID，是当前候选筛选构建门类/大类的主要依据。
- `planMajorDataId`：招生计划专业 ID，只能定位某年某省某校的招生专业计划，不能替代专业目录 ID。
- `majorUnitCode`：院校/招生计划侧专业代码，适合展示和回传计划，不适合作为全局专业分类依据。

处理原则：

- agent 不负责维护专业目录。agent 只应表达用户偏好、调用工具和解释结果，不能把专业 ontology 写在 prompt 或工具逻辑里。
- server 是近期主修复点：补齐专业主数据或增加受控的名称归一化/别名映射，在进入候选筛选、状态展示和外部 catalog 查询前补出门类/大类。
- rank 需要同步治理：如果只在 server 补展示，筛选树会变好，但算法侧仍可能因为“未知专业”给出错误减分或错误推荐解释。后续应让 rank 和 server 使用同一份专业目录/别名表。
- 不建议用前端兜底硬编码“其他专业”的分类。前端最多展示“未归类专业”，不能自行推断专业门类。

短期落地建议：

- 在 server 增加缺失专业扫描工具或测试样例，输出候选池里 `majorId/categoryId/subCategoryId=0` 的专业名、学校、计划 ID 和出现次数。
- 补充职业本科专业目录/别名数据，至少覆盖当前样本中高频缺失名称。
- 对名称带括号备注的专业，先取括号前主体名做精确匹配；仍未命中时保持未归类，并在运维报告中暴露。
- 筛选树展示上，未归类专业统一归入“其他专业”，并稳定放在专业筛选树尾部，避免干扰正常门类/大类定位。
- 验证 `major` 和 `majorGroup` 两种模式，避免只修专业+大学模式。

## 6. 候选为空与筛选无结果的口径区分

### 6.1 目标

用户筛选导致当前列表为空，和系统生成候选池本身为空/偏少，是两类问题：

- 用户筛选无结果：只在候选列表空态提示“当前筛选结果为空”，不提示系统候选不足。
- 系统候选为空：展示候选池状态和风险原因，引导检查专项资格、批次、分数线或硬性限制。
- 系统候选偏少：允许继续操作，但在候选概览里用 tooltip 展示偏少原因。

### 6.2 当前链路

- 后端 `candidatePoolState.statusCode` 已支持 `not_generated / ready / empty / low_count / failed`。
- 后端 `candidatePoolState.riskHints` 已沉淀候选数量、冲稳保缺口、分数线边界和硬性约束提示。
- 前端 `WorkspacePanel` 空态已按 `workflowStatus.candidateStatus` 和当前筛选条件区分展示。

### 6.3 本期修正

- 后端系统候选为空文案去掉“筛选条件”，避免把候选池供给问题误解释为用户筛选问题。
- 用户筛选为空继续只由前端当前筛选条件和查询结果判断，不改写后端候选池状态。
- 补充后端回归测试，固定候选池生成结果为空时的 `statusCode/statusMessage/riskHints/workflowStatus`。

### 6.4 验收

- 候选池本身为空时，状态为 `empty`，文案不包含“筛选”。
- 用户选择筛选/排除条件后结果为空时，候选列表只显示“当前筛选结果为空”。
- 候选偏少时，候选概览展示“候选不足”标签，详情在 tooltip 中展示。

## 7. 专业组内专业顺序和专业模式导出结构

### 7.1 背景和目标

生产会话 `2268` 暴露两个方案可信度问题：

- 院校专业组模式下，生成方案里的专业组内专业没有默认按专业录取率正排。
- 专业+大学模式下，导出文件会呈现类似专业组的“学校下嵌套多个专业”结构。

这两个问题都发生在新版 PlanningState 接管旧版推荐结果之后，属于新状态模型和导出模型的语义偏移。`3.0.2` 需要把专业组、专业+大学两种模式的用户心智重新固定：

- `majorGroup`：一个专业组是一个排序单元，组内专业明细按专业录取率从低到高展示和导出，对齐老版本口径。
- `major`：一个“学校 + 专业”组合就是一条排序志愿，导出时一条志愿一行，不按学校合并。
- 专业组模式下，前端工作区优先直接消费 `orderedPlanState.units`；只有单位结构缺失时才回退到扁平 `orderedPlanState.items` 重新分组，避免把后端已归一好的组内顺序和院校录取率再次打散。

### 7.2 问题 1：专业组内专业没有按录取率正排

当前链路：

1. rank 返回专业组候选，每个专业组内有 `majorList`。
2. `PlanningStateService.flattenCandidates()` 将专业组候选拆平成多个 `CandidateItemDTO`，每个专业携带 `admissionRatio`，组层录取率在 `schoolEnrollRatio`。
3. `groupCandidatesToPlanningUnits()` 按专业组重新聚合。
4. `buildPlanningUnit()` 调用 `selectMajorGroupPreferredMajors()` 选择组内专业。
5. `replaceDraftWithInitialRecommendation()` 将 `PlanningUnitDTO.selectedMajors` 写入 `draft.units` 和 `draft.items`。
6. `generateOrderedPlan()` 通过 `buildOrderedUnitsFromOrderedItems()` 生成 `orderedPlanState.units`。
7. 前端工作区和导出都读取 `orderedPlanState.units.majorItems`。

根因：

- `buildMajorGroupInnerCandidateComparator()` 的排序优先级是 `preferred -> futureDevelopmentScore -> intentScore -> admissionRatio -> finalScore -> volunteerId`，录取率不是第一排序维度。
- `selectMajorGroupPreferredMajors()` 会把满足 `admissionRatio >= schoolEnrollRatio` 的托底专业提前加入 `selectedMajors`，之后没有做展示顺序归一。
- `buildDraftUnitsFromPlanningUnits()` 和 `buildOrderedUnitsFromOrderedItems()` 都保留上游顺序，导致该顺序进入页面和导出。

修复原则：

- 选择专业和展示专业分开处理：
  - 选择阶段继续保留偏好、就业/发展、意向、托底等策略，避免影响专业组能否覆盖用户要求。
  - 展示/导出阶段对已选专业统一按 `admissionRatio asc` 排序，录取率为空排最后。
- 托底专业不丢失，但托底不再强制置顶。托底能力用 `safetyMajor` 标记和审查信息表达。
- `allMajors` 如果用于候选明细，可继续保留策略排序；`selectedMajors / draftUnit.majorItems / orderedUnit.majorItems` 是当前方案明细，应使用录取率正排。

建议落点：

- 在 `PlanningStateService` 增加一个私有 comparator，例如 `buildSelectedMajorDisplayComparator()`：
  - `admissionRatio asc`
  - `intentScore desc` 或 `finalScore desc` 作为稳定兜底
  - `volunteerId asc` 作为最终稳定键
- 在以下位置统一调用，避免只修一个入口：
  - `buildPlanningUnit()` 设置 `selectedMajors` 前或后。
  - `buildDraftUnitsFromPlanningUnits()` 拷贝 `selectedMajors` 时。
  - `buildOrderedUnitsFromOrderedItems()` 返回 `OrderedUnitDTO` 前，对每个 `unit.majorItems` 归一排序。
  - `buildMajorGroupExcelRowsFromItems()` fallback 路径中，对聚合出来的 `majorItems` 排序。

实现记录：

- 已在 `PlanningStateService` 增加 `buildSelectedMajorDisplayComparator()` 与 `sortSelectedMajorsForDisplay()`，排序规则为 `admissionRatio asc -> intentScore desc -> finalScore desc -> volunteerId asc`，录取率缺失排后。
- `buildPlanningUnit()` 只在 `selectedMajors` 输出阶段排序，不改变 `selectMajorGroupPreferredMajors()` 的选专业策略，因此偏好、发展/就业、意向和托底选择仍按原逻辑生效。
- `buildDraftUnitsFromPlanningUnits()`、`syncDraftUnitsWithItems()`、`buildOrderedUnitsFromOrderedItems()` 均在写出 unit 前统一归一 `majorItems` 顺序，覆盖初始方案、手动加入方案、草稿同步、专业组移动/排序区重建等入口。
- `PlanningExcelExportBuilder` 在专业组导出时对 `unit.majorItems` 做候选池兜底排序：如果历史 unit 内专业缺少录取率，会通过 `CandidateExportResolver` 根据 `volunteerId`、旧 ID 前缀或专业组名 + 专业名反查候选后排序。

不做项：

- 不改变专业组本身在排序区的顺序。
- 不改变 `rank` 服务的推荐得分计算。
- 不把托底专业从方案中移除。

### 7.3 问题 2：专业+大学模式导出出现专业组式嵌套结构

当前链路：

- `PlanningExcelExportBuilder.build()` 根据 `candidatePoolState.volunteerModel` 判断模式。
- `majorGroup` 调 `buildMajorGroupExcelRows()`，按 `OrderedUnitDTO` 导出。
- `major` 调 `buildMajorSchoolExcelRows()`。
- `buildMajorSchoolExcelRows()` 当前会按 `schoolId / planSchoolDataId / schoolName` 聚合同校志愿，并把多个专业写入同一个 `VolunteerExcelData.majorList`。
- `ExcelUtil.createDataRows()` 会按 `majorList` 生成多行并合并学校列，因此专业模式也呈现“学校下多个专业”的结构。

根因：

- 新版导出构建器把专业+大学模式理解为“学校聚合 + 专业明细”，而产品心智应是“每条专业志愿独立排序”。
- 单测 `shouldBuildMajorSchoolExportRowsGroupedBySchool()` 固定了该行为，因此需要同步调整测试语义，而不是只改实现。

修复原则：

- `major` 模式导出一条 `OrderedItemDTO` 对应一个 `VolunteerExcelData`。
- 每个 `VolunteerExcelData.majorList` 只包含当前志愿对应的一个专业。
- `index` 来自当前排序顺序重新连续编号，继续复用已有 `renumberMainRows()`。
- 同校不同专业不合并、不共享一个序号。
- `majorGroup` 模式逻辑不变，继续按 `OrderedUnitDTO` 聚合。

建议落点：

- 将 `buildMajorSchoolExcelRows()` 从“按学校聚合”改为“按 ordered item 映射”：
  - 遍历 `orderedPlanState.items`。
  - 使用 `CandidateExportResolver.resolve(orderedItem)` 找候选明细。
  - 每个 item 构建一个 `VolunteerExcelData`，`majorList` 放一个 `toMajorExcelData(candidate, false)`。
  - 如果 candidate 解析失败，应尽量用 `orderedItem.schoolName / majorName` 构建最小可导出行，避免整条志愿静默丢失；是否允许缺失候选需要在实现时结合现有导出异常策略确认。
- 删除或改写 `MajorSchoolExportGroup / MajorSchoolExportEntry` 的专业模式使用路径；如只剩 fallback，可移除未使用内部类。
- 更新 `PlanningExcelExportBuilderTest.shouldBuildMajorSchoolExportRowsGroupedBySchool()` 为“同校多专业也按志愿独立导出”。

实现记录：

- `buildMajorSchoolExcelRows()` 已改为按 `OrderedItemDTO.position` 遍历映射，每条排序志愿生成一条 `VolunteerExcelData`。
- 每条专业+大学导出行的 `majorList` 只包含当前候选对应的一个专业，最终序号继续通过 `renumberMainRows()` 连续重排。
- 已移除专业模式按学校聚合的 `MajorSchoolExportGroup / MajorSchoolExportEntry` 使用路径，避免后续再次把专业模式导出误建模成专业组结构。
- `majorGroup` 导出仍走 `OrderedUnitDTO`，一个专业组一条主志愿，组内专业明细保留。

不做项：

- 不改 `ExcelUtil` 的通用写表能力；它仍需要支持专业组模式多专业明细。
- 不改旧版 legacy 导出接口。
- 不在前端对下载文件做二次处理。

### 7.4 测试设计

后端单测：

- `PlanningStateServiceTest`
  - `majorGroup` 初始方案中，同一专业组被选专业按 `admissionRatio asc`。
  - 含托底专业时，托底专业仍存在，但顺序按录取率。
  - 录取率为空的专业排在最后。
  - `buildOrderedUnitsFromOrderedItems()` 兼容历史 draft/unit 顺序，最终输出仍归一。
- `PlanningExcelExportBuilderTest`
  - `major` 模式同校两个专业导出为两条主志愿行，每条 `majorList.size()==1`。
  - `major` 模式导出序号连续，和 `orderedPlanState.items` 顺序一致。
  - `majorGroup` 模式仍从 `orderedPlanState.units` 导出，一个专业组一条主志愿，组内专业明细保留。
  - 旧 ID 兼容解析仍能导出专业明细。

人工验收：

- 新建 `majorGroup` 会话，检查页面方案区每个专业组内专业录取率从低到高。
- 对同一 `majorGroup` 会话导出 Excel，检查组内专业顺序与页面一致。
- 新建 `major` 会话，手动让同一学校多个专业同时在方案中，导出 Excel 后确认每个专业是独立志愿行。
- 对手动移动/排序后的 `major` 会话导出，确认导出顺序等于页面排序区顺序。

### 7.5 风险

- 如果当前产品仍希望专业组内优先展示“更符合偏好/就业更好”的专业，录取率正排会改变用户看到的首位专业。本期按老版本专业组内专业展示口径处理：低录取率在前、高录取率在后。
- 如果某些候选缺少 `admissionRatio`，排序会把它放到后面；需要通过测试确保不会导致专业丢失。
- 专业模式导出改为独立行后，文件行数可能比之前增加，但这符合专业+大学模式“一条志愿一个专业”的用户心智。

## 8. Agent 长历史污染和上下文成本治理

### 8.1 背景和目标

`3.0.2` P0 要求至少完成长历史污染和 token 过重的设计方案，并完成验证或首轮低风险实现。当前目标不是重写整个 agent planner，而是先把“主 agent 每轮带完整历史”的风险收敛：

- 降低长会话下每轮请求的输入 token 和接口延迟。
- 降低旧回复、旧 tool return、旧 pending preview 对本轮意图判断的污染。
- 保留最近上下文、当前待确认动作和必要规划摘要，避免影响“确认执行”“按刚才那个处理”等多轮承接。
- 不改变高副作用动作必须 preview -> confirm -> apply 的协议。

### 8.2 当前链路

当前 `ChatService.handle_message()` 的主流程如下：

1. `ChatHistoryStore.load(session_id)` 从 SQLite 读取完整 pydantic-ai 历史。
2. `pydantic_ai_messages_to_dicts(history)` 抽取文本历史给 `RequestContext.chat_history`，并追加当前用户输入。
3. `_extract_pending_plan_action(history)` 从完整历史中查找待确认方案动作。
4. `ConversationPhase.from_legacy_context()` 用 pending 信息和 `PlanningSummary` 构建当前阶段。
5. 普通路径调用 `self.agent.run_with_message_deltas(user_prompt=content, message_history=history, deps=request_context)`，主模型会看到完整 `message_history`。
6. 返回后把 `new_messages` 追加到原 `history` 并整体保存。

已存在的局部保护：

- 专业、院校、地域、职业意向抽取工具内部大多使用 `trim_last_n_messages()`，默认只取最近 `EXTRACT_LAST_N_MESSAGES=10`。
- `intent_state_tool` 的确认落库链路已经避免从完整历史重复抽取旧偏好。
- direct pending plan / intent confirmation 可以绕过主模型，直接执行上一轮 pending。
- `UsageTracker` 已记录每轮 token，可以作为优化前后观测口径。

主要缺口：

- 主 agent 调用仍传完整 pydantic-ai 历史，长会话里旧 tool call / tool return / assistant 解释会持续进入模型上下文。
- `RequestContext.chat_history` 当前也是完整文本历史加当前输入，虽然部分工具会裁剪，但其他工具或指令层仍可能读取完整历史。
- SQLite 只保存完整历史，没有“发送给模型的短上下文”和“长期审计历史”的分层。
- 缺少针对长历史会话的固定回归样本，无法量化输入 token、延迟和误路由改善。

### 8.3 方案原则

本期采用“传给模型裁剪，持久化仍完整”的低风险方案：

- 历史库继续保存完整 pydantic-ai 历史，便于审计、排查和恢复。
- 每轮调用主 agent 前构造 `runtime_history`，只传给模型使用，不覆盖原始历史。
- direct pending 确认仍使用完整历史查找 pending payload，避免裁剪后丢失确认动作。
- `RequestContext.chat_history` 也使用同一份可控短文本历史，外加当前用户输入；需要找 pending 的代码继续读完整 pydantic 历史。
- 首版只做规则裁剪，不做 LLM 摘要，避免引入新的模型调用和摘要误差。

### 8.4 Runtime History 裁剪规则

新增 agent history 配置，建议环境变量前缀仍放在 `HISTORY_`：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `HISTORY_RUNTIME_MAX_MESSAGES` | `24` | 主 agent 每轮最多携带的历史 message 数，不含当前用户输入 |
| `HISTORY_RUNTIME_KEEP_RECENT_TURNS` | `8` | 至少保留最近若干轮用户/助手文本消息 |
| `HISTORY_RUNTIME_KEEP_PENDING` | `true` | 若完整历史中存在 pending plan / intent，保留相关 tool call / tool return |
| `HISTORY_RUNTIME_DROP_TOOL_RETURNS_OVER_CHARS` | `3000` | 超长 tool return 不直接带入模型，可替换为摘要占位 |
| `HISTORY_RUNTIME_SUMMARY_ENABLED` | `false` | LLM 摘要后续再打开，本期默认关闭 |

裁剪输入：

- `full_history`：SQLite 中完整 pydantic-ai 消息。
- `latest_user_content`：当前用户输入。
- `pending_plan_action`、`pending_intent_change`、`planning_summary`：当前已解析出的结构化状态。

裁剪输出：

- `runtime_model_history`：传给 `BaseAgent.run_with_message_deltas()` 的 pydantic-ai 消息列表。
- `runtime_chat_history`：传给 `RequestContext.chat_history` 的文本历史，最后追加当前用户输入。
- `history_metrics`：记录 `full_len / runtime_len / full_text_chars / runtime_text_chars / dropped_tool_return_count / has_pending`。

保留优先级：

1. 最近用户输入之前的最近 N 条真实文本消息。
2. 上一轮 pending action 相关的 tool call / tool return / assistant preview，确保“确认”承接。
3. 最近一次方案编辑、审查、排序、筛选相关工具调用的简短结果摘要。
4. 旧欢迎语、旧长篇方案播报、旧候选大列表、旧导出/审查 tool return 默认不保留原文。

超长工具结果处理：

- 对超过阈值的 tool return，只保留：
  - `tool_name`
  - `result_kind / action_family / message_code`
  - `workspace_refresh_targets`
  - `summary / userFacingSummary`
  - pending payload 的引用信息
- 不把候选池大列表、完整方案大 JSON、完整 review checks 原样带入主模型。

实现记录：

- `HistoryConfig` 新增 `runtime_max_messages / runtime_keep_pending / runtime_drop_tool_returns_over_chars / runtime_summary_enabled` 配置，其中首版默认 `runtime_max_messages=24`、`runtime_drop_tool_returns_over_chars=3000`、摘要关闭。
- `ChatService.handle_message()` 在解析完整历史中的 pending 之后，调用 `build_runtime_history()` 构造只用于本轮模型调用的 `runtime_model_history` 和 `runtime_chat_history`。
- 主 agent 调用改为传入 `runtime_model_history`；`RequestContext.chat_history` 改为短文本历史加当前用户输入。
- SQLite 保存仍以完整历史为基底追加本轮 `new_messages`，不会把完整历史缩短成 runtime history。
- `runtime_keep_pending=true` 时，如果完整历史中存在有效待确认方案动作，runtime history 会额外保留产生该 pending 的最近一轮用户请求、工具调用、工具返回和 assistant 预览回复；因此 pending 场景下 runtime 消息数可能略高于 `runtime_max_messages`，但可以避免“刚预览完，用户追问这个调整影响什么”时模型看不到预览上下文。
- 超长 `ToolReturnPart.content` 会压缩为包含 `result_kind / action_family / message / summary / workspace_refresh_targets / applied` 等关键字段的短 JSON，占位标记 `_truncated=true`。
- 日志新增 `Runtime history prepared`，记录 `full_len / runtime_len / full_chars / runtime_chars / dropped_tool_returns / has_pending`，用于后续对比 token 和长历史污染。

### 8.5 与 Pending 协议的关系

高副作用动作仍按现有规则执行：

- 未确认：`execute_plan_action` 返回 `preview_only`，写入 pending payload。
- 用户确认：优先走 direct pending confirmation，不进入主 agent。
- 没有 pending 却说“确认”：继续返回“没有上一轮待确认动作”的保护提示。

因此 runtime 裁剪不得影响：

- `_extract_pending_plan_action(full_history)` 仍读完整历史。
- `_has_pending_intent_change(session_id)` 仍读后端 pending 状态。
- `ConversationPhase` 仍以结构化 pending 和 `PlanningSummary` 为准，不依赖被裁剪的自然语言历史。

### 8.6 测试设计

Agent 单测：

- 构造 60+ 条历史，其中包含旧方案 preview、大 tool return 和当前最新问题，断言传给主 agent 的 `message_history` 不超过配置上限。
- 构造含 pending plan action 且 pending 轮不在最近窗口内的长历史，断言 runtime history 仍保留对应 tool call / tool return 和预览回复。
- 构造含 pending plan action 的长历史，断言 direct confirmation 仍能执行，不因 runtime 裁剪丢失 payload。
- 构造无 pending 但用户说“确认”的长历史，断言仍返回 no-pending guard。
- 构造旧历史中有“我想去北京”，最新输入“不要去北京”，断言 intent preview 只围绕最新输入，不被旧偏好反向污染。

场景回归：

- 干净会话和长历史会话分别跑：
  - “看看方案”
  - “按院校层次排序”
  - “确认”
  - “去掉 XX 大学的 XX 专业”
  - “加一个 XX 大学 XX 专业”
- 记录每轮：
  - input_tokens
  - total duration
  - tool_calls
  - action_family
  - result_kind
  - workspace_refresh_targets

验收口径：

- 长历史会话下，主 agent 输入 token 明显下降。
- 当前轮动作语义与干净会话一致。
- 高副作用动作仍先 preview，确认后才 apply。
- 方案编辑后工作区刷新目标不丢失。

新增固定场景样例：

- `zhiyuan-agent/examples/dialog_regression_302_agent_cases.json`
- 覆盖方案现状、按院校层次排序、专业组整体移动、按学校/专业简称删除、调整后查询等 3.0.2 关键入口。
- `zhiyuan-agent/examples/dialog_regression_302_explore_intent_cases.json`
- 覆盖 Explore/Intent 前置层：专业/职业/地域/院校探索，软偏好、硬约束、软硬混合、意向修订、未确认意向下查询方案、候选风险解释和专项资格解释。
- `zhiyuan-agent/examples/dialog_regression_302_readonly_real_session_cases.json`
- 覆盖真实 `session=17` 后端方案数据下的只读 Explore/Intent smoke，要求不发送无意义工作台联动卡片。
- 运行方式：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_agent_cases.json \
  --assert-plan-style

.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_explore_intent_cases.json \
  --assert-plan-style \
  --session-offset 200000

.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_readonly_real_session_cases.json \
  --assert-plan-style \
  --response-timeout 180 \
  --clear-history
```

这些样例需要本地 agent/server/web 数据链路和模型配置可用；自动单测只负责验证 pending 协议、runtime history 和场景目录结构不破坏内部结构。
`--session-offset` 会把样例里的固定数字 session 映射到一批新的数字会话，并在输出里保留 `base=<原始 sessionId>`，用于规避历史聊天记录、旧 `planEditCache` 和已消费 pending 对真实回归结果的污染。因为后端 `chatSessionId` 当前按数字处理，该参数只支持数字 session。
需要注意，`--session-offset` 只隔离 Agent 本地聊天历史和后端按 session 写入的 extra-data，不会复制原 session 的成绩、候选池、排序方案或历史迁移文件。因此：

- 方案编辑、方案查询、候选承接这类依赖真实后端会话数据的回归，优先使用已有数据完整的 session（例如本地 `16/17`），并在执行前清理 Agent 本地 SQLite 对话历史。
- Explore/Intent 纯对话历史隔离、确认边界和模型回复风格观察，可以使用 `--session-offset` 跑干净数字 session。
- 如果 offset 后样例提示“缺少成绩信息”“方案为空”“候选为空”，不能直接判定为业务链路失败，应先确认该映射 session 是否具备后端基础数据。

### 8.7 WebSocket 异常收口

真实场景验证依赖外部大模型服务。若模型接口返回 `503`、超时或其他异常，plus 兼容 WebSocket 必须返回一个完整结束包：

- `type="error"`
- 面向用户的错误文案
- `end=true`

这样前端和 `dialog_regression_runner.py` 都能明确结束当前轮，不会把模型服务异常误判为本地 WebSocket 180 秒超时。该处理只负责协议收口，不在异常分支执行方案动作，也不生成工作台刷新卡片。

验证口径：

- service 抛异常时，compat endpoint 返回 `error + end=true`。
- timeout fallback 原有 `text + end=true` 行为保持不变。
- 真实模型服务不可用时，验收结论记录为模型服务不可用，不能据此判定方案编辑链路失败。

### 8.8 Explore/Intent 场景增强

本轮先增强场景覆盖，不直接改主 agent 路由或工具选择逻辑。目标是给后续串联调优提供稳定样本：

- Explore 只读类问题：
  - 专业比较：法学 vs 财经。
  - 职业比较：体制内 vs 读研。
  - 地域/院校机会：天津、河北、具体院校。
  - 候选解释：计算机方向机会、压线时可选少的原因、专项资格限制。
- Intent 状态类问题：
  - 软偏好：专业、职业、地域、院校关注。
  - 硬约束：排除护理、中西医结合、北京等。
  - 软硬混合：财经优先但排除指定专业。
  - 意向修订：旧地域偏好被新表达覆盖或调整。
  - 未确认意向：用户说“先不确认，看看方案”时，不应直接落库或重复触发确认。

验收口径：

- Explore 回复不触发方案变更、不出现确认执行文案。
- Intent 变更先 preview，用户确认后再生效。
- 未确认 Intent 下的 Plan 查询仍能回答当前方案，不自动确认上一条意向。
- 方案相关后续问题只读时不发送无意义工作台刷新；真正进入 Plan 调整时仍走 preview -> confirm -> apply。

本期不做：

- 不新增确定性字符串路由短路。
- 不在 `ChatService` 增加 Explore/Intent 的硬编码匹配。
- 不改写意向状态模型；后续根据真实 WebSocket 结果再判断是否需要调整 prompt、tool dispatch rules 或 intent_state_tool。

真实回归复盘：

- 意向确认缓存收口后，`conversation_phase.pending` 是运行时确认主源；真实 WebSocket 复测中已验证 `planEditCache` 可被 `confirm` 消费并清空。
- 302 Explore/Intent 场景的固定 session 已出现历史状态污染：部分首轮回复显示“已经记录”，后续确认又找不到 pending，不能直接判定为新链路失败。
- 302 Explore/Intent offset 场景又暴露另一个边界：干净映射 session 没有原 session 的成绩/方案/候选数据，适合验证对话确认边界，不适合作为“当前方案承接/候选里有没有”的业务正确性准入。
- 模型接口偶发 `503` 或连接错误时，compat WebSocket 应返回 `error + end=true`，该场景记录为模型服务不可用，不作为业务链路失败。
- 后续全量 302 WebSocket 回归分两类执行：依赖真实方案数据的用例使用原 session 并清理 Agent 本地历史；纯对话隔离用例使用 `--session-offset` 跑干净映射 session。如果 offset 后仍失败，先确认是否缺少后端基础数据，再按具体 case 定位 Explore -> Intent preview -> confirm -> Plan query 链路。

### 8.9 本期不做项

- 不删除 SQLite 完整历史。
- 不把历史摘要写入正式用户画像或 planningState。
- 不引入 LLM 摘要作为默认链路。
- 不重写 `planning_workflow_tool` 或删除旧 router。
- 不为了个别脏历史会话增加关键词短路规则。

### 8.10 创建成功跳转与采集确认文案回归

问题：

- 创建会话成功后的跳转被过度收口到会话列表/抽屉，导致用户新建完成后没有进入刚创建的详情页。
- “个人信息补全完成后回会话列表”和“创建会话完成后进详情页”属于两个不同入口，不能共用同一跳转策略。
- 专业意向采集确认气泡直接字符串化结构化值，出现 `[object Object]`、`false` 这类用户不可理解内容。

设计：

- 独立 `/customerDetail` 创建入口成功后跳转 `/sessionDetailV2`，携带 `chatSessionId / userId / userName / page / pageSize`。
- 移动端或详情页内嵌创建抽屉只负责承载采集流程；创建成功后关闭抽屉并进入新会话详情，不再打开会话列表抽屉。
- 登录后的基础个人信息补全仍保留“回会话列表”的产品语义，不复用创建会话成功跳转。
- 专业意向确认气泡按字段格式化：
  - 意向专业：展示专业大类/子类名称，过长时截断为“等 N 个”。
  - 排除专业：展示用户排除的专业名称。
  - 中外合作：展示“接受/不接受”。
  - 学费区间：展示“不限 / X 万以上 / X - Y”。

### 8.11 专业组内专业排序复核

`sessionId=121` 本地接口复核结果：

- `orderedPlanState.units` 已返回 30 个专业组、94 个专业。
- 专业组内部 `majorItems` 应按专业录取率正排，例如修正后防灾科技学院应为 `10 / 10 / 14 / 18`，华北科技学院应为 `18 / 22 / 22 / 22 / 22`。
- 专业组之间按组录取率 `18 / 22 / 26...` 升序，是方案层录取率排序口径，不等同于组内专业排序。

处理口径：

- 后端组内排序链路已收口到 `orderedPlanState.units.majorItems`，前端继续以该字段作为专业组展示和导出的顺序来源。
- 若页面仍看到组内倒排，优先确认后端已重启到最新代码，并检查前端是否走了 `orderedPlanState.units`。

### 8.12 方案 pending 确认链路复盘

#### 8.12.1 完整调用链

方案动作从对话到实际改方案的链路是：

1. WebSocket / HTTP 对话入口把用户文本交给 `ChatService.handle_message()`。
2. `ChatService` 先读取完整 SQLite 历史。完整历史只用于恢复结构化状态、审计和 pending 解析，不会因为 runtime 裁剪而丢弃。
3. `_extract_pending_plan_action(full_history)` 从完整历史中的 `plan_next_action` / `execute_plan_action` 工具返回里提取上一轮仍待确认的方案动作，并把 preview payload 改写成 `stage="apply"` 的确认后执行 payload。
4. `build_runtime_history()` 构造短上下文，只发送给主 agent；完整历史继续保留。若存在 pending，会额外保留产生 pending 的工具调用、工具返回和预览回复。
5. `ConversationPhase.from_legacy_context()` 把旧的 `pending_plan_action`、`pending_intent_change` 和当前 `PlanningSummary` 转为统一阶段对象，注入 `RequestContext`；从这里开始，运行时只认 `conversation_phase.pending` 作为待确认主源。
6. 如果本轮是短确认词且存在 `conversation_phase.pending`，`ChatService` 直接调用 `execute_plan_action(..., stage="apply")`，不再进入主模型。
7. 如果不存在 pending 或本轮不是确认，才进入主 agent。主 agent 根据工具协议走只读查询、preview，或继续产生新的 pending。
8. 本轮产生的 tool call / tool return / assistant 回复追加写回完整历史，供下一轮继续恢复 pending。

#### 8.12.2 当前实现边界

现在不是把“按院校层次排序、移动、删除、加入方案”等业务动作重新改成字符串模板匹配。业务动作仍由模型和结构化工具链决定：

- `plan_next_action` 负责规划动作类型和参数。
- `execute_plan_action` 负责 preview / apply。
- `_allows_mutating_apply()` 负责高副作用动作的 apply guard，只有 action_family 与 pending 匹配且用户是短确认时才允许执行。
- 工作区刷新由 `execute_plan_action` 返回的 `workspace_refresh_targets` 决定。
- 工作区刷新只允许真实成功的变更动作触发。`execute_plan_action` 返回 `applied=false` 或 `result_kind=error` 时，即使某个旧 handler 误带了 `workspace_refresh_targets`，`ChatService` 也必须过滤掉，避免出现“文本说没有定位到/没有执行，右侧却刷新方案”的错位。

代码里仍存在少量字符串判断，但它们不是核心业务路由：

- `_is_plan_action_confirmation()` / `_is_short_plan_confirmation()`：只识别“确认、执行、好的、就按这个来”等短确认，用于承接上一轮 pending。
- `_PLAN_MUTATION_PROMPT_KEYWORDS`：只在 timeout fallback 里避免把“排序/移动/删除”这类变更请求误降级成 `query_state` 播报，不用于规划具体动作。
- `_PLAN_STYLE_GUARD_PROMPT_KEYWORDS`：只用于回复风格兜底，避免严重用户体验问题，不决定方案如何变更。

因此当前收口原则是：允许有限的确认词和保护性 guard，但不再增加“用户说某关键词就固定走某动作”的字符串路由。

补充说明：

- `pending_plan_action` / `pending_intent_change` 仍然保留在旧会话和测试桥接里，但只作为 phase 尚未注入时的兼容来源。
- 一旦 `conversation_phase` 已经存在，旧字段就不再参与运行时 pending 判定，避免出现 phase 与 legacy 两套状态各说各话。
- `planEditCache` 这类旧意向缓存先在服务层转换为 `PendingConfirmation` 再注入 phase；确认动作优先消费 phase 内的 payload，不再直接把 backend cache 当成运行时状态源。

#### 8.12.3 当前问题

当前暴露的问题集中在 pending 状态仍然依赖聊天历史恢复，而不是独立持久化状态：

- 若上一轮已经 preview，用户中间追问“解释一下影响”这类说明型内容，主 agent 可能只自然语言解释，不再产生新的 tool call。
- 旧实现曾在 `_extract_pending_plan_action()` 遇到新的 `UserPromptPart` 时直接清空 pending，导致下一轮“确认”读不到 pending，退化成 no-pending guard。
- runtime 裁剪解决了长历史污染和 token 膨胀，但如果 pending 只存在于很早的工具返回里，必须额外保留对应 preview 轮，否则模型解释时会缺上下文。
- 真实 WebSocket 验证仍未闭环：`session=16 / 把第3个专业组移到第5位` 曾出现 180s 超时或模型服务 `503`，目前自动单测已覆盖协议，但真实 agent 链路还需要在服务可用时复跑。
- 302 负例复跑暴露过一次刷新错位：`session=17 / 把河南农大建筑去掉` 的 preview 文案被模型说成“删除预览”，但确认 apply 重新解析时仍无法定位真实编号；旧 `remove_units` error 分支仍返回 `ordered` 刷新目标，导致前端收到无效刷新卡片。当前已按“错误不刷新”收口。

这不是后端方案执行能力本身坏了，而是“pending 状态来源、历史裁剪、模型解释轮次”之间的边界不够清晰。

#### 8.12.4 为什么之前没有暴露

之前没有及时暴露，主要是覆盖路径不够贴近真实对话：

- 旧回归主要覆盖“preview 后立即确认”的最短路径。
- 覆盖了“没有 pending 却说确认”的保护分支，但没有覆盖“preview -> 追问解释 -> 再确认”。
- 单测里曾保留“有新用户轮次就清掉 pending”的旧假设，所以错误行为被当成期望行为。
- 很多方案调整是从前端按钮直接触发，绕过了 agent 对话确认链路，不会暴露这类问题。
- 本地验证曾出现旧 agent 进程悬挂、端口命中旧代码的问题，导致“代码已修但验证仍像旧行为”的假象。

#### 8.12.5 3.0.2 收口口径

3.0.2 的收口口径：

- pending 解析继续读完整历史，不受 runtime history 裁剪影响。
- 允许说明型追问后继续保留 pending；超过多轮未确认再过期，避免长期挂起。
- 只有真实变更动作 apply 成功才清 pending；只读 query_state 不能清掉 pending。
- 只有真实变更动作 apply 成功才刷新工作区；普通定位失败、候选/志愿未唯一命中、缺少 volunteerId 等 error 分支只返回用户可理解的澄清，不发送 `planningWorkspaceAction`。
- `plan_next_action(stage="preview")` 和 `execute_plan_action(result_kind="preview_only")` 都能形成 pending，降低模型漏调用 `execute_plan_action` 的影响。
- 没有 pending 时的“确认”仍返回 no-pending guard，不能猜测执行。
- 后续若继续优化，优先把 plan pending 下沉为后端/agent 的结构化持久状态，避免继续从自然语言历史中反推。

#### 8.12.6 本次实现落地

本次修复把 pending 的来源、版本和过期边界进一步收紧：

- `plan_next_action` preview 和 `execute_plan_action` preview 都会把 `planning_version` 透传到 pending，并记录 `created_turn`。
- `ConversationPhase.from_legacy_context()` 恢复旧会话时，会优先使用 pending 自带版本号回填 `last_backend_version`，避免确认时拿错基线。
- `ChatService.handle_message()` 在进入主模型前会先做一次 `PlanningStateSync` 过期检查；但 mutating apply 仍会在 `execute_plan_action` 内再做一次守卫，保证确认态和执行态一致。
- 如果用户确认的是旧预览，而当前 `planningState.version` 已变化，系统会直接返回“预览已失效/请重新查看当前方案后再确认”一类的用户可理解提示，不会再调用后端变更接口，也不会发方案刷新卡片。
- 运行时的状态主源仍然只有 `conversation_phase.pending`；legacy 的 `pending_plan_action`、`pending_intent_change` 只做兼容桥接，不再参与新链路的状态判定。

### 8.13 大模型路由、触发和确认链路统一说明

当前运行时已经统一到一条主链路：

1. **路由入口统一**：`ChatAgent` 只注册语义工具和 Plan / Intent / Explore 相关工具，主路由依赖工具调用和指令约束，不再依赖固定关键词分流。
2. **Explore / Intent / Plan 分层统一**：
   - Explore 只负责方向适配度、学校/专业/地域/职业的只读分析。
   - Intent 只负责把新偏好/新要求整理成待确认预览。
   - Plan 只负责当前方案的查询、预览、确认和执行。
3. **确认入口统一**：本轮若存在 `conversation_phase.pending`，`ChatService` 直接消费短确认词并执行 `apply`，不再让主模型自己猜是不是在确认上一轮。
4. **状态主源统一**：运行时只认 `conversation_phase.pending`；`pending_plan_action` / `pending_intent_change` / `planEditCache` 只保留为旧会话兼容和数据桥接。
5. **字符串判断只留兜底**：`_is_plan_action_confirmation`、`_is_pending_intent_confirmation`、`_PLAN_MUTATION_PROMPT_KEYWORDS` 只用于短确认、错误兜底和超时保护，不参与正常动作规划。

尚未完全删除的兼容层：

- `planning_router_tool.py` 仍是旧单步规划兼容壳，不再作为 `ChatAgent` 的正式入口。
- `ActionResolver` 仍保留在仓库里作为结构化动作映射的实验/测试入口，主运行时未接入它。
- `handlers/registry.py` 仍是旧 handler 注册壳，当前仍处于迁移兼容状态。

因此当前结论不是“所有旧链路都物理删除了”，而是“主运行链路已经统一，旧链路只作为兼容和测试存在”。后续如果继续收口，应优先做的是把这些兼容壳逐步从主文档和主入口中剥离，而不是再增加新的关键词路由。

### 8.14 行为事件新表与导出态迁移

#### 8.14.1 目标

行为反馈数据后续以独立新表为主，不再把 `behaviorEvents` 作为长期主存储挂在 `planningState` JSON 里。当前规划是：

- 新表作为行为事件主存储，承接添加、删除、移动、排序、导出等成功动作。
- `planningState.behaviorEvents` 不再作为导出态或行为分析来源，新动作不再写入旧 JSON，服务端工作台响应也不再返回事件列表。
- `exportStatus / lastExportedAt` 改为读取新表；新表未命中时按未导出处理。
- `PlanningStateDTO` 已移除 `behaviorEvents` 字段；老 JSON 里即使仍存在该字段，也会在解析时被忽略。

#### 8.14.2 读写口径

新表需要承接的最小能力：

- 记录单条结构化行为事件，至少包含：
  - `chatSessionId`
  - `tenantId`
  - `eventType`
  - `planVersion`
  - `generationMode`
  - `volunteerIds / unitIds`
  - `fromPositions / toPositions`
  - `sortKey`
  - `positiveFeedback`
  - `snapshotDigest`：短摘要，只用于快速识别载荷是否变化，不承载大 JSON。
  - `eventPayloadJson`：事件详细载荷，记录动作涉及的志愿/专业组、前后位置和必要展示字段。
  - `createdAt`
- 事件范围只覆盖方案层面的成功动作，包括加入方案、从方案删除、单条移动、专业组移动/删除、应用排序和导出。
- 加入/删除只记录实际改变方案状态的志愿；重复加入、删除不存在志愿等无效请求不写行为事件，也不递增方案版本，避免反馈数据被无效点击污染，并避免导出态误判为已过期。
- 候选筛选的添加/排除/移除/清空不纳入本期行为事件闭环，仍只作为前端可见、可撤销的视图状态处理。
- 方案层动作的 `eventPayloadJson.items` 优先通过候选池补齐志愿字段，包含 `schoolId / schoolRank / majorId / admissionRatio / schoolEnrollRatio / finalScore` 等后续分析所需信息；找不到候选时再回退到排序区轻量字段。条目里的 `position` 表示动作后的排序位置，移动前后位置由 `beforePositions / afterPositions` 单独表达。
- 导出成功写 `plan_export`，并保留当前方案版本。
- `exportStatus` 计算优先看新表最新导出事件：
  - 没有导出事件：`not_exported`
  - 最新导出版本小于当前方案版本：`stale`
  - 最新导出版本与当前一致：`exported`

兼容策略：

- 读路径只查新表。
- 新表未命中时，不再读取旧 `planningState.behaviorEvents`，避免旧 JSON 中不完整或过期的事件影响当前导出态。
- 旧 `planningState.behaviorEvents` 不再保留 DTO 字段；新动作不再写入旧 JSON，避免规划状态 JSON 继续膨胀。
- 老会话 JSON 中残留的 `behaviorEvents` 会被忽略，不参与导出态和行为分析。

#### 8.14.3 双模式覆盖

行为事件写入跟随当前会话的 `candidatePoolState.volunteerModel`，最终落库到 `mode` 字段：

- `mode=major`：专业+大学模式，一条排序志愿就是一个学校 + 专业。
- `mode=majorGroup`：院校专业组模式，一个专业组是一个排序单元，组内包含多个已选专业。

两种模式都支持方案层行为事件，差异主要在是否存在专业组单元 `unitIds`：

| 事件类型 | 触发入口 | 专业+大学模式 | 院校专业组模式 | 主要分析语义 |
| --- | --- | --- | --- | --- |
| `plan_add` | 从候选加入方案 | 记录实际新增的 `volunteerIds` | 记录实际新增的专业 `volunteerIds`，专业组 unit 会由方案状态重建 | 用户主动选择某个志愿 |
| `plan_remove` | 从方案移除志愿 | 记录实际移除的 `volunteerIds` | 记录实际移除的专业 `volunteerIds`，如果是整组删除则走 `plan_unit_remove` | 用户否定或暂不需要某个志愿 |
| `plan_item_move` | 单条志愿移动 | 记录单条 `volunteerId` 的前后位置 | 保留兼容能力，但产品主入口优先使用专业组整体移动 | 用户调整单条志愿顺序 |
| `plan_unit_move` | 专业组整体移动 | 不作为主入口 | 记录 `unitIds` 以及组内全部 `volunteerIds`，位置以专业组为单位 | 用户调整专业组顺序 |
| `plan_unit_remove` | 专业组整体删除 | 不作为主入口 | 记录 `unitIds` 以及组内全部 `volunteerIds` | 用户删除整个专业组 |
| `plan_sort_apply` | 应用方案排序 | 记录排序后的全部 `volunteerIds`，行为分析主键仍是单条志愿 | 记录排序后的全部 `volunteerIds` 和专业组 `unitIds`，排序保持组内专业结构 | 用户认可某种排序规则 |
| `plan_export` | 导出方案 | 记录导出时的全部 `volunteerIds`，`positiveFeedback=true` | 记录导出时的全部 `volunteerIds` 和 `unitIds`，`positiveFeedback=true` | 强正反馈样本 |

专业组模式下，`unitIds` 只在组级操作、排序和导出中有稳定业务意义；加入/删除单个专业仍以 `volunteerIds` 为准。专业模式的行为分析主键统一使用 `volunteerIds`，即使某些兼容路径存在可派生的单位结构，也不把它解释成专业组。

#### 8.14.4 存储格式

最终存储表为 `assistant_planning_behavior_event`。结构化字段用于快速筛选，详细上下文进入 `event_payload_json`：

| 字段 | 含义 |
| --- | --- |
| `event_id` | 事件唯一 ID |
| `chat_session_id` | 会话 ID |
| `tenant_id` | 租户 ID，可为空 |
| `event_type` | `plan_add / plan_remove / plan_item_move / plan_unit_move / plan_unit_remove / plan_sort_apply / plan_export` |
| `mode` | `major` 或 `majorGroup` |
| `plan_version` | 事件对应的方案版本；导出事件为导出时版本，调整事件为即将保存后的版本 |
| `generation_mode` | 当前方案生成模式，如 `initial_auto / draft_reorder` 等 |
| `volunteer_ids_json` | 动作涉及的志愿 ID 列表 JSON |
| `unit_ids_json` | 动作涉及的专业组 ID 列表 JSON；只有 `mode=majorGroup` 的组级动作、排序和导出具备稳定组级语义 |
| `from_positions_json` | 移动或排序前的位置映射 JSON |
| `to_positions_json` | 移动或排序后的位置映射 JSON |
| `tier` | 事件代表志愿的冲稳保层级，用于轻量查询 |
| `admission_ratio` | 事件代表志愿的录取率，用于轻量查询 |
| `school_name / major_name` | 事件代表志愿的学校和专业名，用于轻量查询 |
| `sort_key` | 排序字段，如 `admissionRatio / schoolRank / finalScore` |
| `positive_feedback` | 是否正反馈；当前导出为 `true`，其他方案操作为 `false` |
| `snapshot_digest` | `event_payload_json` 的 SHA-256 短摘要 |
| `event_payload_json` | 事件详细载荷 JSON |
| `create_time / update_time` | 事件创建和更新时间 |

`event_payload_json` 按事件类型存详细上下文，不要求每类事件都有完全相同字段。专业+大学模式单条移动示例如下：

```json
{
  "source": "plan_item",
  "mode": "major",
  "planVersion": 8,
  "requiredCount": 45,
  "requiredUnitCount": null,
  "volunteerIds": ["ps1_m1"],
  "beforePositions": {"ps1_m1": 1},
  "afterPositions": {"ps1_m1": 3},
  "items": [
    {
      "volunteerId": "ps1_m1",
      "planSchoolDataId": "ps1",
      "schoolId": "s1",
      "schoolName": "北京邮电大学",
      "schoolRank": 42,
      "provinceName": "北京",
      "cityName": "北京",
      "majorId": "m1",
      "majorName": "计算机科学与技术",
      "majorCode": "080901",
      "tier": "稳",
      "admissionRatio": 58.0,
      "schoolEnrollRatio": 58.0,
      "finalScore": 91.5,
      "preferred": true,
      "position": 3,
      "orderedBy": "user",
      "orderReason": "user_move"
    }
  ]
}
```

专业组整体移动示例：

```json
{
  "source": "plan_unit",
  "mode": "majorGroup",
  "planVersion": 12,
  "requiredCount": 30,
  "requiredUnitCount": 30,
  "unitId": "ps2",
  "volunteerIds": ["ps2_m3", "ps2_m4"],
  "beforePositions": {"ps2": 5},
  "afterPositions": {"ps2": 2},
  "items": [
    {
      "volunteerId": "ps2_m3",
      "planSchoolDataId": "ps2",
      "schoolId": "s2",
      "schoolName": "天津财经大学珠江学院第01组",
      "schoolRank": 870,
      "majorId": "m3",
      "majorName": "会计学",
      "tier": "稳",
      "admissionRatio": 24.0,
      "schoolEnrollRatio": 18.0,
      "finalScore": 83.2,
      "position": 2,
      "orderedBy": "user",
      "orderReason": "user_unit_move"
    }
  ]
}
```

说明：

- `items` 是后续行为分析的主数据，优先从候选池补全；如果候选池缺失，才使用排序区已有轻量字段兜底。
- 专业组模式中，组级录取率在 `schoolEnrollRatio`，专业录取率在 `admissionRatio`；组级移动/删除的 payload 使用 `unitId` 表示当前组，结构化列 `unit_ids_json` 保留动作涉及的专业组列表，组内专业仍保留各自 `volunteerId`。
- `plan_sort_apply` 的排序字段同时写入结构化列 `sort_key` 和 payload 的 `sortField`；专业组排序涉及的专业组列表写入结构化列 `unit_ids_json`。
- `plan_export` 的 payload 会携带 `volunteerIds / unitIds / items`，用于把导出正反馈关联到当时完整方案。
- `position` 表示动作完成后的排序位置；移动前后位置统一读取 `beforePositions / afterPositions`。
- `snapshotDigest` 不再存大 JSON，只存摘要，完整事件上下文只在 `event_payload_json`。

#### 8.14.5 迁移边界

- 老会话不会强制回填历史事件到新表。
- 新表上线前后可以保留双写或兼容读，但主口径必须是新表。
- 不把行为事件直接用于算法训练或推荐调参，仍只作为反馈和状态派生数据。

#### 8.14.6 验收

- 添加、删除、移动、排序、导出后，新表能查到对应事件。
- `exportStatus` 在前端展示和旧口径一致。
- 新表未命中时，导出态明确回到未导出，不再从旧 JSON 推导。
- 移除旧字段消费后，导出态仍可从新表稳定恢复。
- 专业+大学模式写入 `mode=major`，以 `volunteerIds` 作为主要对象；院校专业组模式写入 `mode=majorGroup`，组级动作同时带 `unitIds` 和组内 `volunteerIds`。

当前实现已经完成：

- 行为事件写入已接入独立新表，旧 `planningState.behaviorEvents` 不再作为业务读源。
- `exportStatus / lastExportedAt` 已改为读取新表；新表未命中按未导出处理。
- `selectDraftItems / removeDraftItems / moveOrderedItem / moveOrderedUnit / removeOrderedUnits / sortOrderedPlan / exportOrderedPlan` 已改为同事务内双写行为事件。
- 专业+大学模式覆盖 `plan_add / plan_remove / plan_item_move / plan_sort_apply / plan_export`；院校专业组模式覆盖 `plan_add / plan_remove / plan_unit_move / plan_unit_remove / plan_sort_apply / plan_export`。
- 事件载荷已从 `snapshotDigest` 拆出为 `eventPayloadJson`，避免短摘要字段存大 JSON；`snapshotDigest` 只保留 SHA-256 短摘要。
- `plan_unit_move / plan_unit_remove / plan_sort_apply` 的事件载荷已通过候选池补齐组内专业或排序后志愿的录取率、院校层次、推荐分等字段，避免后续行为分析只能看到 `OrderedItemDTO` 的轻量字段。
- `planningState.behaviorEvents` 已停止新写入，详细 `eventPayloadJson` 仅进入新表，工作台响应也不再返回行为事件列表。
- `PlanningStateDTO` 已移除旧 `behaviorEvents` 字段；老 JSON 残留字段不会影响当前业务判断。
- 加入/删除方案事件已收紧为只记录实际新增/实际移除的志愿，重复加入、删除不存在志愿不会落行为事件，也不会触发版本递增。
- 本期不记录候选筛选事件，筛选状态仍只作为工作台视图状态和后续对话筛选入口管理。
- 对应单测已覆盖新表读取、新表未命中按未导出、成功动作写入和无效动作不写入。
