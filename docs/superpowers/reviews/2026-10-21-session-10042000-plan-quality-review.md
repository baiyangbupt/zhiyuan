# 会话 10042000：方案质量与审查链路复核

日期：2026-10-21。对象：3201 对应环境中实际保存的 `planningState.version=5`，
审查时间为 `2026-10-21T11:42:52.742+08:00`。本轮只读取存量状态、候选池、消息和运行日志，
并在临时目录调用当前构建产物的纯内存方法复现；未重跑真实会话审查、修改方案或调整运行开关。

## 结论

不是只有旧审查文案需要调整。已确认生成排序、资格事实落地、风险识别、解读判定、
意向来源五个方面的问题。可以先暂停旧审查的用户结论和修复建议，但不能把事务后置校验、
容量/选科等真实约束、版本守门和确认链一起关闭，也不能把“暂停”投影为“全部通过”。

新求解器实际上参与了本次生成：11:42:46 的 prepare 日志记录 staged solver 从 600 个候选
中选择 45 组。不能仅凭最终 `generationMode=legacy_import` 就断定仍是旧生成器。
该字段没有随冻结结果应用准确反映生成来源，本身也是观测元数据问题。

## 已确认的重要问题

### P0：明确没有专项资格，仍生成地方专项，审查漏报

- 用户消息明确说“没有专项”。实际方案第 36 组为“衡阳师范学院第442组(地方专项)”，
  所选专业包括“法学(地方专项)”等 5 条。
- 当前约束中没有对应的资格排除，`special_enrollment` 与 `admission_limit` 都为 `pass`，
  全局 `hardFeasible=true`。对本会话而言，这个结果不能解释为报考资格已核验。
- 归一后的 `reasonCodes/riskFlags` 主要是学校描述和排名分数说明，没有专项风险标记。
  `EvaluationContextBuilder.riskTags` 没从校名/专业名提取专项；
  `ReviewEvaluationMapper.matchesRiskEntry` 的专项分支只查标签，不查名称。
  离线调用该方法，在名字明确带“地方专项”的真实条目上仍返回 `false`。
- 相关代码：`EvaluationContextBuilder.java:165`、`ReviewEvaluationMapper.java:485`、
  `PlanningStateService.java:12135`、`RepairCandidateEligibility.java:27`。
- 修复必须覆盖“用户资格事实 → 可执行约束 → 候选资格 → 方案校验”；只给 review
  补一个名称关键词，还不能保证后续重生成不再选入不符合资格的项目。

### P1：新生成方案的档位顺序反了，且被当作正常冻结应用

- 保存的实际顺序为第 1–13 组“稳”、14–32 组“保”、33–45 组“冲”。
  这是普通新方案，当前没有用户优先规则或 pinned 项要求这种顺序。
- `CandidateSnapshotBuilder` 的 stable order 来自意向分/综合分等排序；
  `StagedDeterministicPlanSolver.orderSelected` 按 stable order 首次出现的档位依次建桶，
  没有为新方案使用明确的档位顺序。用真实选中的 45 组调用当前方法，复现得到
  `[stable, protect, sprint]`。
- 相关代码：`CandidateSnapshotBuilder.java:497`、`StagedDeterministicPlanSolver.java:949`。
- 修复应区分“初始生成的默认顺序”与“维护存量方案的保序语义”。不能全局无条件重排，
  否则会破坏用户手动顺序、pinned 项和显式优先规则。

### P1：审查与解读的顺序异常判定互相矛盾

- `orderedPlanState.summary.sequenceOk=false`；审查记录 11 处倒挂、12 处断层。
  助手却同时说“系统没有判定为顺序异常”。
- `PlanAdmissionInterpretationService.hasOrderAnomaly` 只看“第一条保底是否早于
  第一条冲/稳”，不能识别“稳 → 保 → 冲”。对实际 45 组调用返回 `false`，与消息一致。
- 相关代码：`PlanAdmissionInterpretationService.java:365`。
- 顺序异常、方案可解释性和审查结果应消费同一份结构判断；不能每个消费者各写一套。

### P1：用户尚未确认专业意向，却产生“非意向专业托底”结论

- `explicitProfile.positiveMajors`、硬包含专业、软偏好专业、覆盖目标和优先规则均为空。
  然而 `major_group_safety_intent_alignment` 对 4 组报“非意向专业托底”。
- 该规则把候选 `preferred` 和 `intentScore` 差值当作已确认意向依据。对实际状态调用
  `reviewMajorGroupSafetyIntentAlignment`，在用户正向专业数为 0 时仍得到 `passed=false`、
  `affectedUnitIds=4`。
- 相关代码：`PlanningStateService.java:12248`。
- 无明确用户意向时只能描述“系统匹配分差异”，不能声称偏离用户意向。
  明确意向、模型建议和默认排序必须保留不同来源。

### P1：方案定位未收敛，助手又把自己的建议归因给用户

- 这份方案为 45 组 / 186 个专业，覆盖工学、医学、经管、法学等多个门类。
  电气类有 16 条，但医学也有 22 条，前 3 组都是医学相关院校专业组。
- 电气方向最初是助手推荐；用户只说“可以出一版方案吧”，没有明确选中“电气为主”。
  生成前助手也说明本版“不设专业方向硬限制”。之后再说“和你之前说的电气方向对不上”，
  是把助手建议错误归因为用户偏好，不能据此自动补写电气硬约束或重做方案。
- 生成前应说明本版是不限专业的探索草案还是有主线的正式方案，缺少意向时先给可比较的
  方向选择或明确标为探索版。不能用“凑满容量 + 默认得分”替代适配目标的确认。

## 为什么不能直接关现有修复开关

- 目前未找到独立的审查暂停开关。`review.fix.command.enabled` 是修复命令灰度位，
  不是审查总开关；关闭它不能让旧检查停止运行。
- `runReviewWorkflow` 仍执行“审查 → 修复建议生成”；部分方案命令强制要求
  `regenerateOrderedPlan=true` 和 `rerunReview=true`。直接删掉重审或把结果伪造成成功，
  会破坏既有确认/执行契约。
- 前端仍读取 `reviewState.checks`，summary 和部分消费者已读取 findings；
  暂停必须同时覆盖工具、工作台和对话投影，不能仅把一个按钮藏起来。
- 相关代码：`PlanningStateService.java:1115`、`PlanningStateService.java:3730`、
  `PendingPlanningCommandBizService.java:1563`、`WorkspacePanel/index.tsx:762`。

## 建议推进顺序（待确认，未实施）

1. **止血范围**：提供可回退的独立暂停状态，暂不把旧经验审查当作用户侧质量结论，
   不产生/执行旧 review 驱动的修复建议；存量卡显示暂停或结果不可信，不能显示通过。
   保留命令完整性、幂等、版本与冻结结果后置校验；报考资格硬条件需要同时补齐。
2. **修真实生成缺陷**：先修已否认的专项资格过滤、初始方案档位顺序、解读漏判，
   并用本会话数据建立回归。没有用户意向时停用“非意向偏离”判断，不擅自补写电气偏好。
3. **重建质量评价口径**：资格可行性、已确认偏好适配、结构建议、未知/缺失证据分别输出，
   明确本版探索/正式定位。固定录取率差值 8、本省保底数量、2 万学费阈值等经验策略
   不应未经用户目标和数据适用性判断就等同于好坏或安全保证。
4. **再开启建议执行**：评价结果与解读、前端统一为同一来源，验证规则修复后再恢复
   review → proposal → pending → apply，保持预览冻结、确认与执行幂等契约。

## 复现证据边界

临时目录 `/tmp/zhiyuan-session-10042000-review/` 中保存私有只读快照和一次性诊断程序。
诊断使用当前隔离构建的 classpath，直接调用原有排序、解读和风险/意向规则；未为证明
问题重写算法，也未启动新后端或修改业务状态。这是调查证据，不是已修复或全链路验收。

## 后续设计核对：专项链并非完全缺失

- Java 已有 `CreateSessionReq.specialPlan`，旧 `VolunteerFilterChain` 也能在值为 false
  时过滤本例“地方专项”。直接调用现有过滤方法确认可识别本例，不能归因为后端完全没有字段。
- 真正断点包括：用户事实未写入成绩；Python `ScoreUpdateRequest` 拒收 `specialPlan`；
  Java `isEmptyScoreUpdateRequest` 不认可专项单独更新；确认 summary 未展示该资格。
- 还有补丁语义缺陷：仅构造 `specialPlan=false` 增量，通过现有 merge 后，已有
  `filterType=3` 会被 DTO 默认值覆盖为 `2`。这不是专项关键词检查可以解决的问题。
- 设计需同时覆盖资格预览/确认与入口实际字段集；不把用户旧消息直接迁移为已确认事实。
  详见 `../specs/2026-10-21-plan-quality-and-review-containment-design.md` 及对应设计审查记录。

上述核对仍为代码阅读/离线诊断，未改变会话 `10042000` 或实际运行的审查模式。
