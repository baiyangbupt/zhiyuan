# Release 3.1.1 Feature Inventory

## 1. 版本定位

`3.1.1` 是 `prod-3.1.0` 上线后的对话质量和典型场景收敛版本。当前已冻结封版，后续只接受明确回退修复；结构性问题进入 3.2.0 profile 和主路径设计。

## 2. 当前待处理范围

### 2.1 压线风险咨询

- 修复“分数刚压本科线，别给我画大饼”被误回成确认边界话术的问题。
- 目标是走只读 Policy/风险解释，回答本科线、压线、保底、兜底、民办/专科和下一步建议。
- 不生成偏好、要求或方案调整确认卡。

### 2.2 专业组内局部操作

- 修复“专业组里只保留最稳的专业行不行”被误解为长期稳定就业意向的问题。
- 目标是归入 Plan/Policy，解释专业组内专业保留、组内安全垫、是否需要当前方案和具体专业组。
- 不生成职业/发展方向 Intent pending。

### 2.3 Full agent 长尾治理

- 继续基于 `turnObservability` 区分模型长尾、工具长尾、重复工具和误路由。
- 高置信只读政策和明确 Plan 局部操作可以优化语义入口。
- 对复杂问题仍保持质量优先，不用低质量模板换延迟。

### 2.4 审查修复和约束联动观察

- 继续检查审查/修复回复是否出现内部系统词。
- 继续验证 `only_keep / must_have / exclude` 采纳后是否能正确生成方案预览、确认执行、刷新方案和审查状态。

### 2.5 前端人工走查问题

- 确认采纳卡点击后，标题和按钮状态必须从“待确认”切到用户可理解的处理中/已采纳/已执行/已失效状态。
- 方案替换预览必须展示完整 `from -> to`，不能只展示被替换项或只展示补入项 ID。
- 补充志愿必须结合用户已确认和当前表达的 intent 做排序，先满足硬要求，再兼顾软偏好、推荐系数、录取风险、院校层次和专业相似度。

### 2.6 Benchmark 建设

- 将 `assets/` 下 autoexplorer、生产样本、长 prompt replay、真实转写和意图标注纳入 benchmark 事实来源。
- 建立固定回归、生产抽象模拟、真实样本抽取、长对话 replay、前端人工走查五层 benchmark。
- 高价值 autoexplorer issue 修复后晋级稳定回归 case，评估噪声和上下文 mismatch 不直接当产品缺陷。

### 2.7 结构性框架观察和 3.2.0 储备

- 3.1.1 不做大框架切换，不引入动态 Plan DSL、compiler 或新的主路由。
- 结构性问题先作为 3.2.0 后续优化储备记录；当前版本只在已有链路下修复明确 bad case，并保持确认卡、Java proposal/apply policy 和现有 Plan action 链路稳定一致。
- 当前修补仍遵守：不新增用户话术字符串路由、不新增多套确认卡路径、不让 Python 绕过 Java repair apply policy。
- 需要继续观察审查/修复、普通原子方案动作、复合用户目标之间的边界问题，并把无法低风险修补的内容移入 3.2.0 结构性优化。

## 3. 验证结论

3.1.1 封版前已完成：

- 历史积累场景三轮：`2283` step，`2209` pass，整体 `96.76%`；失败主要来自 full journey fixture/旧断言契约和结构性边界。
- current gate 三轮：`681` step，`664` pass，整体 `97.50%`；暴露的 P0-3/P0-4/P0-5 已完成窄修。
- P0 小修后小范围回归：
  - P0-3 constraint plan action：9/9。
  - P0-4 career intent：4/4。
  - P0-5 negative region：2/2。
  - review/repair 防串扰：9/9。
- 封版单元验证：
  - `zhiyuan-agent` 定向单测 662/662。
  - `zhiyuan-server` `UserGoalProposalBuilderTest` 通过。

封版口径：

- 不新增 runtime shadow、长期 bridge、新旧并行确认路径或用户话术字符串兼容表。
- P0-3/P0-4/P0-5 已按现有主协议和 formatter/normalization 窄修。
- negative-only 地域排除可以生成普通排除 pending；负向专业/院校若被模型误标成 `only_keep/must_have` 且没有明确正向范围，继续阻断，避免把“不要英语相关专业”误写成“只保留文学/外国语言文学类”。
- full journey fixture、费用类 preview 波动、pending+readonly 复合 turn、PlanQuery projection、特殊批次 schema 和性能长尾不在 3.1.1 继续扩修。

## 4. 原验证要求

修复完成前要求至少复跑：

- 3.0.3 真实对话衍生 88 case。
- 3.1.0 constraint plan action case。
- 3.1.0 review repair case。
- open quality、career direction、full journey 和生产抽象场景。
- autoexplorer 生产风格 follow/diverge 场景。
- 前端人工走查：确认卡、工作区刷新、审查详情、修复预览、方案/候选筛选联动。

验收口径：

- `failures=[]`。
- 典型业务场景不能因为极端玩笑输入牺牲修复优先级。
- 不新增用户话术字符串枚举式快路由。
- 不保留多套兼容执行路径。

## 5. 事实来源索引

| 文档 | 用途 |
| --- | --- |
| [release-3.1.1-dialogue-known-issues.md](./release-3.1.1-dialogue-known-issues.md) | 当前已摘出的 3.1.1 对话待处理问题 |
| [release-3.1.1-dialogue-benchmark.md](./release-3.1.1-dialogue-benchmark.md) | 3.1.1 对话 benchmark 和 assets 索引 |
| [release-3.2.0-structural-plan-framework-analysis.md](./release-3.2.0-structural-plan-framework-analysis.md) | 3.2.0 Plan 结构性框架问题、历史补丁和动态计划落地边界；3.1.1 仅作为后续储备 |
| [release-3.1.0-feature-inventory.md](./release-3.1.0-feature-inventory.md) | 3.1.0 基线能力和遗留 |
| [release-3.1.0-summary-and-upgrade-plan.md](./release-3.1.0-summary-and-upgrade-plan.md) | 3.1.0 发布收口 |
| [plan_action_orchestration_design.md](../zhiyuan-agent/docs/plan_action_orchestration_design.md) | 统一方案动作框架 |
| [semantic_layer_structure.md](../zhiyuan-agent/docs/semantic_layer_structure.md) | 语义分层边界 |
