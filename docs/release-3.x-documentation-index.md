# Release 3.x Documentation Index

本文是 3.x 版本文档的统一入口。原始设计、测试记录、上线执行记录和长篇排查文档保持原样，作为事实来源；每个版本的最终能力范围、修复点和遗留问题以对应 `feature-inventory` 为标准化阅读入口。

## 1. 文档体系

每个版本按以下层次维护：

| 类型 | 作用 | 维护方式 |
| --- | --- | --- |
| `release-x.y.z-feature-inventory.md` | 版本功能清单、关键设计、验证结论、遗留问题、事实来源索引 | 每个版本的标准入口，后续补充优先更新这里 |
| `release-x.y.z-summary-and-upgrade-plan.md` | 发布收口和升级口径 | 有发布收口时保留；不替代功能清单 |
| `release-x.y.z-production-upgrade-plan.md` | 生产部署、回滚、资产和冒烟 | 仅记录可执行上线步骤 |
| `release-x.y.z-implementation/design/requirements.md` | 具体设计和实现细节 | 保留原始设计语境，作为事实来源 |
| `release-x.y.z-*-case/evaluation/report*.md` | 回归、评估、问题复盘、探索记录 | 保留原始记录，不再揉进主文档 |
| 跨版本架构文档 | 规划状态、Agent 编排、审查语义、WebSocket 协议等长期设计 | 从版本清单中索引到对应章节或文件 |

原则：

- 长篇原始记录不删、不强行压缩，避免丢失事实证据。
- 新版本能力变更必须沉淀到对应 `feature-inventory`，不要只留在聊天记录或临时报告里。
- 同一个能力如果跨版本演进，在每个版本的清单里只写该版本新增或完成的部分，完整终态放到跨版本架构文档。
- 上线后发现的问题，先进入下一版本 known issues，再在修复完成后迁入下一版本 feature inventory。

## 2. 版本入口

| 版本 | 标准功能清单 | 发布/状态 |
| --- | --- | --- |
| 3.0.0 | [release-3.0.0-feature-inventory.md](./release-3.0.0-feature-inventory.md) | 初始 3.x 发布锁定和 backlog 收口 |
| 3.0.1 | [release-3.0.1-feature-inventory.md](./release-3.0.1-feature-inventory.md) | 工作台、状态、Agent 方案动作和稳定性增强 |
| 3.0.2 | [release-3.0.2-feature-inventory.md](./release-3.0.2-feature-inventory.md) | 外部初始化、采集缓存、筛选、导出、年份和权益修复 |
| 3.0.3 | [release-3.0.3-feature-inventory.md](./release-3.0.3-feature-inventory.md) | Agent 对话质量、统一确认协议、意向/方案联动 |
| 3.1.0 | [release-3.1.0-feature-inventory.md](./release-3.1.0-feature-inventory.md) | 数据新鲜度、审查修复、Agent 编排与回归体系 |
| 3.1.1 | [release-3.1.1-feature-inventory.md](./release-3.1.1-feature-inventory.md) | 3.1.0 上线后的对话问题收敛版本 |

## 2.1 3.1.1 专项分析

| 文档 | 作用 |
| --- | --- |
| [release-3.1.1-dialogue-known-issues.md](./release-3.1.1-dialogue-known-issues.md) | 3.1.1 当前对话待处理问题 |
| [release-3.1.1-dialogue-benchmark.md](./release-3.1.1-dialogue-benchmark.md) | 3.1.1 对话 benchmark 和 assets 索引 |
| [release-3.2.0-structural-plan-framework-analysis.md](./release-3.2.0-structural-plan-framework-analysis.md) | Plan 结构性框架问题、历史补丁和动态计划落地边界；3.1.1 仅作为后续储备 |
| [release-3.2.0-model-capability-profile-plan.md](./release-3.2.0-model-capability-profile-plan.md) | 3.2.0 前置模型理解/生成能力 profile 计划；离线评估，不进入 3.1.1 runtime shadow |

## 3. 跨版本设计入口

| 领域 | 文档 |
| --- | --- |
| Agent 方案动作编排 | [plan_action_orchestration_design.md](../zhiyuan-agent/docs/plan_action_orchestration_design.md) |
| Explore / Intent / Plan 语义分层 | [semantic_layer_structure.md](../zhiyuan-agent/docs/semantic_layer_structure.md) |
| 规划状态全量设计 | [planning_state_full_design.md](../zhiyuan-agent/docs/planning_state_full_design.md) |
| 规划状态概览 | [planning_state_overview.md](../zhiyuan-agent/docs/planning_state_overview.md) |
| 审查问题语义 | [review_issue_semantics_design.md](../zhiyuan-agent/docs/review_issue_semantics_design.md) |
| Agent 化设计历史 | [planning_agentize_design.md](../zhiyuan-agent/docs/planning_agentize_design.md) |
| WebSocket 协议 | [websocket_protocol.md](../zhiyuan-agent/docs/websocket_protocol.md) |
| Agent 变更流水 | [CHANGELOG.md](../zhiyuan-agent/docs/CHANGELOG.md) |

## 4. 原始记录保留口径

以下类型文档仍保持原样，不要求改造成短清单：

- 自动探索报告和 case recovery index。
- 生产会话采样记录。
- 发布执行记录。
- 早期 deep dive 和评估报告。
- 详细实现设计。

后续维护时，只需要在版本 `feature-inventory` 的“事实来源索引”中补链接和一句话说明。
