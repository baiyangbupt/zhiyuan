---
name: plan-final-review
description: Use when a user asks for a final read-only audit of a volunteer draft before the separate confirmation and CAS execution flow.
version: 1.0.0
---

> 执行口径以 `r1/admission-fact-analysis/references/evidence-policy.md`（跨技能引用，路径以插件根为基准） 为准（提问顺序、冲突处理、单轮问题数等细则在那里）。
> **动手前先读它**——读一次比凭印象写更省事，也避免和规范悄悄分叉。

# Plan Final Review

## 适用条件

- 用户已有方案草案，要求查漏补缺、核验依据和确认前风险提示。
- 当前阶段允许读取方案摘要、候选 Artifact、资格和招生 Evidence。

## 不适用条件

- 没有最新方案草案、Snapshot 或关键 Evidence 时，不做最终结论。
- 用户要求直接提交、应用或修改方案时，第一期保持 read-only，转入显式确认和 CAS。

## 前置状态

- 方案草案、候选集合和 Evidence 属于当前 tenant/session/thread。
- `stateVersion` 与最新 Snapshot 一致；旧 Snapshot 不得覆盖新 Snapshot。
- 已确认用户的硬约束、风险偏好和目标省份/年份。

## 允许能力

- 仅允许目录和招生只读工具进行事实复核。
- Proposal、profile patch、plan apply、Shell、文件写入和任意代码执行均 forbidden。

## 标准步骤

1. 读取最新方案和版本，先检查跨会话、跨线程和引用完整性。
2. 逐项核验资格、招生单元、系统录取率风险标签、数据版本和限制。
3. 检查重复、空位、硬约束冲突、风险集中、梯度与保底覆盖；把 finding 分为阻断/警告/信息。
4. 对不可比历史、缺失数据和未确认偏好明确标注，不替用户隐式取舍。
5. 输出只读审查结果和确认前问题；用户确认后由外部 CAS 流程重新读取权威版本。

## Evidence 要求

<HARD-GATE>
本技能**只审不改**：不生成新草案、不修改方案、不创建 Proposal、**不调用写工具**（含 `plan_apply`）。
用户要求"直接提交 / 应用"时，只输出确认前问题，交外部 CAS 确认流程执行。
同一问题**两轮仍未收敛**即熔断：列出分歧点交回用户裁决，不继续自动调整（修复循环上限）。
</HARD-GATE>

- 每个阻断或关键事实 finding 必须有 Evidence/Artifact 引用。
- Evidence 线程、会话、版本任一不匹配即拒绝使用；不得以 assistant 文本修补数字。

## 单轮调用预算

- 最多 8 次只读调用；相同参数去重，失败最多重试一次。
- 先批量取数再审查，不循环调用未知数量的候选。

## 停止条件

- 发现 stale state、跨线程引用、关键 Evidence 缺失或硬约束冲突时停止并标记阻断。
- 本 Skill 永远不创建 Proposal、不执行写入；最终确认必须离开本 Skill。

## 输出结构

- `responseType=review`，必须有 `artifactRefs` 和 `evidenceRefs`。
- 输出 `blockingFindings`、`warnings`、`verifiedItems`、`limitations`、`confirmationQuestions` 和 `stateVersion`。

## 降级策略

- 数据服务不可用时返回可恢复错误和未完成的审查项，不给“审核通过”。
- 方案版本过期时要求刷新 Snapshot 并重新复核，禁止继续沿用旧结论。
