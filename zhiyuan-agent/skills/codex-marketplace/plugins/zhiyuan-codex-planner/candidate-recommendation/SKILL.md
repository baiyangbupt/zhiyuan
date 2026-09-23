---
name: candidate-recommendation
description: Use when a user has enough confirmed score context and constraints to request ranked volunteer candidates with evidence-backed risk and preference explanations.
version: 1.0.0
---

# Candidate Recommendation

## 适用条件

- 用户明确要求候选、排序或“冲稳保”建议。
- Snapshot 已确认省份、考试年份、成绩或位次、选科/批次以及硬约束。

## 不适用条件

- 缺少省份、年份、位次/成绩、选科或批次时，不输出候选，必须 clarification。
- 存在硬约束冲突、实体歧义、资格未知或数据不可比时，不输出候选。
- 用户要求直接写入方案时，先输出只读候选并转入 Proposal/CAS，不自行 apply。

## 前置状态

- 已取得当前 Snapshot 和最新 `stateVersion`。
- 目标院校/专业/招生单元已由 `entity.resolve` 解析为标准 ID。
- 读取用户确认的偏好与排除项；tentative 偏好只能影响解释，不能当硬约束。
- Required gate fields are `province`, `year`, `score` or `rank`, subject mode/batch, and confirmed hard constraints.

## 允许能力

- `entity.resolve`、目录只读工具和全部 `admission.*` 只读工具。
- 不调用写工具、不创建 Proposal、不凭模型记忆生成招生数字。

## 标准步骤

1. 先执行输入门槛检查：省份、年份、成绩/位次、选科/批次、硬约束和目标范围。
2. 解析实体并检查资格；任何硬约束冲突都列入排除原因。
3. 获取招生单元层面的系统录取率、历史可比性和 Evidence。
4. 分开呈现 Eligibility、Admission Probability、Preference Fit、Data Confidence 四个维度。
5. 依据系统录取率标记风险：`<50%` 为“冲”，`50%~70%` 为“稳”，`70%~99%` 为“保”；不自行重算或改变边界。
6. 给出少量可比较候选、取舍和下一步确认问题，而非伪造确定性。

## Evidence 要求

- 每个候选必须绑定标准招生单元 ID、录取率来源、数据版本、适用省份/年份和限制。
- 缺失数据、不可比历史或资格未确认必须显示在 `limitations`/`uncertainties`。
- 解释“冲/稳/保”只引用系统计算的招生单元录取率，不把学校平均值冒充专业结论。

## 单轮调用预算

- 先澄清再调用；完整推荐最多 8 次只读调用，重复参数去重，失败最多重试一次。
- 推荐范围优先批量获取，禁止逐候选 N+1 扫描。

## 停止条件

- 任一必需字段缺失、硬约束冲突、实体未唯一解析、资格未知或状态过期时停止。
- 没有足够 Evidence 支撑的候选不进入结果列表。

## 输出结构

- `responseType=recommendation`，必须有 `artifactRefs` 和 `evidenceRefs`。
- 每个候选包含招生单元 ID、学校/专业名称、风险标签、系统录取率、偏好匹配、资格和限制。
- 明确“依据、风险、未知项、下一步”，不承诺录取。

## 降级策略

- 数据暂不可用时返回可恢复错误和补充问题，不用历史记忆替代当前数据。
- 只能得到部分候选时标记 coverage，不补齐数量；用户确认后再继续查询。
