# Release 3.0.1 Feature Inventory

## 1. 版本定位

`3.0.1` 是 3.x 的稳定性和工作台能力增强版本。重点从 3.0.0 发布后的 backlog 出发，补齐工作台状态、导出、低候选解释、方案排序、Agent 方案动作和生产部署稳定性。

## 2. 功能清单

### 2.1 工作台状态和审查入口

- 候选状态、方案状态和审查状态显式化，避免用户看不到当前是未生成、生成中、已生成、待审查还是已审查。
- 候选为空或候选过少时给出可解释状态，不再只表现为空页面或失败。
- 工作台风险和审查入口进入稳定口径，后续 3.1.0 审查修复体系在此基础上扩展。

### 2.2 导出与展示

- 导出文件志愿序号连续。
- 方案展示补充近三年录取分数/位次等用户可判断信息。
- 用户侧去除“草稿”概念，Agent 和工作台统一表达为“方案/已加入方案”。

### 2.3 会话和入口

- B 端返回会话列表入口。
- 外部初始化会话 API 进入稳定联调口径。
- 生产部署计划中补充高途权限、用户等级和权益同步相关检查。

### 2.4 Agent 方案动作

- Agent 侧方案状态、审查、排序、移动等能力进入真实 WebSocket smoke 验证。
- 新增 `sort_ordered_plan`，支持按录取率、院校层次、推荐系数排序当前方案。
- 高副作用动作开始按 `preview -> confirm -> apply` 方向收口。
- 旧 `pin/unpin/lock` 用户入口退场，前端不可见能力不再通过对话触发。
- 专业组级 `move_ordered_unit / remove_ordered_unit` 动作进入基础编排和测试。

### 2.5 观测和回归

- 新增最小结构化日志：`conversation_turn_event / plan_action_event / intent_state_event`。
- 真实 WebSocket smoke 用例覆盖方案现状、审查、排序和专业组移动。
- Agent 指令和测试开始清理旧 router/workflow 兼容债务。

## 3. 验证与遗留

已验证：

- 生产部署计划、执行记录和 smoke 场景已沉淀。
- Agent 首轮方案动作能力进入真实 WebSocket 验证。

主要遗留：

- 早期 preview -> confirm -> apply 链路仍不稳定，排序和专业组移动曾出现 pending 丢失或循环。
- Pending 状态双系统、内存 preview 缓存、多 worker 兼容和 handler 边界不清，在 3.0.3 统一确认协议中进一步收口。

## 4. 事实来源索引

| 文档 | 用途 |
| --- | --- |
| [release-3.0.1-stability-plan.md](./release-3.0.1-stability-plan.md) | 版本目标、P0/P1 范围和 backlog 迁入 |
| [release-3.0.1-implementation-design.md](./release-3.0.1-implementation-design.md) | 后端、前端和状态实现细节 |
| [release-3.0.1-current-state-and-optimization-roadmap.md](./release-3.0.1-current-state-and-optimization-roadmap.md) | 当时系统状态、问题和优化路线 |
| [release-3.0.1-agent-optimization-design.md](./release-3.0.1-agent-optimization-design.md) | Agent 编排、日志和回归设计 |
| [release-3.0.1-external-session-initialize-api.md](./release-3.0.1-external-session-initialize-api.md) | 外部初始化接口说明 |
| [release-3.0.1-production-deployment-plan.md](./release-3.0.1-production-deployment-plan.md) | 生产部署计划 |
| [production-upgrade-3.0.1-execution-record-2026-05-17.md](./production-upgrade-3.0.1-execution-record-2026-05-17.md) | 生产升级执行记录 |
| [CHANGELOG.md](../zhiyuan-agent/docs/CHANGELOG.md) | Agent 侧 3.0.1 变更流水 |
