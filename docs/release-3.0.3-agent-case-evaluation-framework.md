# Release 3.0.3 Agent Case Evaluation Framework

本文定义 `3.0.3` 的 case 级回复评估框架，用于后续对不同实现方案、不同模型 provider、以及修复前/修复后版本做统一对照。

发布收口说明：本文仍作为 3.0.3 当前评估框架使用；发布范围、最终回归结果和升级计划见 `docs/release-3.0.3-summary-and-upgrade-plan.md`。

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
- `expectedKeyPoints / forbiddenPatterns`：case 定义里的业务期望点进入自动评分。`expectedKeyPoints` 用来描述该回复必须覆盖的业务含义，工具会尽量按文本短语检查；`forbiddenPatterns` 用来补充该 case 特有的禁用表达。这样可以避免回复格式完整但漏掉“导出顺序影响”“审查待重新看”“确认前不生效”等业务要点时仍被评成 strong。
- `expectedKeyPointGroups`：用于真实用户表达和多模型回复的语义等价检查。比如用户说“财会”，模型回复可能写“会计 / 审计”；用户说“别踩坑”，模型可能写“风险 / 坑点”。这类场景不适合用单个固定字符串卡死，应该用 `{"label": "...", "any": ["...", "..."]}` 表达任一命中即可。
- `expectedNoAction`：用于无 pending 确认保护、只读追问、空结果查询等不应触发工作台动作的 case。评估器会把实际 tool/action 视为 `unexpected_action`，同时对“没有待确认动作、不会修改方案、可继续查看/调整/确认具体要求”等确认保护说明做完整度评分，不再把正确的短确认保护误判成薄预览。
- `minTextLengthWarn`：只作为“回复可能过薄”的 warning，不作为硬失败。它用于多模型对比中发现“速度很快但信息量明显不足”的候选，不能替代业务关键点、禁用表达、确认边界和人工细评。
- `routingPath`：`dialog_regression_runner.py` 会从历史中的 fast-route `model_name` 或 `fast-/direct-` tool call id 推断本轮路由，并写入 `turnObservability.routingPath`。完整 Agent 调用同名工具时不会仅凭工具名推断快路径，避免把真实路由误标。

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

本版本明确采用“回复质量优先于延迟”的排序原则。延迟优化只能在不牺牲正确性、信息量、边界说明和决策支持的前提下做；如果快路径和完整语义链路之间存在不确定性，应优先选择能保证回复质量的路径，再通过进度提示、流式提示和后续缓存降低等待感。

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

- 普通 fast route：总耗时尽量在 3-6 秒内，但前提是回复必须达到该场景的质量门槛。
- 只读复杂分析：超过 10 秒必须有用户可理解的进度提示。
- 单轮超过 case 的 `maxElapsedSeconds` 直接失败。
- 单轮超过 `warnElapsedSeconds` 进入复核，结合回复质量判断是否接受；质量充分、信息完整的慢回复可以接受，快但漏掉关键判断的回复不能接受。

### 3.6 质量优先的路由评分

`fast route` 不能继续作为独立关键词抢路由。本轮已落地统一仲裁层：各 fast router 先产生候选，ChatService 再用 `fast_route_arbitrator` 选择最终路径或降级完整 Agent。后续路由评估按以下顺序判断：

1. 先判断用户语义是否足够明确：场景范围、动作类型、对象实体、是否只读、是否会修改方案。
2. 再判断当前路径是否能输出足够高质量的回复：能否覆盖关键事实、分布信息、影响边界和下一步建议。
3. 最后才看延迟和成本：在质量相近时选择更快、更便宜的路径。

因此，快路径只应处理两类场景：

- 高置信、低歧义、结构化事实足够的场景，例如方案数量概览、明确排序预览、显式审查、无 pending 确认保护。
- 高副作用但语义明确的场景，只生成预览和确认边界，不直接执行。

以下场景不应被关键词快路径直接接管：

- 用户表达混合了地域、风险、专业、家庭约束等多重取舍，需要综合判断。
- 用户使用简称、口语、弱指令，且对象或动作不够明确。
- 快路径只能给出薄回复，但完整 Agent 能给出更有价值的分析。
- 路由之间存在冲突，例如同一句同时像“方案查询”和“意向调整影响”。

这类情况应进入统一语义路由/完整 Agent，或先发起澄清；如果耗时变长，需要用 thinking/progress 提示告诉用户系统正在读取方案、比较候选、生成影响分析，而不是为了速度返回信息不足的结论。

当前仲裁层的验收重点：

- 所有 fast-route 候选必须记录 `scene / actionFamily / sideEffect / quality / blockers`，便于后续分析路由错位。
- case 评估要看 `routeDecision.arbitration.candidates`，不能只看最终 `routingPath`。
- 如果 `fallbackReason=quality_gate_blocked_fast_route`，说明系统主动放弃了更快但信息不足的路径；这类 case 不应判为性能失败，应继续复核完整 Agent 回复质量。
- 新增路由混淆矩阵时，要同时覆盖“应该快”和“不应该快”两类样例。

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
- 真实用户口语化输入：短句、省略、简称、错别字和低信息密度表达，例如“这方案咋样”“法和财哪个好”“青城那个多不多”“按好学校排下看看”。这类 case 单独维护，避免只用测试人员式标准问法代表真实效果。
- 开放式真实问法：家长视角、风险焦虑、专业压力、候选机会和只读追问，例如“这版是不是太冲了，能不能给我说人话”“家里就想让孩子以后稳一点进体制”“法学会不会太卷”“候选里还有没有更稳一点的会计审计”。这类 case 不要求全部走快路径，目标是评估模型组织能力和真实顾问感。
- 意向影响问法：用户可能不会说“记录偏好”，而是说“医学护理这些别碰，财会还能接受，先看看影响”。这类 case 要检查是否进入待确认意向预览，而不是被方案局部查询误抢路由。
- 方案调整边界问法：用户可能说“就按别太冒险的思路把这版调稳点，先给我看看会怎么动”。这类 case 要检查是否说明影响、是否确认后才执行，以及是否允许必要的工作台刷新，而不是一律要求无 follow-up。

每个 case 定义应尽量补齐：

- `flow`：场景族，例如 `plan / explore / intent / confirm_guard`。
- `coverage`：能力标签，例如 `plan_fast_route / preview_confirm_boundary / majorGroup_model`。
- `warnElapsedSeconds / maxElapsedSeconds`：该步骤的耗时预算。
- `expectedRoutingPath / expectedActionFamily`：必要时显式指定链路期望。
- `expectedKeyPoints`：该步骤回复必须覆盖的业务点。建议写成用户语言或可被回复直接命中的短语，例如“导出顺序”“待重新审查”“确认前不会写入后续参考”。
- `expectedKeyPointGroups`：该步骤允许多个等价表达命中同一业务点时使用，例如“财会”可由“会计 / 审计”承接，“别踩坑”可由“风险 / 需要留意”承接。
- `expectedNoAction`：该步骤明确不应触发方案调整、候选加入、刷新工作台或写入偏好的动作时使用。适合只读分析后的“确认”、查询空结果、影响追问等场景。
- `forbiddenPatterns`：该步骤专属禁用表达。通用内部术语、pending 边界等已有全局门禁；这里只放 case 特有风险，例如“不应说候选结果收紧”“不应出现专家推荐”。

### 4.1.1 真实用户输入样例层

真实用户往往不会输入完整业务术语，也不会主动说“结构化输出”“按院校层次”“待确认意向”。这类样例要覆盖：

- 懒输入：一句话、少量词、没有完整上下文，例如“咋样”“能稳吗”“帮我看看”。
- 口语输入：带语气词、模糊词和省略，例如“这版是不是太冲”“保底够不够啊”。
- 简称输入：院校、专业和职业方向简称，例如“青城”“法和财”“新媒体和跨电”“考公”。
- 弱指令输入：没有明确“只分析/不要改”的说法，但语义是先看、先判断、先给建议。
- 高副作用输入：用户说“排下”“挪一下”“加进去”时，系统必须先预览并确认，不因口语化就直接执行。

回复质量要求比标准问法更高：

- 主动把模糊输入翻译成用户能理解的业务问题，但不要暴露系统术语。
- 不能只回“可以/建议/已为你整理”，必须补足结论、依据、风险和下一步。
- 引用数据要有代表性或覆盖面，至少说明数量、冲稳保/层次/热度/候选空间中的关键维度。
- 下一步要能交互：给用户可直接回复的自然动作，例如“继续看审查详情”“按稳妥程度调”“确认后排序”。

### 4.1.2 多模型开放质量层

结构化快路径 case 容易让不同模型输出高度一致，因此多模型对比需要单独维护一批更开放、但仍可自动验收边界的 case：

- 文件：`zhiyuan-agent/examples/model_provider_303_open_quality_realistic_cases.json`
- 用途：用于 `model_provider_benchmark.py --agent-only` 的 provider 横向对比。
- 语言风格：保留真实用户口语和省略表达，不改写成“请结构化分析”。新增样例优先覆盖短句、简称、家长视角、低预算、地域执念、弱确认和“先看看”的只读表达。
- 质量门禁：每个 step 都必须有 `expectedKeyPoints` 或 `expectedKeyPointGroups`、`forbiddenPatterns`、`assertNoFollowups` 和耗时预算，避免只比较耗时。
- 质量 warning：开放 case 可以配置 `minTextLengthWarn`。该字段只用于发现回复信息量偏薄，不直接判失败；最终仍以关键点、边界、联动和人工复核为准。
- 输出要求：使用 `--keep-response-text` 保存完整回复，后续再用 `dialog_case_evaluation_report.py --candidates` 合并到统一质量报告。

推荐命令：

```bash
cd zhiyuan-agent

SILICONFLOW_API_KEY=*** ./.venv/bin/python examples/model_provider_benchmark.py \
  --config examples/model_provider_benchmark.providers.example.json \
  --agent-only \
  --cases examples/model_provider_303_open_quality_realistic_cases.json \
  --start-agent \
  --agent-port 8100 \
  --clear-history \
  --keep-response-text \
  --output /private/tmp/model-provider-303-open-realistic-benchmark.json

./.venv/bin/python examples/dialog_case_evaluation_report.py \
  --candidates models=/private/tmp/model-provider-303-open-realistic-benchmark.json \
  --case-definitions examples/model_provider_303_open_quality_realistic_cases.json \
  --markdown-detail \
  --output /private/tmp/model-provider-303-open-realistic-benchmark-eval.md
```

如果只需要先验证当前本地已生效模型，不启动多 provider 临时 agent，可改用：

```bash
./.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_303_open_quality_cases.json \
  --clear-history \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_agent_303_open_quality_realistic_expanded.json
```

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

- 是否返回命中结果和必要示例；如果真实结果为空，要说明查询口径、空结果原因和可继续的替代路径，不能强行要求“共命中/示例”。
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

# 4. 生成便于人工细评回复质量的完整 Markdown
python3 examples/dialog_case_evaluation_report.py \
  --current /private/tmp/dialog-regression-303-current-text.json \
  --case-definitions examples/dialog_regression_303_effect_perf_cases.json \
  --markdown-detail \
  --output /private/tmp/dialog-case-evaluation-detail.md
```

注意：如果是在评估当前版本自身，必须使用 `--current`。`--candidates current=...` 只适合把某个结果作为候选模型/候选实现展示，报告中的“当前回复”和当前延迟会为空，容易被误读为业务没有返回。

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
2. `case_summary.md`：逐 case 结论和问题摘要，适合快速扫结果。
3. `case_detail.md`：逐 case 完整用户输入、完整回复、评分表、质量问题、链路证据和人工复核清单，适合评审回复质量。
4. `model_matrix.md`：模型横向对比总表。

## 9. 后续执行顺序

1. 先冻结 case 集。
2. 再跑修复前 / 修复后对照。
3. 再跑模型候选矩阵。
4. 最后补人工效果分析，判断是内容提升、速度提升，还是仅仅修掉 bug。
