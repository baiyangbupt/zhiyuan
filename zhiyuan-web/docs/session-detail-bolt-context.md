# Session Detail Bolt Context

## 1. 目标

本文件用于给 `bolt.new` 或类似 AI 前端生成工具提供 `sessionDetail` 页面重构的最小上下文。

目标不是让工具直接接管整个工程，而是让它基于当前业务语义和页面结构，生成一版更合理的页面信息架构、布局和交互壳子，后续再由本地工程接入真实接口和 WebSocket。

## 2. 当前工程信息

- 工程路径: `gaokao-volunteer-pc`
- 技术栈:
  - `Next.js 13`
  - `React 18`
  - `TypeScript`
  - `Ant Design 5`
  - `CSS Modules + SCSS`
- 当前页面入口:
  - [`src/pages/sessionDetail/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetail/index.tsx)
- 当前页面主样式:
  - [`src/pages/sessionDetail/style.module.scss`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetail/style.module.scss)

## 3. 页面业务定位

这是一个高考志愿填报助手的会话详情页，不是通用 IM 页面。

页面核心职责有三件事:

1. 用户通过对话表达诉求
2. 系统将诉求映射到志愿规划工作区
3. 用户在志愿工作区中查看、选择、排序、审查方案，并结合画像持续调整

补充要求：

- 前台对候选标签和筛选条件需要区分语义层级
- 不能把所有标签都当成同一种“筛选条件”
- 页面应让用户明确感知“临时查看”“偏好”“要求”三者的区别
- 初始进入 `sessionDetailV2` 时，不自动改动草稿或排序结果
- 仅将用户初始已知意向自动映射为候选区默认筛选条件
- 方案生成、重排、补志愿、审查等动作都应由对话显式触发

页面中至少包含三类核心信息:

1. 对话区
2. 志愿工作区

## 4. 当前页面结构

### 4.1 入口页结构

当前入口页 [`src/pages/sessionDetail/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetail/index.tsx) 主要由以下区域组成:

- `Header`
- `MessageList`
- `Volunteer`
- `UserProfile`

当前有两套视图模式:

- `standard`
  - 左侧 `MessageList`
  - 右侧 Tab 切换 `Volunteer` / `UserProfile`
- `immersive`
  - 在移动端或沉浸模式下切换 `chat` / `plan`
  - 使用 `Drawer` 承载部分内容

状态较多，集中在页面入口:

- `chatSessionId`
- `userId`
- `sessionStatus`
- `entityCardList`
- `fetchFlag`
- `tabIndex`
- `workspaceIntent`
- 各种 Drawer 显隐
- 权益状态 `doChatRights`

### 4.2 关键组件职责

#### MessageList

文件:
- [`src/pageComponents/sessionDetail/MessageList/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/MessageList/index.tsx)

职责:

- 拉取历史消息列表
- 建立 WebSocket 连接
- 发送用户消息
- 展示 agent `thinking` 过程
- 处理反馈、实体点击、临时卡片
- 通过 `onWorkspaceIntent` 将意图传给志愿工作区

当前使用的 WebSocket 路径:

- `${NEXT_PUBLIC_AGENT_WS_BASE}/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`

消息区当前包含:

- 历史消息加载
- 心跳保活
- 回答超时
- markdown 渲染
- 关键词识别
- 快捷操作按钮
- `intentDetectPopup` / `intentConfirmPopup` / `planningWorkspaceAction` 类卡片联动

#### Volunteer

文件:
- [`src/pageComponents/sessionDetail/Volunteer/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/Volunteer/index.tsx)

职责:

- 展示推荐志愿列表
- 展示 planning state
- 候选池查询
- 草稿选择 / 删除 / 锁定 / 禁用
- 排序结果生成 / 移动 / pin / unpin
- 审查结果展示
- 补偿建议执行
- 志愿导出 

当前一个组件同时承担了:

- 推荐志愿展示
- planning 工作台
- 筛选、分页、操作弹窗
- 审查与补偿

组件职责偏重。

#### UserProfile(新版可以仅保留基础信息和分数位次其他的去掉）

文件:
- [`src/pageComponents/sessionDetail/UserProfile/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/UserProfile/index.tsx)

职责:

- 拉取静态画像
- 拉取动态画像
- 编辑动态画像意向情绪
- 保存正负向意向

当前承载内容:

- 基础信息
- 分数与位次
- 动态画像分组
- 情绪强弱编辑

## 5. 当前主要问题

### 5.1 布局层面

- 页面采用简单的左右分栏，但实际信息密度远超普通聊天页
- 遗留了一些冲稳保完整列表的内容，这部分在新版本中是要改造去掉的
- 希望工作区作为后续的核心面板，与对话共同辅助用户构建最终的志愿方案
- 希望工作区首先呈现概览部分（类似现在展示了候选多少个志愿，排序多少个，风险情况如何）
- 希望工作区常驻主体包含用于筛选和选择志愿的选择态，点击可弹开的草稿区，查看、删除、禁用、锁定其中的志愿，以及同时能够上下移动（含锁定）的排序态

### 5.2 交互层面

- 对话中的诉求表达，与右侧工作区动作之间的映射感知弱
- 用户看不清“系统建议了什么”“我已经选了什么”“还差什么”
- 候选池、草稿、排序、审查、补偿虽然已经有状态，但页面缺少阶段化表达
- 用户对当前所在步骤认知弱，不知道下一步该做什么
- 希望工作区的设计包含了选取和排序两种核心功能，选择和排序的穿插使用挑选和形成最终方案
- 希望在选择后即类似加购物车一样的体验，进入草稿区，同时一键可切换到排序态、或者排序态切换到选择态
- 希望自动审查和自动补偿（补全/剔除/置换）能力均是系统提供的智能辅助,用户可以通过对话或者系统自动触发
- 希望系统自动完成的工作要尽可能引入用户交互，让用户确认或者不同颜色背景来进行对比展示
- 希望保留能够切换到纯对话和纯工作界面的视图切换能力


### 5.3 组件职责层面

- `Volunteer` 组件过重，既做展示又做工作台又做弹窗操作
- `MessageList` 兼有消息、WebSocket、思考态、动作卡片、多种联动逻辑
- 页面入口聚合状态太多，导致后续扩展困难

### 5.4 用户感知层面

- 当前页面仍更像“聊天 + 右侧结果面板”
- 但真实业务需要“对话驱动的规划工作台”
- 用户对“可手动干预”和“系统自动补偿”的边界认知不够清晰

## 6. 页面重构目标

重构后希望强化的方向:

1. 让页面更像“志愿规划工作台”，不是普通聊天页
2. 明确分成:
   - 对话区
   - 规划工作区
3. 强化流程感:
   - 候选池
   - 草稿
   - 排序方案
   - 审查 / 补偿
4. 强化“系统自动推荐 + 用户手动干预”的协同感
5. 保留业务术语，不要抽象成通用任务管理器
6. 界面美观大方，专业简洁

## 7. 必须保留的业务语义

页面重构时必须保留以下概念:

- 冲 / 稳 / 保
- 候选池
- 草稿
- 排序方案
- 审查
- 补偿

不能被替换成过于抽象的通用词，比如:

- 不要把 `候选池` 直接改成 `list`
- 不要把 `草稿方案` 直接改成 `cart`
- 不要把 `审查` 直接改成模糊的 `validation summary`

## 8. 页面建议信息架构

建议让工具优先尝试以下结构:

### 8.1 Desktop

- 左栏: 对话区
  - 会话消息
  - thinking 状态
  - 快捷操作
  - 动作确认卡片
- 中栏: 规划工作区
  - 顶部显示当前阶段和统计摘要
  - 主体显示:
    - 选择
    - 草稿
    - 排序方案
    - 审查结果
- 右栏: 用户画像与约束摘要
  - 基础信息
  - 分数 / 位次
  - 优势学科

### 8.2 Mobile / 小屏

- 单栏布局
- 以顶部 segmented control 或底部浮层切换:
  - 对话
  - 工作区
  - 画像

## 9. 建议组件拆分

建议工具输出时，将页面拆成以下层次:

- `SessionDetailShell`
- `ConversationPanel`
- `WorkspacePanel`
- `ProfileSummaryPanel`
- `WorkspaceStageHeader`
- `CandidatePoolView`
- `DraftPlanView`
- `OrderedPlanView`
- `ReviewCompensationView`
- `IntentActionCard`
- `ThinkingTimeline`
- `ProfileConstraintCard`

不要继续维持单个超大 `Volunteer` 组件。

## 10. 当前接口与数据上下文

### 10.1 会话和消息

文件:
- [`src/service/apis/sessionDetail.ts`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/service/apis/sessionDetail.ts)
- [`src/interface/api/sessionDetail.ts`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/interface/api/sessionDetail.ts)

关键接口:

- `getSessionDetailApi`
- `getMessageListApi`
- WebSocket:
  - `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`

关键消息结构:

```ts
interface IMessage {
  id: number;
  chatSessionId?: number;
  messageFrom: string;
  feedback?: number;
  messageFromUserName?: string;
  contentType?: 'TEXT' | 'CARD';
  content: string;
  displayTime?: string;
  nerList: NerItem[];
  contentSegments?: TextSegment[];
}
```

### 10.2 Planning 工作台

文件:
- [`src/interface/api/volunteer.ts`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/interface/api/volunteer.ts)

关键结构:

```ts
interface PlanningStateRes {
  sessionId?: number;
  version?: number;
  phase?: string;
  staleFlags?: {
    candidatePool?: boolean;
    orderedPlan?: boolean;
    review?: boolean;
  };
  candidatePoolState?: { ... };
  draftPlanState?: { ... };
  orderedPlanState?: { ... };
  reviewState?: { ... };
  pendingActions?: PlanningPendingAction[];
}
```

当前 planning 工作区的关键视图:

- `draft`
- `ordered`
- `review`

工作区还需要承接对话侧发来的 `workspaceIntent`:

```ts
interface PlanningWorkspaceIntent {
  nonce: number;
  targetTab?: 'volunteer';
  targetView?: 'draft' | 'ordered' | 'review';
  volunteerIds?: string[];
  refresh?: boolean;
}
```

### 10.3 用户画像

关键数据来源:

- `getSessionUserInfoApi`
- `getSessionUserDynasticInfoApi`
- `saveUserIntentEmotionApi`

动态画像结构:

```ts
interface ProfileKVDto {
  name: string;
  pDetails: UserIntentValueDetail[];
  nDetails: UserIntentValueDetail[];
}
```

## 11. 视觉和交互约束

### 11.1 应保留

- 品牌主色可继续沿用偏红橙方向
- Ant Design 作为基础控件库
- 中文业务语义
- 数据密度较高的专业工作台属性

### 11.2 应避免

- 做成泛化 AI 聊天室
- 过度依赖默认 Antd Table 页面气质
- 只做换皮，不重构信息组织

## 12. 推荐生成方式

先让工具生成:

1. 页面信息架构
2. 组件树
3. 关键状态流
4. 一版静态 mock 页面

第一轮不要接真实接口，不要写复杂业务逻辑，只用 mock 数据模拟:

- 会话消息
- planning state
- 审查结果

## 13. 可直接投喂 bolt.new 的 Prompt

```text
我正在重构一个高考志愿填报系统的 PC 端会话详情页。

技术栈:
- Next.js 13
- React 18
- TypeScript
- Ant Design 5
- SCSS Modules

页面不是普通聊天页，而是“对话驱动的志愿规划工作台”。

页面核心包含三块:
1. 左侧对话区
2. 规划工作区

业务语义必须保留:
- 冲 / 稳 / 保
- 候选池
- 草稿方案
- 排序方案
- 审查
- 补偿

当前问题:
1. 布局拥挤，对话区和工作区主次不清
2. 对话诉求与右侧动作联动弱
3. 页面仍像“聊天 + 结果面板”，而不是“规划工作台”

重构目标:
1. 强化“系统自动推荐 + 用户手动干预”的协同感
2. 用更清晰的信息架构展示规划流程
3. 中间工作区明确分成:
   - 候选池
   - 草稿
   - 排序方案
   - 审查
4. 右侧持续展示用户画像、约束、意向和风险偏好
5. 桌面端采用三栏工作台布局，小屏保留单栏切换能力

请输出:
1. 页面信息架构
2. 组件拆分方案
3. 桌面端和移动端布局方案
4. 关键交互流程说明
5. 一版 React + TypeScript + Ant Design + SCSS Modules 的静态页面代码
6. 使用 mock 数据，不接真实接口

请注意:
- 不要做成通用 AI 聊天产品
- 不要只做换皮
- 要保留高考志愿填报场景的专业感和决策感
- 页面要更像“规划工作台”
```

## 14. 建议一起提供给工具的文件

如果后续需要继续补充上下文，优先补这些文件:

- [`src/pages/sessionDetail/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetail/index.tsx)
- [`src/pages/sessionDetail/style.module.scss`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pages/sessionDetail/style.module.scss)
- [`src/pageComponents/sessionDetail/MessageList/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/MessageList/index.tsx)
- [`src/pageComponents/sessionDetail/Volunteer/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/Volunteer/index.tsx)
- [`src/pageComponents/sessionDetail/UserProfile/index.tsx`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/UserProfile/index.tsx)
- [`src/interface/api/sessionDetail.ts`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/interface/api/sessionDetail.ts)
- [`src/interface/api/volunteer.ts`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/interface/api/volunteer.ts)
- [`src/service/apis/sessionDetail.ts`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/service/apis/sessionDetail.ts)
