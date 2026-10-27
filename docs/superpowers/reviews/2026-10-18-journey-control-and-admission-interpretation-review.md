# 用户旅程、对话控制与录取解读设计（v1）独立审查

对象：`docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`
（v1，2026-10-18）
实现计划：`docs/superpowers/plans/2026-10-18-journey-control-and-admission-interpretation.md`
基线：`616464c`（工作区含 add_units EXPAND 未提交改动）
日期：2026-10-18
方式：只读审查（未改设计稿/代码、未跑测试、未部署）

## 一、结论

**BLOCK。**

方向是对的：三问题诊断准确；保留模型驱动路由与确认链；只读解读不编概率；
正确识别了 `rankInTier` 不是历史位次、历史没有投影到 preview/plan、review 没有
专门“滑档”规则。但设计稿在进入实现前有 9 个 blocker：其中数据口径（B1）、
旅程可派生性（B2）、场景算法可判定性（B3）会直接产生错误或不可测试的实现；
事件/卡片合同（B6/B8/B9）在当前代码里没有生产者或没有白名单；
scope 持久化（B4）是已拍板产品口径但没有切片；触发目录（B5）和 pending 规则（B7）
与现有契约/行为冲突。

下面每条 blocker 都给出代码证据、为什么阻塞、最小修复。Majors/Minors 见后。

## 二、Blockers

### B1. 录取解读把 `tier` 与 `admissionRatio` 当成同源同粒度，数据口径不成立

**证据**

- §8.2（spec:447-454）写“候选行和方案单元已经带 `admissionRatio`（专业级，0–99）
  与 `schoolEnrollRatio`（校级）；系统档位按固定边界派生：`<50 冲`、`50–70 稳`、
  `>=70 保`（`admission/facts.py:53-66`）”，§8.3（spec:492-497）又写“两者冲突时
  以 `tier` 为准并标 `unknown` 风险”。
- 候选 `tier` 实际来自推荐流水线按 **`schoolEnrollRatio`（校级）** 的三区间：
  `VolunteerIntervalService.java:96-102`（`ratio <= 50` 冲、`<= 70` 稳、否则保）；
  `PlanningStateService.java:9329-9330,9349` 只是把区间名写进 `tier`。
- `CandidateItemDTO.admissionRatio` 在专业行是 `major.getEnroll_ratio()`（专业级，
  `PlanningStateService.java:9361`）；在没有专业行的校行是 `school.getEnroll_ratio()`
  （校级，同文件 `:9331`）；`schoolEnrollRatio` 另存校级（`:9910`）。
- 方案侧更不一致：`OrderedUnitDTO.admissionRatio` 在主要构建路径取
  `candidate.getSchoolEnrollRatio()`（校级，`PlanningStateService.java:12757`），
  但另一条路径会把 `PlanningUnitDTO.admissionRatio`（代表专业的 ratio，
  `:4806`）回填进来（`:12951-12953`）——同一个字段可能是校级也可能是专业级；
  组内 `PlanningUnitMajorDTO.admissionRatio` 才是专业级（`:12736`）；
  `OrderedItemDTO` 根本没有 `admissionRatio` 字段（`OrderedItemDTO.java:6-18`）。
- `admission/facts.py:53-61` 的 `derive_risk_tier` 是招生事实工具对“招生单元录取率”
  的规范化函数，不是候选池档位来源；且边界是 `<50`，与 Java 的 `<=50` 在 50 这个点
  不一致。

**为什么阻塞**

“校线 60（稳）+ 专业线 40（冲）”是完全合法且常见的候选形态。按本设计会被判成
“tier 与 ratio 冲突 → unknown”，或者按 §8.3 的 OR 规则把一个校线“冲”升级成“保”。
这不是数据缺口，是口径错误；J2 的基准落点、upside 判断、unknown 比例都会系统性
偏错。`OrderedItemDTO` 没有 ratio 这一点还会让 major 模式下的当前方案解读无输入。

**最小修复**

明确两套信号并禁止互相覆盖：

1. `pathTier`：只由 `schoolEnrollRatio` 派生（与 `VolunteerIntervalService` 同边界，
   写清 `<=50`/`<=70`/`>70`）；这是“冲稳保路径”的唯一档位来源。
2. `majorAdmissionRatio`：只在专业行/组内专业上使用，作为组内证据；不得用来改
   `pathTier`，也不得与 `pathTier` 做“冲突判 unknown”。
3. 方案条目：`OrderedItemDTO` 必须按 `volunteerId` join 候选池取 ratio；join 不到
   标 `unknown`，不要静默用 `tier` 代替。`OrderedUnitDTO` 用校级 ratio，
   `majorItems` 用专业级 ratio，并在输出里带 `signalSource`/`level`。
4. 边界统一为 Java 推荐流水线的口径；`admission/facts.py` 只用于招生事实工具，
   不用于候选/方案解读。
5. 增加 fixture：校线 60/专业线 40、校线 45/专业线 75、ratio 缺失、ratio=50/70
   四个边界点。

### B2. `JourneyContext` 在当前快照上不可派生；`journeyPhase` 依赖本轮用户意图

**证据**

- `JourneyContext` 要求 `has_profile/has_candidates/has_plan/plan_version/stale`
  （spec:226-246），但 `ConversationTurnSnapshotDTO.java:9-20` 只有
  snapshotVersion、admissionMode、planningStage、scoreContext、
  confirmedConstraints、preferences、activeProposal、missingFacts、
  allowedCapabilities、evidence、admissionFacts；没有 staleFlags、没有
  workingPlanState/orderedPlanState、没有 candidatePoolState 是否存在。
- `ConversationSnapshotService.java:42-52` 只填这些字段；`:130-140` 的
  `fillMissingFacts` 只补 province/score/rank。
- `PlanningWorkspaceStateRes.java:10-24` 确实有 `staleFlags`/`candidatePoolState`/
  `workingPlanState`/`orderedPlanState`/`reviewState`，但它们在投影到快照时被丢弃。
- `working_set.py:70-81` 完全由快照构建；`candidate_entities` 只来自本会话工具的
  payload（`:125-152`），不是候选池的权威存在性；`:83-105` 在 stage 变化时清空候选。
- `planningStage` 也不可靠：`PlanningStateService.java:618` 在补录成绩后把 phase
  重置为 `profile_ready`，但现有 working/ordered plan 并不清空。此时“有方案”
  无法从 phase 推出。
- §3.4（spec:157-166）用“用户在问方向/城市/院校”“用户在问风险/问题/审查”
  “用户在问能上哪/会不会滑档”作为 verify/review/interpret 的推导条件；但网关在
  模型看到用户消息之前就构造上下文（`service.py:2440-2510`），且路由是模型驱动，
  没有意图分类器。这些行在 pre-turn 不可计算。
- 实现计划 `2026-10-18-...md:51` 的函数签名多了一个 `last_action`，但快照/工作集
  没有“最近动作”字段（`working_set.py` 只有 `last_response_type`/`last_turn_id`），
  与 spec §4.4 的“snapshot + working_set + 最近 pending”不一致。

**为什么阻塞**

`has_plan`/`has_candidates`/`stale`/`plan_version` 会普遍是 false/unknown；phase 会
在“补录成绩后仍有方案”等真实形态下判错；`available_actions`/`blocked_actions` 随之
判错，后端白名单会误伤合法动作。J1 的核心承诺“派生、不要求 Java 新增字段”不成立。

**最小修复**

二选一，并写进设计：

- **A（推荐）**：在 Java `ConversationTurnSnapshot` 增加一个紧凑的 `journey` 块：
  `hasCandidates/candidatePoolSourceVersion/hasPlan/planEntryCount/planVersion/
  staleFlags(subset)/reviewSourceVersion`。这是小字段扩展，不是新表。
- **B**：网关在回合开始额外调用 `workspace-state`（`internal_client.get_planning_workspace_state`
  已存在），从 workspace 派生；代价是每轮多一次内部请求，且要处理失败降级。

同时把 phase 拆成两层：

- `statePhase`（pre-turn，状态派生）：discover/candidates/build/review 等；
- `taskIntent`（post-model，模型判断）：verify/interpret/review/adjust。

不要在 pre-turn 声称能知道“用户这轮在问什么”；不要用 `last_action` 这种不存在的状态。

### B3. 四场景算法缺少可判定的输出规则；顺序假设与真实方案冲突；存在过度声明

**证据**

- §8.3（spec:487-512）只给了 `chance_band` 与“最早冲/最早稳/最后保”的选择规则；
  §8.4（spec:514-537）的 `likelihood_band`（较可能/有机会/风险较大/无法判断）、
  `slip_risk`（低/中/高/无法判断）、`data_coverage`、`drivers`、`caveats` 都没有
  判定规则或公式。
- “base = 最早的稳；没有稳取最早的保”；“downside = 最后一条保”；“upside = 最早的冲”
  这三条在用户可手动 move/pin 的方案上会给出矛盾路径：`PlanningStateService.java:2598`
  有 `moveOrderedItem`，`OrderedItemDTO` 有 `locked/pinned`（`OrderedItemDTO.java:6-18`）。
  如果方案顺序是“保、冲、稳”，`base` 会取到后面的稳，而实际顺序扫描会先被保接住；
  `downside` 取最后一条保也可能在某个冲之前。
- §8.5（spec:539-549）示例写“按往年位次，最可能在第 18 志愿……”，但 §8.3 的算法
  只用系统档位；`admission.get_history` 只在 §8.3.4 作为“补一条证据”，不参与落点
  判断，也没有“用户位次 vs 往年位次”的比较。`drivers` 里的“位次差”无实现。
- 粒度未定义：major_group 模式是“单元”还是“组内专业”？`EntryRef` 没有定义；
  `OrderedItemDTO` 无 ratio，`OrderedUnitDTO` 是单元级 ratio，`DraftUnitDTO`/
  `PlanningUnitMajorDTO` 是专业级（`DraftUnitDTO.java:9-16`、
  `PlanningUnitMajorDTO.java:10-35`）。
- §8.3.5 说反事实覆盖“去掉/加入/替换/重排”，但 §9.1 的请求体只有
  `counterfactual.removeEntryIds`（spec:584-589）。
- §12.2 验收要求“场景路径顺序、基准落点、滑档风险、unknown 传播”，但没有给任何
  expected JSON 或判定表；实现计划 J2-T1（plan:141-145）也只列 fixture 形态，没有
  likelihood/slip/dataCoverage 的期望规则。

**为什么阻塞**

J2 的验收标准“4 类场景正确”在当前定义下不可判定；不同实现者会给出不同的 base/
slip；而 `base` 被称为“最可能”会被用户理解为概率结论。这是本设计最核心的用户
可见输出，不能靠“实现时再定”。

**最小修复**

1. 写一张确定性真值表：输入（每条 `pathTier`、`majorAdmissionRatio`、顺序、
   `locked/pinned`、历史有无、用户位次有无）→ 输出（upside/base/downside/slip
   是否存在、每条 `likelihood_band`、`slip_risk`、`data_coverage`）。
2. 改为**按方案顺序扫描**：维护“当前路径”；第一个命中即落点；不要用“最早稳”
   跨过前面的保。对乱序/锁定/固定给出明确语义（例如“顺序异常，按实际顺序推演并
   在 caveats 标注”）。
3. 明确粒度：major_group 以单元为 EntryRef，组内专业只做组内证据；major 以
   volunteerId 为 EntryRef。`OrderedItemDTO` 必须 join 候选池。
4. 二选一：要么把历史/位次真正纳入判断（例如 base 条目有历史且用户位次高于往年
   最低位次 → 上调 band），要么删除“按往年位次/位次差”的措辞，只写“按系统档位”。
5. 反事实：要么扩展 `counterfactual` 支持 add/replace/reorder（并定义 entry 集合），
   要么把 §8.3.5 收窄为 remove 一种；`scenarioDepth`/`EntryRef`/`dataCoverage`/
   `drivers`/`caveats` 都要有定义。
6. 统一用“基准情景/系统档位判断”措辞，避免“最可能”在没有概率模型时被当成承诺。

### B4. scope/学费“默认持久”是已拍板产品口径，但没有任何切片落地

**证据**

- v6 产品口径：`docs/superpowers/specs/2026-10-17-plan-action-contract-design.md:17-18`
  “scope / 学费类意向默认持久（persist=true）……后续重新生成仍生效”。
- 当前实现：`PlanningStateService.java:1075-1111` 的
  `applyUserGoalTargetToPlanningState` 只持久化 `requirements`、`priorityRules`、
  `tierQuotaChange`、`selectionTargetCount`；`targetScopes` 不在其中，学费也不写回
  `userScoreDetail.tuitionRange`（后者另有 `ChatSessionBizService.java:216-245`，
  且不标记候选池 stale）。
- 10-17 分析报告 P0-2（`2026-10-17-plan-generation-and-fill-analysis.md:339-344`）
  已把“scope 不持久化、应用后可能被 solver/重生成撤销”列为 P0。
- 本设计 §5.1（spec:257）把“方向偏好”标成“是（确认后）”，§6.2（spec:351）写
  “学费上限默认持久”；但 J4（spec:661）只列 REPLACE/remove/move/fill，J5 也没有
  把 scope 持久化作为前置。

**为什么阻塞**

用户 2026-10-18 的明确产品决定是“默认持久”。如果 J1 的触发目录告诉模型“这是持久
偏好”，而 J4 执行后 scope 仍然一次性消失、学费更新不标 stale，用户会看到“说了不要
医学，下一版又出现”。这比不实现更糟，因为文案承诺了没有发生的事。

**最小修复**

增加 J4.0（或 J2 前置）：“scope/tuition 持久化”：

- 扩展 `applyUserGoalTargetToPlanningState` 持久化 `targetScopes`/`negativeScopes`/
  `tuitionRange`，带 `persist=once|session` 生命周期；
- `updateTuitionRange` 标记候选池/规划 stale（与 `resolveEffectiveCandidates` 同口径）；
- 卡片写“本次生效/以后都生效”；
- 测试：应用“只看北京”后重新生成，外地不回来；学费更新后 fill/scope/initial 都不选
  超预算候选。
在此之前，触发目录和卡片必须写“仅本次”，不能写“持久”。

### B5. 触发目录把不存在/未实现的载体写成可用动作，且 golden 测试不测模型

**证据**

- §5.1（spec:250-271）的动作族里：
  - `query_plan`、`review_plan` 不是 codex MCP 工具。`tools_readonly.py:25-97`
    的 `CAPABILITIES` 没有这两个名字；codex 的读方案是
    `planning.get_working_plan`/`admission.get_current_plan`，审查是
    `plan-final-review` 技能 + 只读工具，不是 `review_plan` 工具。
  - `proposalRequest(scope/only/exclude/prefer)`：`ProposalRequest.goal_type`
    （`contracts.py:325-333`）没有 `prefer`；软偏好只能走
    `requirements(kind=include,min_count)` 或 `priority_rules`。
  - `REPLACE / replace_units`：v6 明确“第一期只实现 EXPAND；REPLACE 作为下一纵切”
    （`2026-10-17-plan-action-contract-design.md:13-16,69-71,122-125`）。
    触发表没有标“待实现”，与 remove/move/undo 的标记方式不一致。
  - `regenerate/reorder`：没有对应 goalType；`prioritize_within_tier` 只在档内
    重排，不能表达“重新排一版”。表里没有标“待实现”。
  - “稳一点/冲一点”“保专业/保学校/保录取/城市/学费排序”：J6 才实现
    （spec:662-663），当前没有 contract；但 §5.3（spec:295-299）把它们写成动作。
- 实现计划 J1-T3（plan:77-100）的“golden fixture”测试只断言
  `expected_action` 在 `JourneyAction` 枚举里、`write=true` 且 `required_slots`
  非空——它**不调用模型，也不验证同一句话会走到哪个动作**。spec §5.4/§12.1
  却把它当作“防止同一句话换个说法走到别的动作”的回归测试。
- 另外：`must_include_scope` 在方案已满时只尝试替换 1 组
  （10-17 分析报告 `:376-377`），本设计 §5.3 没有把这个限制写进“必须有”的
  选项；`add_units` 在已确认精确档位配额时直接阻断
  （`UserGoalProposalBuilder.java:245-251`），触发目录/blocked_actions 也没有写。

**为什么阻塞**

模型会按目录去用不存在的动作，或者在“重排/稳一点/必须有”上给出不安全默认
（静默扩总数、只替换 1 组、必被 Java 拒单）。而所谓 golden 测试是静态 fixture
自检，不能证明触发行为；J1 的验收“40 条全绿”没有覆盖真实模型输出。

**最小修复**

1. 触发目录增加三列：**载体**（MCP 工具名 / `proposalRequest.goalType` /
   `conversationAction` / 技能名）、**状态**（已实现/工作树/待实现/不适用）、
   **失败时的用户可见行为**（blocked 文案/先问一次/降级只读）。
2. 把所有未来动作明确标 `planned`：REPLACE、remove、move/sort/pin、
   regenerate/reorder、risk posture、priority order、undo/rollback。
3. 把 `query_plan` 改成 `planning.get_working_plan`/`admission.get_current_plan`；
   `review_plan` 改成 `plan-final-review` 技能 + 读工具；`prefer` 改成
   `requirements(include)`/`priority_rules` 两种真实载体。
4. 把 `add_units` 的已知阻断（tierQuotaGoal、current != target、stale plan item）
   放进 `blocked_actions` 和触发表，避免死卡。
5. golden 测试二选一：
   - 真 eval：固定 40 条话术喂 codex，断言输出动作（接受非确定性、要记录模型版本）；
   - 或降级为“网关校验器单测 + fixture 只做契约覆盖”，并明确它不验证模型路由。

### B6. `system.action` 没有生产者，且与 `conversationAction.result` 重复；事件合同不完整

**证据**

- §10.1（spec:614-626）假设“自动方案生成、重排、审查在 Java 内部完成，完成后返回
  receipt/reviewState”。但 codex 写路径只有 `prepare`（`service.py:2871-2884`）；
  网关没有调用 `initial-plan/generate` 或 `review/run`；那些调用只在 legacy
  `app/zhiyuan_agent/tools.py:8135`。codex 模式没有“自动生成/重排”入口。
- 在 codex 网关路径，审查只在 apply 时随 `rerunReview=true` 发生，结果已经通过
  `ConversationActionResult.review_state`/`actualChanges` 返回
  （`conversation_actions.py:1035-1053`），并由
  `server.py:1083-1104` 的 `_action_result_payload` 发成
  `conversationAction.result`。再发一条 `system.action` 会把同一笔变更说两遍。
  （Java 另有直接 `/review/run` inner endpoint，`PlanningStateController.java:554-557`，
  但 codex 网关没有调用它；legacy 路径不属于本设计。）
- 事件类型不是只改前端就行：服务端有硬白名单
  `app/gateway/ui_events.py:18-37` 的 `EVENT_TYPES`，`event_store.py:171` 会拒绝
  未知类型；单条事件上限 16KB（`event_store.py:175-179`），而 `system.action` 的
  `scope`+`receipt`（可能含数十条条目）有超限风险。
- `UiEvent.turn_id` 是必填（`ui_events.py:95`）；自动/后台动作没有用户回合，
  没有明确的 turnId 策略；前端 reducer 按 turnId 归并
  （`conversationSession.mjs:41-43`）。
- spec §9.2 只写“前端 `conversationEvents.mjs` 白名单增加这两类”，没有提
  `ui_events.py`、`event_store.py`、`conversationSession.mjs` reducer、
  `_LEGACY_FRAME_TYPE`（`server.py:1567`）和事件体积。
- 实现计划 J3-T1（plan:225-229）自己写了“与 conversationAction.result 去重”，
  但没有去重/顺序规则；且它修改的是 `server.py`，而不是服务端白名单所在的
  `ui_events.py`。

**为什么阻塞**

J3 按当前设计无法产生事件：没有自动动作源；如果强行在确认路径再发，用户会看到
两张卡；如果后台动作发生在回合外，没有 turnId，事件流/reducer 无法正确归并。

**最小修复**

先决定事件模型，二选一：

- **A（推荐，若没有真正的后台动作）**：不新增 `system.action`。扩展
  `conversationAction.result` 的 payload，加 `origin`、`actionType`、`scope`、
  `receipt`（小摘要）；一张卡。J3 降级为“把现有回执讲清楚”，而不是新事件。
- **B（若确实要后台自动动作）**：定义 Java→agent 的通知/拉取机制（例如 apply/prepare
  响应里带 `systemActions[]`，由网关在同一回合发出；或后台任务写入事件表），
  并明确：
  - `EVENT_TYPES` + payload 白名单 + reducer + legacy 映射；
  - 同一 `operationId` 的去重与顺序（system.action 先于/后于
    conversationAction.result、assistant.completed）；
  - turnId 规则（合成 system turn 还是 session 级事件）；
  - 16KB 上限：大回执只发摘要/artifact 引用。

在 B 落地前，J3 不应进入实现。另：§13.6 要求“所有自动动作有可撤销路径”，
而 undo 未实现；J3 必须等 undo 或自带回滚，不能先上自动改方案。

### B7. “一个活跃 pending”硬规则与 Java `prepareOnce` 的 supersede 冲突；状态机没有状态载体

**证据**

- spec §4.3 硬规则 1（spec:212-213）：“已有待确认提案时，新的写意图必须先取消旧
  提案或明确替换，不能悄悄覆盖。”
- 现有行为：`ConversationProposalRequestService.java:79-130` 的 `prepareOnce`
  成功后调用 `supersedeSiblings`（`:130`、`:167-178`），把同会话其它 `prepared`
  记录自动标成 `superseded`——新预览**就是**覆盖旧预览，旧卡失效。另
  `prepareOnce:90-93` 在 pending `applying` 时抛 409 `pending_applying`。
- 快照只暴露当前 active pending（`ConversationSnapshotService.java:142-168`）；
  没有 `PROPOSING`/`AWAITING_CONFIRM`/`EXECUTING`/`RECOVERING` 的持久状态字段。
- spec §4.2 的状态表（spec:197-208）包含 8 个状态，但 §4.4 只派生
  `pending_kind`；没有说明 CLARIFYING/READING/EXPLAINING/RECOVERING 如何存储/
  恢复。

**为什么阻塞**

如果按 spec 在网关层拦截“有新 pending 时的新写”，会破坏现有“用户改主意 → 新预览
取代旧预览”的正常流；如果不拦截，状态机规则就是空话。`pending_applying` 时新写
请求的失败路径也没有在状态机/用户文案里出现。

**最小修复**

采用并写清“supersede 是显式策略”：

- 新提案允许取代旧 `prepared` 提案，但卡片/正文明确“上一条预览已失效，以新卡为准”；
- `applying` 时拒绝新写（409 `pending_applying`），给“正在生效，请稍候/取消”文案；
- 状态机降级为**每回合派生的建议状态**（IDLE/AWAITING_CONFIRM/CLARIFYING/
  READING/EXPLAINING），只由 `activeProposal`、`missingFacts`、`planningStage`、
  最近工具结果派生；PROPOSING/EXECUTING 作为同步内部阶段，不建模为可恢复状态；
- 如果产品真的要“先取消再新写”，必须在 Java 增加状态与接口并补测试，不能只在
  prompt 里写。

### B8. `interpretation.preview` 卡片没有事件/结果合同

**证据**

- §8.6（spec:560-564）要求“对话卡 `interpretation.preview`，展示 4 条场景路径……
  带按钮”；§9.2（spec:596-603）只写前端白名单和新增卡。
- `TurnOutput`（`contracts.py:509-540`）没有 interpretation 字段；网关只把
  `proposalPreview`/`actionResult`/`clarification` 转成事件
  （`service.py:2850-2970`、`server.py:1187-1196`）。MCP 工具结果不会自动变成卡。
- 服务端 `EVENT_TYPES`（`ui_events.py:18-37`）没有 `interpretation.preview`；
  `event_store.py:171` 会拒绝。
- 前端 `conversationSession.mjs` 的 reducer 没有该事件分支；只改
  `conversationEvents.mjs` 白名单不会渲染卡片。

**为什么阻塞**

J2-T5 的卡片无法从 `plan.interpret_admission` 的工具结果到达前端；J2 只能退化成
一段文本，而 spec 的验收要求卡片。

**最小修复**

定义一条明确的卡路，三选一：

- `TurnOutput` 增加可选的 `interpretation_preview`（网关像 `proposalPreview`
  一样在收尾发事件）；
- 网关拦截 `plan.interpret_admission` 的工具结果，转成 `interpretationPreview`；
- 由模型输出 `artifactRefs` 指向一个 `interpretation` artifact（需要先扩展
  artifact 类型/签发）。

同时补齐：服务端 `EVENT_TYPES`、前端 payload 白名单、reducer、`InterpretationCard`、
legacy 映射、事件体积（只带摘要，明细走 artifact/卡片按需拉取）。

### B9. `review_read` 修法是 no-op；`plan-final-review` 的 review 产物也没有签发路径

**证据**

- spec §1.2（spec:77-82）说“review_read 仅在 skill 参数含 review 时加入，但网关
  总是传 skill=None……修法：只要存在方案就加入，这样 plan-final-review 和后续
  interpret 都能直接用。”
- 实际情况：`ConversationSnapshotService.java:180-185` 确实只在 skill 含 "review"
  时加 `review_read`；网关确实传 `skill=None`（`service.py:1389,1640`）。但
  `tools_readonly.py:25-97` 的 `CAPABILITIES` **没有任何工具消费 `review_read`**；
  全仓 grep 只有签发点，没有使用点。加了这个 capability 不会打开任何工具。
- `plan-final-review` 是技能，不是工具；它输出 `responseType=review`，而
  `TurnOutput` 要求 `artifactRefs`（`contracts.py:538-539`）。产物台账
  `artifact_store.py:80` 只允许 `candidate`/`comparison`，`review` 类型无法签发；
  `output_validation.py:213-215` 会做类型匹配。模型若改引 candidate artifact 虽能
  过类型检查，但语义是“用候选产物冒充审查产物”。

**为什么阻塞**

J1 声称修了一个能力缺口，但实际什么都没打开；J3 的“审查完成 → system.action”
也缺少评审结果来源。按当前代码，`plan-final-review` 没有可引用的 review 产物，
只能退化成正文审查或借用 candidate artifact。

**最小修复**

- 要么新增只读 `plan.review`（或 `plan.get_review_state`）工具，返回
  `ReviewStateDTO`，并让 `review_read` 在存在方案时签发；补 CAPABILITIES/
  TOOL_KINDS/dispatch/TOOL_LABELS/单测。
- 要么删掉“review_read 修法”这一段，明确 `plan-final-review` 仍是模型基于读工具
  的人工审查，不依赖 review capability。
- 若要保留 review 卡片，扩展 artifact store 签发 `review`/`plan_draft`，或允许
  review 输出引用 plan artifact 并调整校验。

## 三、Majors

### M1. `PlanReceipt` 没有“取舍/原因”，且没有生产者

`PlanReceipt`（spec:406-427）只有 added/removed/counts/structure/postcondition/
reviewState；没有 `tradeoffs`/`reasonCodes`/`why`。而 §10.2（spec:628-641）要求
“一句取舍解释（为什么这样改）”，§2.5 又说“回执是唯一事实来源”。当前 Java 的
add_units 回执只有 count/added/removed（`PendingPlanningCommandBizService.java:452-473`），
fill/priority/scope 也没有统一 StructureVector。要么给 receipt 加
`tradeoffs/reasonCodes` 并让每个动作产出，要么明确“取舍解释可以来自 review/
structure 对比”，否则这条原则不可执行。

### M2. `planVersion`/缓存语义未定义

spec §9.1 请求 `planVersion`，§13.4 说“按 planVersion 缓存”，但没有说它是
workspace `version`、`snapshotVersion`、`ReviewStateDTO.sourceVersion` 还是
plan 自己的版本。当前 `ConversationTurnSnapshotDTO.snapshotVersion` 是 workspace
版本（`ConversationSnapshotService.java:42`），补录成绩也会 +1。缓存键至少还要
包含 `candidatePoolState.sourceVersion`/`dataVersion`/`admissionMode`，否则候选池
刷新后仍返回旧解读。请写死：`planVersion = workspace.version`（或新增 plan version），
并定义 stale 判定与缓存失效。

### M3. 反事实/输出模型的字段缺口

`counterfactual` 只有 `removeEntryIds`（spec:584-589），与 §8.3.5 的 add/replace/
reorder 不一致。`EntryRef`、`scenarioDepth`、`dataCoverage`、`drivers`、`caveats`
都没有定义/公式。建议先收窄 MVP 为 remove-only，其他在 J2 后续；或者把
`EntryRef` 定义为 `{level: "unit"|"volunteer", id}` 并扩展请求。

### M4. “审查发现高滑档风险时主动提示”没有实现基础

spec §8.6 和 §10.3 要求 review 发现高滑档风险时主动提示；但 §8.2/§1.3 自己说
review 没有专门的滑档规则（`ReviewStateDTO.checks` 只有 ratio_distribution/
safety_guard/probability_inversion/probability_gap/count_validation 等）。要么在
J2 里新增一个 `slip_risk` review 规则（并让 review 与 interpret 同源），要么删掉
这条主动提示；否则模型只能自己编。

### M5. J4/J5/J6 切片不现实，J5 不是一刀能落的

- J4（spec:661）把 REPLACE/remove/move/fill 混在一起，但 REPLACE/remove/move
  分别是不同的 frozen command、预览 DTO、后置条件；v6 自己说 REPLACE 是下一纵切。
- J5（spec:662）实际上是 10-17 分析报告的阶段 1–4（候选事实统一、objective
  compiler、solver 软效用、统一后置条件），每阶段 2–5 天，且要先修 P0（scope 持久化、
  candidate source 三套、coverage 40905、review 的 tierQuotaGoal 口径）。把它列为
  一个 J5 会严重低估。
- J6 依赖 J5；风险姿态目前在 `PlanningStateService.java:9313` 硬编码 medium 且
  无人消费（10-17 分析报告 `:380-381`）。
建议：J4 拆成 J4a（scope/tuition 持久化 + REPLACE）与 J4b（remove/move/pin）；
J5/J6 另立路线图，按 10-17 报告阶段 0–6 推进，不纳入本批。

### M6. `available_actions`/DialogueController 的校验语义未定义

spec §5.4 说“后端校验动作是否在 available_actions 内；不在就返回可解释的阻断”，
§9.3 说是 agent 侧新模块。但：

- `available_actions` 是 pre-turn 从快照派生（B2），而 verify/interpret/review/
  adjust 依赖用户本轮意图；
- 校验失败时是“修复回合”“blocked 卡”还是“文本说明”？`validate_turn_output`
  抛 `OutputContractError` 会走 repair/失败，不会自动给用户一张可读的阻断卡；
- 没有持久状态，CLARIFYING 等状态无法恢复。
建议把 J1 限定为**建议性上下文 + 硬不变量校验**（一轮一个写、有 pending 才能
confirm、版本守卫、已知阻断如 add_units tier quota/no plan），不要声称完整的
8 状态机；`available_actions` 只做“读动作全集 + 当前状态允许的写动作”，并在
校验失败时返回固定文案，不重试。

### M7. 解读结论的证据签发未定义

`EvidenceLedgerService.sign`（`EvidenceLedgerService.java:76-120`）要求
`sourceSystem`、`dataVersion`、完整 `scope`；`output_validation` 会核验模型引用的
证据必须来自台账（`output_validation.py` 的 artifact/evidence 部分）。解读是
computed/planner_experience 结论，不是上游取数；如果不显式签发计算证据，
`evidenceRefs` 要么为空（违反 §8.2“每条结论绑定 evidenceRefs”），要么在收尾被拒。
建议定义：`sourceSystem=plan.interpret_admission`、`dataVersion=hash(planVersion,
candidate sourceVersion, history dataVersion)`、`scope=session`，并明确
`sourceLevel=computed` 的核验规则。

### M8. `plan.interpret_admission` 的 MCP 参数包含 `chatSessionId`，违反受信 binding 纪律

spec §9.1 的请求体（spec:584-589）带 `chatSessionId`；实现计划 J2-T3 也写
`plan.interpret_admission(chatSessionId, planVersion?, counterfactual?)`。但 MCP
工具的身份只能来自 binding：`tools_readonly.py:533-558` 的 `_trusted_arguments`
会丢掉 `chatSessionId/tenantId/sessionId/userId`。工具应只收 `planVersion`/
`counterfactual`，会话身份由 `self.binding` 注入；Java 内部接口再从受信参数取
tenant/session。否则文档会让实现者把 `chatSessionId` 当输入，轻则被静默忽略，
重则形成跨会话读取面。

### M9. 方案条目数据缺口：join 策略未定义

`OrderedItemDTO` 没有 `admissionRatio`/`planNum`/`riskFlags`；
`OrderedUnitDTO`/`DraftUnitDTO` 没有 `planNum`；`riskFlags` 只在候选行。
解读要么按 `volunteerId` join 候选池，要么从 `majorItems` 取专业级 ratio。
join 不到（候选池刷新/overlay/旧 plan）时，必须标 `unknown` 并说明；不能静默
用 tier 代替 ratio。请把 join 写成契约的一部分，并覆盖“方案条目不在候选池”的
fixture（现有 add_units 预览就要求当前方案每条都在候选池，解读也应同口径）。

### M10. 专业组/专业粒度与投档规则未落到算法

spec 的 caveat 说得对（没有专业组代码、不能声称省考试院投档模拟），但算法没有
定义在 unit 模式与 major 模式下 `EntryRef`/`path`/`landing_entry` 的粒度；组内
调剂、组内专业顺序、`safetyMajor` 都没有进入场景。MVP 至少要明确：
- unit 模式：一个单元一个 EntryRef，组内专业作为 `drivers`/证据；
- major 模式：一个 volunteerId 一个 EntryRef；
- 两种模式分别给 fixture 和 expected。

### M11. 自动动作可撤销性

§13.6 要求“所有自动动作必须有回执和可撤销路径”，但 undo/rollback 仍是待实现
（spec:271）。J3 如果先上 `system.action` + 自动重排/审查，却没有 undo，会违反
自己的风险条款。建议 J3 不早于 undo，或自动动作只允许“可重新生成/可再次预览”的
幂等操作，不做不可逆删除。

### M12. J1 的 golden 测试与验收口径

见 B5：计划里的测试只校验 fixture schema。若坚持“40 条全绿”，需要一个明确
eval harness（固定 codex 版本、温度、输入、记录实际动作；允许 flaky 时重试 N 次
并记录）。否则应把 J1 验收改为“契约/校验器单测全绿 + 采样 eval 报告”，不要把
静态 fixture 说成触发回归。

## 四、Minors

1. `DialogueController` 在 §5.4 是“后端校验层”，§9.3 是“agent 侧新模块”；
   统一命名与所在进程。
2. `admissionRatio` 写“0–99”，候选上游可能给 0–100；`50–70 稳` 与 facts.py
   `<70` 在 70 点不一致；统一闭开区间。
3. `rankInTier` 的描述正确（推荐排序名次，非历史位次），保留；但解读输出不要
   把它放进 `drivers` 的“位次”字段。
4. `planNum` 在 §1.3 被说成“方案单元里有”，实际 `OrderedUnitDTO`/`DraftUnitDTO`
   都没有；只有候选行/历史有。
5. `system.action` 用点号命名，`conversationAction.result` 用驼峰；统一事件命名
   风格，或说明这是历史例外。
6. `origin="system"` 与事件类型 `system.action` 重复；二选一。
7. `scenarioDepth` 未使用；要么删掉，要么定义 `brief/standard` 的差异。
8. `data_coverage` 是内部数值；面向用户不展示系数，若展示请转成“数据完整/有缺口”。
9. `admission.get_history` 对 `groupCode` 返回 `unsupported_scope`
   （`tools_readonly.py:1867-1878`）；组级历史不能查，caveat 里应写明。
10. 前端 `formatAdmissionProbability` 会把 ratio 渲染成百分比
    （`conversationEvents.mjs:133-138`）；解读卡必须用档位/band，不能直接复用该格式。
11. `must_include_scope` 满方案只替换 1 组（10-17 分析报告 `:376-377`）；
    触发表“必须有”要写这个限制或明确不走它。
12. `add_units` 的已知阻断（tierQuotaGoal、current != confirmed target、stale
    plan item）应进入 `blocked_actions`；否则 J1 会给出“可加”但 J4 必拒的卡。
13. `review_read` 的签发条件“只要存在方案”需要定义“存在方案”= working 或
    ordered 非空；当前快照没有 plan 存在性字段（见 B2）。
14. 用户旅程表缺少“方案 stale（补录成绩/改偏好后）”“无方案但用户问落点”
    的明确分支；后者 §5.3 有一句，旅程表没有。
15. 触发表缺少“改目标总数”“撤回已确认偏好”“提交/导出”等；如果 out of scope，
    在表下写明，不要让模型猜。
16. `entry` 级 `riskFlags` 在方案侧不存在；解读的 `drivers` 若要写“风险标签”，
    必须来自候选 join 或 review checks。
17. `system.action` 事件体积 16KB：大回执请只发摘要 + artifact 引用；spec 没有
    写这一点。
18. `planVersion` 在工具参数里是可选，但 §13.4 又要求按它缓存；MVP 建议必填
    （或明确缺省=当前 workspace version）。

## 五、逐项回答审查目标

### 1. 数据模型声明

| 声明 | 结论 |
|---|---|
| `admissionRatio` 专业级 0–99 | 部分错。专业行是专业级；校行/`OrderedUnitDTO` 是校级（B1） |
| `tier` 按 `<50/50–70/≥70` 派生 | 错。候选 tier 来自 `schoolEnrollRatio` 的 ≤50/≤70/>70（B1） |
| `position/tier/volunteerId/locked/pinned` | 对（`OrderedItemDTO.java:6-18`） |
| `OrderedUnitDTO` 有 unitId/ratio/finalScore/schoolEnrollRatio | 对；但 ratio 是校级（`:12757`） |
| `DraftUnitDTO` major items 有 admissionRatio/finalScore/safetyMajor/rankInTier | 对（`PlanningUnitMajorDTO.java:10-35`） |
| `planNum` 在方案单元里可用 | 错。方案单元/专业项都没有 planNum；只有候选行/历史（B1/M9） |
| 历史只在 `CandidateItemDTO.schoolHistoryScores/majorHistoryScores`，preview/plan 不投影 | 对（`CandidateItemDTO.java:63-64`；`CandidatePreviewRes.java:32-50`） |
| `rankInTier` 是推荐排序名次，不是历史位次 | 对（`VolunteerResponseBuilder.java:147-164`） |
| `ReviewStateDTO.checks` 有 ratio_distribution/safety_guard/probability_inversion/probability_gap/count_validation/edge_score，且无滑档规则 | 对（`ReviewCheckDTO.java:9-36`；spec 自述也承认） |
| `admission.get_history` 有 year/score/pos/planNum/enrollNum | 对（`CandidateItemDTO.HistoryScoreItem:66-73`） |

### 2. 控制流

模型驱动的路由和确认链应保留；但 `JourneyContext` 的关键字段无来源（B2），
状态机无可恢复状态（B7），`available_actions` 校验语义未定义（M6）。建议把
J1 缩成“状态派生建议 + 硬不变量”，不要做 8 状态机。

### 3. 触发目录

动作与真实契约的映射不完整（B5）；REPLACE/reorder/risk/priority/review/query
没有标“待实现”或用错载体；golden 测试不测模型。必须先补“载体/状态/失败行为”
三列，并把未来动作从活跃提示词里移出。

### 4. 录取解读

方向正确（不乘概率、不承诺、加 caveat），但数据口径错（B1）、算法不可判定
（B3）、证据签发/条目 join 未定义（M7/M9/M10）。MVP 可以先做“按校线档位的
基准落点 + 滑档风险”纯函数，但必须用真值表和 fixture 锁死。

### 5. 系统动作事件

`system.action` 没有生产者、与 `conversationAction.result` 重复、服务端白名单
/体积/turnId/前端 reducer 都没处理（B6）；解读卡也没有事件路径（B8）。建议
优先复用现有 `conversationAction.result`，不要新造第二套回执事件。

### 6. 切片与顺序

J1 应拆成 J1a（快照 journey 块）、J1b（触发目录/提示词）、J1c（校验/测试）；
J2 应拆成 J2a（Java 纯函数 + fixture）、J2b（内部接口 + MCP）、J2c（卡片事件）；
J4 拆成 J4a（scope 持久化 + REPLACE）/J4b（remove/move/pin）；J5/J6 另立路线图。
J3 在 B6/B8 解决前不应开工。

### 7. 用户明确要求

- 用户旅程：有 §3 表，但缺 stale/无方案分支，且 phase 推导依赖本轮意图（B2）。
- 对话控制流：有 §4，但状态机不可落地、与 pending 行为冲突（B7）。
- 可能的用户触发：有 §5，但载体/未来动作/测试不完整（B5）。
- 当前方案录取解读（演绎场景）：有 §8，但数据口径与算法规则需要重写（B1/B3）。
因此“要求覆盖”是齐的，“可执行性”不够。

## 六、建议实施顺序

**阶段 0：设计修订（不改代码）**

1. 定数据信号契约（B1）：`pathTier` vs `majorAdmissionRatio`，条目 join，
   边界，unknown 规则。
2. 定事件模型（B6/B8）：复用 `conversationAction.result` 还是新 `system.action`；
   服务端 `EVENT_TYPES`、payload、reducer、16KB、turnId。
3. 定 pending 策略（B7）：supersede 是正式策略；`pending_applying` 文案。
4. 定 scope/学费持久化（B4）与 J4 拆分。
5. 出触发目录“载体/状态/失败行为”表（B5）；把 planned 动作移出活跃提示词。
6. 定义 `JourneyContext` 的 Java 快照扩展/workspace 读取方案（B2）。

**阶段 1：J2 只读核心（先文本，不先卡片）**

- J2a：Java 纯函数 + 真值表 + fixture（B3/M3/M9/M10）；
- J2b：Java 内部只读接口 + MCP `plan.interpret_admission`（B1/M7/M8）；
- 先以文本返回验证；卡片等阶段 2 的事件合同。

**阶段 2：J1a/J1b/J1c**

- J1a：快照 `journey` 块 + agent 派生（B2）；
- J1b：触发目录/技能/提示词 + blocked_actions（B5）；
- J1c：网关不变量校验 + 确定性单测；如果要模型 golden，另立 eval harness。

**阶段 3：J2 卡片**

- B8 的事件/结果合同 + `ui_events.py` + reducer + `InterpretationCard`；
- 只带摘要，明细按需。

**阶段 4：J4a**

- scope/tuition 持久化 + stale 标记（B4）；
- REPLACE 按 v6 的 frozen/预览/后置骨架实现；
- 预览列全新增/移出，零静默删除。

**阶段 5：J4b**

- remove/move/pin；每个动作独立 frozen command/后置条件。

**阶段 6：J3**

- 只有在存在真实自动动作源 + undo/回滚时才做；否则把 J3 降级为
  `conversationAction.result` 的 origin/receipt 扩展。

**阶段 7：J5/J6**

- 按 10-17 分析报告的阶段 0–6 单独推进，不纳入本批；先修 P0（scope 持久化、
  candidate source 统一、coverage 40905、review tierQuotaGoal 口径）。

## 七、应保留的优点

- 三问题诊断与 10-17 分析报告一致，不是凭空加工具。
- 保留模型解析意图、后端编译/确认链，不让模型直接写。
- 明确“无权威概率、不乘概率、不承诺录取”，并给了 caveat 与反例。
- 正确识别 `rankInTier` 是推荐顺序、历史没有投影到 preview/plan、review 没有
  滑档规则。
- add_units 默认 EXPAND、REPLACE 显式、零删除，与 v6 口径一致。
- “回执是唯一事实来源”“不静默改变用户方案”“先给内容再问问题”方向正确。
- 只读解读与写动作分离、不产生 pending，是正确的边界。

## 八、审查边界

- 只读代码与文档；没有运行测试、没有构造真实 fixture、没有调用模型。
- 没有验证候选池 4–29MB、planningState 1–4MB 的实际规模；这些数字未在本次
  审查中复核。
- 没有验证 `plan-final-review` 在当前真栈上的实际输出；B9 基于契约/产物台账
  代码路径推断。
- 没有验证 pending 过期调度的实际触发点；B7 只按 `PendingConfirmationBizService`
  的状态转移与 `prepareOnce` 行为判断。
