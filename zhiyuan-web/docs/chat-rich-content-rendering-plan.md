# 对话富内容输出与展示美化方案

## 1. 背景

当前对话区内容主要由 agent 输出 markdown 文本，前端在 [MessageList](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/MessageList/index.tsx) 中通过 `marked.parse()` 直接转成 HTML 后渲染。

这种方式接入成本低，但在当前高考志愿场景下存在明显问题：

- markdown 表格在窄栏聊天区容易错位、挤压、横向溢出
- bullet point、引用块、标题、段落间距依赖浏览器默认样式，观感不稳定
- agent 输出一旦复杂，前端无法区分“普通说明”“风险提醒”“对比信息”“待确认动作”
- 富内容能力全部压在 markdown 语法上，缺少受控的展示协议

因此需要从“自由 markdown + 兜底 CSS”升级为“受控输出协议 + 统一富文本渲染层”。

## 2. 目标

目标不是单独修表格样式，而是建立一套稳定、可扩展、可验证的对话展示体系：

- 在当前聊天区宽度下，普通说明、列表、提醒、对比内容都能稳定展示
- 限制 agent 的自由排版，减少输出格式漂移
- 将高价值内容类型逐步从 markdown 升级为结构化卡片
- 让前端拥有统一的 typography、列表、表格、卡片、提醒组件
- 支撑后续 planning / 审查 / 补偿 / 方案对比等复杂内容展示

## 3. 设计原则

- 内容与样式解耦：agent 负责表达语义，前端负责稳定渲染
- 先止血后演进：先通过受控 markdown 和基础样式解决当前问题，再逐步引入结构化协议
- 窄栏优先：聊天区默认按移动端和中窄栏体验设计，不假设有大屏表格空间
- 语义优先：风险、建议、结论、动作不再只靠文本措辞区分
- 渐进兼容：保留现有 markdown 消息渲染能力，新增结构化消息协议并逐步迁移

## 4. 当前问题拆解

### 4.1 markdown 原始 HTML 渲染不可控

目前前端直接使用 `dangerouslySetInnerHTML` 渲染 markdown 解析结果，导致：

- `ul/ol/li` 缩进、符号、行距不统一
- `table/th/td` 没有固定的布局与滚动容器
- `blockquote/code/pre` 没有统一视觉规则
- 不同内容类型全部混在一个 `.markdownBody` 下，无法按语义定制表现

### 4.2 agent 输出格式漂移

当前 agent 可以自由输出：

- 段落
- 项目符号
- 表格
- 伪表格
- 标题
- 多层缩进列表

这导致前端很难稳定处理，尤其是：

- 列多于 3 的 markdown 表格
- 单元格里有换行、括号说明、长专业名
- 多级 bullet list
- “结论 + 比较 + 提醒 + 下一步动作”混在一条消息中

### 4.3 志愿场景本身更适合结构化内容

高考志愿咨询中，以下内容本质上更适合结构化渲染，而不是 markdown：

- 学校 / 专业 / 地域对比
- 风险审查结论
- 方案调整前后影响
- 建议补充或删除的志愿
- 需要用户确认的下一步动作

## 5. 总体方案

总体采用“两层协议、三段落地”的设计：

### 5.1 两层协议

- 第一层：受控 markdown
  - 用于普通说明、简单列表、短结论
- 第二层：结构化富内容协议
  - 用于对比、风险、总结、确认动作、规划联动卡片

### 5.2 三段落地

- 阶段 A：补齐 markdown typography 和表格样式，先解决当前错位和缩进问题
- 阶段 B：将 markdown 渲染改为“parse -> token/AST -> React 组件”，不再直接注入原始 HTML
- 阶段 C：让高价值内容走结构化卡片协议，不再依赖 markdown 自由表达

## 6. 输出内容分层

建议将聊天输出分为以下六类：

### 6.1 普通说明 `plain_text`

适用场景：

- 回答专业介绍
- 回答志愿规则解释
- 回答简单建议

推荐形式：

- 短段落
- 简单无序列表
- 不超过二级缩进

### 6.2 结论摘要 `summary_box`

适用场景：

- 先给用户一眼看懂的结论
- 给出“更推荐哪个方向”的归纳

前端建议渲染为：

- 轻量高亮卡片
- 标题 + 1 到 3 行摘要

### 6.3 风险提醒 `risk_notice`

适用场景：

- 保底不足
- 梯度断层
- 数量不足
- 限报或高收费提醒

前端建议渲染为：

- 风险色 notice
- 支持 hover / 展开看详细说明

### 6.4 对比内容 `comparison_card`

适用场景：

- 北京 vs 天津
- 法学 vs 汉语言
- 当前方案 vs 加入新诉求后的变化

不建议继续使用 markdown table 作为主要承载。

建议渲染为：

- 标题
- 若干对比维度行
- 底部结论摘要

### 6.5 动作建议 `action_prompt`

适用场景：

- 是否补充更稳的保底
- 是否按“体制内倾向”重筛候选
- 是否把指定志愿加入草稿

前端建议渲染为：

- 标题
- 影响说明
- CTA 按钮

### 6.6 工作台联动 `planning_workspace_action`

适用场景：

- 需要联动右侧候选池 / 草稿 / 排序区

这类已经有初步实现，应继续沿结构化协议演进，不再退回 markdown 表达。

## 7. agent 输出规范

## 7.1 默认规范

agent 默认不输出复杂 markdown 表格。

优先级建议：

1. 先给结论
2. 再给 2 到 5 条分点说明
3. 最后给下一步建议或确认动作

### 7.2 列表规范

- 默认只允许一级列表
- 二级列表仅在步骤说明中允许使用
- 不建议三级及以上缩进
- 每个 bullet 尽量控制在 1 到 2 行

### 7.3 表格规范

仅在以下条件同时满足时允许 markdown table：

- 列数不超过 3
- 每个单元格内容较短
- 不包含长括号说明
- 不包含多行内容

否则统一转成：

- 分点对比
- 或结构化 `comparison_card`

### 7.4 高价值场景强制结构化

以下场景建议直接要求 agent 返回结构化内容：

- 对比
- 风险提醒
- 结论摘要
- 下一步动作确认
- 方案调整影响说明

## 8. 结构化富内容协议建议

建议在消息 `contentType=CARD` 之外逐步扩展更稳定的内容协议。

### 8.1 示例：摘要卡片

```json
{
  "type": "summary_box",
  "title": "结论",
  "summary": "如果你优先体制内就业，当前候选里师范、法学、汉语言方向更值得优先看。"
}
```

### 8.2 示例：风险提醒

```json
{
  "type": "risk_notice",
  "level": "warn",
  "title": "保底仍偏少",
  "summary": "当前排序里本省保底志愿不足。",
  "detail": "建议优先补 1 到 2 个本省录取概率更高的志愿。"
}
```

### 8.3 示例：对比卡片

```json
{
  "type": "comparison_card",
  "title": "北京与天津方案差异",
  "dimensions": [
    {
      "label": "城市资源",
      "left": "北京更强",
      "right": "天津相对均衡"
    },
    {
      "label": "录取风险",
      "left": "更高",
      "right": "更低"
    }
  ],
  "summary": "如果你更重视平台和资源，可以继续看北京；如果更重视稳妥性，天津更合适。"
}
```

### 8.4 示例：动作卡片

```json
{
  "type": "action_prompt",
  "title": "补一些更稳的体制内方向志愿",
  "impact": "会优先在当前候选、草稿、排序中查找，如不足再从候选池补充。",
  "actionText": "查看候选",
  "targetView": "candidate",
  "refresh": true
}
```

## 9. 前端渲染层设计

## 9.1 短期：统一 markdown typography

在 `.markdownBody` 层统一补以下能力：

- 段落间距
- 标题字号和字重
- `ul/ol/li` 的缩进、marker 样式、行高
- `blockquote` 的左边线与背景
- `pre/code` 的背景与横向滚动
- `table` 的横向滚动和单元格样式

建议规则：

- 列表间距不要使用浏览器默认值
- 表格统一包裹横向滚动
- `td/th` 允许换行但不允许撑爆容器
- 长单词、专业代码、URL 允许断行

### 9.1.1 表格兜底样式建议

```scss
:global(.markdownBody) {
  line-height: 1.75;
  color: #1f2430;
  overflow-wrap: anywhere;
  word-break: break-word;

  p {
    margin: 0 0 10px;
  }

  ul,
  ol {
    margin: 8px 0 10px 20px;
    padding: 0;
  }

  li {
    margin: 4px 0;
  }

  table {
    display: block;
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
    border-collapse: collapse;
  }

  th,
  td {
    min-width: 88px;
    padding: 8px 10px;
    border: 1px solid #e8e8e8;
    vertical-align: top;
    white-space: normal;
  }
}
```

## 9.2 中期：AST -> React 组件渲染

不再直接使用 `dangerouslySetInnerHTML` 作为主要方案，而是：

- markdown -> token / AST
- token -> React 组件

例如：

- `paragraph` -> `RichParagraph`
- `list` -> `RichList`
- `blockquote` -> `RichQuote`
- `table` -> `RichTable`
- `heading` -> `RichHeading`

好处：

- 样式稳定
- 可以在组件层做额外规则
- 可以识别特殊 block 并替换为更适合的 UI
- 后续和结构化消息卡片体系更容易统一

## 9.3 长期：统一富内容组件库

建议抽出一套聊天富内容组件：

- `RichParagraph`
- `RichList`
- `RichHeading`
- `RichQuote`
- `RichCodeBlock`
- `RichTable`
- `SummaryBox`
- `RiskNotice`
- `ComparisonCard`
- `ActionPrompt`

形成统一 design token：

- 字号
- 行高
- 段落间距
- 标题层级
- 列表缩进
- 卡片圆角
- 颜色与边框语义

## 10. 适配高考志愿场景的推荐策略

### 10.1 继续使用 markdown 的内容

- 专业介绍
- 地域说明
- 规则解释
- 简单建议

### 10.2 优先升级为结构化卡片的内容

- 专业 / 城市 / 院校对比
- 审查结论
- 补偿建议
- 方案前后影响
- 工作台跳转与确认动作

### 10.3 不建议再使用 markdown table 的内容

- 专业名称很长的多列比较
- 包含“风险、理由、建议、影响”的混合对比
- 包含大量括号说明、学费、学制、选科要求的表格

## 11. 分阶段落地计划

### 阶段 1：样式止血

目标：

- 解决当前 bullet 缩进、段落、表格错位问题

改动：

- 为 `.markdownBody` 增加统一 typography 样式
- 为 `table` 增加横向滚动和单元格样式
- 为 `blockquote/pre/code` 增加基础样式

验证：

- 普通段落
- 一级 / 二级列表
- 2 列、3 列 markdown 表格
- 长专业名和长链接断行

### 阶段 2：输出规范收口

目标：

- 让 agent 默认减少复杂 markdown 输出

改动：

- 在 agent 提示词或 skill 中新增输出规范
- 对比类默认输出分点或结构化卡片

验证：

- 对比问题不再默认返回 markdown 表格
- 风险提醒不再用长段落堆叠

### 阶段 3：结构化富内容协议

目标：

- 将高价值内容稳定化

改动：

- 扩展 CARD 协议
- 新增 `summary_box`、`risk_notice`、`comparison_card`、`action_prompt`

验证：

- 前端正确渲染结构化卡片
- 与工作台联动动作兼容

### 阶段 4：markdown AST 渲染替换

目标：

- 摆脱原始 HTML 注入的主要依赖

改动：

- `marked` 仅做解析
- 前端自定义 token -> React 渲染器

验证：

- 与现有普通消息兼容
- 视觉一致性提升
- 安全性和可控性增强

## 12. 验证与测试建议

### 12.1 样例集

建议建立一组固定消息样例：

- 普通说明
- 一级列表
- 二级列表
- 对比内容
- 风险提醒
- 结构化卡片
- markdown 表格
- 超长专业名

### 12.2 前端验证点

- 窄栏下无横向抖动
- 列表缩进一致
- 表格横向滚动正常
- 风险 / 总结 / 动作的视觉层次清晰
- 长文本不撑破消息卡片

### 12.3 agent 验证点

- 常规说明输出不滥用表格
- 对比问题优先输出摘要 + 分点
- 结构化消息字段稳定

## 13. 建议的近期执行顺序

建议按以下顺序推进：

1. 先补 `MessageList` 的 markdown typography 和 table 样式
2. 补一份 agent 输出规范文档，限制 markdown table 的使用
3. 先把“对比、风险、动作”三类内容升级成结构化卡片
4. 再考虑 markdown AST 渲染替换

这样可以在不大动现有链路的前提下，快速改善观感，并为后续规划链路的复杂交互留出稳定承载方式。
