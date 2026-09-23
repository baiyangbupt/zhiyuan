---
name: admission-fact-analysis
description: Use when a user asks about current plans, historical admission data, subject eligibility, or the factual basis for whether a school-major choice can be submitted.
version: 1.0.0
---

# Admission Fact Analysis

## 适用条件

- 用户询问招生计划、选科要求、历年分数/位次、招生单元或填报资格。
- 候选推荐或方案审查需要补充可审计的招生事实。

## 不适用条件

- 仅讨论兴趣、培养路径或个人偏好时，不主动调用招生接口。
- 用户要求修改画像、方案或最终确认时，保持只读并转交 Proposal/CAS 流程。

## 前置状态

- 已确认省份、考试年份、科目/选科、批次和招生类别。
- 院校、专业和招生单元必须有标准 ID；实体歧义先澄清。
- 读取当前 `stateVersion`，所有查询结果必须带数据版本和适用范围。

## 允许能力

- `entity.resolve`、`catalog.get_school`、`catalog.get_major`
- `admission.get_current_plan`、`admission.get_history`、`admission.check_eligibility`
- 只读招生事实；不重算系统录取率，不调用 Solver 或写工具。

## 标准步骤

1. 检查查询口径是否完整：省份、年份、批次、科目模式、招生单元和专业。
2. 先检查资格，再查询当前计划和历史数据；避免对无资格项目做概率解释。
3. 对历史数据检查 `comparability`、scope、coverage、dataVersion 和 limitations。
4. 原样展示系统提供的录取率/位次结论，区分招生单元与学校整体口径。
5. 说明缺失、未发布、不招生、不适用和未收录的区别，提出下一步澄清。

## Evidence 要求

- 每个关键数字必须引用对应 Evidence、数据版本、省份/年份和招生口径。
- `admission.get_history` 的缺失字段不能转为 0；若不可比，明确 `not_comparable` 或限制。
- 录取率只使用系统针对招生单元、结合成绩和位次计算的结果，第一期不自行重算。

## 单轮调用预算

- 最多 5 次只读调用；相同参数去重，失败最多重试一次。
- 缺少必要查询字段时调用次数为 0，直接请求补充信息。

## 停止条件

- 省份、年份、选科/批次或标准实体缺失时停止，不猜测。
- stateVersion stale、Evidence 越权或后端不可用时停止并返回可恢复错误。

## 输出结构

- `responseType=fact`，包含 `evidenceRefs`、`uncertainties` 和 `limitations`。
- 展示 `eligibility`、`currentPlan`、`history`、`comparability` 和 `dataVersion`，不把多个口径拼成单一结论。

## 降级策略

- 历史数据不完整时只报告实际覆盖范围，允许用户选择更窄的比较口径。
- 后端超时或版本过期时返回 `recoverable.error`，先刷新 Snapshot，不继续基于旧数据推理。
