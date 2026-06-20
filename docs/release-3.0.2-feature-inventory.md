# Release 3.0.2 Feature Inventory

## 1. 版本定位

`3.0.2` 是面向使用体验、外部初始化稳定性、采集流程、筛选和导出的修复版本，同时包含智能填报权益热修和高考年份/历年数据展示口径修复。

## 2. 功能清单

### 2.1 外部初始化和会话入口

- 外部初始化会话支持展示学员姓名。
- 新增版本化稳定路径 `integration/v1/session/initialize`，旧路径继续兼容。
- 外部初始化缺失 `sex`、`strategyType` 时按前端采集流默认值归一化。
- `strategy_type` snake_case 入参兼容。
- 登录后默认进入会话列表，采集页创建成功后也回到会话列表，减少误进旧会话。

### 2.2 前置信息采集缓存

- 创建会话前的高考信息、个人信息、专业意向、区域意向、志愿策略按步骤缓存。
- 页面刷新或短时间离开后恢复到上次未完成步骤。
- 创建会话成功后清理缓存。
- 第一阶段只缓存已确认步骤，不缓存当前表单未确认的半填写字段。

### 2.3 候选筛选和展示

- 候选筛选已选条件支持快捷移除。
- 院校名称和三级专业筛选能力增强。
- 候选空态和候选偏少口径进一步明确。
- 专业组内专业顺序按录取率等业务规则修正。

### 2.4 导出和数据年份

- 专业+大学模式导出按每条“学校 + 专业”志愿独立一行，不再呈现专业组式嵌套结构。
- 高考年份、招生计划年份和历年分数信息展示口径梳理。
- 外部初始化会话要求调用方传入正确 `examYear`，页面不再硬编码 2025 招生计划。

### 2.5 权益和报考模式

- 热修 `VOLUNTEER` 智能填报每日权益限制。
- `SUPER_VIP` 不受每日次数限制，非 `SUPER_VIP` 创建智能填报会话每天最多 2 次。
- 不采用全局 `SUPER_VIP-only` 开关。
- `prepareType` 缺失时按智能填报口径补齐，防止绕过日限。

### 2.6 Agent 回归和准生产场景

- 新增 `302` 真实 WebSocket 对话场景，覆盖方案查询、排序、专业组移动、按学校/专业简称删除和调整后查询。
- 只读 Explore/Intent smoke 覆盖方向承接、压线风险和专项资格解释。

## 3. 验证与遗留

已验证：

- 3.0.2 验收清单覆盖登录、采集缓存、外部初始化、筛选、空态、专业组顺序和导出。
- 生产升级计划记录构建、部署和回滚口径。

主要遗留：

- Agent 对话质量和确认协议仍需继续增强，进入 3.0.3 主线。
- 专业/院校简称解析虽有受控能力，但仍需要更完整实体规范化和歧义处理。

## 4. 事实来源索引

| 文档 | 用途 |
| --- | --- |
| [release-3.0.2-stability-plan.md](./release-3.0.2-stability-plan.md) | 版本目标和新增反馈范围 |
| [release-3.0.2-implementation-design.md](./release-3.0.2-implementation-design.md) | 外部初始化、登录、采集缓存等实现设计 |
| [release-3.0.2-acceptance-checklist.md](./release-3.0.2-acceptance-checklist.md) | 验收清单 |
| [release-3.0.2-production-upgrade-plan.md](./release-3.0.2-production-upgrade-plan.md) | 生产升级计划 |
| [release-3.0.2-routing-preview-action-review.md](./release-3.0.2-routing-preview-action-review.md) | 当时路由、预览、动作和审查链路梳理 |
| [release-3.0.2-hotfix-volunteer-rights-mode.md](./release-3.0.2-hotfix-volunteer-rights-mode.md) | 智能填报权益热修 |
| [3.0.2-examYear-info--plan-update.md](./3.0.2-examYear-info--plan-update.md) | 高考年份与历年分数信息调整 |
| [CHANGELOG.md](../zhiyuan-agent/docs/CHANGELOG.md) | Agent 侧 3.0.2 回归和变更流水 |
