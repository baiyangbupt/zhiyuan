# Release 3.0.3 Feature Inventory

## 1. 版本定位

`3.0.3` 是 Agent 对话质量、确认协议和方案操作可靠性的集中收口版本。核心目标是把意向更新、硬要求和方案调整统一到确认卡/pending 状态机，减少多路径兼容和模型自由执行带来的错改、误确认和回复质量问题。

## 2. 功能清单

### 2.1 统一确认协议

- 引入统一 `pendingConfirmationCard`。
- 卡片点击是主确认入口，短文本确认只作为 active pending 的兜底。
- 无 active pending 时，“确认/可以/执行”不执行历史动作。
- 新 pending 替代旧 pending，旧卡片置灰。
- `planEditCache` 只作为旧会话兼容，不再作为新链路主状态源。

### 2.2 意向、偏好和约束

- 明确 `preference` 软偏好和 `constraint` 硬要求。
- 负向软偏好和硬排除分开处理，例如“不太想去江苏”和“不去江苏”不等价。
- 正向硬要求细分为普通要求、`only_keep` 和 `must_have`。
- `only_keep` 表示仅保留目标范围，其他方向不要；`must_have` 表示至少保留目标方向但不删其他方向。
- 采纳后影响推荐系数、专家优选推荐、方案解释和后续方案调整参考，不物理缩小基础候选池。
- 对已命中当前方案的冲突项，只做简明影响披露；真正删除或替换仍需要方案调整确认。

### 2.3 方案操作和方案审查

- 覆盖当前方案状态查询、局部命中查询、候选机会查询。
- 覆盖方案审查、风险解释、高收费/中外合作等只读分析。
- 覆盖按学校/专业/专业组命名移动、按展示序号移动排序单元、添加、删除、替换、调稳和排序预览。
- 明确操作才生成预览卡，例如“把太贵的那几个先去掉看看”；只读询问不生成删除/替换卡。
- 移动/排序预览披露当前位置、目标位置、影响对象和确认边界。
- 方案风险回复开始感知候选不足、保区不足或没有可补保底，不再空泛建议补保底。

### 2.4 只读分析、政策和回复质量

- Explore 分析优先让模型综合工具事实，不把工具片段薄直返给用户。
- 地域、专业、职业取舍按语义进入对应只读工具；只有明确要求看当前方案/候选命中时才局部查询。
- 报考政策、资格、流程、学校章程引入官方来源检索工具和官方核验边界。
- 转专业、专项资格、体检限制、口试、学费预算等优先给决策框架，必要时结合官方来源。
- 不恢复按用户话术字符串匹配的快路由，质量优先于延迟。

### 2.5 实体识别和歧义处理

- 专业识别基于官方专业层级，并补充常用简称和别名。
- 大模型抽取后再走本地规范化，避免把具体专业误归为门类或漏掉用户明确对象。
- 地域取舍按接受度、排斥度、就读体验、家庭距离、保底空间等语义判断，不依赖单一词。
- “工商管理”和“工商管理类”等标准专业与招生计划自定义专业类歧义，作为后续继续增强点。

### 2.6 前端和工作区联动

- 消息列表支持 pending confirmation 卡片展示和状态。
- 点击确认后展示处理中状态，旧卡片被替代或失效后不可点击。
- 方案工作区操作后尽量保留当前视图，避免无意切回候选。
- 超时/处理中提示继续作为体验优化项。

## 3. 验证与遗留

已验证：

- Agent 单测、open-quality、dialogue-derived、后端权益 hotfix、Rank 回归和部分 Web 构建/类型检查记录已沉淀。
- `prod-3.0.3` tag 和生产升级资产记录已形成。

主要遗留：

- 模型供应商长尾和部分地域/政策类长耗时仍存在。
- 专业实体歧义、招生计划自定义专业类和方案联动仍需继续完善。
- Web 既有 TypeScript debt 不属于 3.0.3 主改动，但仍需要单独治理。

## 4. 事实来源索引

| 文档 | 用途 |
| --- | --- |
| [release-3.0.3-summary-and-upgrade-plan.md](./release-3.0.3-summary-and-upgrade-plan.md) | 3.0.3 发布收口主入口 |
| [release-3.0.3-production-upgrade-plan.md](./release-3.0.3-production-upgrade-plan.md) | 生产升级和资产记录 |
| [release-3.0.3-agent-intent-plan-mutation-confirmation-design.md](./release-3.0.3-agent-intent-plan-mutation-confirmation-design.md) | 意图、意向和方案更新确认机制 |
| [release-3.0.3-agent-intent-plan-update-interaction-design.md](./release-3.0.3-agent-intent-plan-update-interaction-design.md) | 意向与方案更新交互设计 |
| [release-3.0.3-agent-effect-performance-deep-dive.md](./release-3.0.3-agent-effect-performance-deep-dive.md) | Agent 效果和性能 deep dive |
| [release-3.0.3-agent-case-evaluation-framework.md](./release-3.0.3-agent-case-evaluation-framework.md) | 评估体系 |
| [release-3.0.3-agent-case-evaluation-first-pass.md](./release-3.0.3-agent-case-evaluation-first-pass.md) | 首轮评估记录 |
| [release-3.0.3-agent-response-quality-review.md](./release-3.0.3-agent-response-quality-review.md) | 回复质量人工评审 |
| [plan_action_orchestration_design.md](../zhiyuan-agent/docs/plan_action_orchestration_design.md) | 后续统一方案动作编排设计 |
| [semantic_layer_structure.md](../zhiyuan-agent/docs/semantic_layer_structure.md) | Explore / Intent / Plan 分层 |
