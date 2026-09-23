---
name: plan-construction
description: Use when a user wants to arrange confirmed candidates into a draft volunteer plan while preserving explicit constraints, evidence, and state versions.
version: 1.0.0
---

# Plan Construction

## 适用条件

- 已有经过资格和证据校验的候选集合，用户开始讨论顺序、组合和取舍。
- 用户需要查看只读草案或比较不同排列，不是最终确认写入。

## 不适用条件

- 候选集合缺少省份、年份、成绩/位次、选科或硬约束时，先回到 `profile-discovery`/`candidate-recommendation`。
- 用户要求直接保存、应用或最终提交时，第一期禁止在本 Skill 执行 Proposal。

## 前置状态

- 读取最新 Snapshot、候选 Artifact、Evidence Ledger 和 `stateVersion`。
- 确认每个候选有招生单元 ID、资格结果、风险标签和限制。
- 方案构建第一阶段明确为 read-only；任何写意图只记录为用户待确认动作。

## 允许能力

- 仅允许目录和招生只读工具，用于补齐候选事实和资格。
- `profile.propose_patch`、`plan.propose_changes`、`plan.propose_finalize` 及旧链路 apply 均 forbidden。

## 标准步骤

1. 检查候选覆盖、资格、风险和用户硬约束。
2. 让用户确认排序偏好、可接受风险和地域/专业取舍。
3. 生成只读 plan draft，展示每个位置的招生单元、风险、依据和限制。
4. 做基础完整性检查：重复、空位、资格冲突、梯度断裂和保底覆盖，并将规则 finding 透明展示。
5. 询问用户是否需要调整；不把草案写入权威方案状态。

## Evidence 要求

- 每个草案条目引用候选 Artifact 和相关 Evidence；关键数字不得来自 assistant 文本。
- 缺失 Evidence、过期状态或跨会话引用会使草案不可用，必须停止。

## 单轮调用预算

- 最多 6 次只读调用；相同参数去重，禁止逐条无上限查询。
- 方案排列本身在当前上下文完成，不为每个排序变化重复查库。

## 停止条件

- 任一硬约束冲突、资格未知、候选缺证据或 Snapshot stale 时停止。
- 只读草案未获用户确认前，不创建 Proposal、不调用 apply。

## 输出结构

- `responseType=review` 或 `recommendation`，必须有 `artifactRefs`/`evidenceRefs`。
- 输出只读 `planDraft`、风险分布、完整性 findings、待确认问题和当前 `stateVersion`。

## 降级策略

- 缺少候选或数据服务不可用时回到候选澄清，不生成空壳方案。
- 任何写请求统一返回“需要用户确认并由旧 CAS 链路执行”，本 Skill 不越权。
