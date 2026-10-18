---
name: plan-admission-interpretation
description: Use when the user asks what the current plan could land on, how safe its structure is, or what happens if some entries are removed — read the plan structure via planning.interpret_admission and explain scenarios without probabilities.
version: 1.0.0
---

> 执行口径以 `r1/admission-fact-analysis/references/evidence-policy.md`（跨技能引用，路径以插件根为基准）为准。
> **动手前先读它**——读一次比凭印象写更省事，也避免和规范悄悄分叉。

# Plan Admission Interpretation

## 适用条件

- 用户问“以我现在这个方案，大概会被什么录取走 / 能上哪一档 / 这个方案稳不稳”。
- 用户问“去掉某几条会怎样”“保底够不够”“梯度有没有断层”。
- 方案执行完成后的续接回合：需要说明这版方案的结构与条件情景。

## 不适用条件

- 没有正式方案（`planInterpretable=false`，包括只有 working-only 草稿）：
  先说明“当前没有可解读的正式方案”，建议先补足/生成 ordered 方案，不调用工具编情景。
- 用户要**录取概率/滑档概率**：明确说“没有权威概率源，只能讲结构与条件”，
  不估算、不拿历史分数顶替。
- 单点事实问题（某校某专业多少分/什么选科）：用事实查询工具，不用本技能。

## 前置状态

- 最新方案快照可用；`planVersion` **原样取注入的【当前旅程】里的方案版本**
  （不是旧回合的值，也不自行猜）。
- `planInterpretable=true` 才调用工具；working-only 先补足成 ordered 方案。
- 方案 `planFreshness=stale` 时仍可解读，但正文要说明“这是旧条件下的一版”；
  不因 stale 伪造新结论。
- 只读：不创建 pending、不写方案、不 bump 版本。

## 允许能力

- `planning.interpret_admission`（只读，单轮最多 1 次）。
- 需要事实补充时可用既有只读查询工具；不得调用任何写工具。

## 标准步骤

1. 从【当前旅程】原样取 `planVersion`；与用户讨论的方案版本不一致时先重新读取状态。
2. 调一次 `planning.interpret_admission(planVersion=...)`。
   - 用户明确问“去掉 X 会怎样”且能指出条目：传
     `counterfactual.removeEntryRefs=[{level,id}]`；MVP 只支持 remove。
3. 按返回的 `scenarios` 讲四类情景：
   - `base`：首个稳/保位置（条件：若前序均未满足）；
   - `upside`：冲档最高校线率位置（条件：若冲档命中）；
   - `downside`：最后保底位置；
   - `no_safe`：没有可识别的保底档位。
4. 把**结构覆盖**与**数据缺口**分开说：
   - `safetyCoverage` / `dataCompletenessBand` / `orderAnomaly` 逐项转述；
   - 缺数据说“无法判断/数据不足”，不说“风险低”。
5. 结尾给一个可行动的下一步（补保底、补数据、调整梯度、看具体候选），
   但不自动执行任何写操作。

## 输出口径（必须遵守）

- **禁止**：录取概率、滑档概率、“最可能”“大概率被录取”等概率性结论；
  禁止把 `base` 叫“最可能”。
- **不得转述 `admissionRatio` / `schoolEnrollRatio` 的具体百分比**：那是系统
  口径的证据值，用户会读成录取概率。只说档位、位置、条件和数据是否齐全。
- 可以说：“结构上先落到…”“如果冲档命中…”“最后保底在…”“当前没有可识别的保底档位”。
- 引用具体条目时用院校/专业/位置，与返回一致；不要补充返回里没有的数字。
- 缺 `ratio`/省份等数据时如实说缺口；不得用 0 或“安全”补齐。
- **解读卡由系统自动渲染**：正文不要声称“没有卡片 / 没有可引用记录 / 生成了解读卡”；
  只讲结论、数据缺口和下一步。卡片是否出现不是模型负责的事。

## Evidence 要求

- 解读是**由当前方案结构计算的说明**，不是一条权威录取事实；不得自铸
  `sourceLevel=authoritative` 的证据。
- 工具返回的 `caveats` / 数据缺口要原样转述；没有 `evidenceRefs` 就说没有，
  不要拿历史分数或热度顶替。
- 引用条目必须来自返回的 `landingEntry` / `path`，不凭印象补条目。

## 停止条件

- 没有方案（`hasPlan=false`）：说明“当前没有可解读的方案”，停下来等用户建方案。
- `stale_interpretation` 且重新读取状态后仍不一致：停下来请用户刷新/重新生成预览。
- 工具连续失败两次：如实说“暂无法解读”，不再重试。
- 用户坚持要录取概率：说明边界（只有权威概率源才能给，当前没有），不估算。

## 输出结构

- 一句话结论（当前方案结构上先落到哪）。
- 最多四条情景：基准 / 向上 / 向下 / 无保底（有哪条说哪条，不硬凑）。
- 一段结构覆盖与数据缺口（安全覆盖、数据完整度、顺序异常）。
- 一个可行动的下一步（补保底 / 补数据 / 调梯度 / 看具体候选）。

## 降级策略

- 工具 `backend_unavailable` / `unavailable`：说“暂无法解读当前方案”，
  可给只读方案事实，但不自行推演情景。
- 缺 ratio/省份：对应情景标“无法判断”，不把缺数据说成安全或危险。
- 反事实只支持 remove；用户要 add/replace/reorder 反事实时，说明暂不支持，
  可改为先出对应调整预览。

## 单轮调用预算

- `planning.interpret_admission` 1 次；事实补充工具合计 ≤3 次；不得 N+1 循环。
