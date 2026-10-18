---
name: candidate-recommendation
description: Use when a user has enough confirmed score context and constraints to request ranked volunteer candidates with evidence-backed risk and preference explanations.
version: 1.0.0
---

> 执行口径以 `r1/candidate-recommendation/references/recommendation-explanation-guide.md`（跨技能引用，路径以插件根为基准） 为准（提问顺序、冲突处理、单轮问题数等细则在那里）。
> **动手前先读它**——读一次比凭印象写更省事，也避免和规范悄悄分叉。
>
> **续接/续写回合也要加载本技能**：只要本轮涉及候选、冲稳保、选科资格或专业方向推荐，
> 即使上一轮走的是 `profile-discovery`，也必须先加载本技能再动手——「单轮只读 ≤8」
> 「禁 N+1」的预算只写在这里，没加载就没有这些约束。

# Candidate Recommendation

## 适用条件

- 用户明确要求候选、排序或“冲稳保”建议。
- Snapshot 已确认省份、考试年份、成绩或位次、选科/批次以及硬约束。

## 不适用条件

- 缺少省份、年份、位次/成绩、选科或批次时，不输出候选，必须 clarification。
- 存在硬约束冲突、实体歧义、资格未知或数据不可比时，不输出候选。
- 用户要求直接写入方案时，先输出只读候选并转入 Proposal/CAS，不自行 apply。

## 点名加入 ≠ 覆盖要求（2026-10-17 硬规则）

- 用户点名**具体院校 + 专业**并说“加入 / 加进 / 放进 / 补进方案”，且这些条目还不在当前
  方案里：这是**加入动作**，交给确认链路的
  `proposalRequest(goalType="add_units", exactTargets=[{schoolName: "...", majorName: "..."}])`
  ——先从 `recommendation.preview_candidates` 复制准确名称。
- **不要**用 `preview_intent_change(constraint_type="must_have")` /
  `must_include_scope` 做点名加入：该路径只在**方案已有条目**里校验“必须包含”，
  条目不在方案里会以 `user_goal_target_not_found` 整单退回（2026-10-17 实测：六条
  点名加入被拒）。
- 只有“方案里必须保留 / 不能删 / 必须有某类”且**不要求立即加入具体条目**时，才用
  must_have / must_include_scope。
- **默认语义是 EXPAND（扩总数、零删除）**，卡面写明总数变化；用户明确说“总数不变 /
  必须有这几条 / 换掉几条”时不要用 add_units 静默扩总数，先问一次“扩总数还是保持总数
  替换”。
- **按范围加 N 条**（不点名具体院校/专业）→
  `proposalRequest(goalType="add_units_by_scope", addCount=N, targetScopes=[...], context={"maxTuitionPerYear":...})`；
  筛选条件只作用于本次新增。不要把范围条件塞进 `add_units`（它只接受点名目标）。

## 前置状态

- 已取得当前 Snapshot 和最新 `stateVersion`。
- 先看注入的【当前旅程】：`candidateFreshness=stale`（如刚补录成绩）时先刷新/重取候选，
  不把旧候选当当前结果；`planFreshness=stale` 时推荐候选仍可做，但说明方案需重算。
- 目标院校/专业/招生单元已由 `entity.resolve` 解析为标准 ID。
- 读取用户确认的偏好与排除项；tentative 偏好只能影响解释，不能当硬约束。
- 已确认的发展方向（快照 `preferences.careerTypes`，四类中文标签）是**弱偏好**：
  只进 Preference Fit 维度、推荐理由、排序与解释，**不做硬筛**（不据此排除候选 ✗）。
- Required gate fields are `province`, `year`, `score` or `rank`, subject mode/batch, and confirmed hard constraints.

## 允许能力

- `entity.resolve`、目录只读工具和全部 `admission.*` 只读工具。
- 不调用写工具、不创建 Proposal、不凭模型记忆生成招生数字。

## 标准步骤

1. 先执行输入门槛检查：省份、年份、成绩/位次、选科/批次、硬约束和目标范围。
2. 解析实体并检查资格；任何硬约束冲突都列入排除原因。**分数变更不重新核对选科资格**
   （资格只与省/年/批/选科组合有关）；同一选科组合已核过的专业直接复用结果，
   只有新出现的专业才需要核。
3. 获取招生单元层面的系统录取率、历史可比性和 Evidence。
4. 分开呈现 Eligibility、Admission Probability、Preference Fit、Data Confidence 四个维度。
   已确认的发展方向（careerTypes）进 Preference Fit 与排序解释（如"该校该专业近年去向与
   考公/深造路线衔接"）：只作为**理由**，不改变资格判定、不排除候选。
5. 依据系统录取率标记风险：`<50%` 为“冲”，`50%~70%` 为“稳”，`70%~99%` 为“保”；不自行重算或改变边界。
6. 给出少量可比较候选、取舍，并**宣布下一步**（需要用户定的用封闭式选项），而非伪造确定性。
   封闭式选项里的「都不对 / 换一批」必须写成**明确的第 N 个选项**（如「④ 都不太合适，
   换一批」），不得写成陈述句——陈述句会被读成结论而不是可选项。

## Evidence 要求

<HARD-GATE>
必需字段（省份/年份/成绩或位次/选科或批次/已确认硬约束）缺一 → **不输出候选**，只澄清。
候选**只读**：用户要"直接写进方案"时，只输出候选并说明写请求需经用户确认的链路（本技能不创建
Proposal、不自行 apply）；**不调用任何写工具**（含 `plan_apply` 这类 `readOnlyHint: false` 工具，
即使参数齐、看起来一步能完成）。
</HARD-GATE>

- 每个候选必须绑定标准招生单元 ID、录取率来源、数据版本、适用省份/年份和限制。
- 缺失数据、不可比历史或资格未确认必须显示在 `limitations`/`uncertainties`。
- 解释“冲/稳/保”只引用系统计算的招生单元录取率，不把学校平均值冒充专业结论。

## 单轮调用预算

- 先澄清再调用；**单轮只读调用总预算 ≤8 次**（含重试），重复参数去重，失败最多重试一次。
- **禁 N+1 逐条循环**：能批量拿到的绝不逐条调用。`admission.check_eligibility` 一次只核
  一个 `majorId`——要核的集合先按选科组合去重、只核没核过的新专业，不得把每个候选挨个
  循环一遍（真事故：一个续接回合因此打了 15 次资格核验）。
- 推荐范围优先批量获取，禁止逐候选 N+1 扫描。

## 停止条件

- 任一必需字段缺失、硬约束冲突、实体未唯一解析、资格未知或状态过期时停止。
- 没有足够 Evidence 支撑的候选不进入结果列表。

## 输出结构

- `responseType=recommendation`，必须有 `artifactRefs` 和 `evidenceRefs`。
- 每个候选包含招生单元 ID、学校/专业名称、风险标签、系统录取率、偏好匹配、资格和限制。
- **面向用户不直出原始数值**：`<50%` / `50%~70%` / `70%~99%` 是内部判定口径，给用户说
  「冲/稳/保」和可溯源的理由（选科匹配、分数/位次区间、地域/学费约束等）；
  专业方向推荐（`recommendation.preview_majors`）返回里的 `score` 与各维度指数只作内部依据，
  给用户的文本里不出现这些数字。
- 明确“依据、风险、未知项、下一步”，不承诺录取。

## 降级策略

- 数据暂不可用时返回可恢复错误和补充问题，不用历史记忆替代当前数据。
- 只能得到部分候选时标记 coverage，不补齐数量；用户确认后再继续查询。
