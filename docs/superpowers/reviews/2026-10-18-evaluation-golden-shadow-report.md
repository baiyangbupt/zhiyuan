# J5.0 评价影子 Golden Diff 报告（2026-10-18）

对象：`ReviewEvaluationMapper`（旧 `ReviewStateDTO.checks` → 新
`PlanEvaluation.findings`）在真实会话快照上的影子对照。
**未切换**：运行时审查仍以旧 checks 为准；本报告只用于切换前的差异审计。

## 一、样本

| 会话 | 方案版本 | 审查来源版本 | 旧 checks | 新 findings | hardFeasible |
|---|---|---|---|---|---|
| 10041984（恢复态） | 5 | 4 | 14 | 15 | true |
| 10041984（缩水后快照，仅对照） | 11 | 7 | 14 | 15 | false |
| 900040 | 5 | 4 | 14 | 15 | false |
| 10041981 | 5 | 4 | 14 | 15 | true |
| 900038 | 4 | 3 | 14 | 15 | false |
| 900028 | 4 | 3 | 14 | 15 | false |
| 900018 | 4 | 3 | 14 | 15 | false |
| 10041983（32MB 候选池） | 17 | 16 | 14 | 15 | false |
| 900047 | 24 | — | 0 | — | 跳过（无审查结果） |

样本覆盖：大/小方案、32MB 大候选池、专业组模式、用户目标数量、软失败、
硬失败、旧快照（`severity` 字段尚未写入）与无审查结果。

10041983 读数：`safety_guard` fail/block、`count_missing`（hard fail/block）、
概率断层与高收费为软失败；14→15、无 pass/fail 漂移，大池 join 正常。

## 二、结构差异（全部可解释）

1. **数量校验拆分**：14 → 15。每个样本的 `count_validation` 都拆为
   - `count_validation_hard`：官方口径（block）；
   - `count_target`：方案目标口径（action/notice；无目标 → not_applicable）。
   `count_over_limit` 样本（10041984 缩水快照）hard=fail/block；
   `count_below_target` 单元测试 hard=pass、target=fail/action。
2. **pass → info**：所有通过的旧 check 统一映射 `displaySeverity=info`，
   不再保留旧默认 severity（action/block/notice）。这是四字段口径的预期变化。
3. **旧快照 severity 为空**：900040/900038/900028/900018/10041981 的旧 check
   没有 `severity` 字段（2026-10-16 之前的数据），新映射按注册表补齐：
   - safety → block；group_inner → block；count → block/action；
   - high_tuition/cooperative/probability_gap → action；
   - probability_inversion/edge_score → notice。
   不是规则变化，是旧数据缺字段。
4. **unknown 显式化**：缺生源省/缺官方数量的旧 check 是 `passed=true + level=warn`；
   新模型映射为 `unknown`（hard → block）。单测
   `missingProvinceIsUnknownNotPass` 钉住；本轮真实样本未触发。

## 三、结论差异

- 所有非数量 check 的 pass/fail 与旧 check 一致（测试逐条断言），没有出现
  “旧说通过、新说失败”的漂移。
- `hardFeasible` 的新读数与旧 check 的硬失败一致：
  - 900040/900038/900028/900018：`safety_guard` fail → false；
  - 10041984 缩水快照：`count_over_limit` + `group_inner_safety_guard` → false；
  - 10041981/10041984 恢复态：只有软失败 → true。
- 软失败（倒挂/断层/高收费/边缘分/非意向托底）不拉低 `hardFeasible`，符合设计。

## 四、切换门槛（J5.2 前必须满足）

- [x] 把 10041983（32MB 池）纳入 golden，确认大池下性能与 join 正确。
- [ ] `objectiveDelta` 由 ActionCompiler 生成并与预览命令一致（当前影子恒 null）。
- [ ] `ReviewState` 改为薄视图，审查/解读统一读 `PlanEvaluation.findings`。
- [ ] 旧 checks 与 findings 的字段映射固化为契约测试，禁止静默改映射。
- [ ] 任何阈值/权重变化 bump `probeRegistryVersion`，旧缓存失效。

## 五、落地物

- DTO：`EvaluationContextDTO` / `EvaluationEntryRefDTO` / `StructureVectorDTO` /
  `ObjectiveDeltaDTO` / `EvaluationFindingDTO` / `PlanEvaluationDTO` /
  `EvaluationProbeMetadataDTO`。
- 注册表：`EvaluationProbeRegistry`（15 probe，含 count 拆分）。
- 版本/缓存：`EvaluationVersion`（evaluationVersion 必含 evaluatedStateVersion）。
- 影子映射：`ReviewEvaluationMapper`。
- 测试：`EvaluationProbeRegistryTest`、`EvaluationVersionTest`、
  `ReviewEvaluationMapperTest`、`EvaluationGoldenShadowTest`（环境变量开关）。
