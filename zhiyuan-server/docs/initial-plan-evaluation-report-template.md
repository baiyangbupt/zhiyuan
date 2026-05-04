# 初始方案评估报告模板

## 1. 文档目的

本文档用于固定“初始方案生成评估”的统一输出格式，确保后续针对：

- 老版本优选结果
- 新版本初始方案结果
- 新旧差异分析

的记录口径一致。

配套输入来源：

- [initial-plan-evaluation-matrix.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/initial-plan-evaluation-matrix.md)
- [initial-plan-evaluation-sample-pool-v1.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/initial-plan-evaluation-sample-pool-v1.md)
- [initial-plan-evaluation-executable-samples-v1.yaml](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/initial-plan-evaluation-executable-samples-v1.yaml)

## 2. 单样本报告模板

每个样本建议固定输出以下 6 个区块。

### 2.1 样本信息

字段：

- `sampleId`
- `sourceType`
- `sessionId`
- `province`
- `volunteerModel`
- `scoreBand`
- `totalScore`
- `rank`
- `batch`
- `scoreGapToBatch`
- `gender`
- `strategyType`
- `subjectCombination`
- `majorIntentSummary`
- `regionIntentSummary`

建议格式：

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
  batch: 本科批
  scoreGapToBatch: 37
  gender: 男
  strategyType: traditional
  subjectCombination: [物理, 化学, 生物]
  majorIntentSummary:
    positive: [交通运输类, 电气类, 自动化类]
    negative: [纺织类]
  regionIntentSummary:
    positive: [广东, 广西]
    negative: []
```

### 2.2 老版本结果

字段：

- `legacyTargetTierCounts`
- `legacyReturnedTierCounts`
- `legacyPreferredTierCounts`
- `legacyRepresentativeItems`
- `legacyObservations`

说明：

- `legacyRepresentativeItems` 每个 tier 建议摘 3 到 5 个代表项
- `legacyObservations` 只描述结果事实，不做结论判断

建议格式：

```yaml
legacy:
  targetTierCounts:
    sprint: 9
    safe: 19
    protect: 20
  returnedTierCounts:
    sprint: 514
    safe: 102
    protect: 499
  preferredTierCounts:
    sprint: 9
    safe: 19
    protect: 20
  representativeItems:
    sprint: []
    safe: []
    protect: []
  observations:
    - 老版优选数量能贴齐目标数
    - 结果更多依赖 rank 和 preferred 标记
```

### 2.3 新版本结果

字段：

- `requiredTierCounts`
- `candidatePoolTierCounts`
- `initialTierCounts`
- `draftTierCounts`
- `orderedTierCounts`
- `summaryTotal`
- `unresolvedRuleCodes`
- `representativeItems`
- `v2Observations`

说明：

- 若 `majorGroup` 模式下展示，`summaryTotal` 按专业组统计
- `representativeItems` 也建议每个 tier 取 3 到 5 项

建议格式：

```yaml
v2:
  requiredTierCounts:
    sprint: 9
    safe: 19
    protect: 20
  candidatePoolTierCounts:
    sprint: 2439
    safe: 559
    protect: 3423
  initialTierCounts:
    sprint: 9
    safe: 19
    protect: 20
  draftTierCounts:
    sprint: 9
    safe: 19
    protect: 20
  orderedTierCounts:
    sprint: 9
    safe: 19
    protect: 20
  summaryTotal: 48
  unresolvedRuleCodes: []
  representativeItems:
    sprint: []
    safe: []
    protect: []
  observations:
    - 新版初始方案总数满足目标
    - 分层与目标数量一致
```

### 2.4 差异分析

字段：

- `structureDelta`
- `safetyDelta`
- `intentAlignmentDelta`
- `supplyDrivenExplanation`
- `ruleDrivenExplanation`

说明：

- `structureDelta` 看数量、tier、组层统计
- `safetyDelta` 看保底、断层、倒挂
- `intentAlignmentDelta` 看专业/地域偏好体现
- `supplyDrivenExplanation` 用于解释供给不足导致的变化
- `ruleDrivenExplanation` 用于解释审查规则前置导致的变化

建议格式：

```yaml
diff:
  structureDelta:
    - 新版从按 preferred 扁平透传，变为按目标 tier 组装
  safetyDelta:
    - 新版保底更稳定
    - 梯度断层更少
  intentAlignmentDelta:
    - 新版仍保留理工和地域偏好
  supplyDrivenExplanation:
    - 当前保区供给充足，因此无需向稳借位
  ruleDrivenExplanation:
    - 新版前置执行 safety_guard 和 probability_gap 修正
```

### 2.5 合理性判断

字段：

- `structureAssessment`
- `safetyAssessment`
- `intentAssessment`
- `overallJudgement`
- `judgementTag`

判定标签统一为：

- `better_than_legacy`
- `roughly_equal`
- `safer_but_more_conservative`
- `more_intent_aligned_but_riskier`
- `possible_regression`

建议格式：

```yaml
assessment:
  structureAssessment: 合理
  safetyAssessment: 合理
  intentAssessment: 基本合理
  overallJudgement: 新版优于老版
  judgementTag: better_than_legacy
```

### 2.6 风险与后续动作

字段：

- `remainingRisks`
- `followUpActions`

说明：

- 若发现疑似退化，这里必须明确后续动作
- 若只是供给原因，也应显式写明

建议格式：

```yaml
next:
  remainingRisks:
    - 高分段样本仍需扩大
  followUpActions:
    - 继续补 H2 女生样本
    - 对 majorGroup 组内安全垫做专项复核
```

## 3. 汇总报告模板

除单样本报告外，还需要聚合结果。

### 3.1 省份汇总

每个省输出：

- 样本数
- `major / majorGroup` 分布
- 低中高分覆盖情况
- 新版优于老版的样本数
- 存在疑似退化的样本数
- 主要问题

建议格式：

```yaml
province_summary:
  province: 河南
  sampleCount: 16
  volunteerModel:
    major: 0
    majorGroup: 16
  scoreBandCoverage: [L1, L2, M1, M2, H1, H2]
  judgement:
    better_than_legacy: 10
    roughly_equal: 4
    safer_but_more_conservative: 2
    possible_regression: 0
  mainIssues:
    - 高分激进样本仍需观察冲区质量
```

### 3.2 模式汇总

按 `major` 和 `majorGroup` 分别输出：

- 结构稳定性
- 审查规则前置收益
- 主要问题

### 3.3 分数段汇总

按 `L1/L2/M1/M2/H1/H2` 输出：

- 新版是否过于保守
- 是否存在供给不足导致的 tier 借位
- 是否在高分段仍保持推荐质量

### 3.4 策略型汇总

按：

- `traditional`
- `cautious`
- `aggressive`

分别输出：

- 目标 tier 数是否落地
- 无保区供给时的借位是否合理

## 4. 建议的最终产物

最终建议形成以下三份材料。

### A. 样本明细 YAML 或表格

一行一个样本，便于追踪。

### B. 人工分析版报告

针对异常样本写成短文说明，便于产品和算法共同判断。

### C. 汇总结论页

直接给出：

- 哪些省份表现稳定
- 哪些模式仍需优化
- 哪些场景相对老版有明显收益

## 5. 当前下一步

按当前文档体系，下一步执行顺序建议为：

1. 先跑 P0 真实样本
2. 再补跑 P1 高分样本
3. 最后跑 P2 负向约束样本
4. 按本模板沉淀首轮报告
