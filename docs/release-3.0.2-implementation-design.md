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

## 2. 登录后默认进入会话列表

### 2.1 目标

用户登录后优先看到会话列表，而不是直接进入最近一次会话详情。这样 B 端或服务人员能先确认当前服务对象，再进入具体会话。

### 2.2 当前逻辑

- 普通账号密码/手机号登录：
  - `isCustomer=true` 跳转 `/customer`
  - `isCustomer=false` 跳转 `/session`
- token 静默登录：
  - 同样按 `isCustomer` 跳转。
- `/customer` 页面默认会自动查询最新会话并跳转 `/sessionDetailV2`。
- `/customer?openSessionList=1` 已有逻辑：打开会话列表抽屉，并跳过自动进入最新会话。

### 2.3 实施方案

本次不重写 `/customer` 页面，只复用已有 `openSessionList=1` 入口：

- 登录后如果 `isCustomer=true`，跳转 `/customer?openSessionList=1`。
- 登录后如果 `isCustomer=false`，继续跳转 `/session`。
- `source=minip` 仍由 router 工具自动透传。

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
- 个人信息：`subjectList / subjectScoreList / strengthSubjectList / batch / sex / height / visionAbility / ethnicity / colorSistuation / specialPlan / politicalStatus` 回填到两段个人信息表单。
- 专业意向：`preferredMajors / unacceptableMajors / acceptForeignSchool / tuitionRange` 回填到专业选择、排除专业、是否接受中外合作和学费区间。
- 区域意向：`preferredRegions` 回填到区域选择。
- 志愿策略：`strategyType.code` 回填到策略卡片。

第一阶段仍不缓存“用户正在当前表单中输入但还没有点击确认提交”的字段。也就是说，已确认步骤必须能恢复和回填；当前步骤里未确认的半填写内容暂不保证恢复，后续如继续优化再做字段级 autosave。

补充实现约束：

- 个人信息采集页内部的分数填写和身体情况填写使用各自独立的表单实例与总结锚点，避免一个子表单的确认操作把页面滚动或表单状态带回到另一段。
- 分数计算、位次查询与批次联动只绑定分数子表单；身体情况确认只更新当前子表单的缓存和总结态，不会重新触发分数段的计算逻辑。
- 视力情况、分数列表这类组合字段的必填校验要落在内部真实输入项上，外层容器只负责展示和布局，避免明明填了 4.3 / 4.3 却仍被当成未填。
- 个人信息任一子步骤如果已经从缓存恢复为“已确认”，必须同时恢复总结区和“了解完成，继续下一步”入口；不能出现只展示“确认提交”气泡、但仍要求用户再次提交一次才可继续的中间态。
- 专业意向页中“以下专业类，哪些是明确排斥不想选的？”必须展示后端按选科和批次动态注入的 `bachelorMajors / associateMajors` 冷门/排斥专业类；批次暂时未恢复或动态字段缺失时，不能回退到静态 `options` 里的具体专业列表，避免把“建筑学、计算机科学与技术”等普通专业误展示为排斥专业类。
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
