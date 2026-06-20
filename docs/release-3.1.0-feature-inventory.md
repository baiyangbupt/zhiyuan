# Release 3.1.0 Feature Inventory

## 1. 版本定位

`3.1.0` 是 `3.0.3` 之后的数据新鲜度、审查修复和 Agent 方案动作编排增强版本。生产标签为 `prod-3.1.0`，核心目标是让工作区数据变化、审查结果、修复建议和对话动作进入统一可验证链路。

## 2. 功能清单

### 2.1 数据新鲜度

- 新增 `DataFreshnessStateDTO` 和 `DataFreshnessScheduleDTO`。
- 工作区可返回最新同步时间、预计下次同步、变化摘要、候选刷新和重新审查标记。
- 新增后台巡检索引表 `assistant_planning_data_freshness_schedule`。
- `VOLUNTEER` 会话支持节流式静默检查，真实变化后标记候选、初始推荐和审查 stale。
- `PREDICT` 会话只展示静态数据说明，不进入后台巡检。
- 后台巡检生产首发默认关闭，稳定后再单独开启。

### 2.2 审查与修复

- 新增后端 `ReviewRuleRegistry`，统一审查规则元数据。
- 新增 `FixProposalStateDTO`、`FixProposalDTO`、dry-run、candidate shortage 和 repair report。
- `fix-proposals/generate` 负责生成可展示、可验证的修复建议。
- `fix-proposals/apply` 是正式高副作用修复入口，应用前校验 proposal 状态、版本、策略和候选可用性。
- 专业组内安全垫、数量缺口、比例失衡、梯度断层、高收费、中外合作、限报等问题进入统一审查/修复表达。
- 旧 `plan-adjustment/apply` 明确退场，旧 compensation 外部入口不再作为发布能力。

### 2.3 Agent 方案动作编排

- Agent 主链收口到 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。
- `PlanActionPlan` 只作为动作 envelope，复合目标、可行性、取舍依据和歧义进入 `composite_proposal`。
- 删除历史 `planning_router_tool` 主路由依赖。
- `only_keep / must_have / exclude` 方案联动迁入 Java `user_goal` proposal/apply 主链路。
- Python Agent 不再自行生成最终 replacement pairs、dry-run 或真实 mutation 方案。
- 对话侧 repair apply 不给模型直接工具权限，只通过 service active pending 桥调用 Java apply。

### 2.4 对话质量和回归体系

- 增加真实生产抽象对话、review repair、constraint plan action、full journey 等回归 case。
- 引入 dialog auto explorer 和生产会话采样工具，用于发现连续对话、pending、空预览和 grounding 问题。
- 强化只读费用/定向审查边界、结构缺口与取舍问题分流、正向约束完整性和审查修复语义路由。
- 保持质量优先：高置信语义快捷入口只承接低副作用、边界清晰的只读或计划动作场景。

### 2.5 Web 工作区

- 工作区顶部弱提示展示数据同步信息，hover 展示预计下次同步和最近变化摘要。
- 候选区按后端状态自动刷新，不额外暴露“检查更新”按钮。
- 方案区和候选区展示推荐系数、录取概率、历年信息等用户可感知字段。
- 审查状态、修复建议和对话 pending confirmation 保持同一高副作用确认边界。

### 2.6 发布和运维

- 新增 release smoke 脚本 `ops/release-smoke.sh`。
- 生产升级要求手工确认 V6 数据库表，生产 Flyway 长期关闭时不能依赖自动 migration。
- Backend、Web、Agent 均需要升级；Rank 本轮不升级。

## 3. 验证与遗留

已验证：

- Agent 全量测试、Server Maven 全量测试、Web build 和 release smoke 已记录。
- 本地标准测试环境完成 Backend、Web、Agent、Rank 和 release smoke 验证。
- `prod-3.1.0` 已上线。

主要遗留：

- 上线后仍有部分典型对话问题进入 3.1.1：压线风险误回确认边界话术、专业组内只保留最稳专业误生成长期意向、full agent 长尾。
- 审查修复文案仍需继续观察内部状态词和用户语言化。
- 约束意向与方案联动仍需持续端到端验收。

## 4. 事实来源索引

| 文档 | 用途 |
| --- | --- |
| [release-3.1.0-summary-and-upgrade-plan.md](./release-3.1.0-summary-and-upgrade-plan.md) | 3.1.0 发布收口主入口 |
| [release-3.1.0-production-upgrade-plan.md](./release-3.1.0-production-upgrade-plan.md) | 生产升级和回滚步骤 |
| [release-3.1.0-data-freshness-and-impact-notification-design.md](./release-3.1.0-data-freshness-and-impact-notification-design.md) | 数据新鲜度和影响通知设计 |
| [release-3.1.0-review-repair-requirements.md](./release-3.1.0-review-repair-requirements.md) | 审查与修复需求和现状 |
| [release-3.1.0-dialog-auto-explorer.md](./release-3.1.0-dialog-auto-explorer.md) | 对话自动探索工具 |
| [release-3.1.0-dialog-auto-explorer-issue-summary-20260614.md](./release-3.1.0-dialog-auto-explorer-issue-summary-20260614.md) | 自动探索问题汇总原始记录 |
| [release-3.1.0-dialog-case-recovery-index-20260614.md](./release-3.1.0-dialog-case-recovery-index-20260614.md) | 关键 case 恢复索引 |
| [release-3.1.0-production-session-sampling.md](./release-3.1.0-production-session-sampling.md) | 生产会话采样工具与记录 |
| [release-3.1.0-production-dialogue-case-export.md](./release-3.1.0-production-dialogue-case-export.md) | 生产对话 case 汇总方案 |
| [release-3.1.0-performance-stress-test-targets.md](./release-3.1.0-performance-stress-test-targets.md) | 压测目标 |
| [plan_action_orchestration_design.md](../zhiyuan-agent/docs/plan_action_orchestration_design.md) | 方案动作统一框架 |
| [review_issue_semantics_design.md](../zhiyuan-agent/docs/review_issue_semantics_design.md) | 审查问题语义框架 |
