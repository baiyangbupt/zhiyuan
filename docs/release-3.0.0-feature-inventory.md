# Release 3.0.0 Feature Inventory

## 1. 版本定位

`3.0.0` 是 3.x 版本线的初始发布锁定版本，核心价值是把新版志愿规划工作台、候选/方案/审查基础能力和生产发布流程稳定下来。本版本的详细记录较少，现有文档主要是发布锁定 backlog 和外部评审记录。

## 2. 功能清单

### 2.1 工作台和方案基础能力

- 支持候选、方案、审查等规划工作台基础视图。
- 支持专业+大学和院校专业组等基础展示结构。
- 已具备初始方案生成、方案查看和基础审查能力。
- 发布前重点关注空候选、候选偏少、审查结论一致性和专业组断层展示。

### 2.2 风险和审查基础口径

- 已识别 `probability_gap`、`gradientOk`、专业组断层等审查解释问题。
- 明确 `probability_gap` 不是硬约束，不能直接等同于不可填报。
- 需要区分候选不足、方案结构问题和审查提示，不应把所有风险都压成同一种提示。

### 2.3 生产发布和回滚基础

- 发布前需要固定 release commit、前端生产包路径、WebSocket 地址和真实会话迁移抽样。
- 新建会话主链路和老会话迁移抽样是 3.0.0 发布锁定前的关键验证项。

## 3. 验证与遗留

遗留问题主要在 `release-3.0.0-backlog.md` 中记录，包括：

- 空候选初始化失败可见性。
- 候选偏少时的用户解释。
- `probability_gap` 与审查展示口径。
- 专业组断层详情展示。

这些问题在后续 3.0.1、3.0.2、3.1.0 的状态、审查和修复体系中继续演进。

## 4. 事实来源索引

| 文档 | 用途 |
| --- | --- |
| [release-3.0.0-backlog.md](./release-3.0.0-backlog.md) | 发布锁定状态、P0/P1 backlog 和遗留问题 |
| [release-3.0.0-review-claude.md](./release-3.0.0-review-claude.md) | 外部评审记录 |
| [planning_state_overview.md](../zhiyuan-agent/docs/planning_state_overview.md) | 后续规划状态概览 |
| [planning_state_full_design.md](../zhiyuan-agent/docs/planning_state_full_design.md) | 后续规划状态完整设计 |
