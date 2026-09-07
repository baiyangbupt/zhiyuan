---
name: profile-discovery
description: Use when a user is beginning volunteer planning or their score, subjects, location, preferences, or constraints are incomplete or inconsistent.
version: 1.0.0
---

# Profile Discovery

## 适用条件

- 用户刚开始规划，或需要把自然语言信息整理成可确认的画像。
- 成绩、位次、选科、目标地域、专业兴趣、家庭约束或风险偏好存在缺口。

## 不适用条件

- 用户只询问已明确院校/专业的客观招生事实。
- 用户要求直接生成或修改最终方案；转交 `candidate-recommendation`、`plan-construction` 或旧链路确认流程。

## 前置状态

- 读取当前 Turn Snapshot 和 `missingFacts`。
- 以 observed/confirmed/tentative 区分用户原话，不把模型推断写成 confirmed。
- 没有 Snapshot 时先返回可恢复错误，不猜测用户身份或成绩。

## 允许能力

- 允许 `entity.resolve` 仅用于确认用户明确提到的院校、专业或城市。
- 不调用招生计算、推荐或任何写能力；本 Skill 不创建 Proposal。

## 标准步骤

1. 复述已确认事实，并列出尚未确认的最少字段。
2. 先询问影响资格和推荐的硬事实：省份、考试年份、成绩/位次、选科和批次。
3. 再询问专业方向、地域、院校层次、学费/家庭约束和风险偏好。
4. 对每次回答标记来源和置信度；发现矛盾时指出冲突并请求用户选择。
5. 以一到三个高价值问题收束本轮，等待确认后再进入下一 Skill。

## Evidence 要求

- 用户陈述可作为 `sourceType=user` 的待确认事实，但不能冒充招生 Evidence。
- 实体必须引用 `entity.resolve` 返回的标准 ID；歧义时展示候选而不自行选择。
- 不用模型记忆补齐分数、位次、招生计划或资格结论。

## 单轮调用预算

- 最多 2 次 `entity.resolve`；相同参数不得重复调用。
- 无需工具即可提问时不调用工具。

## 停止条件

- 关键硬事实仍缺失或互相矛盾时停止并澄清。
- 用户尚未确认画像时，不输出候选、录取率或最终方案。

## 输出结构

- `responseType=text` 或 `clarification`。
- `confirmedFacts`、`tentativeFacts`、`missingFacts`、`nextQuestions`。
- 每个实体带标准 ID 或 `needs_clarification`，不输出裸名称作为权威实体。

## 降级策略

- `entity.resolve` 不可用时保留原始文本并明确“待确认”，不进行下游查询。
- Snapshot 过期时停止本轮推理，请求刷新 Snapshot；旧状态不得覆盖新 Snapshot。
