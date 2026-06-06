# Release 3.0.3 Agent Case Evaluation Report Template

本文是 `case` 级评估的结果记录模板，配合 `release-3.0.3-agent-case-evaluation-framework.md` 使用。

发布收口说明：本文仍作为 case 级报告模板使用；发布范围、最终回归结果和升级计划见 `docs/release-3.0.3-summary-and-upgrade-plan.md`。

评估报告不能只输出“通过 / 不通过”，需要同时保留回复原文、质量评分、链路证据、延迟和人工判断。

## 1. 批量汇总

每轮评估先写总览，便于快速判断是否能进入人工抽检或发布候选。

| 字段 | 说明 |
| --- | --- |
| totalCases | 本轮 case step 总数 |
| current.verdicts | 当前版本 `strong / needs_review / fail` 分布 |
| current.qualityViolationsByType | 硬门禁问题分布，例如内部术语、确认边界、薄预览 |
| current.evaluationWarningsByType | 非硬失败但需关注的问题，例如耗时 warning、缺少路由观测 |
| current.averageScores | 正确性、完整度、自然度、可行动性、结构、延迟、路由的平均分 |
| current.latency | `elapsedMedianMs / elapsedP95Ms / elapsedMaxMs / firstMessageMedianMs` |
| scenarioSummary | 按 `flow` 汇总 Plan / Explore / Intent / Confirm 等场景 |
| coverageSummary | 按 `coverage` 汇总具体能力点 |
| candidateSummary | 按 provider/model 汇总候选模型 |
| baselineComparison | 当前版本与修复前版本的 `improved / same / regressed` |
| acceptance | 本轮是否满足发布前 hard gate |

发布候选建议门槛：

- `fail = 0`。
- `qualityViolationsByType` 为空，或每个硬失败都有明确修复 / 豁免说明。
- `needs_review` 已完成人工复核，且没有关键场景质量退化。
- Plan / Explore / Intent / Confirm guard 至少各有一组有效覆盖。
- 候选模型不能只看耗时，必须同时看回复质量和边界错误。

## 2. 单个 Case 记录

每个 case 建议记录为一条独立结果，字段如下：

| 字段 | 说明 |
| --- | --- |
| case | case 名称 |
| flow | 场景族，如 `plan / explore / intent / confirm_guard` |
| coverage | 能力标签，如 `plan_fast_route / preview_confirm_boundary` |
| prompt | 用户输入原文 |
| sessionId | 会话 ID |
| stepIndex | 同一 case 内的步骤序号 |
| expectedRoutingPath | 预期路由，可为空 |
| expectedActionFamily | 预期 action family，可为空 |
| latencyBudget | `warnElapsedMs / maxElapsedMs` |
| baseline.reply | 修复前完整回复 |
| current.reply | 当前版本完整回复 |
| candidates[].reply | 候选模型或候选实现完整回复 |
| elapsedMs / firstMessageMs / finalMessageMs | 总耗时、首响、最终回复时间 |
| score | 自动质量评分 |
| distributionCoverage | 是否覆盖学校层次、冲稳保、专业热度、数量空间、代表样本 |
| qualityViolations | 硬门禁或薄弱点 |
| evaluationWarnings | 警告项 |
| routingPath / actionFamilies / toolNames | 链路证据 |
| manualReview | 人工复核结论和扣分原因 |

### 2.1 详细 Markdown 报告

人工评审回复质量时，优先生成详细 Markdown：

```bash
cd zhiyuan-agent

python3 examples/dialog_case_evaluation_report.py \
  --current /private/tmp/dialog-regression-303-current-text.json \
  --case-definitions examples/dialog_regression_303_effect_perf_cases.json \
  --markdown-detail \
  --output /private/tmp/dialog-case-evaluation-detail.md
```

详细报告每个 case 应包含：

- 用户输入原文。
- 当前版本完整回复。
- 基线回复和候选模型回复，如果本轮提供了对照数据。
- 自动评分表。
- 覆盖维度、质量问题、warning、路由和工具证据。
- case 定义里的断言和质量期望。
- 人工复核清单。

## 3. 回复质量评分

自动评分和人工评分都按 1-5 分理解：

| 维度 | 1 分 | 3 分 | 5 分 |
| --- | --- | --- | --- |
| 正确性 | 明显答错或边界错 | 基本对但有轻微不准 | 事实和边界完全正确 |
| 完整度 | 丢关键点 | 能回答主要问题 | 结论、依据、影响、下一步齐全 |
| 自然度 | 机械、生硬或像系统日志 | 能读但模板感明显 | 自然顺口，用户容易理解 |
| 决策支持度 | 用户看完不能行动 | 勉强知道下一步 | 可直接确认、追问或调整 |
| 结构清楚度 | 混成一段或堆字段 | 有基本分段 | 结构服务理解，不过度模板化 |
| 延迟 | 明显慢或超时 | 可接受 | 快且稳定，有必要进度提示 |
| 路由 | 链路错或误执行 | 链路不明但结果可用 | 路由、工具、动作都符合预期 |

回复质量人工复核应保留至少这些内容：

| 项 | 内容 |
| --- | --- |
| 用户输入 | 原始 prompt |
| 当前回复 | 完整回复，不只截断摘要 |
| 质量判定 | strong / needs_review / fail |
| 打分 | 正确性、完整度、自然度、决策支持度、结构、延迟 |
| 好的地方 | 具体到回复片段或业务信息 |
| 扣分原因 | 具体说明缺了什么、错了什么或哪里生硬 |
| 下一步 | 修 prompt、修 renderer、修 route、补 case、换模型或人工豁免 |

## 4. 结论标签

建议只用下面几类结论，方便后续汇总：

- `strong`：当前回复质量和链路都满足要求。
- `needs_review`：没有硬失败，但需要人工判断是否够好。
- `fail`：命中硬门禁或明显不可用。
- `improved`：相对基线有明确提升。
- `same`：相对基线基本持平。
- `regressed`：相对基线有退化。
- `invalid_case`：case 本身失效，例如历史脏数据或依赖环境不存在。

## 5. Case 级分析写法

每个 case 的分析建议按这个顺序写：

1. 用户想要什么。
2. 当前链路走了哪里，是否符合预期。
3. 回复有没有回答核心问题。
4. 回复有没有覆盖关键分布或影响面。
5. 延迟和进度提示是否可接受。
6. 与基线或候选模型相比是否更好。
7. 是否需要保留人工复核或补充 case。

## 6. 多模型汇总

如果同一批 case 跑了多个 provider，建议额外补一层：

| provider | model | case 数 | strong | needs_review | fail | p50 总耗时 | p95 总耗时 | 主要问题 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |

这样可以直接看：

- 哪个模型更适合 Plan / Explore / Intent 各自的回复风格。
- 哪个模型虽然快，但会丢信息。
- 哪个模型虽然长一点，但更完整、更稳。
- 哪个模型更容易出现确认边界或内部术语问题。
