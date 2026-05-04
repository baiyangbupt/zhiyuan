# 初始方案评估报告 P0

## 1. 评估范围

本轮只覆盖 `P0` 真实样本回归，目标是先确认：

- 当前 `sessionDetailV2` 初始方案链路在真实会话下是否能稳定给出结果
- `majorGroup / major` 两种模式下，新版相对老版的主要差异是否可解释
- 当前异常更偏向“供给不足”还是“算法退化”还是“样本数据异常”

执行方式：

- 读取真实会话已有 `planningState`
- 在内存中只读仿真 `initialRecommendation + orderedPlan`
- 不回写数据库，避免评测过程污染会话状态或写爆 `assistant_chat_session_extra_data`

对应样本：

- `HN-01A` -> session `14`
- `HN-02A` -> session `11`
- `HN-03A` -> session `15`
- `HN-04A` -> session `16`
- `SD-01A` -> session `17`
- `SD-02A` -> session `7`

## 2. 汇总结论

### 2.1 总体判断

- `majorGroup` 主链路当前基本可用。`session 14/15/16` 均能贴齐目标组数，且新旧结果差异主要来自“先按组生成，再补组内专业”的新口径。
- `major` 模式仍有明显供给约束场景。`session 17/7` 的保区供给明显不足，新版没有硬造保区，而是把缺口回收到了稳区，这一行为本身可解释，但最终比例偏离目标较大，仍需后续专项优化。
- `session 11` 当前不应计入算法优劣判断。该样本的持久化 `planningState` 中候选池本身为空，导致新版结果直接为 `0/0/0`，属于样本数据异常，不是本轮算法结论。

### 2.2 分类结论

| session | sampleId | mode | judgement | 结论摘要 |
|---|---|---|---|---|
| 14 | HN-01A | majorGroup | better_than_legacy | 目标数贴齐，组层口径正确，结果可解释 |
| 11 | HN-02A | majorGroup | invalid_sample | 持久化候选池为空，暂不用于算法判断 |
| 15 | HN-03A | majorGroup | better_than_legacy | 目标数贴齐，保守策略下结构稳定 |
| 16 | HN-04A | majorGroup | better_than_legacy | 当前核心回归样本通过 |
| 17 | SD-01A | major | safer_but_supply_limited | 保区供给为 0，只能回补稳区 |
| 7 | SD-02A | major | possible_regression_but_supply_limited | 保区供给仅 9，离目标 39 差距较大，需继续优化 |

## 3. 样本明细

### 3.1 HN-01A / session 14

```yaml
sample:
  sampleId: HN-01A
  sourceType: real_session
  sessionId: 14
  province: 河南
  volunteerModel: majorGroup
  scoreBand: L2
  totalScore: 444
  rank: 317514
  strategyType: traditional
  gender: 男
legacy:
  targetTierCounts: {冲: 9, 稳: 19, 保: 20}
  preferredTierCounts: {冲: 9, 稳: 19, 保: 20}
v2:
  requiredTierCounts: {冲: 9, 稳: 19, 保: 20}
  candidatePoolTierCounts: {冲: 849, 稳: 763, 保: 2003}
  initialTierCounts: {冲: 9, 稳: 19, 保: 20}
  orderedTierCounts: {冲: 9, 稳: 19, 保: 20}
  unresolvedRuleCodes: [unit_major_count_validation, group_inner_safety_guard]
assessment:
  judgementTag: better_than_legacy
```

判断：

- 新版已按专业组口径贴齐 `9/19/20`，没有再出现“组内专业摊平后数量放大”的老问题。
- 候选池三层供给充足，说明当前结果不是被供给硬逼出来的，而是算法能稳定完成组层组装。
- `unit_major_count_validation / group_inner_safety_guard` 仍未完全消除，表示组层数量满足后，组内专业安全垫还存在后续优化空间。

### 3.2 HN-02A / session 11

```yaml
sample:
  sampleId: HN-02A
  sourceType: real_session
  sessionId: 11
  province: 河南
  volunteerModel: majorGroup
legacy:
  targetTierCounts: {冲: 9, 稳: 19, 保: 20}
  preferredTierCounts: {冲: 9, 稳: 19, 保: 20}
v2:
  requiredTierCounts: {冲: 0, 稳: 0, 保: 0}
  candidatePoolTierCounts: {冲: 0, 稳: 0, 保: 0}
  initialTierCounts: {冲: 0, 稳: 0, 保: 0}
  orderedTierCounts: {冲: 0, 稳: 0, 保: 0}
assessment:
  judgementTag: invalid_sample
```

判断：

- 该样本当前持久化 `planningState` 内候选池就是空的，因此新版只读仿真必然得到 `0/0/0`。
- 本地库核查结果：`planningState.bytes=2017`、`phase=profile_ready`、`candidate_total=0`、`required_count=NULL`，说明这条会话停留在画像准备阶段，没有完成候选池生成。
- 老版能返回正常结果，说明外部推荐链路并非无数据，问题更可能在该会话的 `planningState` 历史数据缺失或未初始化完整。
- 本样本需先回补数据，再重新纳入评估。

### 3.3 HN-03A / session 15

```yaml
sample:
  sampleId: HN-03A
  sourceType: real_session
  sessionId: 15
  province: 河南
  volunteerModel: majorGroup
  scoreBand: M2
  totalScore: 474
  rank: 260370
  strategyType: cautious
legacy:
  targetTierCounts: {冲: 14, 稳: 14, 保: 20}
  preferredTierCounts: {冲: 14, 稳: 14, 保: 20}
v2:
  requiredTierCounts: {冲: 14, 稳: 14, 保: 20}
  candidatePoolTierCounts: {冲: 3159, 稳: 555, 保: 2255}
  initialTierCounts: {冲: 14, 稳: 14, 保: 20}
  orderedTierCounts: {冲: 14, 稳: 14, 保: 20}
  unresolvedRuleCodes: [unit_major_count_validation, group_inner_safety_guard]
assessment:
  judgementTag: better_than_legacy
```

判断：

- 在 `cautious` 策略下，新版仍能维持 `14/14/20` 的目标结构，没有被冲区超大供给带偏。
- 候选池冲区明显过大，但新版最终没有继续堆冲，说明目标 tier 配额控制已经生效。
- 当前剩余问题仍集中在专业组内部，而不是组层数量本身。

### 3.4 HN-04A / session 16

```yaml
sample:
  sampleId: HN-04A
  sourceType: real_session
  sessionId: 16
  province: 河南
  volunteerModel: majorGroup
  scoreBand: M1
  totalScore: 464
  rank: 279857
  strategyType: traditional
legacy:
  targetTierCounts: {冲: 9, 稳: 19, 保: 20}
  preferredTierCounts: {冲: 9, 稳: 19, 保: 20}
v2:
  requiredTierCounts: {冲: 9, 稳: 19, 保: 20}
  candidatePoolTierCounts: {冲: 2439, 稳: 559, 保: 3423}
  initialTierCounts: {冲: 9, 稳: 19, 保: 20}
  orderedTierCounts: {冲: 9, 稳: 19, 保: 20}
  unresolvedRuleCodes: [unit_major_count_validation, group_inner_safety_guard]
assessment:
  judgementTag: better_than_legacy
```

判断：

- 这是当前核心回归样本，结果已回到预期的 `48` 个专业组目标口径。
- 供给充足且结果贴齐，说明 `majorGroup` 下“先按组生成，再补组内专业”的主链路已经稳定。
- 后续重点不是再修总数，而是继续增强组内安全垫与组内排序质量。

### 3.5 SD-01A / session 17

```yaml
sample:
  sampleId: SD-01A
  sourceType: real_session
  sessionId: 17
  province: 山东
  volunteerModel: major
  scoreBand: L1
  totalScore: 450
  rank: 312055
  strategyType: aggressive
legacy:
  targetTierCounts: {冲: 38, 稳: 28, 保: 30}
  preferredTierCounts: {冲: 38, 稳: 28, 保: 0}
v2:
  requiredTierCounts: {冲: 38, 稳: 28, 保: 30}
  candidatePoolTierCounts: {冲: 272, 稳: 130, 保: 0}
  initialTierCounts: {冲: 38, 稳: 58, 保: 0}
  orderedTierCounts: {冲: 38, 稳: 58, 保: 0}
  unresolvedRuleCodes: [safety_guard, ratio_distribution]
assessment:
  judgementTag: safer_but_supply_limited
```

判断：

- 保区候选池本身就是 `0`，因此新版不可能完成 `30` 个保区目标。
- 新版把保区缺口全部回收到了稳区，得到 `38/58/0`。这比“继续补冲”更可解释，也更符合风险收口方向。
- 但 `ratio_distribution` 仍未闭合，说明当前 `major` 模式在“保区完全缺失”场景下，还缺一套更明确的借位和展示说明策略。

### 3.6 SD-02A / session 7

```yaml
sample:
  sampleId: SD-02A
  sourceType: real_session
  sessionId: 7
  province: 山东
  volunteerModel: major
  scoreBand: M1
  totalScore: 477
  rank: 244345
  strategyType: traditional
legacy:
  targetTierCounts: {冲: 19, 稳: 38, 保: 39}
  preferredTierCounts: {冲: 19, 稳: 38, 保: 9}
v2:
  requiredTierCounts: {冲: 19, 稳: 38, 保: 39}
  candidatePoolTierCounts: {冲: 851, 稳: 204, 保: 9}
  initialTierCounts: {冲: 19, 稳: 68, 保: 9}
  orderedTierCounts: {冲: 19, 稳: 68, 保: 9}
  unresolvedRuleCodes: [probability_gap, ratio_distribution]
assessment:
  judgementTag: possible_regression_but_supply_limited
```

判断：

- 保区供给只有 `9`，明显低于目标 `39`，因此新版无法贴齐目标。
- 但与 `session 17` 相比，该样本不是“保区为 0”，而是“保区严重不足但不为空”；当前新版直接把剩余缺口都压到稳区，最终形成 `19/68/9`，结构偏移仍然较大。
- 这里既有供给原因，也有算法层面的进一步优化空间，尤其是“保区不足时稳区最多能借多少”仍需更细策略。

## 4. 当前结论

### 4.1 已确认可继续推进的部分

- `majorGroup` 初始化方案主链路可以继续作为当前版本基线。
- 组层数量统计、组层排序和组内补专业口径，已明显优于旧的扁平化处理。
- 只读仿真测试可继续复用到后续 `P1/P2`，不再依赖落库生成结果。

### 4.2 当前还不能直接下结论的部分

- `session 11` 需要先修复样本数据。
- `major` 模式下保区供给不足的借位策略还不能算最终版本，特别是 `session 7` 这类“保区少量存在但远远不够”的情况。

### 4.3 下一步建议

1. 先把 `session 11` 的候选池缺失原因查清，确认是历史脏数据还是初始化链路漏生成。
2. 针对 `major` 模式补一轮“保区不足借位策略”专项测试，至少覆盖：
   - 保区为 `0`
   - 保区极少但不为 `0`
   - 冲区过大、稳区中等、保区不足
3. 进入 `P1` 高分样本前，优先把 `major` 模式当前这类供给约束行为沉淀成显式规则说明。
