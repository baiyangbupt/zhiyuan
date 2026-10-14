---
name: plan-construction
description: Use when a user wants to arrange confirmed candidates into a draft volunteer plan while preserving explicit constraints, evidence, and state versions.
version: 1.0.0
---

> 执行口径以 `r1/admission-fact-analysis/references/evidence-policy.md`（跨技能引用，路径以插件根为基准） 为准（提问顺序、冲突处理、单轮问题数等细则在那里）。
> **动手前先读它**——读一次比凭印象写更省事，也避免和规范悄悄分叉。

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
2. 排序偏好、可接受风险和地域/专业取舍用**封闭式选项**确认（给 2-3 个可判定选项），
   不以开放反问代替推进。
3. 生成只读 plan draft，展示每个位置的招生单元、风险、依据和限制。
4. 做基础完整性检查：重复、空位、资格冲突、梯度断裂和保底覆盖，并将规则 finding 透明展示。
4b. **方向覆盖核对**（弱偏好，不是硬约束）：对画像里每一条已确认发展方向
   （快照 `preferences.careerTypes`，四类中文标签）核对方案里有没有承接——
   每条方向给出**至少一条承接证据**（可指到具体条目的专业/院校与该方向的关系，
   或明确写"本条方向暂无承接"作为缺口列出）。只用业务语言说结论，不甩系数/权重/打分等
   内部数值；方向覆盖不参与排除，只作为补档与排序解释的依据。
5. 收束时**宣布下一步**（如「这版我先按冲稳保排给你看」或「要不要进入终审」），是否调整用封闭式
   问法；不把草案写入权威方案状态。

## Evidence 要求

<HARD-GATE>
本阶段恒为 read-only：用户要求"写 / 改 / 删 / 加进方案 / 提交"时，
**不调用任何 `readOnlyHint: false` 的工具**——点名 `plan_apply`，即使参数齐全、看起来一步就能做完；
也不调用 Proposal 类工具（`plan.propose_*`）。写请求按"需要用户确认"处理：说清要改什么、改了会怎样，
把执行交给用户确认后的链路（本技能不创建 Proposal、不自行 apply）。
同一处调整**两轮内不收敛**就停下，把分歧点交回用户裁决并写进本轮输出（修复循环上限）。
实现与审查分离：本技能**不给自己刚生成的草案做终审**，终审走 `plan-final-review`。
</HARD-GATE>

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
