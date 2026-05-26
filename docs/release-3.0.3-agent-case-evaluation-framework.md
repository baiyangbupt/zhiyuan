# Release 3.0.3 Agent Case Evaluation Framework

本文定义 `3.0.3` 的 case 级回复评估框架，用于后续对不同实现方案、不同模型 provider、以及修复前/修复后版本做统一对照。

## 1. 目标

本框架不是只看“快不快”或“短不短”，而是同时评估：

1. 回复有没有答到用户真正要的信息。
2. 回复有没有丢关键事实，或者把未确认内容说成已生效。
3. 回复是否足够自然、可读、可继续追问。
4. 回复延迟是否可接受，长任务是否有及时反馈。
5. 不同实现方案和不同模型之间，谁更适合当前业务场景。

## 2. 评估对象

### 2.1 Case 级别

每个 case 都是一个最小评估单元，建议包含：

- `case_name`
- `scenario_family`，例如 `plan` / `explore` / `intent` / `confirm_guard`
- `session_id`
- `user_prompt`
- `expected_key_points`
- `forbidden_patterns`
- `latency_budget`
- `baseline_version`
- `candidate_versions`
- `candidate_models`

### 2.2 对照维度

每个 case 至少做三组对照：

| 维度 | 说明 |
| --- | --- |
| 修复前版本 vs 当前版本 | 看这次修复到底解决了什么，是否引入回退 |
| 当前实现方案 A vs 方案 B | 例如 fast route、renderer、fallback 等不同实现路径 |
| 模型候选对比 | 例如当前线上模型、`Pro/MiniMaxAI`、`MiniMax-M2.5`、`DeepSeek-V4-Flash Pro`、`GLM-5.1` |

### 2.3 已有工具的关系

现有工具可直接复用：

- `zhiyuan-agent/examples/dialog_regression_runner.py`：适合 case 级对话回归、thinking、followup、tool trace、延迟门禁。
- `zhiyuan-agent/examples/model_provider_benchmark.py`：适合同一 prompt 在多个 provider 间做直接/agent 双模式对比。
- `zhiyuan-agent/examples/dialog_regression_303_effect_perf_cases.json`：适合作为 3.0.3 的主 case 集。

### 2.4 多模型对照如何进入同一评估流

多模型对照不是单独看性能分，而是和 case 级质量评分合并到同一套输出里：

1. 先用 `dialog_regression_runner.py --keep-response-text` 跑修复前 / 当前版本，得到 case 级对照和真实回复文本。
2. 再用 `model_provider_benchmark.py --agent-only` 跑同一批 case，得到多个 provider / model 的回复文本和延迟。
3. 最后用 `dialog_case_evaluation_report.py` 统一合并两类输出，按 `case + stepIndex` 对齐。

这样可以在同一个表里同时看：

- 修复前 vs 修复后
- 当前实现方案 vs 候选实现方案
- 当前模型 vs 候选模型
- 内容质量 vs 延迟

当前 `dialog_case_evaluation_report.py` 已把这套标准落到 case 级评分输出中：

- `qualityViolations`：记录硬门禁问题，例如内部字段外露、待确认/已生效边界冲突、预览缺少关键分布。
- `distributionCoverage`：记录回复覆盖了哪些关键分布，例如冲稳保、学校层次、专业热度、数量空间和代表样本。
- `verdict`：按硬门禁和维度得分给出 `fail / needs_review / strong`，便于后续批量筛出薄回复。
- 确认保护类回复不套用预览分布门禁：用户只回复“确认/确认这个偏好/确认这个要求”时，如果系统是在说明没有待确认动作或执行确认结果，不要求额外覆盖冲稳保、院校层次、专业热度等分布，避免把正确的确认边界保护误判为薄预览。

## 3. 评分框架

3.0.3 的评估框架分为七层，不能只看单条回复是否通过断言：

| 层级 | 评估目标 | 主要产物 |
| --- | --- | --- |
| Case 覆盖 | 是否覆盖 Plan / Explore / Intent / Confirm / 降级等核心场景 | `flow`、`coverage` 统计 |
| 单轮回复质量 | 回复是否正确、完整、自然、有决策价值 | 维度评分、原文样例 |
| 多轮链路正确性 | preview -> confirm -> apply、只读 -> confirm guard 是否连贯 | step 级结果、pending 边界 |
| 路由和工具链 | 是否命中预期 fast route / full agent / action family | `routingPath`、`actionFamily`、tool trace |
| 性能和进度 | 首响、总耗时、长任务提示是否达标 | p50 / p95 / max、thinking 覆盖 |
| 安全和边界 | 是否外露内部术语、误执行高副作用动作、把待确认说成已生效 | hard gate |
| 模型和版本对照 | 当前版本、基线版本、候选模型谁更适合 | provider/model summary |

### 3.1 硬门禁

以下任一项命中，直接判失败：

- 答非所问。
- 把“待确认”说成“已生效”。
- 待确认意向预览里使用“把 X 记成/作为/都会按这个要求来”等已生效语气，却没有明确“确认后”条件。
- 把 preview 说成 apply。
- 泄露内部字段或内部术语。
- 关键事实缺失到影响下一步操作。
- 超时或长时间无进度提示。
- 误触发无联动卡片或误执行旧 pending。
- 路由与场景明显不符，例如只读查询误走变更 apply、确认保护误执行旧动作。

对预览 / 举例类回复，若只给对象或个例、却没有覆盖关键分布，也视为不完整，至少应补到下面几类中的两类或以上：

- 学校层次分布。
- 冲稳保分布。
- 专业热度或专业方向分布。
- 数量缺口或可操作空间。
- 代表性样本和它们为何被举例。

### 3.2 回复质量评分

建议按 1-5 分评分：

| 维度 | 关注点 |
| --- | --- |
| 正确性 | 事实是否对，边界是否对 |
| 完整度 | 关键结论、依据、影响、下一步是否说全 |
| 决策支持度 | 用户看完能否直接继续下一步 |
| 自然度 | 是否像正常人说话，不像系统播报 |
| 结构清楚度 | 是否层次清楚，但不过度模板化 |
| 场景适配度 | Plan / Explore / Intent / 查询类是否用对口径 |

回复可以结构化，且多数业务回复应结构化；问题不是“有没有标题”，而是结构是否服务用户理解。评估时重点看：

- 是否先给结论，再给依据、影响和下一步。
- 是否保留用户真正关心的信息，不为了变快把内容做薄。
- 是否能解释“为什么这样建议”，而不是只列对象。
- 是否把当前方案、候选机会、用户偏好、风险和操作边界讲清。
- 是否避免系统内部概念，例如 `payload / stage / action_family / level1`。

预览 / 举例类回复还要额外看：

- 是否把关键分布讲清楚。
- 是否只给了个例，没有告诉用户整体结构。
- 是否能让用户据此判断要不要补稳保、换层次或调整专业热度。

### 3.3 场景特化质量要求

| 场景 | 质量重点 |
| --- | --- |
| Plan 状态查询 | 至少覆盖方案数量、冲稳保、审查状态、代表样本和下一步建议 |
| Plan 预览调整 | 说清目标对象、当前位置/目标位置、数量影响、导出顺序、审查状态和确认边界 |
| Plan 审查 | 先给审查结论，再给主要风险、影响范围、建议动作和是否需要用户确认 |
| Explore 职业/方向 | 给方向判断、方案承接、候选机会、短板和下一步，不直接写偏好 |
| Explore 专业对比 | 对比适配人群、就业方向、学习压力、风险点和当前会话事实 |
| Intent 预览 | 区分软偏好和硬要求，明确确认前不会写入后续参考 |
| Intent 确认 | 复述本次确认内容，说明后续如何参考，不夸大为候选池永久变化 |
| Confirm guard | 没有待确认动作时必须说明上一轮只是查询/分析/对比，并给可继续动作 |

### 3.4 自动评估与人工评估边界

自动评估负责第一道筛查：

- hard gate：内部术语、待确认边界、空回复、超时硬阈值、路由错位。
- 质量维度：正确性、完整度、自然度、决策支持度、结构清楚度、延迟、路由。
- 预览覆盖：学校层次、冲稳保、专业热度、数量空间、代表样本。
- 汇总统计：按 `flow / coverage / provider / model` 看 `strong / needs_review / fail`。

人工评估负责最终判断：

- 逐 case 保留用户输入和完整回复原文。
- 对核心 case 给 1-5 分，并写明扣分原因。
- 对 `needs_review` 和模型候选差异做人工复核。
- 对“快但信息丢失”“长但有价值”的情况给业务判断，不能只按字数或耗时裁决。

### 3.5 延迟评分

延迟不能只看总耗时，要拆开看：

| 指标 | 说明 |
| --- | --- |
| 首响时间 | 用户多久看到第一条有用信息 |
| 有效结论时间 | 用户多久看到核心判断 |
| 总耗时 | 一轮完整结束需要多久 |
| 波动性 | 同类 case 快慢是否稳定 |
| 超时率 | 是否经常跑满超时阈值 |
| 进度覆盖率 | 长任务是否有 thinking / progress hint |

建议门槛：

- 普通 fast route：总耗时尽量在 3-6 秒内。
- 只读复杂分析：超过 10 秒必须有用户可理解的进度提示。
- 单轮超过 case 的 `maxElapsedSeconds` 直接失败。
- 单轮超过 `warnElapsedSeconds` 进入复核，结合回复质量判断是否接受。

## 4. Case 级评估流程

### 4.1 固定 case 集

先冻结一份 case 集，不在同一轮里频繁改动 case 内容。
case 需要覆盖：

- Plan 状态查询
- Plan 排序 / 移动 / 加入 / 删除 / 确认
- Explore 职业方向
- Explore 专业对比
- Intent 预览 / 确认
- 无 pending 的确认保护
- 降级 / 无数据 / 脏历史保护

每个 case 定义应尽量补齐：

- `flow`：场景族，例如 `plan / explore / intent / confirm_guard`。
- `coverage`：能力标签，例如 `plan_fast_route / preview_confirm_boundary / majorGroup_model`。
- `warnElapsedSeconds / maxElapsedSeconds`：该步骤的耗时预算。
- `expectedRoutingPath / expectedActionFamily`：必要时显式指定链路期望。

### 4.2 统一跑法

同一 case 要在相同上下文下分别跑：

1. 修复前版本。
2. 当前版本。
3. 候选实现方案。
4. 候选模型。

建议记录为四列对照：

| case | baseline | current | candidate/model |
| --- | --- | --- | --- |

### 4.3 每个 case 的输出

每条样本建议输出以下内容：

```json
{
  "case": "303-quality-plan-status-rich-structured",
  "scenario": "plan",
  "prompt": "看看现在的方案，给我一个结构化一点的结论",
  "baseline_reply": "...",
  "current_reply": "...",
  "candidate_replies": [
    {
      "name": "MiniMax-M2.5 Pro",
      "reply": "...",
      "first_message_ms": 1800,
      "total_ms": 5200
    }
  ],
  "tool_trace": {
    "routingPath": "plan_fast_route",
    "toolCalls": ["plan_next_action", "execute_plan_action"]
  },
  "scores": {
    "correctness": 5,
    "completeness": 4,
    "naturalness": 4,
    "actionability": 5,
    "latency": 4,
    "route": 5
  },
  "verdict": "improved"
}
```

### 4.4 批量报告要求

`dialog_case_evaluation_report.py` 的输出应至少包含：

- `summary.current`：当前版本总览、质量问题、平均分、延迟分位数。
- `summary.scenarioSummary`：按 `flow` 汇总。
- `summary.coverageSummary`：按能力标签汇总。
- `summary.candidateSummary`：按 provider/model 汇总。
- `summary.baselineComparison`：与基线版本的强弱变化。
- `cases[]`：逐 case 回复原文、分数、路由、耗时、候选模型对照。

发布前建议门禁：

- `fail = 0`。
- 不允许出现内部术语和确认边界硬失败。
- `needs_review` 必须有人工复核结论。
- 核心 Plan / Explore / Intent 场景都要有覆盖，不允许只用 fast route smoke 代表整体质量。

## 5. 场景级重点

### 5.1 Plan

重点看：

- 是否说清对象、位置、影响面、确认边界。
- 是否把排序 / 移动 / 加入 / 删除 / 审查的副作用说明到位。
- 是否保住 `preview -> confirm -> apply`。

### 5.2 Explore

重点看：

- 是否给出结论，而不是只给一句“可以看看”。
- 是否包含依据、当前方案承接、候选机会、下一步。
- 信息不足时，是否只追问最关键的一项，而不是一次问太多。

### 5.3 Intent

重点看：

- 是否把正向 / 负向意向说清。
- 是否明确“待确认”，而不是提前说“已经记下”。
- 确认后是否才真正写入。

### 5.4 查询类

重点看：

- 是否返回命中结果和必要示例。
- 是否避免内部 ID、payload、stage 这类字段外露。
- 是否不会把局部查询误写成改方案。

## 6. 模型对照方式

建议把模型配置拆成独立 provider 维度，不要把模型名和实现方案混在一起。

### 6.1 推荐候选

- 当前线上基线模型
- `Pro/MiniMaxAI`
- `MiniMax-M2.5`
- `DeepSeek-V4-Flash Pro`
- `GLM-5.1`

### 6.2 对照方法

每个模型都用同一批 case、同一份上下文、同一套评分标准跑一遍，最后看：

- 谁更完整。
- 谁更稳。
- 谁更少出边界问题。
- 谁的首响和总耗时更好。

建议把输出统一落到 `dialog_case_evaluation_report.py`，这样多模型结果和修复前后结果可以直接横向比对。

推荐本地跑法：

```bash
cd zhiyuan-agent

# 1. 当前实现：保留完整回复和 thinking，用于内容评分
python3 examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_303_effect_perf_cases.json \
  --metrics-output /private/tmp/dialog-regression-303-current-text.json \
  --keep-response-text

# 2. 多模型候选：同一批 agent e2e case，key 只从环境变量读取
SILICONFLOW_API_KEY=*** python3 examples/model_provider_benchmark.py \
  --config examples/model_provider_benchmark.providers.example.json \
  --agent-only \
  --cases examples/model_provider_benchmark_e2e_cases.json \
  --output /private/tmp/model-provider-agent-benchmark.json

# 3. 合并为统一 case 报告
python3 examples/dialog_case_evaluation_report.py \
  --baseline examples/dialog_regression_302_effect_perf_output.json \
  --current /private/tmp/dialog-regression-303-current-text.json \
  --case-definitions examples/dialog_regression_303_effect_perf_cases.json \
  --candidates models=/private/tmp/model-provider-agent-benchmark.json \
  --output /private/tmp/dialog-case-evaluation-report.json
```

## 7. 版本对照方式

修复前版本的作用是做基线，不是回退上线。

### 7.1 保留对照的版本

- 修复前回复版本
- 当前修复后版本
- 不同实现方案版本

### 7.2 不必回退对照的情况

如果某个环节已经确认是无效路径、废弃入口或纯 bug 修复，不再纳入模型对照，只记录在变更说明和回归结论里即可。

## 8. 推荐产物

建议每轮评估输出三份文件：

1. `case_results.json`：逐 case 原始结果。
2. `case_summary.md`：逐 case 结论和问题摘要。
3. `model_matrix.md`：模型横向对比总表。

## 9. 后续执行顺序

1. 先冻结 case 集。
2. 再跑修复前 / 修复后对照。
3. 再跑模型候选矩阵。
4. 最后补人工效果分析，判断是内容提升、速度提升，还是仅仅修掉 bug。
