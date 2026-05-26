# Release 3.0.3 Agent Case Evaluation Report Template

本文是 `case` 级评估的结果记录模板，配合 `release-3.0.3-agent-case-evaluation-framework.md` 使用。

## 1. 单个 Case 记录

每个 case 建议记录为一条独立结果，字段如下：

| 字段 | 说明 |
| --- | --- |
| case | case 名称 |
| scenario | 场景族，如 `plan` / `explore` / `intent` |
| prompt | 用户输入 |
| session_id | 会话 ID |
| baseline_version | 修复前版本 |
| current_version | 当前版本 |
| candidate_model | 候选模型或实现方案 |
| provider | 模型提供方或实现方案提供方 |
| step_index | 同一 case 内的步骤序号 |
| baseline_reply | 修复前回复 |
| current_reply | 当前回复 |
| candidate_reply | 候选回复 |
| first_message_ms | 首响时间 |
| total_ms | 总耗时 |
| tool_trace | routingPath / toolCalls / resultKind |
| content_score | 内容评分 |
| latency_score | 延迟评分 |
| distribution_coverage | 预览 / 举例类回复是否覆盖学校层次、冲稳保、专业热度、数量缺口等关键分布 |
| quality_violations | 硬门禁或薄弱点，例如内部术语、确认边界冲突、预览缺少关键分布 |
| verdict | 结论 |
| notes | 人工补充说明 |

## 2. 推荐评分表

| 维度 | 1 分 | 3 分 | 5 分 |
| --- | --- | --- | --- |
| 正确性 | 明显答错 | 基本对 | 完全正确 |
| 完整度 | 丢关键点 | 够用 | 关键点齐全 |
| 自然度 | 很机械 | 还能读 | 自然顺口 |
| 决策支持度 | 不能继续 | 勉强可用 | 可直接下一步 |
| 延迟 | 明显慢或超时 | 可接受 | 很快且稳定 |

## 3. 结论标签

建议只用下面几类结论，方便后续汇总：

- `improved`
- `same`
- `regressed`
- `bug_fixed`
- `needs_followup`
- `invalid_case`

## 4. Case 级分析写法

每个 case 的分析建议按这个顺序写：

1. 用户想要什么。
2. 修复前哪里有问题。
3. 修复后有没有解决。
4. 是否引入新的副作用。
5. 哪个模型 / 哪种实现更适合这个 case。
6. 是否需要保留人工复核。

## 5. 汇总方式

当一批 case 跑完后，建议再补一层汇总：

| 场景族 | 总数 | 通过数 | 回退数 | 需要人工复核 | 主要问题 |
| --- | ---: | ---: | ---: | ---: | --- |

汇总时重点看：

- 哪类 case 最容易薄回复。
- 哪类 case 最容易超时。
- 哪类 case 最容易把预览说成生效。
- 哪类预览 / 举例 case 最容易缺少关键分布，只给单个样本不够丰满。
- 哪个模型在结构化和自然度之间更平衡。

### 5.1 多模型汇总

如果同一批 case 跑了多个 provider，建议额外补一层：

| provider | model | case 数 | 平均首响 | 平均总耗时 | 质量回退数 |
| --- | --- | ---: | ---: | ---: | ---: |

这样可以直接看：

- 哪个模型更适合 Plan / Explore / Intent 各自的回复风格。
- 哪个模型虽然快，但会丢信息。
- 哪个模型虽然长一点，但更完整、更稳。
