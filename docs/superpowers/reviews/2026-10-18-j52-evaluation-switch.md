# J5.2 评价接入（第一刀）验收记录（2026-10-18）

## 这一刀做了什么

1. **审查产出统一评价**（J5.2a）：
   - `ReviewStateDTO` 新增 `evaluationVersion / objectiveModelVersion /
     evaluatedStateVersion / evaluationStatus / probesRun / hardFeasible /
     findings`；`checks` 暂保留兼容。
   - `EvaluationContextBuilder` 从方案状态投影不可变输入（entries、目标数量、
     候选源版本、dataVersion、planContentDigest）。
   - `runReviewInternal` 在 checks 生成后调 `ReviewEvaluationMapper`，把同一份
     检查结果投影成 15 个 findings；评价失败降级为 `unavailable`，不影响审查。
   - 快照 `preferences` 增加 `reviewEvaluationStatus / reviewEvaluationVersion /
     reviewHardFeasible`（不塞 15 条 findings）。
2. **解读消费 findings**（J5.2b）：
   - 解读门面把 `reviewState.findings` 传给 J2a 服务；
   - fail/unknown findings 按 `affectedEntryRefs` 关联到对应情景 drivers；
     hard/policy 未通过项进全局 caveats（去重、最多 4 条）；
   - pass/not_applicable 不产生提醒；不输出 metric/概率数字。

## 真栈读数

- 900053（10041984 状态）：`POST /session/review/run` → 版本 6、
  `evaluationStatus=completed`、`probesRun=15`、`hardFeasible=true`、
  findings 15 条、checks 14 条、evaluationVersion 已写入；
  interpretation.preview 的 base 落点仍为第 14 个潍坊学院（无硬提醒时
  drivers 只有结构档位）。
- 900054（900028 状态，safety_guard 硬失败）：review 后
  `hardFeasible=false`、findings 15；interpretation.preview 的 caveats 出现
  `审查：本省保底不足（本省保底志愿数量不足）`，no_safe 情景保留结构缺口说明。
- 两个克隆会话测试后已删除。

## 兼容与边界

- `ReviewState.checks` **未删除**：旧 UI、旧工具、旧快照仍按 checks 工作；
  summary 仍按 checks 统计（14），因此 findings 的 15 条（count 拆分）暂不改
  用户面计数。切 summary/去 checks 需单独一刀，避免一次改两个消费者。
- 评价失败（如映射非法）只降级 evaluation，不阻断 review；日志记 session+错误。
- 解读在没有 findings 的旧会话上行为与旧版逐字一致。

## 第二刀：summary 派生 + objectiveDelta → ActionCompiler（同日）

- `recalculateReviewSummary` 优先从 findings 派生：total = 实际 probe 数（15），
  pass/not_applicable 计通过，block → risk，action/notice → warn，info 单列；
  无 findings 的旧会话回退 checks 统计（14），行为不变。
- 未通过/未知 finding 带 `objectiveDelta`：策略来自 `ReviewRuleRegistry` 默认修复
  策略，`count_over_limit` 纠正为 `remove_risk_items`；affected refs 按策略归入
  add/remove/reorder targets。
- `ActionCompiler` 从 delta 编译 `CompiledActionDTO`，填 `suggestedCommand`；
  当前 `executable=false`（只产意图，执行仍走 proposal→pending→确认），
  pass/not_applicable 的 delta/suggestedCommand 必须为 null。
- 真栈：900055 审查后 `summary.total=15`、passed 11 / warn 3 / risk 1 / block 1；
  `safety_guard` fail 的 delta 为 `add_safety_items`，compiled
  `{strategy=add_safety_items, executable=false}`；count hard pass 的 delta=null。

## 第三刀：修复提案以 findings/delta 为入口（同日）

- `generateFixProposals` / `buildFixProposalState`：有 findings 时只从
  **fail/unknown 且 delta 有 strategy** 的 finding 生成候选；同一 sourceCheck
  只出一条（count 拆分先到先得）；旧会话无 findings 时回退 checks 循环。
- `RepairProposalStateBuilder.buildBaseProposal` 新增 strategyOverride：
  delta.strategy 作为权威；actions/dry-run/postcondition 仍复用既有构建器。
- `ReviewStateDTO.checks` 标注为兼容字段（新代码读 findings；删除待消费者迁移）。
- 真栈（900056，先 review 再篡改 probability_gap 的 delta 策略）：
  `fix-proposals/generate` 返回的 proposal strategy=`sort_by_probability`
  （不再是 check 默认的 `fill_probability_gap`），证明入口已切到 delta；
  proposal 因动作构建器不支持该策略标 blocked（预期，未执行）。
- 单测：`PlanningStateServiceTest#fixProposalStrategyComesFromObjectiveDeltaWhenEvaluationExists`
  钉住“delta 覆盖 check 默认策略”。

## 下一步（J5.2 剩余）

- [x] summary 改由 findings 派生（无 findings 的旧会话回退 checks）。
- [x] findings 的 `objectiveDelta` 由 ActionCompiler 编译成意图
  （`executable=false`，尚未接线到修复提案生成/执行）。
- [x] `checks` 标注兼容字段；`generateFixProposals` 以 findings/delta 为入口。
- [ ] 删除 checks 字段（需旧 UI/旧工具/回退路径全部迁移后）。
- [ ] 解读卡按 hard/soft 分组展示 findings（当前只进 caveats/drivers）。
- [ ] 旧会话回填：只有重跑审查才会产生 findings（不做静默批量重算）。
