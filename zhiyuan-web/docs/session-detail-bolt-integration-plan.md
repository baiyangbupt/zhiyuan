# Session Detail Bolt Integration Plan

## 1. 目标

本文件用于说明如何将 `bolt_project` 中生成的 `sessionDetail` 工作台设计，逐步整合进当前 `gaokao-volunteer-pc` 的真实前后端框架。

当前结论:

- `bolt_project` 可作为 `sessionDetail V2` 的布局与交互基底
- 不建议整包替换当前页面
- 建议采用 `V2 壳子 + 真实数据 adapter + 渐进替换` 的方式落地

## 2. 当前整合原则

基于最新确认，V2 页面遵循以下约束:

1. 草稿仅作为快捷入口，不做重型独立主视图
2. 暂不接入独立画像区
3. 审查 / 补偿主要由对话触发或系统自动触发
4. 排序后的审查结果只做轻量标签和 tips 展示
5. 保留三种整体视图:
   - 标准视图
   - 纯对话
   - 纯工作台

## 3. 推荐整合后的页面结构

### 3.1 Desktop

- 左栏: 对话区
- 右栏: 工作台
  - 顶部概览区
  - 主体切换:
    - 候选志愿
    - 排序方案
  - 浮动草稿篮

### 3.2 Mobile

- 顶部或底部切换:
  - 对话
  - 工作台

## 3.3 前台标签语义分层

前台候选筛选区不能只把所有标签混成一个统一标签池，而应区分三类语义：

### A. 普通类标签

用于临时查看和本次筛选，不影响方案主状态。

典型示例：

- 北京
- 计算机类
- 师范
- 低学费
- 稳区
- 双一流
- 就业好

交互要求：

- 作为候选面板当前筛选条件使用
- 关闭后即失效
- 不写入画像
- 不更新推荐系数
- 不影响草稿、排序、审查

视觉要求：

- 使用中性标签样式
- 不带“偏好”或“要求”语义前缀

### B. 偏好类标签

表示用户对方案的长期倾向，会影响专家推荐覆盖层，但不直接缩小候选基础池。

典型示例：

- 偏好北京
- 偏好就业导向
- 偏好计算机周边
- 偏好体制内方向

交互要求：

- 可由对话采纳进入
- 也可由前台显式确认进入
- 写入 `profileState`
- 触发推荐系数、专家优选组合、默认推荐顺序刷新

视觉要求：

- 使用固定“偏好态”颜色或底色
- 建议文案上明确体现“偏好”语义

### C. 要求类标签

表示硬限制，会直接影响候选基础池和后续方案。

典型示例：

- 仅限计算机相关
- 不报中外合作
- 不去北京
- 学费不高于 1 万

交互要求：

- 进入前建议二次确认
- 写入 constraint / hard filter
- 触发候选基础池重建
- 连带影响推荐、草稿、排序、审查

视觉要求：

- 使用更强的约束色
- 建议文案上明确体现“要求”或“限制”语义

## 3.4 当前候选筛选字段的语义归类

统一标签治理约定见：

- [tag-governance.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/tag-governance.md)

当前 V2 工作台候选区已具备以下筛选输入：

- `tier`
- `provinceNames` / `negativeProvinceNames`
- `schoolKeywords` / `negativeSchoolKeywords`
- `majorKeywords` / `negativeMajorKeywords`
- `schoolTags` / `negativeSchoolTags`
- `majorTags` / `negativeMajorTags`
- `sortField`
- `sortOrder`

对应文件：

- [WorkspacePanel/index.tsx](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx#L1051)

建议归类如下：

- `tier`
  - 属于普通类筛选
  - 只影响当前候选面板视图
- `provinceNames` / `negativeProvinceNames`
  - 属于地域筛选
  - 当前口径固定为省份名
- `schoolKeywords` / `majorKeywords`
  - 属于名称关键词筛选
- `schoolTags` / `majorTags`
  - 属于标准化枚举筛选
  - 必须与 backend `candidate-pool/filter-options` 对齐
  - 不再使用旧的通用 `tags`
- `sortField`
  - 属于临时查看排序
  - 不写入规划主状态
- `sortOrder`
  - 属于临时查看排序
  - 不写入规划主状态

## 3.5 顶部已生效标签区与候选筛选区分离

推荐在工作台顶部或候选区上方，增加“已生效标签”区域，只展示真正会影响方案的标签：

- 偏好类标签
- 要求类标签

候选面板内部的筛选区则只承接当前查看用条件：

- 普通类标签
- 临时关键词
- 当前排序方式

这样可以让用户明确感知：

- 我现在只是“看看”
- 还是我已经让系统“以后按这个方向推荐”
- 还是我已经给系统加了“必须满足的限制”

## 4. 组件整合映射

### 4.1 壳子与布局

#### `bolt_project`

- [`SessionDetailShell.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/layout/SessionDetailShell.tsx)

#### 当前工程

- [`src/pages/sessionDetail/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetail/index.tsx)

#### 结论

可复用 `SessionDetailShell` 的整体布局思路，但不能直接复制使用。

需要改造点:

- 现有 shell 只有 `对话 + 工作台`，这与当前目标一致
- `viewMode` 可以保留:
  - `standard`
  - `chat-only`
  - `workspace-only`
- 当前 `mobileTab` 也可保留

### 4.2 对话区

#### `bolt_project`

- [`ConversationPanel.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/conversation/ConversationPanel.tsx)
- [`IntentActionCard.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/conversation/IntentActionCard.tsx)

#### 当前工程

- [`src/pageComponents/sessionDetail/MessageList/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/MessageList/index.tsx)

#### 结论

不能直接替换。

原因:

- `ConversationPanel` 当前是 mock 本地消息流
- 没接真实 WebSocket
- 没接心跳
- 没接 `thinking`
- 没接消息分页
- 没接消息反馈接口

#### 推荐做法

- 保留当前 `MessageList` 的真实数据链路
- 只提取或重写渲染层，使其向 `ConversationPanel` 的视觉风格靠拢
- 将 `IntentActionCard` 的视觉与结构接到当前 `CARD` 消息渲染逻辑中

#### 需要映射的真实能力

- 消息分页:
  - `getMessageListApi`
- 反馈:
  - `getFeedbackApi`
- WebSocket:
  - `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`
- agent 推送的 `planningWorkspaceAction`
- 当前 `onWorkspaceIntent` 联动

### 4.3 工作台主面板

#### `bolt_project`

- [`WorkspacePanel.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/workspace/WorkspacePanel.tsx)
- [`WorkspaceStageHeader.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/workspace/WorkspaceStageHeader.tsx)

#### 当前工程

- [`src/pageComponents/sessionDetail/Volunteer/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/Volunteer/index.tsx)

#### 结论

工作台结构可以复用，但状态管理不能复用。

`bolt_project` 当前通过 `localState` 在前端本地改草稿和排序，这是原型方式，不适合真实业务。

#### 推荐做法

- 保留组件拆分思路
- 用当前真实 `planningState` 和 planning API 驱动工作台
- `WorkspacePanel` 不自己“持有真状态”，而是：
  - 接收外层传入的 `planningState`
  - 调用真实接口
  - 更新外层状态

### 4.4 候选视图

#### `bolt_project`

- [`CandidatePoolView.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/workspace/CandidatePoolView.tsx)

#### 当前能力

- `getPlanningStateApi`
- `generatePlanningCandidatePoolApi`
- `queryPlanningCandidatePoolApi`
- `selectPlanningDraftItemsApi`
- `banPlanningDraftItemsApi`

#### 结论

可以较直接接入。

#### 需要改造点

- 现在 `CandidatePoolView` 使用 `candidates` 全量数组直接渲染
- 当前真实系统里更推荐通过:
  - `planningState.candidatePoolState.summary`
  - `queryPlanningCandidatePoolApi(...)`
 进行筛选和分页

#### 推荐映射

- 顶部摘要:
  - 使用 `planningState.candidatePoolState.summary`
- 列表:
  - 使用 `queryPlanningCandidatePoolApi`
- 加入草稿:
  - `selectPlanningDraftItemsApi`
- 禁用:
  - 如果是候选池语义上的“不再推荐”，当前后端更接近 `banDraftItems`
  - 建议第一版先只支持“加入草稿”，禁用按钮可以暂时隐藏或转为本地 UI 待定态

### 4.5 草稿快捷篮

#### `bolt_project`

- [`DraftBasket.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/workspace/DraftBasket.tsx)

#### 当前能力

- `planningState.draftPlanState.items`
- `removePlanningDraftItemsApi`
- `lockPlanningDraftItemsApi`
- `banPlanningDraftItemsApi`

#### 结论

这是当前最适合直接落地的组件之一。

#### 推荐做法

- 保留“浮动草稿篮”的体验
- 作为快捷入口，不单独做独立主视图
- 第一版支持:
  - 查看草稿项
  - 删除草稿项
  - 展示 tier
  - 展示锁定状态
- 第二版可扩展:
  - 在草稿篮中直接锁定 / 解锁
  - 一键生成排序方案

### 4.6 排序视图

#### `bolt_project`

- [`OrderedPlanView.tsx`](/Users/baiyang/git/zhiyuan/bolt_project/src/components/workspace/OrderedPlanView.tsx)

#### 当前能力

- `generatePlanningOrderedPlanApi`
- `movePlanningOrderedItemApi`
- `pinPlanningOrderedItemApi`
- `unpinPlanningOrderedItemApi`
- `runPlanningReviewApi`

#### 结论

可以接，但要做两点改造。

#### 需要改造点

1. 当前排序列表的真实数据不是本地拖拽状态，而是 `planningState.orderedPlanState.items`
2. 审查结果不作为独立主视图，而是在排序头部或顶部摘要中轻量展示

#### 推荐映射

- 排序列表:
  - `planningState.orderedPlanState.items`
- 拖拽后:
  - 调 `movePlanningOrderedItemApi`
- pin/unpin:
  - 调 `pinPlanningOrderedItemApi`
  - 调 `unpinPlanningOrderedItemApi`
- 排序前无数据时:
  - 可从草稿篮触发 `generatePlanningOrderedPlanApi`
- 审查标签:
  - 从 `planningState.reviewState.checks`
  - 只取 `summary + detail/suggestedAction`

## 5. 数据模型映射

建议不要直接使用 `bolt_project/src/types/index.ts` 作为真实页面类型。

推荐新增一层 adapter:

- `SessionDetailRes -> SessionDetailShellViewModel`
- `PlanningStateRes -> WorkspaceViewModel`
- `IMessage -> ConversationMessageViewModel`

## 6. 推荐新增的 V2 目录结构

建议在当前工程中新增，而不是覆盖旧页面:

```text
src/pages/sessionDetailV2/index.tsx
src/pageComponents/sessionDetailV2/
  SessionDetailShell/
  ConversationPanel/
  WorkspacePanel/
  WorkspaceStageHeader/
  CandidatePoolView/
  OrderedPlanView/
  DraftBasket/
src/pageComponents/sessionDetailV2/adapters/
  sessionDetailAdapter.ts
  planningAdapter.ts
  messageAdapter.ts
```

## 7. 第一阶段推荐接入顺序

### Phase 1: 壳子与只读数据

- 搭 `SessionDetailV2` 基础布局
- 接:
  - `getSessionDetailApi`
  - `getPlanningStateApi`
  - `getMessageListApi`
- 工作台先只读展示

### Phase 2: 候选与草稿

- 接:
  - `queryPlanningCandidatePoolApi`
  - `selectPlanningDraftItemsApi`
  - `removePlanningDraftItemsApi`
- 草稿篮开始可交互

### Phase 3: 排序

- 接:
  - `generatePlanningOrderedPlanApi`
  - `movePlanningOrderedItemApi`
  - `pinPlanningOrderedItemApi`
  - `unpinPlanningOrderedItemApi`

### Phase 4: 审查轻展示

- 接:
  - `runPlanningReviewApi`
- 在排序头部展示轻量 tags + tips

### Phase 5: 对话联动

- 将当前 `MessageList` 的真实 WebSocket 和动作卡片，接到 V2 对话区外观中

### Phase 6: 对话优先的方案动作承接

- 不在右侧工作台继续堆叠复杂方案按钮
- 复杂方案动作优先由对话承接：
  - “想看看方案有什么建议”
  - “怎么调方案”
  - “这个方案有没有问题”
  - “需不需要补几个志愿”
- 工作台只承接执行后的结果：
  - 候选 / 草稿 / 排序视图跳转
  - 风险标签与专家优选组合展示
  - 具体志愿聚焦与结果差异感知
- `planEdit / intentDetect / intentConfirmPopup` 语义统一归到“意图识别与推荐层更新”
  - 直接影响推荐系数、专家优选组合、默认推荐顺序
  - 不直接表示当前方案已经被改动
- 真正的方案重排、补志愿、审查执行应由对话明确触发后再进入工作台承接

## 8. 当前已落地状态

截至当前版本，已完成以下最小闭环:

- 新增 [`src/pages/sessionDetailV2/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetailV2/index.tsx)
- 左侧继续复用真实 [`MessageList`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/MessageList/index.tsx) 数据链路
- 右侧新增轻量 [`WorkspacePanel`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx)
- 工作台已接通真实 planning API:
  - 候选池生成 / 查询
  - 草稿增删 / 锁定
  - 排序生成 / 上下移动 / pin / unpin
  - 审查执行
- `sessionDetailV2` 初始态不自动生成草稿或排序底稿。
- 会话初始化时，工作台只自动带上用户已收集的初始意向作为候选默认筛选条件，例如地域、专业、院校倾向。
- 候选区默认按推荐度降序展示；`专家优选组合` 当前只保留为统一标签语义，不再单独做顶部置顶展示。
- 真正的方案生成、重排、补志愿与审查，统一等用户在对话中显式提出后再进入编排链路，并把结果回投到工作台。
- 对话动作卡片已可通过 `onWorkspaceIntent` 驱动 V2 工作台切换与聚焦
- 草稿保持为浮动快捷篮，不引入重型独立草稿页
- 排序区只保留轻量审查标签、tips 和补偿提示，不增加独立审查 / 补偿视图

当前仍未完成的部分:

- 将旧页入口或导航正式切到 `sessionDetailV2`
- 在切页前完成 tag 协议统一，禁止 frontend / agent 再透传旧 `tags/negativeTags`
- 将 `MessageList` 渲染层进一步贴近 bolt 设计稿视觉
- 增加更细的候选分页、空态和错误态打磨
- 完整联调本地前后端链路并做交互回归
- 处理当前工程里的历史 TypeScript 报错后再纳入统一编译门禁

## 9. 暂不纳入 V2 主界面的能力

- 独立画像区
- 动态画像编辑
- 重型审查视图
- 独立补偿主视图
- 候选池禁用的复杂策略
- 对实体卡、百科卡、深层画像编辑的完整迁移

## 10. 最终判断

`bolt_project` 当前最适合作为:

- `sessionDetail V2` 的交互和样式母版

不适合作为:

- 当前 `sessionDetail` 页面直接整体替换物

正确落地方式是:

- 保留当前真实数据链路
- 引入 V2 壳子与工作台样式
- 用 adapter 完成新旧数据模型映射
- 逐步用新组件替换旧页面中最重的工作台部分
