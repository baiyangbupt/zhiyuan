# 方案评价 Probe 注册表（J5.0 基线）

日期：2026-10-18。状态：**影子定义，未切换**。本文件是 J5.0 的权威输入：
现有 14 个审查 check 全量 probe 化，先做“旧 check → 新 finding”的可追溯映射和
golden diff，**不改变现有审查行为**；J5.2 再把审查/解读的输入切到
`PlanEvaluation.findings`。

## 一、边界

- 本批不新增规则、不改阈值、不改现有 `ReviewStateDTO.checks` 的输出。
- 新 DTO 只做影子映射；旧字段（code/severity/level/affected ids）保留。
- `PlanEvaluation` 只承载评价结果；`ReviewState` 后续变薄视图，不再承载规则。
- `only_keep` / `exclude` 允许方案收缩；数量判据只对“应保持总数”的目标生效。

## 二、Probe 全表（14 个旧 check → 15 个 probe）

| probe code | 来源 check | layer | ruleStrength | 允许 displaySeverity | metric | 阈值/判据 | 粒度 | fixability |
|---|---|---|---|---|---|---|---|---|
| `ratio_distribution` | 同名 | structure | soft | action | `tierCounts` / `unitTierCounts` | 冲占比 >40%、保 <20% 等；expected 按 `selectionTargetCount/requiredCount` 缩放 | unit（group）/ item（major） | preview_fixable |
| `safety_guard` | 同名 | hard | hard | block / notice(unknown) | `localSafetyUnitCount` + `userScore` | 生源省本省保底数；`userScore >= 580` 短路；缺省份 → unknown | unit / item | preview_fixable |
| `probability_inversion` | 同名 | structure | soft | notice | `ratioSequence`（unit.admissionRatio 或 item.admissionRatio） | 后项 ratio 高于前项 | unit / item | preview_fixable |
| `probability_gap` | 同名 | structure | soft | action | `adjacentRatioDelta` | 相邻差 > 8 | unit / item | preview_fixable |
| `count_validation_hard` | `count_validation` 拆分 | hard | hard | block | `actualCount` vs 官方口径 | 低于官方/硬性数量口径 | unit / item | preview_fixable |
| `count_target` | `count_validation` 拆分 | structure | soft | action / notice | `actualCount` vs `selectionTargetCount` / `requiredCount` | 低于目标 → action；目标内超额 → notice | unit / item | preview_fixable |
| `high_tuition` | 同名 | soft | soft（用户说“不得超过”时 hard） | action / notice | `tuitionPerYear` vs 预算/上限 | 条目学费超预算 | item | preview_fixable |
| `admission_limit` | 同名 | hard | hard | block | `riskFlags.admissionLimit` | 限报标签/资格 | item | preview_fixable |
| `special_enrollment` | 同名 | soft | soft | action | `riskFlags.specialEnrollment` | 特殊类型招生标签 | item | preview_fixable |
| `edge_score` | 同名 | structure | soft | notice | `userScore` 边缘区间 | 分数贴近边界 | structure | preview_fixable |
| `cooperative_program` | 同名 | soft | soft | action | `riskFlags.cooperativeProgram` | 中外合作标签 | item | preview_fixable |
| `group_inner_safety_guard` | 同名 | hard | hard | block | 组内每个 major 的 `admissionRatio` + `schoolEnrollRatio` | 组内无安全垫 | unit | preview_fixable |
| `major_group_safety_intent_alignment` | 同名 | soft | soft | action | 组内托底专业 vs `careerTypes`/意向 | 托底与意向不一致 | unit | preview_fixable |
| `plan_update_notice` | 同名 | soft | policy | info | 政策提示 | 不可优化消失 | plan | none |
| `adjustment_notice` | 同名 | soft | policy | info | 调剂提示 | 不可优化消失 | plan | none |

口径硬约束：

- `group_inner_safety_guard` 必须是 hard/block，不能按旧 `category=major_group_risk`
  批量映射成 structure。
- `count_validation` 必须拆成 `count_validation_hard`（hard/block）与
  `count_target`（structure/action|notice），不能硬塞 hard+action。
- `policy` 类（计划更新/调剂提示）不能被优化器“优化消失”，也不自动升级成约束。
- 缺输入（如缺生源省、缺 ratio）→ `result_status=unknown`，按未通过处理且
  `display_severity=block`（hard）或 `notice`（soft）；不得伪装 pass。

## 三、EvaluationContext（输入清单）

```text
EvaluationContext
  entries: list[EntryRef]
    level: unit | volunteer
    id: unitId | volunteerId
    position: int
    schoolName / majorName
    pathTier: 冲/稳/保/unknown      # 来自 OrderedItemDTO.tier
    schoolRatio: number | null       # schoolEnrollRatio，仅证据
    majorRatio: number | null        # admissionRatio，仅组内证据
    tuitionPerYear: int | null
    riskFlags: list[str]
  selectionTargetCount: int | null   # 用户确认目标
  requiredCount: int
  requiredTierCounts: dict[str,int]
  admissionMode: major | major_group | unknown
  sourceProvince: str | null
  userScore: int | null
  candidateSourceVersion: int | null
```

输入不可变清单：`evaluatedStateVersion + planContentDigest + candidateSourceVersion +
dataFreshnessState.dataVersion + objectiveModelVersion`。旧 findings 不得与新摘要
重新认证；任一不符即 stale。

## 四、StructureVector（输出指标，不反算 probe）

最小字段（后续按 probe 需要扩展，但只增不改语义）：

```text
StructureVector
  unitCount / itemCount
  tierCounts {冲,稳,保,unknown}         # item 口径
  unitTierCounts {冲,稳,保,unknown}     # unit 口径
  localSafetyUnitCount                  # 生源省保底
  adjacentRatioDeltaMax
  highTuitionCount
  cooperativeCount
  specialEnrollmentCount
  admissionLimitCount
```

## 五、PlanEvaluation / EvaluationFinding

```text
EvaluationFinding
  code
  layer: hard | structure | soft
  resultStatus: pass | fail | unknown | not_applicable
  ruleStrength: hard | soft | policy
  displaySeverity: block | action | notice | info
  fixability: none | preview_fixable | manual
  metric / threshold（结构化）
  summary
  affectedEntryRefs
  objectiveDelta | null
  suggestedCommand | null
  source = probe

PlanEvaluation
  planVersion              # evaluatedStateVersion
  evaluatedStateVersion
  planContentDigest
  candidateSourceVersion
  dataVersion
  objectiveModelVersion
  evaluationVersion
  status: completed | partial | unavailable
  probesRun
  structure
  findings                   # 所有跑过的 probe，含 pass
  hardFeasible
  objectiveDigest
```

合法组合：`pass → info`；`fail/unknown` 时 hard → `block`，soft →
`action/notice`，policy → `notice/info`。`fixedability` 独立，不由 severity 推断。
`pass` 的 finding 必须 `objectiveDelta=null`、`suggestedCommand=null`。

`hardFeasible = status=completed && probesRun>0 && 所有 hard finding resultStatus=pass`；
`unknown` 按未通过。

## 六、版本与缓存键

```text
objectiveModelVersion = hash(probeRegistryVersion, objectiveCompilerVersion, weightsVersion)
evaluationVersion     = hash(evaluatedStateVersion, planContentDigest,
                             candidateSourceVersion, dataVersion, objectiveModelVersion)
cacheKey              = tenant + session + evaluationVersion + overlay/mode + counterfactual
```

任何 probe/权重/目标层级变化必须 bump `probeRegistryVersion`。缓存有字节/条目双限；
缺任一输入不建立“部分评价”缓存。

## 七、Golden diff 方法

1. 选 5–10 个基准会话：大候选池、专业组模式、专业模式、学费预算、配额目标、
   数据缺口（缺 ratio/缺省份）各至少一例。
2. 对每个会话记录：`ReviewStateDTO.checks`（旧）、`EvaluationContext`、
   `PlanEvaluation`（影子）。
3. 逐条对照：旧 check → 1 或 2 个 finding；数量拆分、unknown、severity 变化
   必须逐条解释。
4. 差异只允许三类：字段表达变化、count 拆分、unknown 显式化；不允许阈值/结论漂移。
5. 差异报告通过后才允许 J5.1/J5.2 切换。

首批 fixture（单元测试层）：

- `pass_all`：14 项全 pass + 2 条 policy。
- `hard_fail`：safety/admission/count 硬失败。
- `unknown_ratio`：缺 ratio/省份 → unknown + block/notice。
- `count_split`：官方口径通过、用户目标不足 → count_target action。
- `policy_only`：仅两条 info。
