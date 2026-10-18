# 用户旅程、对话控制与录取解读设计（v6）

日期：2026-10-18。代码基线：`616464c`（`wip/2026-09-28-p2-write-loop-green`，
工作区含 2026-10-17/18 add_units EXPAND 未提交改动）。
状态：v6，已按全链路评审
`docs/superpowers/reviews/2026-10-18-plan-conversation-system-review.md` 收口：
**确认执行底座保留；先统一“完整要求 → 约束 → 预览 → 确认 → 执行 → 复查”的语义，
再按 A–F 批次接入代码。** J2a 已按 F04 降级为结构/条件情景（无 likelihood/slipRisk
预测）；J2b 暂缓，等 Batch A 完成。

配套语义权威表：`docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`
（同一语义只留一个 owner；明确哪些合并/删除、哪些保留；含 BLOCK 执行边界）。

**v5 修订摘要（语义权威审查）：**

- 版本：当前只有一个 `stateVersion`（=planningState.version=workspace.version=
  snapshotVersion=sourceVersionGuard，review/偏好/候选生成都会 +1）；新增
  `planContentDigest`，`evaluationVersion` 用 `evaluatedStateVersion +
  planContentDigest`，避免旧 findings 被认证成新。
- 评价：新增 `EvaluationContext`（probe 输入）；`StructureVector` 只做输出；
  J5.0 必须列全 14 个 probe 并做旧/新 golden diff；J2a 不建适配器。
- J1a：`stale` 按 flag 值/reason 判，不按 `staleFlags` 非空；`pendingStatus`
  要 active+applying 确定性查询；`hasPlan` 要 items ∪ units；`taskIntent` 先定
  映射再测试。
- 删除 `$ref` 伪前提；`candidatePoolRef` 由 `loadPlanningStateReadOnly` 回填。
- 修正 ID：`unitId` 是 `volunteerId` 第一个 `_` 前段；`volunteerId` 不保证固定
  两段。
- 修复 `must_include_scope`（已有→no-op、未满→补入、满→最多换 1 组）、
  `targetCount/requiredCount`、tierQuota 读取、持久化生命周期等口径。
- 明确“本批不删持久化字段”：ReviewState/checks、OrderedUnitDTO.admissionRatio、
  PlanGoalTypeValue、RepairProposalTaxonomy 的执行协议等，先停写/读适配。

**v4 修订摘要（审查与优化合并）：**

- 审查不再是零散规则集合，而是 `PlanEvaluator` 对同一 `StructureVector`/
  `ObjectiveModel` 的评价输出；`ReviewStateDTO.checks` 只是当前实现，未来统一为
  `PlanEvaluation.findings`。
- 优化器与审查共用：`CandidateSnapshot`、`IntentModel`、`ObjectiveCompiler`、
  `StructureVector`、`PlanEvaluation`；优化器做搜索，审查做评价。
- 审查 finding 带 `objectiveDelta`/`suggestedCommand`，走同一个 `PlanCommand`
  与后置条件；不再有独立的“修复规则链”。
- J2a/J2b 的解读服务改为消费 `PlanEvaluation`（MVP 用 `ReviewStateDTO` 适配），
  不直接依赖零散 checks；J5 替换适配器内部，不改解读接口。
- J5 路线图合并原阶段 5（审查闭环），改为阶段 0–6 的“统一目标/评价/优化”。

**v3.1 修订摘要（对应 v3 审查窄口）：**

- `slip_risk` 规则 3 与真值表统一：所有保 ratio 缺失 → `高`（行 6/7/10 改高）；
  规则 4 补“至少一条保已知”前提；真值表 13 行全部可判定。
- 删除 `sourceLevel=computed` 证据签发：MVP 不新签计算证据，`evidenceRefs` 只引
  上游证据，推演结论走 `caveats/reasonCodes`；不伪造。
- 计划 J2a 对齐 spec：`pathTier` 以 `OrderedItemDTO.tier` 为准；`base` 跳过
  unknown；`slip` 低不输出、中/高/无法判断输出；13 行 fixture；unit/major 两模式。
- N4 收尾：删除“明细走 artifact”残留；payload 带 `caveats` 文本；事件在
  `turn.completed` 前发射；卡片字段与 payload 对齐。
- N1 收尾：`StatePatch._validate_change_paths` 允许 `journey`；注入预算含
  `plan_version`；N6 补 `TOOL_LABELS`/`TOOL_CONTRACTS`。

**v3 修订摘要（对应 v2 审查 N1–N7）：**

- N1：补 agent 合同/投影/注入：`contracts.py` `journey` 字段、`snapshot.py`
  `build_snapshot`/`diff_snapshots`、`service.py` 注入紧凑 `JourneyContext`。
- N2：重写 §8.3 规则与真值表：`unknown` 跳过；`base` 只可能是稳/保；`upside`
  部分 ratio 缺失取最高已知、全缺取最早；`slip_risk` 互斥穷尽；`dataCompleteness =
  min(tierCoverage, ratioCoverage)`。
- N3：删除结论/验收脚本里的 `system.action`、自动生成与“最可能”；改为现有
  `conversationAction.result` + “基准情景”。
- N4：解读卡改为**有界事件 payload**，不再声称 artifact 存明细/前端按 ref 取数。
- N5：工具改名 `planning.interpret_admission`，避免 `plan.` 只读命名冲突。
- N6：补 `TOOL_INPUT_SCHEMAS`/`TOOL_DESCRIPTIONS`/`TOOL_KINDS`/
  `TOOL_OUTPUT_SCHEMA.kind`/`server.py`/`test_domain_mcp_tools.py`。
- N7：J4a 前 scope/学费一律“仅本次”，删除“默认持久/后续生效”的规范性承诺。

**v2 修订摘要（对应审查 B1–B9）：**

- B1：拆分 `pathTier`（校线档位，来自 `schoolEnrollRatio`，`<=50/<=70/>70`）与
  `majorAdmissionRatio`（专业级证据）；不再“冲突判 unknown”；方案条目按
  `volunteerId` join 候选池。
- B2：`JourneyContext` 改为 Java 快照新增紧凑 `journey` 块 + agent 派生；
  `statePhase`（pre-turn）与 `taskIntent`（post-model）分离，删除不存在的
  `last_action`。
- B3：场景算法改为**按实际顺序扫描** + 确定性真值表；MVP 反事实只支持
  remove；历史只作证据、不参与落点判断；明确 unit/major 粒度。
- B4：scope/学费持久化列为 J4.0 前置；未落地前触发目录/卡片一律标“仅本次”。
- B5：触发目录增加“载体/状态/失败行为”三列；替换不存在的工具名；planned
  动作全部标出；golden 改为契约校验 + 可选 live eval，不冒充模型回归。
- B6/B8：**不新增 `system.action`**；先复用/扩展现有 `conversationAction.result`
  回执。解读卡走“工具结果 → 有界 `interpretation.preview` 摘要事件”，
  需补服务端 `EVENT_TYPES`/reducer/体积限制；卡片排在 J2c。
- B7：承认 Java `prepareOnce` 的 supersede 策略；状态机降级为每回合派生的
  建议状态，不建模可恢复的 8 状态机。
- B9：删除“`review_read` 修法”这段 no-op；`plan-final-review` 暂保持模型基于
  读工具的人工审查；J2 解读直接引用现有 `reviewState.checks`，J5 后再换
  `PlanEvaluation`。

审查记录：`docs/superpowers/reviews/2026-10-18-journey-control-and-admission-interpretation-review.md`。

关联文档：

- `docs/superpowers/reviews/2026-10-17-plan-generation-and-fill-analysis.md`
  （候选→方案的一致性、优化器目标与现状断层）
- `docs/superpowers/specs/2026-10-17-plan-action-contract-design.md`（v6，add_units 契约）
- `docs/superpowers/plans/2026-10-17-plan-action-contract.md`（S1–S10 实施切片）

## 〇、结论（先看这一段）

当前系统有三个互相独立的问题，不能只靠再加一个工具解决：

1. **动作是散的**：模型按技能和提示词自行选动作，后端只做零散校验；用户同一句话
   可能被解释成查询、提案或确认，缺少一张“用户触发 → 目标 → 动作 → 卡/回执”的
   统一目录，也缺少对话状态机来约束“这一轮到底能做什么”。
2. **优化器是散的**：生成、补足、加入、替换、重排各自走不同的候选来源、排序键和
   目标函数；“结构最优”没有统一定义，也没有在回执里向用户解释取舍。
3. **方案结果不可解释**：方案生成/审查是系统内部事件，对话里看不到改了什么；
   用户也看不到“按现在这个方案，我大概会被哪里接住、哪里可能滑档”。

本设计把三件事收成一条链：

```
用户旅程（JourneyContext）
   → 触发目录（Trigger Catalogue）
   → 目标拆解（IntentFrame）
   → 动作编译（ActionRequest / 唯一优化器）
   → 回执（Receipt + StructureVector）
   → 录取解读（LandingScenario，演绎而非承诺）
   → 下一轮建议（闭环）
```

第一期不追求“大一统重构”，而是先落三层可验证的契约：

- **J1 旅程/控制层**：派生 `JourneyContext`，建立触发目录与对话状态机，不新增写工具。
- **J2 录取解读层**：只读的 `planning.interpret_admission`，用现有方案/候选/往年位次做
  确定性场景推演，输出 `LandingScenario`，不编造概率。
- **J3 回执扩展**：不新增 `system.action`；扩展现有 `conversationAction.result`
  的 `origin/actionType/scope/receipt` 摘要，仍然一张卡。

统一优化器（J5）和风险姿态/目标优先级（J6）作为后续纵切，复用同一套
`IntentFrame`/`ActionRequest`/`Receipt`，不再另起炉灶。

## 〇·五、统一方案处理协议（v6，全链路评审收口）

全链路评审：`docs/superpowers/reviews/2026-10-18-plan-conversation-system-review.md`
（F01–F09）。结论：**确认执行底座保留；v5 不能直接照计划继续实现。** 本节是
三份文档共同遵守的协议；与旧章节冲突时以本节为准。

### 0.5.1 核心原则

> **“优化/调整”默认做满足本次完整要求的最小必要变更；“重新做一版”才扩大修改
> 范围；所有写操作仍先预览确认。**

三条限定：

1. **完整要求优先于最小变更**：不能为了少改而丢掉硬要求、预算上限或排除条件。
   目标顺序：硬约束 → 本次完整要求 → 最小必要变更 → 结构底线 → 软偏好提升。
2. **一轮一个待确认变更集 ≠ 一轮只能理解一个意图**：复合要求要一次解析、一次
   冲突检查、一个原子预览；不能先加入、下一轮再补限制。
3. **最小变更不适用于首建**：首建是在已确认口径下选集/排序；“重新做一版”才
   显式放宽变更预算。精确加入/删除/移动/锁定走受限编辑，生成/补足/重优化才走
   搜索；统一的是输入、目标解释、校验、预览、回执，不是强迫所有动作共用一个
   solver。

### 0.5.2 统一闭环

```
用户消息 + 受信快照
  → IntentDraft（完整要求：对象/强度/范围/有效期/未解决项）
  → 作用域与指代解析 + 约束冲突检查
  → 只读分析/比较/反事实（不入 pending）
  → 动作编译 + 规划器（精确编辑 or 搜索）
  → 同一输入基线的评价 + 独立后置校验
  → 冻结变更预览（完整 diff + 不改变 + 代价 + 输入凭据）
  → 明确确认 / 修订 / 取消
  → 现有事务执行 + operationId 幂等回执
  → 当前基线的复查 / 结构条件情景
  → 继续剩余任务或收尾
```

### 0.5.3 F01–F09 收口决定

| 编号 | 决定 |
|---|---|
| F01 复合要求 | 引入 `IntentDraft` + `ChangeSet`：一次解析全部要求；本轮最多一个待确认业务变更集；同时生效的硬要求进入本次前置校验；不支持就阻断/协商分步，不先执行可能违反它们的子动作；剩余项写入有界任务记录 |
| F02 有效期 | 先建立“行为真值表”（写到哪、哪些读路径、是否重排、何时失效）；卡面按真实行为写，**删除“J4a 前一律仅本次”的一刀切**；目标态区分“本次调整/本会话后续规划”；学费只保留一个 owner；未确认草稿不成为有效约束 |
| F03 确认/纠正 | 否定、纠正、新增条件优先于确认；内容变了就重新预览，原卡不执行；删除“用户没反对即确认”；只在对象唯一、内容未变、有效 pending 时识别明确肯定；取消只对未执行提案，applying 不可取消 |
| F04 录取解读 | 只做**结构与条件情景**：首个稳/保位置、冲档最高校线率位置、最后保底位置、保底结构覆盖、顺序异常、数据缺口；删除/停用未验证的 `likelihoodBand` 与整体 `slipRisk`；数据不足、结构覆盖不足、资格失败分开说；不默认把方案问答引向预测落点 |
| F05 评价分类 | 一个 severity 不再承担四种职责：拆 `resultStatus(pass/fail/unknown/not_applicable)`、`ruleStrength(hard/soft/policy)`、`displaySeverity(block/action/notice/info)`、`fixability`；预算上限/资格/政策上限按用户强度进硬校验；安全启发式/专业偏好/政策告知分开 |
| F06 目标排序 | 统一：硬约束 → 完整要求 → 最小必要变更 → 结构底线 → 软效用；精确编辑走确定性逻辑，生成/补足/重优化走搜索；变更预算/容差/tie-break 在预览时冻结并写入回执 |
| F07 缓存 | 个性化缓存必须带受信 tenant/session + 候选输入指纹 + overlay/mode + 反事实参数；按字节和条目双限；公共不可变数据才可共享 |
| F08 输入凭据 | 评价/预览/解读绑定不可变输入清单（方案摘要、有效目标、画像/政策、候选来源/overlay、数据快照、算法版本）；旧 findings 不能和新摘要拼成“新版本”；写执行继续 CAS，不跨版本套用旧确认 |
| F09 交付顺序 | 先语义/保护边界（A），再当前路径闭环（B），再评价输入/规则（C），再按动作接规划器（D），再优化策略（E），最后解读增强（F）；解读卡不等于方案处理闭环完成 |

### 0.5.4 六个职责边界

| 边界 | 负责 | 不负责 |
|---|---|---|
| 权威上下文 | 读取并标识画像、政策、方案、有效约束、候选来源 | 推断用户想要什么 |
| 对话意图与任务 | 解析完整要求、指代、歧义、依赖和未完成项 | 把未确认偏好写成有效业务约束 |
| 命令编译与规划 | 把受支持意图变成受限变更，选择精确编辑或搜索 | 越过授权“顺便优化” |
| 评价与后置校验 | 共享事实和规则定义，检查结果与变更边界 | 因 warning 自动改变用户目标 |
| 预览与执行 | 冻结完整 diff、绑定确认、事务执行、幂等回执 | 确认后偷偷用新输入重解另一版 |
| 解释与续接 | 基于当前评价和真实回执说清取舍、缺口、下一步 | 把结构信号说成录取预测 |

### 0.5.5 TaskDraft / ChangeSet

- `TaskDraft` 是**有界任务记录**（会话持久化元数据，可复用现有载体）：
  `taskId/原始回合/IntentDraft/剩余项/关联 pending/operation/status`。它不是第二份
  方案，不复制 pending 可写状态。
- `ChangeSet` 是本轮唯一待确认业务变更集：可包含多个约束/目标，但服务端必须能
  真实支持全部操作、完整预览、整体回滚和后置条件完整；不支持时不得用单动作卡
  冒充复合事务。
- **`ready` 必须 `atomic=true`**：只要有多个操作（如 constrain + fill/add）就
  不是 `ready`，而是 `needs_constraints_first`/`needs_negotiation`；网关同时
  校验 status 和 atomic，防止“标 ready 但只执行一部分”。
- `ChangeOperation` 必须携带完整 `requirements/priorityRules`（不只是
  targets/scopes/count），保证后续步骤只凭一个操作也能还原完整要求。
- “继续”读取 TaskDraft 的剩余项，进入下一项只读/澄清/预览；不等于批准下一次
  写入。
- **当前实现（Batch B MVP）**：`TurnOutput.intentDraft` 可选；网关用
  `build_change_set` 守卫“非 ready **或非 atomic** 且带 proposalRequest”的复合
  请求；`confirm/cancel` 同轮出现非空 `intentDraft` 直接拒绝（确认回合必须
  `intentDraft=null`）；`ChangeOperation` 携带完整 `requirements/priorityRules`，
  后续步骤只凭一个 operation 也能还原完整要求。TaskDraft 存
  `ConversationWorkingSet.task_draft`，并在配置了事件流 Redis 时通过
  `RedisTaskLedger` 持久化（tenant+session 隔离、TTL 7 天、单条 ≤16KB）；
  Redis 不可用时显式降级为进程内，不阻塞对话。它仍只是任务元数据，不是方案/
  pending 真值。用户取消提案时清空 TaskDraft 与账本，避免“继续”复活旧任务。

### 0.5.6 约束生命周期（先行为真值表，再谈持久化）

源码核对结论（详见
`docs/superpowers/reviews/2026-10-18-constraint-lifecycle-truth-table.md`）：

- **`targetScopes`/`negativeScopes` 当前是持久化的**：预览用 pending
  `userGoalRequest`；确认后 scope goal 映射到 `apply_constraint_and_regenerate` +
  `constraintUpdate`，Java `updateConstraintState` 写 hard/soft preferences，并
  带 `regenerate_ordered_plan=True` 触发重排。卡面不能写“仅本次”。
- **学费是持久化的**：直接 `updateTuitionRange` 写 `userScoreDetail.TuitionRange`，
  不自动标 stale/重排；通过 scope/tuition 提案的命令路径会带
  `regenerate_ordered_plan=True`，会重排。卡面不能写“仅本次”。
- **`requirements`/`priorityRules` 应用时持久化**；priority 会立即重排，
  requirements 是否重排取决于 `regenerateOrderedPlan`；约束命令路径会强制重排+审查。
- **`tierQuotaGoal` 持久化，但 review 实际读的是 `expectedTierCount`**
  （由 `requiredTierCounts` 按 `selectionTargetCount/requiredCount` 缩放），
  不是 goal 原值；两者不一致要诊断。
- **`persistTargetCount` 不是生命周期字段**：只控制 `requiredCount` 是否随
  `selectionTargetCount` 同步。
- 目标态：一个 owner；学费不重复存；scope 的持久化走 constraintState，卡面要
  说明“写入本会话并可能重排”，不能靠“仅本次”文案冒充。

### 0.5.7 录取解读（结构版）

输出只包含：

- `structureStatus`：首个稳/保、冲档最高校线率、最后保底、无保底、无法判断；
- `condition`：若前序均未满足 / 若冲档命中 / 无；
- `safetyCoverage`：有保底档位 / 保底档位存在但数据不足 / 无保底档位 / 无法判断；
- `dataCompletenessBand`：完整 / 有缺口 / 严重缺口（内部另有 tier/ratio 覆盖）；
- `orderAnomaly`、`caveats`。

**禁止**：`likelihoodBand`、`slipRisk` 低/中/高、“最可能”“较可能被录取”、
“滑档风险低”。数据齐全不等于风险低；两条保底只说明结构覆盖。

### 0.5.8 评价输入与缓存凭据

```python
@dataclass
class EvaluationInputManifest:
    tenant_id: str
    session_id: str
    plan_content_digest: str      # 方案内容，不是 stateVersion
    state_version: int            # CAS/guard
    candidate_source_version: int | None
    candidate_digest: str | None
    overlay_version: str | None
    admission_mode: str
    objective_model_version: str
    policy_snapshot_version: str | None
    profile_digest: str | None
    counterfactual_digest: str | None
```

- 评价、预览、解读都绑定自己的 manifest；**旧 findings 不能与新 manifest 拼成
  “新版本”**。
- 个性化缓存 key 必须包含 `tenant_id + session_id + plan_content_digest +
  candidate_digest + overlay_version + admission_mode + objective_model_version +
  counterfactual_digest`；按字节和条目双限，不允许全局只按版本号共享。
- 写执行继续用现有 CAS/stateVersion；内容没变但 review 元数据变化时，不能把旧
  确认跨版本套用。
- 只读结果是否失效按依赖判断：画像/目标/候选/政策变化可使同一方案内容的旧结论
  失效；仅 review 元数据变化不等于方案内容变化。

### 0.5.9 交付批次

| 批次 | 目标 | 验收 |
|---|---|---|
| A 语义/保护边界 | 收口 F01–F05；核对真实持久化/重排；定义 TaskDraft/ChangeSet/确认边界；结构解读口径 | 同一句话不丢硬要求；卡面与执行一致；不输出未经验证的录取风险 |
| B 当前路径闭环 | 现有 add/fill/scope/score 接通完整要求、剩余项、真实回执 | 复合要求可解释阻断/分步；“继续”和失败恢复不丢任务 |
| C 评价输入/规则 | 不可变输入清单、resultStatus/ruleStrength/displaySeverity/fixability、必需 probe；旧新 shadow | 旧 check 可追溯；未知不伪装通过 |
| D 按动作接规划器 | 首建、替换、删除、重排分别接冻结 diff/变更预算/后置 | 每个动作有预览、后置、幂等回执 |
| E 优化策略 | 候选有效视图、首建/增量/重做目标 profile 与排序 | 局部调整不无故大换血 |
| F 解读/产品化 | 用已统一评价提供结构对比/受支持反事实；风险模型另验 | 解释可追溯；不以卡片代替闭环 |

## 一、现状盘点（有代码依据）

### 1.1 对话与动作

- 模型输出 `TurnOutput`，核心字段：`responseType`（`text`/`fact`/`recommendation`/
  `review`/`clarification`）、`proposalRequest`、`scoreUpdateRequest`、
  `careerUpdateRequest`、`conversationAction`（`none`/`request_clarification`/
  `continue_readonly`/`create_proposal`/`confirm_proposal`/`cancel_proposal`/
  `refresh_proposal`）。见 `zhiyuan-agent/app/gateway/contracts.py:160-171,510-533`。
- `proposalRequest.goalType` 当前七类：`only_keep_scope`、`must_include_scope`、
  `exclude_scope`、`tuition_budget_scope`、`fill_to_count`、
  `prioritize_within_tier`、`add_units`（`contracts.py:325-333`）。
- Java 命令类型：`apply_constraint_and_regenerate`、`add_units`、`replace_units`、
  `apply_plan_change_proposal`、`update_score_detail`
  （`PendingPlanningCommandBizService.java:57-62`）。
- codex 侧**没有写工具**：MCP 只暴露只读工具；写一律走
  `proposalRequest` → 待确认卡 → 用户确认 → Java 确认链
  （`zhiyuan-agent/app/mcp_server/tools_readonly.py:25-92`）。
- 模型自行判断确认/取消/澄清，并输出 `conversationAction`；网关不按关键词重判
  （`skills/codex/developer_instructions.md:53`）。这是对的，应保留。

### 1.2 阶段与路由

- `planningStage` 来自 Java 工作区 `phase`，实际值：`profile_ready`、
  `candidate_generated`、`drafting`、`ordered`、`reviewed`
  （`ConversationSnapshotService.java:42`、`PlanningStateService.java:618,1759,
  13581,2592,2906`）。
- 路由是**模型驱动**：`planner-routing/SKILL.md` 按 `planningStage` 选一个阶段技能，
  后端没有意图路由器。
- `allowedCapabilities` 恒为 `catalog_read`+`admission_read`。`review_read`
  曾只在 `skill` 含 "review" 时签发，但网关总传 `skill=None`，且
  `tools_readonly.py` 的 CAPABILITIES 没有任何工具消费它——是**死能力**，
  2026-10-18 已从 `ConversationSnapshotService` 删除（连带删除无用的 `skill`
  参数）。因此本设计**不声称修这个能力**：J2 解读直接引用现有
  `reviewState.checks`，J5 后再换 `PlanEvaluation`；`plan-final-review` 暂保持
  “模型基于只读工具的人工审查”，不依赖 `review_read`，也不签发 review artifact。
  若要 review 卡/工具，另立切片。
- 现有七个 codex 技能：`planner-routing`、`profile-discovery`、
  `school-major-exploration`、`admission-fact-analysis`、
  `candidate-recommendation`、`plan-construction`、`plan-final-review`。

### 1.3 方案与录取数据

- 候选行里有系统录取率/风险档位等字段（具体字段名见 §8.2 的数据模型节），
  方案单元里有顺序、档位、院校/专业、计划数、学费等字段。
- **目前没有任何“按当前方案推演录取落点”的工具、schema 或服务**。
  `probability` 在 `explain_fit` 里恒为 `unavailable`
  （`tools_readonly.py:80-82,1524-1612`），系统明确不提供权威概率。
- 因此录取解读**不能**声称是精确概率；只能做“按往年位次/档位的场景演绎”，
  并明确数据缺口和不确定性。

### 1.4 系统动作不可见

- 自动方案生成、重排、审查发生在 Java 内部；对话里只有零散的 proposal 卡或
  `conversationAction.result`。用户看到的是“结果变了”，但看不到“为什么变、
  改了什么、审查发现了什么”。
- 目前没有 `origin=system` 的动作事件卡；也没有“改动范围/结果”的统一回执。

## 二、设计原则

1. **模型解析意图，后端编译与执行**：不让后端再用关键词猜意图，也不让模型直接
   做写操作。模型输出结构化意图；后端用状态机、版本守卫和确认链约束。
2. **一轮一个主动作**：`proposalRequest`、`scoreUpdateRequest`、
   `careerUpdateRequest` 三者互斥；只读解释可以与提案同轮，但不能同时出两个写。
3. **先给内容，再问问题**：能推断的不问；缺的用封闭式选项；不把选择抛回用户。
4. **不静默改变用户方案**：任何新增/删除/替换/重排都必须先有预览与确认；
   “必须有/总数不变/换掉”不得被静默解释成扩总数。
5. **回执是唯一事实来源**：对话正文只能复述回执/卡片明细，不能自行编排条目清单。
6. **面向用户讲取舍，不甩系数**：内部有权重、有目标层级；用户看到的只有
   “更稳 / 更冲 / 学校更好 / 保底更少”这类业务语言。
7. **解读不是承诺**：录取解读是“按往年数据推演的可能路径”，必须带假设、缺口和
   反例；不得说“保证录取”。

## 三、用户旅程（Journey）

### 3.1 两条状态轴，不混用

- `planningStage`：**方案产物**的生命周期（profile_ready → candidate_generated →
  drafting → ordered → reviewed）。已有，不改语义。
- `journeyPhase`：**对话旅程**的当前位置，是派生视图，不落库：
  `discover`（了解自己）、`explore`（方向/院校探索）、`verify`（事实核验）、
  `candidates`（候选形成）、`build`（方案成形）、`review`（方案体检）、
  `interpret`（录取解读）、`adjust`（调整/定稿）。

`journeyPhase` 由快照 + 工作区 + 最近一次动作推导，不要求 Java 新增字段。
这样既能让模型知道“现在该主持哪一步”，又不会把方案生命周期和对话阶段搅在一起。

### 3.2 旅程表

| Phase | 用户要解决的问题 | 进入条件 | 系统主动作 | 产物/证据 | 退出条件 |
|---|---|---|---|---|---|
| discover | 我是谁、能报什么 | 无画像或画像不全 | 采集省份/年份/科类/批次/成绩/选科；能推断的不问 | 画像 + `profile_ready` | 硬事实齐 |
| explore | 我适合什么方向/城市/学校 | 画像齐 | 先推荐 2–3 个带理由的方向/区域，再收敛 | 方向/地域偏好（弱偏好） | 用户收敛或说“不限” |
| verify | 这个学校/专业到底怎样 | 有目标实体 | 查历史分、计划、资格、章程；区分事实与推断 | 事实卡 + 证据 | 关键事实齐 |
| candidates | 有哪些可填的志愿 | 硬事实齐 | 给候选、冲稳保、比较、解释 fit | 候选 artifact | 用户选定一批 |
| build | 把这些排成方案 | 有候选 | 生成/加入/替换/补足/排序；先预览再确认 | 方案草稿/正式方案 | 方案成形 |
| review | 这个方案有什么问题 | 有方案 | 审查梯度、保底、覆盖、资格、重复 | 审查报告 + 问题 | 问题收敛或用户接受 |
| interpret | 按这个方案，我可能被哪里录取 | 有方案 + 成绩/位次 | 场景演绎：冲高/基准/保底/滑档 | 解读卡 + 证据 | 用户理解并决定是否调整 |
| adjust | 那要怎么改 | 有解读或审查结论 | 把解读结论翻译成动作（加保底/去冲高/换专业/重排） | 新预览/新回执 | 回到 build/review/interpret |

### 3.3 旅程不是直线

- 用户可以在任何阶段跳问：有方案就可以直接 `interpret`；有目标实体就可以直接
  `verify`；没有画像时先 `discover`，但**不阻塞**方向性解释。
- 每次写动作完成后，默认回到 `review` 或 `interpret` 的入口，而不是停在“已生效”。
- 生成/审查在确认链内部完成，不应伪装成用户回合；当前 codex 路径没有
  “后台自动生成/重排”的生产者，不能按有自动源来设计。

### 3.4 journeyPhase 的推导规则

`journeyPhase` 不落库，分两层推导，避免“先有意图才能判阶段”的循环：

**第一层 `statePhase`（pre-turn，只看 Java 快照 `journey` 块）**：

| hasProfile | hasCandidates | hasPlan | statePhase |
|---|---|---|---|
| false | any | any | `discover` |
| true | false | false | `explore` |
| true | true | false | `candidates` |
| true | any | true | `build` |
| true | false | true | `build`（有方案但候选池缺失也按 build，标 gap） |

- `hasProfile`：由 Java 按画像/成绩硬事实计算（省份/年份/科类/批次/成绩或位次），
  不靠 `missingFacts` 的差集猜。
- `hasCandidates = candidatePool.summary.total > 0 && statusCode != not_generated`。
- `hasPlan = ordered items/units 非空 或 working items/units 非空`（不能只数
  items：unit-only working plan 会误判 false；补录成绩后 phase 可能回
  `profile_ready`，但 `hasPlan` 仍为 true）。`planEntryCount` 按 `admissionMode`
  明确是 items 还是 units。
- `stale` 是独立布尔：`any(candidatePool/recommendationOverlay/initialRecommendation/
  orderedPlan/planAdjustment/review 的 flag 为 true) || staleFlags.reasonCode/message
  非空`。**不能**写成“`staleFlags` 非空”——`StaleFlagsDTO` 永远非 null。
  `review` 也不在 pre-turn 推断。

**第二层 `taskIntent`（post-model，模型动作派生）**：
`responseType=fact` 或 compare 工具 → `verify`；`responseType=review` →
`review`；调用 `planning.interpret_admission` → `interpret`；解读后用户明确
“改/加/删/换” → `adjust`；其他 → 沿用 `statePhase`。
这些意图在模型输出之前不可知，**不得**在 pre-turn 用文本关键词猜。
`TurnOutput` 目前没有 `taskIntent` 字段，J1a 必须先定上述映射再写测试，不能
假设模型会直接输出它。

最终 `journeyPhase = taskIntent ?? statePhase`。只读问题永远不强制写动作；
`planningStage` 仍按 Java 原值展示，不因 `journeyPhase` 改写。

最终 `journeyPhase = taskIntent ?? statePhase`。只读问题永远不强制写动作；
`planningStage` 仍按 Java 原值展示，不因 `journeyPhase` 改写。

**快照缺口证据**：当前 `ConversationTurnSnapshotDTO` 只有 snapshotVersion/
admissionMode/planningStage/scoreContext/confirmedConstraints/preferences/
activeProposal/missingFacts/allowedCapabilities/evidence/admissionFacts，
没有 staleFlags、working/ordered plan、candidatePool 是否存在
（`ConversationSnapshotService.java:42-52`）。因此 J1a **必须**给快照加
`journey` 块；不能靠 `working_set` 或 `last_action`（两者都不存在权威方案状态）。

### 3.5 每个阶段的“主持”话术

- `discover`：先复述已知信息，再只问缺的 1 组；能推断的不问。
- `explore`：先给 2–3 个具体方向/区域 + 理由，再请用户增删；不以“你想学什么”收尾。
- `candidates`：先给候选与取舍，再问“要不要按这个方向排方案”。
- `build`：先宣布“我按什么口径排”，给预览，再请确认。
- `review`：先给 top 问题与影响，再给修复选项。
- `interpret`：先给“基准情景落点”，再给冲高/保底/滑档情景，最后给一个可执行建议。
- `adjust`：把解读结论翻译成一个具体动作，不重新问一遍所有偏好。

## 四、对话控制流（Control Loop）

### 4.1 单轮控制链

```
用户消息
  → IntentFrame（目标、对象、范围、强度、生命周期、风险姿态、优先级、数量、版本）
  → JourneyContext（当前 phase、可用动作、阻断动作、推荐下一步）
  → RouteDecision（clarify | readonly | propose | confirm | cancel | interpret | meta）
  → 执行（只读工具 / 生成 pending / 确认链）
  → Receipt（实际变更 + 后置条件 + 审查摘要）
  → Narrator（正文复述回执 + 取舍解释）
  → NextOffer（下一步封闭式建议）
```

### 4.2 对话状态（每回合派生的建议状态，不是持久状态机）

下表是**建议状态**：每回合由 `activeProposal`、`missingFacts`、`statePhase`、
最近工具结果派生；只有 `AWAITING_CONFIRM`/`CLARIFYING` 有真实载体（pending /
missingFacts），其余不落库、不可恢复。`PROPOSING`/`EXECUTING` 是同步内部阶段，
不建模为可恢复状态。

| 状态 | 派生依据 | 允许的动作 | 退出 |
|---|---|---|---|
| `IDLE` | 无 pending、无缺失 | 查询/提案/解读/澄清 | 进入对应状态 |
| `CLARIFYING` | `missingFacts` 非空或本轮要求澄清 | 只读补齐、继续澄清 | 槽位齐 → `IDLE` |
| `READING` | 本轮只读工具在飞 | 只读工具（预算内） | 有结果 → `EXPLAINING`/`IDLE` |
| `PROPOSING` | 本轮正在生成 pending（同步） | 展示 pending、只读解释 | 成功 → `AWAITING_CONFIRM` |
| `AWAITING_CONFIRM` | 快照有 `activeProposal` | 只允许一个活跃 pending | 确认/取消/过期/被 supersede |
| `EXECUTING` | 本轮正在等 Java 结果（同步） | 等待；不接新写 | 结果 → `IDLE`/`RECOVERING` |
| `EXPLAINING` | 本轮只读结果已回 | 只读解读、复述回执 | 用户决定 → `IDLE`/`PROPOSING` |
| `RECOVERING` | 最近结果是 stale/冲突/失败 | 重新预览、修复 | 恢复 → `IDLE`/`PROPOSING` |

### 4.3 硬规则

1. **supersede 是显式策略**：已有 `prepared` 待确认提案时，新的写意图可以生成新预览，
   Java `prepareOnce` 会把旧记录标 `superseded`；卡片/正文必须说明“上一条预览已失效，
   以新卡为准”。`applying` 时拒绝新写（`409 pending_applying`），提示“正在生效，
   请稍候或取消”，不得静默覆盖。**不要求用户先手动取消旧提案**。
2. **确认必须有载体**：没有 pending 时不得执行 `confirm_proposal`；确认结果以
   `conversationAction.result` 为准，不以模型判断为准。
3. **版本守卫**：任何写动作带 `sourceVersionGuard`；版本不匹配先走恢复，不硬写。
4. **一轮一个写**：`proposalRequest`/`scoreUpdateRequest`/`careerUpdateRequest`
   互斥；只读解释可同轮。
5. **歧义只问一次**：扩总数 vs 替换、是否持久、目标数量，这三类歧义用一次封闭式
   问题解决；用户回答后不再重复问。
6. **“都行/看着办”不是确认**：系统可以给推荐默认，但仍然要出预览/确认载体，
   不得静默执行。
7. **失败如实转述**：`stale_state`、`40905`、`40907`、`40908` 等按结果码解释，
   不把失败说成成功。**执行超时 ≠ 未执行**：返回 `applying`（结果未知/处理中），
   重试复用同一 operationId/claimToken；不能生成另一版执行。

### 4.4 JourneyContext（派生）

```python
@dataclass
class JourneyContext:
    phase: Literal["discover","explore","verify","candidates","build","review","interpret","adjust"]
    state_phase: Literal["discover","explore","candidates","build"]  # pre-turn
    task_intent: str | None          # post-model，来自动作族
    planning_stage: str | None
    has_profile: bool
    has_candidates: bool
    candidate_source_version: int | None
    has_plan: bool
    plan_version: int | None         # = stateVersion（同一计数器；不是内容版本）
    plan_entry_count: int
    review_source_version: int | None
    admission_mode: str | None       # major | major_group
    pending_kind: str | None
    pending_applying: bool
    stale: bool
    available_actions: list[str]      # 业务语言/动作枚举
    blocked_actions: list[BlockedAction]  # action + reason + unblock
    recommended_next: str | None
```

- **来源**：Java `ConversationTurnSnapshotDTO` 新增 `journey` 块（J1a）：
  `hasProfile/hasCandidates/candidateSourceVersion/hasPlan/planEntryCount/
  planVersion/reviewSourceVersion/admissionMode/staleFlags/pendingStatus`；agent
  只读该块，不每轮拉 workspace，也不依赖 `working_set` 的候选存在性。
  `pendingStatus` 来自当前 pending（无则 null）。不能沿用现在的
  `getCurrent`（`last("limit 1")` 无 status 过滤/排序，可能取到 applied/cancelled
  旧行）：J1a 要改成按 `status ∈ {active, applying}` + revision 倒序取最新；
  `fillActiveProposal` 仍只暴露 `active`，`journey.pendingStatus` 单独暴露
  `applying`。`journey` 块**不再重复 `admissionMode`**：用快照顶层字段，避免
  同一快照两个同义字段。
- **agent 必须同步改三处**，否则块会被 `extra="forbid"` 丢掉：
  1. `contracts.py` 的 `ConversationTurnSnapshot` 增加 `journey` 字段（独立
     Pydantic 模型或 `dict[str, Any]`）；
  2. `snapshot.py` 的 `build_snapshot` 透传 `journey`，`diff_snapshots` 的
     `allowed` 增加 `journey`，`StatePatch._validate_change_paths` 同步允许
     `journey`（否则 diff 被拒、退回全量快照）；
  3. `service.py` 把紧凑 `JourneyContext` 注入模型可见的 turn 上下文/提示，
     并加预算（只注入 phase/available/blocked/recommended_next/**plan_version**，
     不注入全量状态）。`plan_version` 必须注入：`planning.interpret_admission`
     工具要求 `planVersion`，模型不能从别处猜。
- `phase = task_intent ?? state_phase`；`state_phase` 在模型输出前就能算，
  `task_intent` 在模型输出后覆盖 verify/review/interpret/adjust。
- 只读派生，不新增数据库表；当前**只有一个计数器**
  `stateVersion = planningState.version = workspace.version = snapshotVersion =
  sourceVersionGuard`，review/偏好/候选生成/补录都会 +1，**不是内容版本**。
  `journey.planVersion` 就是这个计数器（供工具/CAS 用）；内容版本另算
  `planContentDigest = hash(working/ordered 内容)`，缓存/新鲜度用它。
- `blocked_actions` 必须给“怎么解锁”，例如“没有成绩/位次 → 先补录成绩”；
  `add_units` 的已知阻断（`tierQuotaGoal`、`current != confirmed target`、
  `stale working plan item`）必须在这里出现。
- 第一阶段不要求模型输出 `JourneyContext`；后端把它注入提示/工具返回值，模型据此选路。
- 校验只做**硬不变量**：一轮一个写、有 pending 才能 confirm、版本守卫、
  已知阻断；不做 8 状态机的自动重试/修复。

`available_actions` 用固定动作枚举（未实现的标 `planned`，不得让模型误以为可用）：

| 动作 | 状态 | 说明 |
|---|---|---|
| `query_plan` | 已实现 | 读当前方案 |
| `query_facts` | 已实现 | 历史分/计划/资格/章程 |
| `compare` / `explain_fit` | 已实现 | 候选比较/适配解释 |
| `recommend_candidates` | 已实现 | 候选推荐 |
| `review_plan` | 人工审查（技能 `plan-final-review`，无专用工具） | 方案审查；不声称有 review artifact |
| `set_preference` | 部分实现 | scope/学费/排除；风险姿态/优先级待实现 |
| `add_units` | 已实现（EXPAND） | 点名加入；REPLACE 待实现 |
| `replace_units` / `remove_units` / `move_units` | planned | 替换/删除/排序 |
| `fill_to_count` | 已实现 | 补数量 |
| `regenerate` | planned | 整体重生成 |
| `interpret_admission` | planned | 本设计新增 |
| `update_score` / `update_career` | 已实现 | 补录成绩/发展方向 |
| `confirm` / `cancel` | 已实现 | 确认链 |
| `undo` / `rollback` | planned | 版本回退 |

## 五、触发动作目录（Trigger Catalogue）

### 5.1 触发分类

| 类别 | 用户典型说法 | 目标 | 动作族 | 写入？ |
|---|---|---|---|---|
| 查询方案 | “我现在方案里有什么”“多少条” | 了解现状 | `query_plan` | 否 |
| 查询事实 | “去年多少分”“招多少人”“我能报吗” | 核验事实 | `admission.*`/`catalog.*` | 否 |
| 比较/解释 | “A 和 B 哪个好”“为什么推荐它” | 做判断 | `compare_candidates`/`explain_fit` | 否 |
| 方向偏好 | “想学电气”“以省内为主”“不要医学” | 改偏好/约束 | `proposalRequest(only_keep_scope/exclude_scope/requirements(include)/priority_rules)` | 是（确认后） |
| 候选 | “再换一批”“看看冲稳保” | 选候选 | `recommendation.*` | 否 |
| 方案加入 | “把这六条加进去”“补两条” | 增加条目 | `add_units`（默认 EXPAND） | 是 |
| 方案替换 | “必须有这六条，总数不变”“换掉三条” | 加入并替换 | REPLACE / `replace_units` | 是 |
| 方案删除 | “把最后两条删了” | 减少条目 | remove（待实现） | 是 |
| 方案排序 | “把 A 放第一”“这个锁死” | 调整顺序/锁定 | move/sort/pin（待实现） | 是 |
| 方案补足 | “补到 50 条”“填满” | 补数量 | `fill_to_count` | 是 |
| 方案重排 | “重新排一版”“按北方优先重排” | 重生成/重排 | regenerate/reorder | 是 |
| 审查 | “帮我审一下”“有什么风险” | 体检 | 技能 `plan-final-review`（读工具） | 否 |
| 录取解读 | “我这样能上哪”“会不会滑档” | 看落点 | `planning.interpret_admission`（新增） | 否 |
| 反事实 | “去掉最后一条会怎样” | 比较方案 | interpret + diff | 否 |
| 补录成绩 | “我考了 600” | 改画像 | `scoreUpdateRequest` | 是 |
| 发展方向 | “以后想考公” | 改画像 | `careerUpdateRequest` | 是 |
| 确认/取消 | “确认”“取消”“先不要” | 推进/回退 | `conversationAction` | 是/否 |
| 元操作 | “撤销”“回到上一版”“重新开始” | 版本/恢复 | undo/rollback（待实现） | 是 |

### 5.1b 载体、状态与失败行为（必须先查这张表）

| 目标 | 真实载体 | 状态 | 失败/阻断时的用户可见行为 |
|---|---|---|---|
| 读当前方案 | MCP `planning.get_working_plan` / `admission.get_current_plan` | 已实现 | 无方案 → “先把方案排出来” |
| 读招生事实 | MCP `admission.*` / `catalog.*` | 已实现 | 缺数据 → 说明缺口，不编 |
| 比较/解释候选 | MCP `recommendation.compare_candidates` / `explain_fit` | 已实现 | 不在候选池 → 逐条列出 |
| 候选推荐 | MCP `recommendation.preview_candidates` / `preview_majors` | 已实现 | 缺画像 → 先澄清 |
| 方案审查 | 技能 `plan-final-review` + 只读工具 | 已实现（人工审查） | 无 review artifact；不声称有审查卡 |
| 范围/排除/学费 | `proposalRequest(goalType=only_keep_scope/exclude_scope/tuition_budget_scope)` | 已实现 | 按行为真值表：scope 经 `apply_constraint_and_regenerate` 写 `constraintState` 并重排；学费写 `userScoreDetail`，提案命令路径会重排 |
| 软偏好 | `proposalRequest(requirements(kind=include,min_count))` / `priority_rules` | 部分实现 | 没有 `prefer` 这个 goalType；不要编 |
| 点名加入 | `proposalRequest(goalType=add_units, exactTargets=[...])` | 已实现（EXPAND） | 已确认精确配额/当前数≠目标/条目 stale → 阻断并说明 |
| 必须有（方案已有） | `must_include_scope` / 保留规则 | 已实现 | 满方案时最多替换 1 组；不足要说明，不承诺一次补齐 |
| 必须有（方案没有） | REPLACE | **planned** | 如实说未支持；给“先扩总数/先看替换清单”选项 |
| 删除/排序/替换 | remove/move/replace | **planned** | 不假装已支持；给只读预览或说明 |
| 整体重生成/重排 | regenerate/reorder | **planned** | 不把 `prioritize_within_tier` 冒充整体重排 |
| 补数量 | `fill_to_count` | 已实现 | 数量 >0、可调整；缺数量会被拒 |
| 风险姿态/目标优先级 | 无当前契约 | **planned（J6）** | 不静默设配额；只给建议并说明未生效 |
| 录取解读 | `planning.interpret_admission` | **planned（J2）** | 无方案/缺数据 → 说明，不编 |
| 确认/取消 | `conversationAction(confirm_proposal/cancel_proposal)` | 已实现 | 无 pending → 拒绝；applying → 409 文案 |
| 撤销/回退 | undo/rollback | **planned** | J3 前不上自动改方案；只能重新预览 |

### 5.2 触发优先级

同一句话命中多个动作时，按以下顺序裁决：

1. **明确确认/取消** > 其他（用户已经在回答 pending）。
2. **明确写动作**（加入/删除/替换/补足/重排）> 只读查询。
3. **明确纠正**（“不是这个意思”“我说的是…”）> 之前的推断。
4. **硬约束/排除** > 软偏好。
5. **安全/合规**（资格、批次、数据缺口）> 用户偏好。
6. 仍无法裁决 → 一次封闭式澄清，不猜。

### 5.3 关键触发细则

- **“加入”**：默认 `add_units` EXPAND；卡面写“总数 当前 → 当前+N、零删除”。
  用户说“总数不变 / 必须有 / 换掉”时，不得静默扩总数；先问一次“扩总数，
  还是保持总数做替换”。
- **“必须有”**：是 must-have 语义，不是普通 add。`must_include_scope` 的真实行为是：
  方案已有 → no-op/保留；方案未满 → 从候选补入；方案已满 → 最多替换 **1 组**。
  超过 1 组或要求“总数不变”时，走 REPLACE 或“加入 + 等量移出”的完整预览；
  第一期 REPLACE 未实现时，如实说明并给“先扩总数/先看替换清单/分步处理”选项，
  不能承诺“一次把 N 条必须有都补齐”。
- **“为主/优先/尽量”**：软偏好，覆盖下限取目标数量的大头，不写成 `minCount=1`；
  不进池过滤。
- **“只/仅限”**：硬过滤（`only_keep_scope`/`exclude_scope`）。
- **“不限/都行”**：不设约束，不替用户加戏。
- **“稳一点/冲一点”**：目标口径是风险姿态（稳健/进取），不是精确配额；
  **J6 未落地前**如实说明“这个偏好还没接进生成器”，可以按现有档位给建议，
  不得假装已生效。
- **“保专业/保学校/保录取”**：目标口径是目标优先级排序，映射到优化器目标层级；
  **J6 未落地前**同样只给建议并说明未生效；面向用户只讲取舍。
- **“补到 N 条”**：`fill_to_count` 必须带 >0 的建议数量（优先当前目标总量），
  卡上可调整；不得留空。
- **“我这样能上哪”**：只读解读；若没有方案，先说“先把方案排出来才能解读”，
  并给出生成方案的动作。
- **“去掉 X 会怎样”**：反事实结构分析；只读，不执行删除；说明保底档位是否
  变为“无保底档位”、数据缺口和顺序变化，不输出概率/风险等级。

### 5.4 常见追问与数据边界

| 用户说法 | 动作 | 数据/边界 |
|---|---|---|
| “这个学校/专业怎么样” | `school-major-exploration` + `compare` | 事实优先；没有的维度说不知道 |
| “这个专业组代码是多少” | 事实解释 | 数据源没有组代码，如实留空，不硬凑 |
| “保研率/就业怎么样” | 院校事实查询 | 有数据才说；没有不编 |
| “学费多少” | `admission.get_enrollment_plan`/方案单元 | 以计划/方案字段为准 |
| “招生章程怎么说” | `admission.get_charter` | 引用章程原文/条款 |
| “今年扩招吗” | 计划对比 | 有两年计划才比较；否则说缺数据 |
| “我不想去北方/离家近点” | 地域偏好（软/硬看措辞） | “不想”可成 exclude；先确认范围 |
| “民办可以吗/只想 211” | 院校层次/类型约束 | 现有 scope 是否支持要先查；不支持就如实说 |
| “服从调剂吗/会不会退档” | 政策解释 + 解读 caveat | 不声称掌握省考试院投档规则 |
| “这个方案能上本科吗” | 解读 + 批次资格 | 先看批次/资格，再给落点 |
| “帮我随便填一个” | 澄清/候选 | 不静默写；给推荐并出预览 |
| “先这样/再看看” | 不写 | 保持只读，不把模糊表达当确认 |

### 5.5 触发目录的落地方式

- **提示词/技能层**：把上表写成 `planner-routing` 的触发速查和各技能的
  “什么时候用哪个动作”；模型必须按目录输出结构化动作。
- **后端校验层**：`DialogueController` 校验动作是否在 `available_actions` 内；
  不在就返回可解释的阻断，而不是让工具报错。
- **测试层**：分两层，不混为一谈：
  1. **契约校验器单测**（CI 必跑）：fixture 里的动作必须在 `JourneyAction` 里、
     载体/状态合法、写动作槽位非空；它只证明目录自洽，**不证明模型会按目录走**。
  2. **live eval**（可选、非 CI）：固定模型版本/温度，把 40 条话术真喂 codex，
     记录实际动作；允许非确定性，报告命中率与偏差。没有 eval harness 时，不得把
     “40 条全绿”写成触发行为的验收结论。

## 六、目标 → 动作拆解（IntentFrame）

### 6.1 IntentFrame

```python
@dataclass
class IntentFrame:
    goal_family: Literal["discover","query","preference","candidate","plan_mutation","review","interpret","meta"]
    action: str
    targets: list[TargetRef]           # 院校/专业/单元/条目
    scope: ScopeSpec | None            # 地域/学费/层次/专业方向
    strength: Literal["only","prefer","exclude","must"] | None
    lifecycle: Literal["persist","once"] | None   # J4a 目标态；之前恒 null
    risk_posture: Literal["steady","balanced","aggressive"] | None  # J6 目标态；之前恒 null
    priority_order: list[str]          # J6 目标态；现有 priorityRules 只做同档前置

    count: int | None
    # 方案版本只在 PlanCommand.base_plan_version；模型看到的 workspace 版本是
    # proposalRequest.sourceVersionGuard。这里不再放第三个版本字段。
    confidence: float
```

- 第一版**不要求模型直接输出这个对象**：由现有 `proposalRequest`/`conversationAction`
  映射得到；后续如需更强的触发控制，再把 `intentFrame` 作为可选输出字段加入契约。
- `strength` 决定“过滤”还是“排序”，当前可从 ProposalRequest 的
  only/exclude/include 映射。
- `lifecycle` 是 **J4a 目标态**（当前不存在 `persist=once|session`；
  `persistTargetCount` 不是意向生命周期），J4a 前必须为 null，不能声称“默认持久”。
- `risk_posture`/`priority_order` 是 **J6 目标态**，当前 ProposalRequest 没有
  对应字段；J6 前必须为 null。现有 `priorityRules` 只做“同档前置”，不是全局
  目标优先级，不能冒充。

### 6.2 拆解规则

| 用户目标 | 拆解 | 备注 |
|---|---|---|
| 纯加入 | `add_units` EXPAND | 默认；零删除；卡面写总数变化 |
| 加入且必须有 | REPLACE / must-have | 显式；预览列全新增+移出 |
| 加入且总数不变 | REPLACE | 显式；不得静默扩总数 |
| 只保留某方向 | `only_keep_scope` | 硬过滤 |
| 排除某方向 | `exclude_scope` | 硬过滤 |
| 某方向为主 | `requirements(kind=include, min_count)` 或 `priority_rules` | 没有 `prefer` goalType；不排除其他 |
| 学费上限 | `tuition_budget_scope` | 当前写 `userScoreDetail`，本会话后续规划使用；不自动重排。**不能统一写“仅本次”** |
| 补数量 | `fill_to_count` | 数量必须 >0，可调整 |
| 重排 | reorder/regenerate | 先说明是否引入新条目 |
| 审查 | review | 只读；输出问题+建议 |
| 解读 | interpret | 只读；输出场景+证据 |
| 调整风险 | risk posture | 稳健/均衡/进取；不是精确配额 |
| 调整优先级 | priority order | 保专业/保学校/保录取/城市/学费 |

### 6.3 拆解示例

用户：“把这六条加进去，另外太远的不要，学费控制在 3 万内，稳妥一点。”

拆成四个意图，但**不能塞进一个提案**：

| # | 意图 | 动作 | 处理 |
|---|---|---|---|
| 1 | 点名加入六条 | `add_units` EXPAND | 本轮主提案；卡面写总数变化、零删除 |
| 2 | 太远的不要 | 地域 `exclude_scope` | 下一轮确认；先问“多远算远/哪些城市” |
| 3 | 学费 ≤3 万 | `tuition_budget_scope` | 下一轮确认；**卡面写“写入本会话预算、不自动重排”**；不能写“仅本次” |
| 4 | 稳妥一点 | 风险姿态 `steady` | J6 前只说明“还没接进生成器”；不变成精确配额 |

本轮只出 1；2–4 在正文里说明“我会分步处理”，或用封闭式选项让用户选先做哪个。
不得把 1 和 2/3/4 混成一个提案（`add_units` 契约明确拒绝混用）。

### 6.4 歧义处理

- “加进去” + 方案已满：默认 EXPAND，但卡面必须写总数变化；用户没反对即确认。
- “必须有” + 未说总数：问一次“扩总数，还是保持总数替换？”
- “以 X 为主” + 没给比例：按目标数量的大头取覆盖下限，不写成 ≥1。
- “便宜点” + 没给预算：先按当前方案学费分布给 2–3 个档位选项，不自行设上限。
- “看着办”：系统给推荐方案 + 预览，不静默写入。

## 七、统一优化器（与 10-17 分析报告对齐）

### 7.0 现状：候选→方案不是一条链

10-17 分析报告（`2026-10-17-plan-generation-and-fill-analysis.md`）的结论，摘要：

- **候选来源至少三套**：原始候选池、effective candidates、agent artifacts；
  不同动作读不同的池，加入/补足/生成可能看到不同的候选集合。
- **排序键至少五套**：推荐分、`schoolEnrollRatio`、`finalScore`、意向分、
  solver 稳定顺序；同名指标在不同路径含义不一致。
- **solver 只优化硬可行性与两个偏差项**（变更成本、结构偏差），软效用/多样性
  没有统一入口；不同动作各自加约束。
- **已知断层（P0）**：legacy add 绕过 frozen command；scope 不持久；学费过滤
  口径不一致；审查的 tier quota 与 solver 不一致；覆盖后置条件与审查不一致；
  候选数量上限分散。
- **结果**：用户看到“同一句要求，生成/加入/补足给出不同结果”；回执也说不清
  改了什么、为什么。

本设计的 J5 不重写 solver，而是先统一**入口与出口**：

```
CandidateSnapshot（一次构建，所有动作共用）
  → IntentModel（硬约束/范围/偏好/风险姿态/优先级/数量）
  → ObjectiveCompiler（字典序目标）
  → 两条腿，同一目标：
       ├─ Solver（搜索）：硬可行 → 结构偏差 → 变更成本 → 软效用/多样性
       └─ PlanEvaluator（评价）：硬约束/结构/软效用 → PlanEvaluation
  → Postcondition + Receipt/StructureVector（所有动作同一套）
  → Review（PlanEvaluation 的用户面） / Interpretation（同一向量的场景推演）
```

在 J5 完成前，J1–J3 只做“触发/控制/解读”，不改变 solver 行为；但所有新动作
必须走 `PlanCommand`（§7.7），为 J5 留好唯一入口。

### 7.1 目标层级

统一优化器按**字典序**处理，不把不同性质的目标混成一个加权和：

1. **硬可行性**：资格、批次、选科、must-have、ban/lock、exact targets。
2. **用户硬约束**：only/exclude、学费上限、已确认的精确配额。
3. **结构目标**：安全 floor、冲稳保梯度、方向/地域覆盖、多样性、组内兜底。
4. **软效用**：专业/院校/城市/发展方向/院校层次的偏好匹配。
5. **变更成本**：尽量少动、少删、少换；纯加入优先零删除。
6. **稳定性**：同输入同输出，避免每次重排都变。

前两层是**硬约束**（不满足就没有可行解）；第三层是**带松弛的结构目标**
（不满足要扣分/报告）；第四、五层是**软目标**（用于在可行解之间选优）。

### 7.2 风险姿态

| 姿态 | 安全 floor | 冲高 | 适用 |
|---|---|---|---|
| 稳健 | 更高；保底覆盖更厚 | 少 | 怕滑档、想稳妥 |
| 均衡 | 默认 | 默认 | 大多数 |
| 进取 | 仍然保留最低保底 | 多 | 想冲更好的学校 |

风险姿态是**预设**，不是精确配额；用户可以在卡上改。任何姿态都不得把保底降到 0。

### 7.3 目标优先级

用户可排序：保专业 > 保学校 > 保录取 > 城市 > 学费。
编译器把它翻译成目标层级/权重；同一层级内仍按变更成本与稳定性裁决。
面向用户的解释只讲“这版更保专业，学校层次会让一点”，不出现权重。

### 7.4 一个求解器，所有动作

生成、补足、加入、替换、重排、范围变更都走同一个
`CandidateSnapshot → IntentModel → ObjectiveCompiler → Solver → Postcondition`，
不允许再出现“生成一套逻辑、加入另一套逻辑”的分叉。
详细现状与目标架构见 10-17 分析报告；本设计只补“旅程/触发/回执/解读”接口。

### 7.5 旅程阶段与优化目标

| phase | 优化目标 | 输出 |
|---|---|---|
| `candidates` | 资格/覆盖/质量/多样性；不追求“排好序” | 候选集 + 冲稳保分布 |
| `build` | 硬约束 + 结构目标 + 软效用 + 变更成本 | 完整方案 |
| `adjust` | **最小变更**下满足新意图；优先保留用户已确认/锁定的条目 | 增量方案 + 回执 |
| `review` | 只评估，不优化；问题按严重度排序 | 审查报告 |
| `interpret` | 只评估，不优化；场景路径 + 反事实 | 解读卡 |

同一套 `StructureVector` 贯穿候选、生成、增量、审查、解读；不允许“候选一套
指标、方案另一套指标、解读再一套口径”。

### 7.6 回执（Receipt + StructureVector）

每次写动作返回：

```python
@dataclass
class PlanReceipt:
    operation_id: str
    action: str
    added: list[EntryRef]
    removed: list[EntryRef]
    kept_count: int
    total_before: int
    total_after: int
    structure_before: StructureVector
    structure_after: StructureVector
    postcondition: PostconditionReport
    evaluation: PlanEvaluation | None   # 评价语义（权威）
    review_state: ReviewState | None    # 生命周期/摘要视图（过渡期；不另定规则）
    tradeoffs: list[str]          # 取舍（用户语言，如“更保专业、学校层次让一点”）
    reason_codes: list[str]       # 引擎原因码，供正文翻译
```

`StructureVector` 至少包含：档位分布、方向覆盖、地域覆盖、保底覆盖、
组内兜底、重复项、变更条目数。正文只能引用回执里的数字和条目。

```python
@dataclass
class StructureVector:
    total: int                         # 实际条目；group 模式为 unit 数
    target_count: int                  # requiredCount（摘要口径），不是 selectionTargetCount
    entry_tier_counts: dict[str, int]  # item 计数（major 模式）
    unit_tier_counts: dict[str, int]   # unit 计数（major_group 模式）
    unknown_tier_count: int
    safety_floor: dict[str, int]       # keys 由 J5.0 probe 表定义
    coverage: dict[str, list[str]]     # keys 与 CoverageRequirementDTO 对齐
    diversity: dict[str, float]        # 内部指标，不直接展示
    duplicates: int
    locked_count: int
    pinned_count: int
    mutation: dict[str, int]           # added/removed/reordered
```

**这是目标 schema，不是当前实现**：字段的精确 key/阈值由 J5.0 的
`EvaluationContext` + 14 个 probe 全表定义；在此之前不得拿它当“已实现”。
`ratio_distribution` 按模式选 `entry_tier_counts`（major）或 `unit_tier_counts`
（major_group），不能混用。

这是 review/probe、solver 目标、回执、解读共用的**唯一**结构定义；任何一层不得
再定义第二套 `ratio_distribution`/`safety_floor`/`coverage` 指标。
`tradeoffs/reason_codes` 是“取舍解释”的唯一来源；**当前 Java 回执还没有这两个
字段**（`conversation_actions.py` 只有 actualChanges/reviewState），J4a/J5 负责
让 Java 产出。在它们落地前，正文只能引用 `structure_before/after` 的可见差异和
`reviewState.checks`，不得声称“回执里写了取舍原因”，也不得自行编原因。

### 7.7 ActionCompiler 契约（旅程 → 优化器的唯一入口）

控制层不直接调用 solver 内部；所有写动作先编译成一个 `PlanCommand`：

```python
@dataclass
class ConstraintPatch:
    target_scopes: list[ScopeSpec]       # only_keep/target
    negative_scopes: list[ScopeSpec]     # exclude
    tuition_range: tuple[int, int] | None
    requirements: list[RequirementSpec]  # coverage/min_count
    priority_rules: list[PriorityRule]
    target_count: int | None
    tier_quota: dict[str, int] | None

@dataclass
class PlanCommand:
    # constrain 承载 scope/学费/requirements/priority 等约束 patch；
    # add/remove/replace/move/fill/reorder 才是方案结构变更。
    command_type: Literal["generate","constrain","add","remove","replace","move","fill","reorder"]
    intent: IntentFrame              # 用户级目标/约束/风险/优先级（唯一来源）
    base_plan_version: int           # 执行所基于的方案版本
    resolved_targets: list[EntryRef] # 由 intent.targets 解析后的执行级目标
    compiled_constraints: ConstraintPatch  # 由 intent.scope/strength 编译
    mutation_budget: MutationBudget  # 允许动多少条/是否允许删除
```

`ConstraintPatch` 的字段与 `ProposalRequest` 的 `targetScopes/negativeScopes/
requirements/priorityRules/targetCount/tierQuotaGoal` 一一对应，不新增用户语义；
解析后的执行级字段才进 `PlanCommand`。`intent` 只作 **provenance/审计**；solver
只读 `resolved_targets`/`compiled_constraints`，两者冲突时以 resolved/compiled
为准，不能出现“solver 读 intent、回执读 resolved”的两套结论。

- `add` 的 `mutation_budget` 默认 `allow_delete=False`（EXPAND）；REPLACE 才允许
  等量删除，且必须在预览里列全。
- `move` 是单条移动/置顶/锁定；`reorder` 是整段/同档重排；`generate` 是重生成。
  三者不互相冒充。
- `adjust` 阶段默认 `min_mutation`：优先保留 locked/pinned/用户已确认的条目。
- 编译器负责把“意图”翻译成“约束/目标”，solver 只认 `PlanCommand`。
- 这样同一句话在生成、加入、重排三个阶段走的是同一条命令契约，而不是三套参数。

**模型词汇 → 内部命令的映射（必须穷尽）**：

| `proposalRequest.goalType` | `PlanCommand.command_type` | 备注 |
|---|---|---|
| `only_keep_scope` / `exclude_scope` / `tuition_budget_scope` | `constrain` | 只改约束；是否重排由后续 `generate`/`reorder` 决定 |
| `must_include_scope` | `constrain` | 覆盖要求；若目标不在方案里，需要另出 `add`，不能假装已包含 |
| `fill_to_count` | `fill` | 数量 >0 |
| `prioritize_within_tier` | `reorder` | `priority_order` 表达同档前置；不是整体重生成 |
| `add_units`（默认 EXPAND） | `add` | `mutation_budget.allow_delete=false` |
| `add_units`（显式 REPLACE） | `replace` | 预览列全新增+移出；等量替换 |

`scoreUpdateRequest` / `careerUpdateRequest` 不是方案命令，保留为独立的 profile
写入，不塞进 `PlanCommand`。legacy `PlanGoalTypeValue`（`query_state`/`rebalance_structure`/
`reduce_risk`/`mixed_adjustment`/`clarify`）只做旧路径映射，新路径不得新增。

### 7.8 审查 = 评价，优化 = 搜索（同一目标模型）

**结论：审查不是优化之外的规则集合，而是优化目标函数的评价面。**

- 优化器：在 `PlanCommand` 的目标下搜索一个可行/较优方案；
- 审查：对当前方案按**同一目标模型**逐项评价，输出通过/缺口/建议；
- 两者共用 `CandidateSnapshot`、`IntentModel`、`ObjectiveCompiler`、
  `StructureVector`、`PlanEvaluation`、`PlanCommand`/后置条件；
- 审查 finding 不是“再写一条 if”，而是带 `objective_delta`/`suggested_command`
  的评价结果，修复走同一个 `ActionCompiler`。

```python
@dataclass
class ObjectiveDelta:
    constraint_patch: ConstraintPatch | None
    target_count_delta: int | None
    tier_quota_delta: dict[str, int] | None
    add_targets: list[EntryRef]
    remove_targets: list[EntryRef]
    reorder_targets: list[EntryRef]
    reason_code: str

@dataclass
class EvaluationContext:
    entries: list[EntryRef]              # 带 pathTier/schoolRatio/majorRatio/tuition/riskFlags
    selection_target_count: int | None   # 用户确认目标（HardPlanningObjectives）
    required_count: int                  # 候选池/摘要目标
    required_tier_counts: dict[str, int]
    admission_mode: Literal["major","major_group","unknown"]
    source_province: str | None
    user_score: int | None
    candidate_source_version: int | None

@dataclass
class EvaluationFinding:
    code: str
    layer: Literal["hard","structure","soft"]   # 目标层；notice 不是 layer
    result_status: Literal["pass","fail","unknown","not_applicable"]
    rule_strength: Literal["hard","soft","policy"]  # 用户/规则强度，不按旧 check 名
    display_severity: Literal["block","action","notice","info"]  # 展示严重度
    fixability: Literal["none","preview_fixable","manual"]
    metric: str                  # 必须是 StructureVector/ObjectiveModel 的枚举键
    threshold: dict | None       # 结构化阈值，不用裸 object
    summary: str                 # 用户语言
    affected_entry_refs: list[EntryRef]
    objective_delta: ObjectiveDelta | None  # 审查 → 修复的桥
    suggested_command: PlanCommand | None
    source: Literal["probe"] = "probe"

@dataclass
class PlanEvaluation:
    plan_version: int              # evaluatedStateVersion（review 时的 stateVersion）
    objective_model_version: str
    candidate_source_version: int | None
    status: Literal["completed","partial","unavailable"]
    probes_run: int
    structure: StructureVector
    findings: list[EvaluationFinding]
    hard_feasible: bool
    objective_digest: str
```

`EvaluationContext` 是 **J5.0 目标态**：J2a/J2b 不构建它，直接读现有
`ReviewStateDTO.checks`；J5.0 先把它和 14 个 probe 全表定义清楚，J5.2 再切换。
`StructureVector` 只是输出指标，不能拿来复算 probe。

**修复来源唯一**：`objective_delta` 是权威；`suggested_command` 必须等于
`ActionCompiler.compile(objective_delta)`，两者不一致时以 delta 为准并拒绝该
finding 的修复；编译器不可用时 `suggested_command=null`。不允许两个字段给出
两个不同修复。

**findings 的完整性**：`PlanEvaluation.findings` 包含本次跑过的**所有** probe
（`result_status=pass/fail/unknown/not_applicable`），用户面默认只展示
fail/unknown/需动作的项；`ReviewState.summary` 由 findings 计数派生，不单独统计。
`result_status=pass` 的 finding 必须 `objective_delta=null`、
`suggested_command=null`，避免“已通过还建议改”。

**四个字段各管一件事**：

- `result_status`：这次评价的结果（pass/fail/unknown/not_applicable）；
- `rule_strength`：规则性质/用户强度（hard=不可放宽、soft=可优化、policy=政策告知）；
- `display_severity`：展示严重度（block/action/notice/info）；
- `fixability`：是否有可用修复（none/preview_fixable/manual）。

**硬可行性派生**：`PlanEvaluation.hardFeasible` 不是独立判断，定义为
“`status=completed && probes_run>0 && 所有 rule_strength=hard 的 finding
result_status=pass`”。`status=partial/unavailable` 或 `probes_run=0` 时必须 false
（否则“没审=硬可行”）；`result_status=unknown` 按**未通过**处理，
`display_severity=block`，summary 说明缺什么。不允许出现 `hardFeasible=true`
但 hard finding 失败/未知的两套结论。

**合法组合**：`result_status=pass` → `display_severity=info`；
`fail/unknown` 时 `rule_strength=hard` → `display_severity=block`，
`soft` → `action/notice`，`policy` → `notice/info`。`fixability` 独立，不得用
`display_severity` 推断。非法组合在构造期拒绝，避免“硬约束只报 notice”或
“已通过的项还是 block”。

**生命周期视图 vs 评价语义**：`PlanEvaluation` 只承载评价结果（structure/
findings/hardFeasible/objectiveDigest）；`ReviewState` 保留为**薄视图**：
`status/evaluatedAt/evaluationVersion/summary + PlanEvaluation 引用`。它不再承载
规则，也不允许出现“ReviewState 说通过、PlanEvaluation 说失败”的两套结论。
长期可将 `ReviewState` 改名为 `EvaluationState`；过渡期保留旧名。

**Probe 化（14 个现有 check 全量，J5.0 必须逐条落地）**：
`runReviewInternal` 当前跑 14 个 check；下表是目标映射，不是“7 个例子”。

| 现 check | layer | ruleStrength | displaySeverity | metric / 输入（EvaluationContext） | 口径备注 |
|---|---|---|---|---|---|
| `ratio_distribution` | structure | soft | action | 实际档位计数 vs `requiredTierCounts` 按 `selectionTargetCount/requiredCount` 缩放的 expected；group 按 **unit**，major 按 **item** | 不能混用 `tier_counts` |
| `safety_guard` | hard | hard | block | 生源省本省保底 unit/volunteer 数、userScore（含 `>=580` 短路） | 缺省份时 result_status=unknown + display=notice，不能伪装 pass/block |
| `probability_inversion` | structure | soft | notice | 有序条目的 `unit.admissionRatio`（group）或 `candidate.admissionRatio`（major） | 不是统一 `schoolEnrollRatio` |
| `probability_gap` | structure | soft | action | 相邻条目 ratio 差（>8） | 同上，按模式取 ratio |
| `count_validation`（J5 拆分） | `count_validation_hard`=hard；`count_target`=structure | hard；soft | block；action/notice | 官方数量 / `selectionTargetCount` / `requiredCount` / 当前数 / 模式 | 旧 check 动态 severity；J5 拆两个 probe，golden 对照 |
| `high_tuition` | soft | soft（用户说“不得超过”时升 hard） | action/notice | 条目学费 vs 预算/上限 | 强度由用户措辞定，不按 check 名固定 |
| `admission_limit` | hard | hard | block | 限报标签/资格 | item 级 |
| `special_enrollment` | soft | soft | action | 特殊类型招生标签 | item 级 |
| `edge_score` | structure | soft | notice | 用户分数是否边缘区间 | 结构/分数 |
| `cooperative_program` | soft | soft | action | 中外合作标签 | item 级 |
| `group_inner_safety_guard` | hard | hard | block | 组内每个 major 的 `admissionRatio` + `schoolEnrollRatio` | 不是 `StructureVector.safetyFloor` 单计数 |
| `major_group_safety_intent_alignment` | soft | soft | action | 组内托底专业 vs `careerTypes`/意向 | 组内 |
| `plan_update_notice` | soft | policy | info | 政策提示 | 不可优化消失 |
| `adjustment_notice` | soft | policy | info | 调剂提示 | 不可优化消失 |

**注意**：`group_inner_safety_guard` 是 `block`，layer/ruleStrength 都必须是
hard，不能按旧 `category=major_group_risk` 批量映射成 structure；
`count_validation` 拆成 `count_validation_hard`（hard/block）与 `count_target`
（structure/action|notice），不要硬塞 hard+action。`policy` 类（计划更新/调剂提示）
不能被优化器“优化消失”，也不自动升级成约束。

**审查 → 修复**：`EvaluationFinding.objective_delta` 由 `ActionCompiler` 编译成
`PlanCommand`；预览、冻结命令、后置条件、回执与普通方案写动作完全相同。不再有
独立的 `RepairDryRunSimulator` 规则链（可保留为过渡适配器）。

**新鲜度**：`objectiveModelVersion = hash(probeRegistryVersion,
objectiveCompilerVersion, weightsVersion)`；任何 probe/权重/目标层级变化都要 bump。
`evaluatedStateVersion = ReviewStateDTO.sourceVersion`（review 计算时的 stateVersion，
review 结束后它比当前 stateVersion 小 1）。
`evaluationVersion = hash(evaluatedStateVersion, planContentDigest,
candidateSourceVersion, dataFreshnessState.dataVersion, objectiveModelVersion)`。
**必须包含 evaluatedStateVersion**：否则旧 findings 会被当前 stateVersion 认证成
“新”。审查/解读读同一 evaluationVersion；不一致标 stale，不拿旧评价解释新方案。

**MVP 边界**：J2a/J2b **直接消费现有 `ReviewStateDTO.checks`**（保留 code/
severity/affected ids 与 unit/item、admissionRatio/schoolEnrollRatio 口径），
**不先造 `PlanEvaluation` 适配器**。J5.0 先定义 `EvaluationContext`、完整 probe
表、`PlanEvaluation`；J5.2 再把 J2a/J2b 的输入切到 `PlanEvaluation.findings`。
`plan-final-review` 在 J5 前仍是模型基于只读工具的人工审查，但输出结构向
`PlanEvaluation` 收敛。

**用户面**：审查按 hard/structure/soft 三层分组，severity 标
block/action/notice/info；每条只讲“哪条不满足、影响哪些条目、建议怎么改”，
不甩系数/权重；完整 `StructureVector` 用于回执和对比，不直接展示原始数值。

## 八、录取解读（Admission Interpretation）

### 8.1 定位

用户问的不是“录取概率是多少”，而是：

- “按我现在这个方案，最可能被哪里接住？”
- “前面冲的有没有希望？”
- “最后一个保底去掉会不会滑档？”
- “把 A 换成 B，结果会怎样？”

所以输出的是**结构位置与条件情景**，不是录取路径或概率：

1. **冲档最高校线率位置**：若冲档命中，结构上会先看到哪一条。
2. **首个稳/保位置**：若前序均未满足，结构上第一个稳/保在哪一条。
3. **最后保底位置**：结构上最深的一条保底。
4. **无保底档位/数据不足**：结构覆盖缺口或数据缺口，不是滑档概率。

### 8.2 数据输入：两套信号，禁止互相覆盖

**信号一：`pathTier`（路径档位，唯一决定冲/稳/保）。**
候选推荐流水线按**校级** `schoolEnrollRatio` 分档：
`<=50 冲`、`<=70 稳`、`>70 保`（`VolunteerIntervalService.java:96-102`；
注意不是 `admission/facts.py` 的 `<50`，后者只用于招生事实工具）。方案条目
`OrderedItemDTO.tier` 就是这层档位；`OrderedUnitDTO.schoolEnrollRatio` 是同一
校线信号，可用来确认，但**不能**反过来改 `pathTier`。

**信号二：`majorAdmissionRatio`（专业级证据，不改变 pathTier）。**
候选池的专业行 `CandidateItemDTO.admissionRatio` 来自专业 `enroll_ratio`；没有
专业行的校行是校级。`PlanningUnitMajorDTO.admissionRatio` 是组内专业级。
它只用于组内证据（`safetyMajor`、组内兜底、专业级风险），**不得**用来把校线
“冲”升级成“保”，也不得与 `pathTier` 做“冲突判 unknown”。

**方案条目的 join**：
- `OrderedItemDTO` **没有** `admissionRatio`/`planNum`/`riskFlags`；必须按
  `volunteerId` join 候选池（`CandidateItemDTO.volunteerId`）取专业级 ratio。
- `OrderedUnitDTO.admissionRatio` 在主要路径取 `schoolEnrollRatio`（校级），
  也可能是代表专业的 ratio；因此**不要把它当唯一专业级信号**；以
  `pathTier` + join 结果为准。
- join 不到（候选池刷新/overlay/旧 plan）→ 该条 `majorAdmissionRatio=unknown`，
  **不得**静默用 tier 冒充 ratio；`pathTier` 仍可用 `OrderedItemDTO.tier`。
- `planNum` 只在候选行/历史里，方案单元没有；不要假设方案单元带计划数。

**粒度**：
- unit 模式（`admissionMode=major_group`）：`EntryRef={level:"unit", id:unitId,
  position}`；组内专业只做证据（`safetyMajor`/major ratio）。
- major 模式（`admissionMode=major`）：`EntryRef={level:"volunteer",
  id:volunteerId, position}`；ratio 来自 join 的候选专业行。
- 模式不明确时按 `orderedPlanState.items` 的 `position` 扫描，并在 caveat 标注。

**历史与位次**：`recommendation.preview_candidates` 没有 `minRank`/历史行；
历史只在 `CandidateItemDTO.schoolHistoryScores/majorHistoryScores`
（`year/score/pos/planNum/enrollNum`），preview/plan 不投影。MVP **不把历史
位次纳入落点判断**；只对落点条目按需查 `admission.get_history` 作为证据。
`rankInTier` 是推荐排序名次，不是历史位次，不能进“位次差”。

**投档规则限制**：当前代码没有平行/顺序志愿的投档模拟；解读是**风险带路径**，
不是省考试院投档模拟。必须写“按常见平行志愿规则推演，具体以省考试院规则为准”。

**证据边界（MVP）**：解读是推演结论，不是上游取数；当前
`EvidenceLedgerService.toEvidenceDTO` 只签发 authoritative 证据，没有
`sourceLevel=computed` 的请求/实体/表支持。因此 MVP **不新签计算证据**：

- `evidenceRefs` 只引用本次实际查到的上游数据（候选/历史/审查）并沿用其证据；
  没有就返回空数组，**不得伪造**。
- 推演结论用 `caveats` + `reasonCodes` 表达，正文明确“按系统档位推演”，
  不声称“有证据证明会被录取”。
- 若以后要签发 computed 证据，先扩展 `EvidenceLedgerService` 的
  `sourceLevel`/请求/实体/迁移与响应载体，另立切片；不在 J2b 偷塞
  `sourceLevel=computed`。
- 历史明细单列 `historyRefs`/`historyDigest`，不混入主数据版本。

### 8.3 结构/条件情景算法（MVP，非预测）

**只描述结构，不推演录取概率或滑档风险。**

1. **分类**：每条条目 `pathTier ∈ {冲,稳,保,unknown}`（§8.2 信号一）。
   `unknown` 只来自 `OrderedItemDTO.tier` 缺失或非法，不因为专业 ratio 冲突而
   unknown。
2. **按实际 `position` 顺序扫描**（`unknown` 一律跳过，不参与结构位置）：
   - `base`：顺序里**第一条 `pathTier ∈ {稳,保}`**；没有则为 `null`。
     结构标签“首个稳/保位置”，条件“若前序均未满足”。
   - `upside`：在 `pathTier=冲` 的条目里选：
     * 有校线 ratio 的，取 **ratio 最高**（同率取更靠前）；
     * 全都没有校线 ratio 的，取**最早**的冲；
     * 没有冲则为 `null`。
     结构标签“冲档最高校线率位置”，条件“若冲档命中”。
   - `downside`：**最后一条 `pathTier=保`**；没有则为 `null`。
     结构标签“最后保底位置”，条件“若前序均未满足”。
   - `no_safe`：仅当 `safetyCoverage` 为“无保底档位”或“无法判断”时输出；
     结构标签“无保底档位/无法判断”，条件“无”。
3. **`safetyCoverage`（结构覆盖，不是风险）**：
   - `无法判断`：所有条目 `pathTier=unknown`；
   - `无保底档位`：没有任何 `保`；
   - `保底档位存在、数据不足`：有 `保`，但所有保的校线 ratio 缺失；
   - `有保底档位`：至少一条保的校线 ratio 已知。
   **“有保底档位”只说明结构覆盖；数据齐全也不等于风险低。**
4. **数据完整度**：
   - `tierCoverage = pathTier 已知条目数 / 总条目数`；
   - `ratioCoverage = 校线 ratio 已知条目数 / 总条目数`；
   - `dataCompleteness = min(tierCoverage, ratioCoverage)`；
   - `dataCompletenessBand`：`>=0.8` 完整、`>=0.5` 有缺口、否则严重缺口。
   面向用户不展示小数；数据缺口与结构覆盖分开说。
5. **顺序异常**：`order_anomaly = true` 当且仅当存在一条 `保` 出现在任意
   `稳/冲` 之前。`base` 仍按实际顺序取该保；`downside` 仍是最后一条保；
   不为了“正常梯度”重排用户方案。
6. **评价证据**：J2a/J2b 直接引用现有 `ReviewStateDTO.checks` 的
   `safety_guard`/`ratio_distribution`/`probability_inversion`/`probability_gap`/
   `high_tuition`/`count_validation` 作为 drivers/caveats；不另算评价结论。
   J5.0 定义 `EvaluationContext`/probe 表/`PlanEvaluation` 后，J5.2 再切换；
   J2a 不造适配器。
7. **历史证据**：对 base/upside/downside 条目，能查 `admission.get_history`
   就补一条往年分数/位次；查不到写“缺往年明细”。历史只作证据，不改变结构标签。
8. **反事实（MVP 只支持 remove）**：请求 `removeEntryRefs`（§9.1），对删除后的
   条目集重跑 1–7，输出结构覆盖变化；只读，不执行写。add/replace/reorder 留后续。
9. **措辞**：只写“首个稳/保位置 / 冲档最高校线率位置 / 最后保底位置 / 无保底
   档位 / 数据缺口 / 顺序异常”；**不得**写“最可能/较可能/有机会/风险较大/滑档
   风险低/高”。

**结构真值表（J2a 已测试）**：

| # | 输入（按 position） | base | upside | downside | no_safe | safetyCoverage | 数据完整度 | order |
|---|---|---|---|---|---|---|---|---|
| 1 | 冲1..13, 稳14..26, 保27..45，ratio 全知 | 第14条（稳） | 冲里校线率最高 | 第45条（保） | null | 有保底档位 | 完整 | false |
| 2 | 冲, 稳, 稳（无保） | 第一条稳 | 冲里最高 | null | 有 | 无保底档位 | 完整 | false |
| 3 | 全冲 | null | 冲里最高 | null | 有 | 无保底档位 | 完整 | false |
| 4 | 全保（≥2，ratio 全知） | 第一条保 | null | 最后一条保 | null | 有保底档位 | 完整 | false |
| 5 | 保, 冲, 稳 | 第一条保 | 冲里最高 | 最后一条保 | null | 有保底档位 | 完整 | true |
| 6 | 冲, 稳, 保（唯一保 ratio 缺失） | 第一条稳 | 冲里最高 | 最后保 | null | 保底档位存在、数据不足 | 有缺口 | false |
| 7 | 冲, 稳, 保（全部 ratio 缺失） | 第一条稳 | 最早冲 | 最后保 | null | 保底档位存在、数据不足 | 严重缺口 | false |
| 8 | 全 unknown tier | null | null | null | 有（无法判断） | 无法判断 | 严重缺口 | false |
| 9 | 空方案 | — | — | — | — | 无法判断 | 严重缺口 | — |
| 10 | major 模式 join 不到 ratio，tier 已知 | 第一条稳/保 | 最早冲 | 最后保 | null | 保底档位存在、数据不足 | 严重缺口 | false |
| 11 | 冲, 稳, 保, 保（一条保 ratio 缺失） | 第一条稳 | 冲里最高 | 最后保 | null | 有保底档位 | 有缺口 | false |
| 12 | 冲, 稳, 保（单保 ratio 已知） | 第一条稳 | 冲里最高 | 最后保 | null | 有保底档位 | 完整 | false |
| 13 | 冲, 稳, 保, 保（两保 ratio 全知） | 第一条稳 | 冲里最高 | 最后保 | null | 有保底档位 | 完整 | false |

### 8.4 输出结构

```python
@dataclass
class EntryRef:
    level: Literal["unit","volunteer"]
    id: str
    position: int
    school_name: str
    major_name: str | None
    path_tier: Literal["冲","稳","保","unknown"]
    school_ratio: float | None           # schoolEnrollRatio，0-100
    major_ratio: float | None            # join 到的专业级 ratio，仅证据

@dataclass
class LandingScenario:
    scenario_id: str
    label: Literal["upside","base","downside","no_safe"]
    structure_status: str                # 首个稳/保位置 / 冲档最高校线率位置 / ...
    condition: str                       # 若前序均未满足 / 若冲档命中 / 无
    landing_entry: EntryRef | None
    path: list[EntryRef]
    drivers: list[str]
    caveats: list[str]
    evidence_refs: list[str]

@dataclass
class AdmissionInterpretation:
    status: Literal["completed","no_plan"]
    plan_version: int
    generated_at: str
    admission_mode: Literal["major","major_group","unknown"]
    scenarios: list[LandingScenario]
    base_landing: LandingScenario | None
    safety_coverage: Literal["有保底档位","保底档位存在、数据不足","无保底档位","无法判断"]
    tier_coverage: float
    ratio_coverage: float
    data_completeness: float
    data_completeness_band: Literal["完整","有缺口","严重缺口"]
    order_anomaly: bool
    caveats: list[str]
```

### 8.5 面向用户的表达

正例（结构说明）：

> 按当前方案结构：**首个稳/保位置**在第 18 志愿（稳档，校线录取率 62；
> 往年明细可查则补上，查不到就标“缺往年明细”）；**冲档最高校线率位置**在
> 第 6 志愿；**最后保底位置**在第 45 志愿。方案**有保底档位**，数据完整度：
> 完整；顺序无异常。
> 注意：这是结构与条件情景说明，不是录取预测；不表示会被某校录取，也不表示
> 滑档风险高或低；今年计划/热度/投档规则变化会影响实际结果。

反例（禁止）：

- “你有 73.2% 的概率被 A 录取。”
- “保证不会滑档 / 滑档风险低。”
- “肯定能上 / 较可能被 A 录取。”
- 只给一句“风险较低”或“最有希望的冲”而不说结构位置、条件和数据缺口。

### 8.6 卡片与入口

- 对话卡：`interpretation.preview`，展示结构/条件情景（首个稳/保位置、冲档最高
  校线率位置、最后保底位置、无保底档位）、`safetyCoverage`、数据完整度、顺序异常、
  证据缺口；不展示 likelihood/slipRisk 预测标签。`重新解读` / `调整方案` 按钮。
- 触发：用户主动问；方案变更后系统主动提供“要不要看录取落点”。**不声称
  review 会主动发现滑档**：review 目前没有专门滑档规则；若 `safety_guard`
  失败或 `ratio_distribution` 异常，只能作为解读的 drivers/caveats。
- **默认出现规则**：凡是“方案类问题”（“这个方案怎么样 / 这些学校稳不稳 /
  我能上哪 / 会不会滑档”），回复默认带一句落点摘要；单点事实问题（只问某校
  历史分/学费）不强制。摘要与完整卡都必须来自解读服务，不能由模型自己推。
- 只读：不产生 pending，不写方案；调整方案走正常 proposal 确认链。

### 8.7 数据缺口与合规

- 缺 `pathTier`（`OrderedItemDTO.tier` 缺失/非法）：该条标 `unknown`，不参与
  “保/稳/冲”判断；整体给“数据不足，无法判断”，不硬编结论。
- 缺专业级 ratio（join 不到候选池）：`majorAdmissionRatio=unknown`，但
  `pathTier` 仍可用；不要把 tier 冒充专业 ratio，也不要因此把整条判 unknown。
- 缺历史明细（preview/plan 都不投影历史）：落点条目可以标明“按系统档位判断，
  往年明细未取到”，不能把 `rankInTier` 伪装成往年位次。
- 专业组/调剂/批次政策变化：列为 caveat；不把外省规则套到本省；不声称做了
  省考试院级的投档模拟。
- 组级历史 `admission.get_history` 可能返回 `unsupported_scope`：caveat 写明
  “组级历史不可查”，不要编。
- 不承诺录取；不使用“概率/命中率/较可能/有机会/风险较大/滑档风险低或高”等
  预测词；只用“首个稳/保位置、冲档最高校线率位置、最后保底位置、无保底档位、
  数据缺口、顺序异常”等结构标签。
- 不展示内部系数、权重、打分；证据只给年份、省份、位次区间、计划数等可核验信息。

## 九、契约与数据模型

### 9.1 新增只读工具

`planning.interpret_admission`（MCP 只读，能力 `admission_read`）：

```json
{
  "planVersion": 12,
  "counterfactual": {"removeEntryRefs": [{"level": "unit", "id": "..."}]}
}
```

- **不带 `chatSessionId/tenantId/sessionId/userId`**：MCP 身份只来自 binding
  （`_trusted_arguments` 会丢掉这些字段）；会话由 Java 内部接口从受信参数取。
- `planVersion` 必填；它就是当前的 `stateVersion`（`planningState.version =
  workspace.version = snapshotVersion = sourceVersionGuard`，同一计数器）。
  **不要**声称它是内容版本；缓存键用
  `stateVersion + planContentDigest + candidateSourceVersion +
  dataFreshnessState.dataVersion + objectiveModelVersion + admissionMode`，
  `planContentDigest` 由工作/顺序方案内容计算；review 本身会让 stateVersion +1，
  所以不能只用 stateVersion 判断“内容是否变了”。
- `counterfactual`  MVP **只支持 remove**；add/replace/reorder 留后续。
- 返回 `AdmissionInterpretation` + `evidenceRefs`（只引本次实际上游证据；
  MVP **不新签 computed 证据**，没有就空数组，不伪造）。
  实现位置：Java `PlanAdmissionInterpretationService`（只读），agent MCP 转发；
  模型只做叙述，不做算术。
- 版本不一致返回 `stale_interpretation`；无方案返回 `no_plan`；不返回空壳。
- 能力 `admission_read` 已存在；不需要新增 `review_read`。
- **注册必须补全**：`TOOL_INPUT_SCHEMAS["planning.interpret_admission"]`
  （`planVersion` required integer、`counterfactual` optional，`additionalProperties:false`）、
  `TOOL_DESCRIPTIONS`、`TOOL_KINDS`（新增 `interpretation` 或明确复用理由）、
  `TOOL_OUTPUT_SCHEMA.kind` 的 enum；`server.py` 的 `tool_listing()` 会对每个
  READONLY_TOOL_NAMES 取 schema，缺条目会让整个 ListTools `KeyError`。
  测试必须调用 `tool_listing()`，并更新 `test_domain_mcp_tools.py` 的只读命名断言。

实现约束：

- **优先只读 `orderedPlanState`/`workingPlanState`**：条目已带 `tier`、
  `position`、`locked/pinned`；不需要每次重扫 4–29MB 候选池。
- **候选池拆分，不是 `$ref`**：`planningState` 可能因候选池拆分而只有瘦池 +
  `candidatePoolRef{len,md5}`；`loadPlanningStateReadOnly` 已调用
  `backfillCandidatePoolFromSplitRow` 回填 `candidatePoolState.items`。
  `workingPlanState`/`orderedPlanState.units[].majorItems` 是**内联字段**，没有
  `$ref` 解析器；不要自己写 `$ref` 展开器。若真实库出现 `$ref`，先给可复现样例
  再单独设计。
- **join**：`OrderedItemDTO` 没有 ratio，按 `volunteerId` join 候选池；join 不到
  标 `major_ratio=unknown`，不静默用 tier 冒充。
- **join 性能**：`loadPlanningStateReadOnly` 可能把整份候选池（4–29MB）解析进
  内存；J2b 必须按 `planVersion + candidateSourceVersion + dataFreshnessState.
  dataVersion + objectiveModelVersion` 建一次 `volunteerId -> CandidateItemDTO`
  派生索引并缓存（进程内 LRU，容量有界），不要每个请求重扫；缓存失效测试要覆盖
  候选池刷新/方案版本变化。
- 历史明细按落点条目**按需**查 `admission.get_history`，不逐条全量拉。
- 只读：不创建 pending、不写方案、不改审查状态。

### 9.2 事件与卡片（先复用现有回执，不新增 system.action）

**结论：不新增 `system.action`。** 当前 codex 写路径没有真正的后台自动动作源；
审查只在 apply 时随 `rerunReview` 发生，结果已经由 `conversationAction.result`
返回（`ConvoAction.result` → `_action_result_payload`）。再发一条 `system.action`
会把同一笔变更说两遍，而且没有 turnId、没有白名单、没有 reducer。

- J3 降级为：扩展现有 `conversationAction.result` 的 payload，加
  `origin`、`actionType`、`scope`、`receipt` 摘要；仍然只有一张卡。
- 真正的后台自动动作（如果以后有）必须先定义 Java→agent 通知/拉取、`EVENT_TYPES`、
  turnId、16KB 上限与去重顺序，再另立切片；**在 undo/回滚落地前不做自动改方案**。
- 解读卡走**有界事件 payload**（不走 artifact 明细）：
  1. `planning.interpret_admission` 返回完整 `AdmissionInterpretation`；
  2. 网关发 `interpretation.preview`，payload 直接带**有界摘要**：
     `planVersion/admissionMode/safetyCoverage/orderAnomaly/
     dataCompletenessBand` + `caveats: string[]`（最多 5 条）+ `scenarios[]`，
     每场景只带
     `{label, structureStatus, condition,
     landingEntry:{schoolName,majorName,position} | null, caveatCount}`；
     不带完整 `path`/全部 drivers；
  3. 网关做 16KB 上限检查：超限时只保留 base/downside/no_safe + 前 3 条 caveat，
     并在 payload 标 `truncated=true`；
  4. 前端 `InterpretationCard` 直接渲染 payload，不按 artifactRef 取数。
  5. **发射时机**：在网关校验完 `TurnOutput` 后、`turn.completed` 之前发
     `interpretation.preview`（与 `proposal.preview` 同一条收尾路径）；事件失败
     只丢卡，不影响的只读结论/正文，不需要回滚（解读不写状态）。
- artifact store 只存身份摘要、不存 payload（`artifact_store.py:140-160`），
  因此**不要**在设计与计划里声称“按 artifactRef 取明细”；完整 `path`/drivers
  留在工具结果与正文，卡片只展示摘要和落点。
- 必须同时改：服务端 `ui_events.py` 的 `EVENT_TYPES`/payload 白名单、
  `event_store.py` 类型的接受、`conversationSession.mjs` reducer、`server.py`
  `_LEGACY_FRAME_TYPE`、前端 `conversationEvents.mjs` 白名单、
  `MessageList/index.tsx` 渲染分支、`conversation.ts` 类型；单条事件 ≤16KB。
- 缺数据时卡片显示 `unknown` 与缺口原因，不显示空白。

### 9.3 控制层契约

- `JourneyContext`：agent 侧 `journey.py` 派生（数据来自 Java 快照 `journey` 块），
  注入提示/工具返回；不落库。
- `DialogueController`：**不新建独立进程/服务**；就是 `journey.py` 的
  `validate_action` + 网关 `validate_turn_output` 的硬不变量校验（一轮一个写、
  有 pending 才能 confirm、版本守卫、已知阻断）。失败返回固定文案，不走 repair
  重试；不替代 Java 确认链。
- `TriggerCatalogue`：提示词/技能 + **契约校验器单测**（验证载体/状态/槽位）；
  可选的 live eval 只做报告，不当作 CI 回归；后端只做白名单校验。

## 十、旅程集成与系统动作

### 10.1 自动生成/审查如何通知对话

**先纠正现状**：codex 写路径没有调用 `initial-plan/generate` 或 `review/run` 的
入口；审查只在 apply 时随 `rerunReview=true` 发生，结果已经通过
`conversationAction.result` 的 `actualChanges/reviewState` 返回。所谓“自动生成/
重排”在 codex 模式下目前**没有生产者**（legacy 才有）。

因此：

1. **不新增 `system.action`**；J3 只扩展现有 `conversationAction.result` 的
   payload（`origin/actionType/scope/receipt` 摘要），仍然一张卡。
2. 如果以后要真正的后台自动动作，必须先定义 Java→agent 的通知/拉取、服务端
   `EVENT_TYPES`、turnId、16KB 上限、reducer 与去重顺序；在 undo/回滚落地前，
   不允许自动改方案。
3. 前端仍用现有 ProposalCard/回执卡；助手正文复述回执要点 + 下一步建议，
   不重复罗列卡片明细。
4. 用户下一轮问“刚才改了什么”，直接引用最近一条 `conversationAction.result`，
   不重新跑生成。

### 10.2 每次写动作后的固定收尾

```
回执卡（改了什么）
  + 一句取舍解释（为什么这样改）
  + 一个下一步建议（审查 / 解读 / 继续调整）
```

不允许只回“已生效”三个字；也不允许在没收到结果事件前说“已生效”。

**结构解读的默认出现位置**：方案首次生成、方案变更、审查完成这三类回复，正文末尾
可带一句“结构摘要”（例如“首个稳/保位置在第 18 志愿，方案有保底档位，数据完整；
这是结构说明，不是录取预测”）。完整结构/条件情景卡按用户追问或主动提供，不必
每轮重复；摘要必须来自回执/解读服务，不得由模型自行推断。**不得写“按往年位次/
最可能/较可能/滑档风险低”**。

**生产者**：apply 后已有续接回合（`server.py:1230-1305`）。J2b/J2c 要在这个续接
回合里调用一次 `planning.interpret_admission`（只读），把摘要放进正文；如果调用
失败或没有方案，就不写摘要，不能由模型自己推。不新增后台任务/事件。

### 10.3 主动时机

| 时机 | 主动作 | 不做什么 |
|---|---|---|
| 画像齐 | 推荐 2–3 个方向 | 不开放反问 |
| 候选生成 | 给冲稳保与取舍 | 不直接写方案 |
| 方案生成/变更 | 回执 + “要不要审一下/看落点” | 不重复生成 |
| 审查完成 | top 问题 + 修复选项 | 不静默改方案 |
| 解读完成 | 落点 + 改变建议 | 不承诺录取 |
| 版本冲突 | 恢复选项 | 不硬写 |

### 10.4 一条完整对话示例（验收脚本）

```
用户：我想学电气，省内为主，先看看方向。
系统：这轮按方向探索走。先给 2–3 个带理由的方向（电气/自动化/能源），
      再问“要不要按省内优先收敛”。（explore，不写）

用户：就电气和自动化，省内优先。
系统：方向已记下；地域“省内优先”是软偏好，不是硬排除。
      出“偏好确认”卡（有效期按真实行为说明，见行为真值表），确认后进入候选。
      （preference，写）

用户：按这个排一版。
系统：这轮按方案构建走。给默认总量与冲稳保口径，出方案预览；
      用户确认后执行。（build，写；预览 → 确认 → 回执）

用户确认后：执行结果卡显示 45 条（冲13/稳13/保19）、审查摘要；
      同一张卡 + 正文末尾一句：“首个稳/保位置在第 14 志愿，方案有保底档位，
      数据完整；这是结构说明，不是录取预测。”
      （没有 system.action、没有后台自动生成；审查随 apply 的 rerunReview 返回）

用户：我这样能上哪？会不会滑档？
系统：这轮按结构解读走（只读）。出结构卡：
      首个稳/保位置（第 14 志愿）、冲档最高校线率位置、
      最后保底位置、无保底档位/数据缺口；不输出录取概率或滑档风险等级。
      （interpret，不写）

用户：把最后一个保底去掉会怎样？
系统：只读结构反事实：最后保底位置变化 / 是否变成“无保底档位”；
      数据缺口与顺序变化一并说明；不输出概率或风险等级。
      不建议直接删；如果要删，给“删除预览”而不是直接执行。
      （interpret counterfactual，不写）

用户：那别删，再加两条保底。
系统：这轮按点名加入走（默认 EXPAND）：出预览“45→47、零删除”，
      确认后执行；执行后回执 + 审查 + 新结构摘要。
      （add_units，写；一轮一个写）
```

验收时按这条脚本逐轮检查：路由句、卡片类型、是否写、回执、落点摘要、
是否有未经确认的删除。

### 10.5 自动动作触发逻辑（什么时候系统自己动）

自动动作只允许**只读或可回执**的步骤；任何会改方案的自动动作必须满足
“用户已确认的口径 + 版本一致 + 可撤销/可预览”。默认策略：

| 触发源 | 自动做什么 | 不自动做什么 | 通知 |
|---|---|---|---|
| 用户应用了 scope/学费（风险姿态 J6 后） | 记录约束；标记方案/候选池 stale；给“按新口径重排”的**预览入口** | 不静默重排已确认方案；不自动生成 | 现有回执卡 + “要不要重排” |
| 用户点名加入/删除/替换 | 执行确认链；`rerunReview=true` 时随结果返回审查摘要 | 不在执行前偷偷改其他条目；不另发第二张卡 | `conversationAction.result` 一张卡 |
| 方案任何写动作完成 | 已有 `rerunReview` 才重跑审查（只读） | 不自动再生成；不新增后台审查 | 同一张回执卡 |
| 补录成绩/位次 | 标记方案 stale；给影响摘要 | 不自动重生成 | “成绩变了，方案需要重算”提示 |
| 候选池更新/数据过期 | 标记 stale；给恢复选项 | 不自动替换候选 | stale 提示 + 恢复按钮 |
| 审查发现高风险 | 提示并给修复选项 | 不自动修复；不声称 review 有滑档规则 | 审查摘要 + 修复选项 |
| 定时任务/后台刷新 | 只更新数据新鲜度 | 不自动改方案 | 通知，不伪造用户回合 |

规则：

1. **一次触发只做一件事**：应用约束和重排是两步，先约束、后预览重排；不把
   “改约束 + 重排 + 审查”合成一个不可见的大动作。
2. **版本闸**：任何重排/执行前检查 `sourceVersion`；不一致就停在恢复，不追着改。
3. **去重**：同一 `sourceVersion` + 同一动作只跑一次；重复触发返回已有回执。
4. **可见**：每个动作都有现有回执卡/结果；没有回执的动作视为没有发生。
5. **可撤销**：自动重排/替换类动作要能回到上一版；在 undo 落地前，不做自动改方案，
   只给预览入口。第一期至少保留 operationLog 和回执。

## 十一、实施切片

| 切片 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| J1a | Java 快照新增紧凑 `journey` 块 + agent 派生 `statePhase` | 无 | 快照字段/接口测试；不新增表 |
| J1b | 触发目录（载体/状态/失败行为）+ 技能/提示词 | J1a | 契约校验器单测；planned 动作不在活跃提示词 |
| J1c | 网关硬不变量校验（一轮一个写、pending 才能 confirm、版本、已知阻断） | J1a/b | 确定性单测；失败固定文案，不 repair |
| J2a | Java 纯函数 `PlanAdmissionInterpretationService` + 真值表 fixture | 无（只读数据） | 13 行真值表全绿；unit/major 两模式 |
| J2b | Java inner 接口 + MCP `planning.interpret_admission` + 证据签发 | J2a | 版本/stale/no_plan/join 缺失；MCP 无 chatSessionId |
| J2c | 解读卡事件/reducer/MessageList/前端卡 | J2b + 事件合同 | 只发有界摘要；16KB 内；缺数据 unknown |
| J3 | 扩展 `conversationAction.result` 回执（origin/actionType/scope） | 现有 apply 回执 | 一张卡；不新增 system.action；undo 前不自动改方案 |
| J4a | scope/学费持久化 + stale 标记 + REPLACE | J1/J2a 数据口径 | 重新生成后 scope 不丢；学费更新标 stale；预览列全新增/移出 |
| J4b | remove/move/pin（各自 frozen command/后置条件） | J4a | 一轮一个写；后置条件；可回滚 |
| J5 | **统一目标/评价/优化（含审查）**：J5.0 先定义 `EvaluationContext` + 14 个 probe 全表 + `PlanEvaluation` + golden diff；再 CandidateSnapshot → IntentModel → ObjectiveCompiler → Solver + PlanEvaluator → Postcondition/StructureVector/PlanEvaluation；finding → objective_delta → 同一 PlanCommand | 10-17 分析报告；J4a scope 持久化 | 另立路线图（阶段 0–6），不纳入本批；J5.0 未完成前不切 probe |
| J6 | 风险姿态 + 目标优先级排序（作为 ObjectiveModel 层） | J5 | 另立路线图，不纳入本批 |

部署顺序：**J2a/J2b（先文本）→ J1a/J1b/J1c → J2c（卡片）→ J4a → J4b**。
J3 只在现有回执上做，不新增事件；J5 合并原报告阶段 5（审查闭环），按
“基线/评价模型 → 候选统一 → objective compiler + evaluator → solver →
后置条件/审查 → 审查→动作 → 清理”推进，J6 作为 ObjectiveModel 层跟在后面。
每批部署前跑定向测试；部署后先跑 WS 连通性 + 一轮只读解读，再让用户验收。

## 十二、测试与验收

### 12.1 触发目录：契约校验，不冒充模型回归

- 40 条 fixture 必须通过 **契约校验器**：动作在 `JourneyAction` 里、载体/状态
  合法、写动作槽位非空、planned 动作不在“可用”集合。
- 它**不证明**模型会按目录走；如果要验证路由，另跑可选 live eval（固定模型版本/
  温度，记录实际动作与命中率），不纳入 CI 必过。
- 歧义条目必须有 `ambiguity` 与“只问一次”的期望；不得静默写。

### 12.2 录取解读：真值表 + 数据口径

- 必须逐行覆盖 §8.3 的 13 行真值表；重点边界：
  - `schoolEnrollRatio` = 50/70 的归属（`<=50 冲`、`<=70 稳`、`>70 保`）；
  - 校线 60/专业线 40：`pathTier=稳`，专业 ratio 只做证据，不改档；
  - 校线 45/专业线 75：`pathTier=冲`，不得升级成保；
  - `OrderedItemDTO` join 不到候选池：`major_ratio=unknown`，`pathTier` 仍可用；
  - 保出现在稳之前：`base` 按实际顺序取保，`order_anomaly=true`；
  - 无保/全冲/全保/空方案/全部 unknown；
  - unit 模式与 major 模式各一组 fixture。
- 断言：base/upside/downside/no_safe 是否存在、structure_status、condition、
  safety_coverage、data_completeness_band、order_anomaly；**不出现**
  likelihood/slipRisk/“最可能/较可能/滑档风险低”。
- 反事实 MVP 只测 remove；删除全部保底 → safety_coverage 变“无保底档位”，
  不是“风险上升”。
- J2a 直接消费 `ReviewStateDTO.checks`；不造 `PlanEvaluation` 适配器。
- 证据：MVP 不新签 computed 证据；`evidenceRefs` 只引上游证据，没有就空数组，
  不得伪造。

### 12.3 控制流与事件

- 新预览 supersede 旧 `prepared`：旧卡失效、文案说明；`pending_applying` 拒绝新写。
- 一轮一个写；有 pending 才能 confirm；版本守卫；已知阻断给固定文案。
- 不新增 `system.action`；现有 `conversationAction.result` 只有一张卡。
- 解读卡事件只带有界摘要；完整 path/drivers 留在工具结果与正文；事件 ≤16KB；
  reducer/legacy 映射有测试；不按 artifactRef 取明细。

### 12.4 端到端（不冒充自动动作）

- 点名加入六条 → 预览 45→51 → 确认 → 回执 + 审查摘要（现有路径）。
- 有方案时请求解读 → 文本先通 → 卡片事件 → 前端渲染；无方案 → 明确提示。
- 去掉全部保底 → 结构反事实显示“无保底档位” → 用户确认后才真删；
  不输出“风险上升”。
- **不测**“自动北方优先重排 → 系统动作卡”：该自动源当前不存在，等 J3/后台动作
  另立设计后再测。

## 十三、风险与开放问题

1. **数据口径（已修正）**：`pathTier` 只来自校线 `schoolEnrollRatio`
   （`<=50/<=70/>70`）；专业级 ratio 只做组内证据。开放项：历史明细覆盖不足、
   组级历史不可查、计划数变化未进入算法。
2. **同档相关性**：MVP 用保守路径，不做独立概率相乘；后续是否引入相关模型需
   回测。
3. **专业组/调剂**：当前数据没有专业组代码；解读只能到院校专业层，不能假装
   有组内调剂信息。
4. **状态规模**：单会话 planningState 可达 1–4MB、候选池 4–29MB；解读必须
   按 `planVersion + candidateSourceVersion + dataVersion + admissionMode` 缓存，
   不能每轮重扫。
5. **模型自由度**：触发目录是提示词约束，模型仍可能走偏；必须用后端硬不变量 +
   契约校验器兜底，不能只靠提示词，也不能把 fixture 自检说成模型回归。
6. **没有真正的后台自动动作**：codex 写路径目前没有自动生成/重排入口；J3 只能
   扩展现有回执。若以后要后台动作，先补通知/事件/turnId/16KB/undo，不能先上
   “系统自己改方案”。
7. **REPLACE 未实现前**：用户说“必须有/总数不变”时只能如实说明并给替代选项，
   不得用 EXPAND 冒充；`must_include_scope` 满方案最多替换 1 组。
8. **scope/学费不能统一写“仅本次”**：scope 经 `apply_constraint_and_regenerate`
   写 `constraintState` 并重排；学费写 `userScoreDetail`，提案命令路径会重排。
   卡面按 `2026-10-18-constraint-lifecycle-truth-table.md` 的真实行为写，不得一刀切。
9. **review 产物/能力**：`review_read` 没有消费者；`plan-final-review` 暂保持
   人工审查，不签发 review artifact。J2 解读直接引用现有 `reviewState.checks`，
   J5 后再换 `PlanEvaluation`。

## 十四、修订记录

- v1（2026-10-18）：首稿。基于 10-17 优化器分析、add_units v6 契约、当前工具/卡片
  盘点；纳入用户 2026-10-18 三条产品口径（默认扩总数、默认持久、稳健/均衡/进取 +
  目标优先级）。
- v2（2026-10-18）：按独立审查（BLOCK，B1–B9）修订。核心变化：拆分
  `pathTier`/`majorAdmissionRatio`；JourneyContext 改为快照 journey 块 + 两阶段
  派生；场景算法改顺序扫描 + 真值表；删除 `system.action`，复用现有回执；解读卡
  走 tool→有界摘要事件；承认 supersede/pending_applying；scope/学费持久化
  列为 J4a；触发目录补载体/状态/失败行为；J1/J2/J4 拆分，J5/J6 另立路线图。
- v3（2026-10-18）：按 v2 审查（BLOCK，N1–N7）修订。补 agent journey 合同/投影/
  注入；重写 §8.3 互斥穷尽规则与真值表；删除结论/验收脚本的 system.action 与
  “最可能”；解读卡改有界事件 payload（不依赖 artifact 明细）；工具改名
  `planning.interpret_admission`；补 MCP schema/kind/注册测试；J4a 前 scope/学费
  只写“仅本次”；补 join 缓存、证据 dataVersion、J3 文件、tradeoffs 生产者与
  apply 后续接摘要任务。
- v3.1（2026-10-18）：按 v3 审查窄口修订。统一 slip_risk 规则与真值表（13 行）；
  删除 computed 证据签发；计划 J2a 对齐 pathTier/base/slip/13 行；清理 artifact
  明细残留；补 StatePatch journey、plan_version 注入、TOOL_LABELS/TOOL_CONTRACTS。
- v4（2026-10-18）：按用户口径把**审查与优化合并为同一评价模型**。新增
  `PlanEvaluation`/`EvaluationFinding`；审查 check 变 probe；审查 finding 带
  objective_delta，修复走同一 `PlanCommand`；解读消费 `PlanEvaluation`（MVP
  适配 `ReviewStateDTO`）；J5 升级为“统一目标/评价/优化（含审查）”阶段 0–6。
- v5（2026-10-18）：按语义权威深度审查（BLOCK）修订。版本改为单计数器 +
  `planContentDigest`/`evaluatedStateVersion`；补 14 probe 全表、ID 表、J1a
  stale/pendingStatus/hasPlan；删除 `$ref` 伪前提；J2a 直接消费
  `ReviewStateDTO.checks`，不造适配器；不删持久化字段。
- v6（2026-10-18）：按全链路评审（F01–F09）收口。新增 §〇·五统一方案处理协议：
  完整要求优先于最小变更；一轮一个 ChangeSet ≠ 一个意图；确认/纠正优先级；
  约束行为真值表；结构版解读（删除 likelihood/slipRisk）；统一目标顺序；缓存
  tenant/session 隔离；不可变输入清单；A–F 交付顺序。J2a 代码已降级为结构情景。
