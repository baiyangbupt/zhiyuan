# 用户旅程、对话控制与录取解读设计（v2）独立审查

对象：
- `docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`（v2）
- `docs/superpowers/plans/2026-10-18-journey-control-and-admission-interpretation.md`（v2）

基线：`616464c`（`wip/2026-09-28-p2-write-loop-green`，工作区含 add_units EXPAND 未提交改动）
日期：2026-10-18
方式：只读审查（未改设计稿/代码、未跑测试、未部署）

## 一、结论

**BLOCK。**

v2 对 B1–B9 的修订方向基本正确，B1/B5/B7/B9 已实质解决；但 B2/B3/B4/B6/B8
只解决了一部分，且修订本身引入了 7 个新的 blocker：

- **N1** Java 的 `journey` 块没有 agent 合同/投影/注入点，`JourneyContext` 永远到不了
  模型；
- **N2** §8.3 真值表与判定规则互相矛盾，J2a 的“9 行全绿”不可实现；
- **N3** 规范性的“结论/验收脚本”仍保留 v1 的 `system.action`、自动动作和“最可能”；
- **N4** 解读卡声称“artifact 存明细、卡片按 ref 取”，但 artifact store 只存引用、
  前端没有取数接口、卡片也没有挂载点；
- **N5** MCP 工具名 `plan.interpret_admission` 违反只读命名空间不变量，现有测试必挂；
- **N6** MCP 注册缺 `TOOL_INPUT_SCHEMAS`，按计划实施会让工具清单直接崩溃；
- **N7** B4 的“仅本次”口径与 §6.2/§6.3/§10.4 的“默认持久”仍互相矛盾。

这些不是“实现时再定”的细节：N1/N2/N4 会让 J1a/J2a/J2c 的验收不可达，N5/N6 会让
J2b 直接失败。建议先把设计/计划修订到自洽，再进入代码。

## 二、B1–B9 状态表

| # | 状态 | 一句话结论 |
|---|---|---|
| B1 | resolved | `pathTier` 与专业 ratio 已拆分，方案条目 join/unknown 已写清；边界与实际流水线一致 |
| B2 | partially | Java 快照块与两层派生已定义，但 agent 合同/投影/注入缺失（N1），派生规则仍不完整 |
| B3 | partially | 顺序扫描、真值表、remove-only、粒度都补了，但真值表与规则自相矛盾（N2） |
| B4 | partially | 已降级为 J4a 前置并在部分章节写“仅本次”，但 §6.2/§6.3/§10.4 仍承诺持久（N7） |
| B5 | resolved | 载体/状态/失败行为表已补，planned 动作已标注，golden 已降级为契约校验；有少量文案残留 |
| B6 | partially | 详细章节已改为复用 `conversationAction.result`，但结论/验收脚本仍有 `system.action`（N3），J3 任务定义不完整 |
| B7 | resolved | 明确 supersede、`pending_applying` 409、派生型状态；与 `prepareOnce` 行为一致 |
| B8 | partially | 事件白名单/reducer/体积已列，但“artifact 明细”链路不可实现（N4） |
| B9 | resolved | 已删除 `review_read` no-op 修法，明确不签发 review artifact；§4.4 有一处旧状态文案 |

### B1（resolved）

- 候选档位确由校级 `schoolEnrollRatio` 分档：`VolunteerSorterAndMerger.java:59` 走
  九区间，`VolunteerIntervalService.java:61-79` 的边界为
  `<=10/34/50/56/62/70/86/98`，`mergeToThreeInterval`（`VolunteerSorterAndMerger.java:161-175`）
  合并后等价于 `<=50 冲 / <=70 稳 / >70 保`。spec:666-670 引用的
  `VolunteerIntervalService.java:96-102` 是**未被生产调用的三区间分支**，引用需修正，
  但边界结论正确。
- `OrderedItemDTO` 确实没有 ratio（`OrderedItemDTO.java:6-18`）；
  `OrderedUnitDTO.admissionRatio` 主路径取 `candidate.getSchoolEnrollRatio()`
  （`PlanningStateService.java:12757`），回填路径可能取代表专业的 ratio
  （`:12951`）；组内 `PlanningUnitMajorDTO.admissionRatio` 是专业级
  （`PlanningUnitMajorDTO.java:27`）。
- v2 §8.2 已明确两套信号、禁止互相覆盖、按 `volunteerId` join、join 不到标 unknown，
  并在 J2a-T1 写入边界 fixture。B1 的核心口径错误已消除。

### B2（partially）

- 已正确补了 Java `ConversationTurnSnapshotDTO` 的 `journey` 块需求
  （spec:300-307、plan J1a-T1），并把 `statePhase`/`taskIntent` 拆开。
- 但 **N1**：agent 的 `ConversationTurnSnapshot`/`build_snapshot` 没有 `journey`
  字段，模型上下文也没有注入 JourneyContext。J1a-T2 的 `journey.py` 拿不到块。
- 派生规则仍不完整：`hasProfile`/`hasCandidates` 没定义；§3.4 的 `statePhase`
  取值含 `stale`，但 `JourneyContext.phase` 的 Literal 没有 `stale`
  （spec:196 vs spec:280）；`explore`/`review` 仍混用了“用户在问什么”的意图条件
  （spec:185-191），pre-turn 不可判定。详见 M1。

### B3（partially）

- 已补：按实际 `position` 顺序扫描；`base=第一条非冲`、`upside=冲里校线 ratio 最高`、
  `downside=最后一条保`；remove-only 反事实；unit/major 粒度；历史不参与落点判断的
  总原则；9 行真值表。
- 但 **N2**：真值表与规则直接冲突，且“历史是否参与 band”在 §8.3 内自相矛盾
  （spec:729 与 spec:750-752）。J2a 的“9 行全绿”按当前文本不可能同时满足。

### B4（partially）

- 已确认当前实现不持久化 scope/学费：`PlanningStateService.java:1075-1111` 只持久化
  requirements/priorityRules/tierQuota/selectionTargetCount；
  `ChatSessionBizService.java:216-245` 的 `updateTuitionRange` 不标 stale。
- v2 已把持久化列为 J4a 前置，并在 §5.1b/§13.8 写“仅本次”（spec:368、1120-1121；
  plan:174）。
- 但 **N7**：§6.2（spec:482）、§6.3（spec:500）、§10.4（spec:985）仍写“默认持久/
  后续生效”，与“仅本次”冲突。按验收脚本执行会重复 B4 原来的用户可见承诺。

### B5（resolved）

- §5.1b 的载体与真实工具一致：`planning.get_working_plan`/`admission.get_current_plan`
  （`tools_readonly.py:31-34`）、`recommendation.preview_candidates/preview_majors/
  compare_candidates/explain_fit`（`:65-84`）。
- `proposalRequest.goalType` 确无 `prefer`（`contracts.py:325-333`）；§5.1b 已明确
  改用 `requirements(include)`/`priority_rules`。
- REPLACE/remove/move/regenerate/risk posture/priority 已标 planned；`add_units` 的
  `tierQuotaGoal`/`current != target`/`stale plan item` 阻断已进 blocked_actions
  （spec:308-310），代码依据 `UserGoalProposalBuilder.java:245-251`、`:263-275`。
- golden 已降级为契约校验 + 可选 live eval（spec:440-445、plan J1b-T1），不再冒充模型
  路由回归；`must_include_scope` 满方案只替换 1 组也已写入（spec:400-401，
  代码 `UserGoalProposalBuilder.java:1727-1733`）。
- 残留仅是文案：§5.1 仍列 `proposalRequest(.../prefer)`（spec:343），§5.3 仍把
  “稳一点/保专业”写成已生效动作（spec:406-409）。见 M8。

### B6（partially）

- 详细章节已正确决策：不新增 `system.action`，复用/扩展 `conversationAction.result`
  （spec:894-904、939-947）；现有回执确有生产者
  （`conversation_actions.py:1035-1053`、`server.py:1083-1104,1164`）。
- 但 **N3**：spec:66 的结论段仍写“J3 系统动作卡…system.action”，§10.4 的验收脚本
  仍写“系统（自动）…出 system.action 卡”（spec:991-994）。这些是规范性文本，会让
  实现者/验收者重新引入已被删除的事件。
- J3 的任务定义不完整：计划只有勾选项，没有列出 `server.py::_action_result_payload`
  和前端 payload 白名单（`conversationEvents.mjs:43-46`）的改动（M4）。

### B7（resolved）

- `prepareOnce` 成功后 `supersedeSiblings` 自动把同会话其它 `prepared` 标
  superseded（`ConversationProposalRequestService.java:130,167-178`）；`applying` 时
  抛 409 `pending_applying`（`:90-93`）。
- v2 已把 supersede 写成显式策略、`applying` 拒绝新写并给文案、状态机降级为每回合
  派生的建议状态（spec:239-262）。与现有代码行为一致。
- 残留：`pending_applying` 在快照中没有来源（`ConversationSnapshotService.java:142-168`
  只暴露 `active`），JourneyContext 的该字段目前只能恒 false；见 M13。

### B8（partially）

- 已定义：`interpretation.preview` 白名单、payload 只带摘要、artifact 引用、reducer/
  legacy 映射、16KB 上限，并列了 `ui_events.py`/`event_store.py`/`server.py`/
  `conversationEvents.mjs`/`conversationSession.mjs` 的改动（spec:894-915、plan J2c-T1）。
- 但 **N4**：该方案假设“artifact 能存明细、前端能按 ref 取”，而
  `SqliteArtifactStore.issue` 只存身份摘要（`artifact_store.py:140-160`），
  payload 只参与 digest，不落库；前端没有 artifact 取数接口，`conversationArtifacts`
  从未被传入（`WorkspacePanel/index.tsx:221,633`；父组件
  `pages/sessionDetailV2/index.tsx:582-600` 不传），MessageList 也没有
  `interpretation.preview` 的渲染分支。J2c 的卡片无法展示 4 条场景路径。

### B9（resolved）

- 已删除“`review_read` 修法”并明确：MCP 侧没有消费者
  （`tools_readonly.py:25-97` 无 `review_read`；全仓 agent 无引用），
  `plan-final-review` 保持人工审查、不签发 review artifact（spec:100-107、1122-1123）。
- 解读服务自带 `ReviewStateDTO.checks` 作为 drivers/caveats 的方向正确。
- 残留：§4.4 的 `review_plan` 仍写“已实现（能力开关待修）”（spec:323），与 B9 结论
  相反；见 M8。

## 三、新增 blocker

### N1. Java 的 `journey` 块到不了 agent，JourneyContext 也没有注入点

**证据**

- `zhiyuan-agent/app/gateway/contracts.py:589-601` 的 `ConversationTurnSnapshot`
  没有 `journey` 字段；`_ContractModel` 是 `extra="forbid"`（`:11-19`）。
- `zhiyuan-agent/app/gateway/snapshot.py:42-172` 的 `build_snapshot` 只逐键投影已知
  字段，最后用固定字段构造 `ConversationTurnSnapshot`（`:159-172`）；没有
  `workspace["journey"]` 的读取。
- `zhiyuan-agent/app/gateway/service.py:912-917` 的 `_snapshot_payload` 一定走
  `build_snapshot`；`:2483-2500` 把 `snapshot.model_dump(by_alias=True)` 作为模型可见的
  `turn_snapshot` 状态块。`journey` 即使被 Java 返回，也会在这一步被丢掉。
- 版本相邻时走 `state_patch`（`service.py:2281-2287`），而 `snapshot.py:174-214`
  的 `diff_snapshots` 只比较固定的 `allowed` 路径集合，没有 `journey`。
- 计划 J1a-T2 只创建 `app/gateway/journey.py` 和测试，没有列
  `contracts.py`/`snapshot.py`/`service.py` 的修改；J1b 只改静态提示词，J1c 只做
  不变量校验。没有任何任务把 `JourneyContext` 注入提示或工具返回值
  （spec:311 要求“后端把它注入提示/工具返回值”）。

**为什么阻塞**

J1a-T2 的输入不存在：`journey.py` 无法从 `ConversationTurnSnapshot` 读到
`hasPlan`/`hasCandidates`/`staleFlags`，`statePhase`、`blocked_actions`、
`recommended_next` 全部没有数据来源。J1b 的触发目录与 J1c 的硬不变量即使实现了，
模型也看不到 `JourneyContext`，J1 的核心承诺不成立。

**最小修复**

1. `ConversationTurnSnapshot` 增加 `journey: dict[str, Any]`（或独立 Pydantic 模型）。
2. `build_snapshot` 同时兼容 `turn-snapshot` 与 workspace 两种形状，透传 `journey`。
3. `diff_snapshots` 的 `allowed` 增加 `journey`（或每轮都注入 journey 块，不走 patch）。
4. `service.py` 增加把 `JourneyContext`（budget 内）注入上下文的任务和测试。
5. 计划 J1a 增加这些文件与测试；J1a-T2 的测试必须从真实 `ConversationTurnSnapshot`
   构造，而不是裸 dict。

### N2. §8.3 真值表与判定规则互相矛盾，J2a “9 行全绿”不可实现

**证据**

- **历史参与 band 的自相矛盾**：§8.3.3 写 `upside` 的 `校线 ratio >=40 或历史证据支持
  → 有机会`（spec:729）；§8.3.8 写历史“不参与 band 判定”（spec:750-752）；
  §8.2 写“MVP 不把历史位次纳入落点判断”（spec:697-699）。同一份设计里历史既参与
  又不参与。
- **规则 4 与真值表冲突**（spec:736-740 vs spec:767-771）：
  - 行 5“保, 冲, 稳”：规则 4 的“恰好 1 条保且 ratio 已知 → 中”，表却写“低/中”；
  - 行 7“冲, 稳, 保（全部 ratio 缺失）”：规则 4 的“最后一条保 ratio 缺失 → 中”，
    表却写“无法判断”；
  - 行 9：`slip_risk` 写“中/无法判断”，未给出判定条件。
- **base 的 unknown 语义未定**：规则 2 写 `base=第一条非冲档（稳或保）`
  （spec:719-720），规则 1 又说 `unknown` 不参与冲/稳/保判断（spec:716-718）。
  `unknown` 条目算不算“非冲档”没有定义；而规则 3 的 `base` 有
  “`unknown → 无法判断`”分支（spec:728），若 base 只可能是稳/保，该分支不可达。
- **upside 选择未定义**：规则 2 要求“冲档里校线 ratio 最高”，但部分冲档 join 不到
  ratio 时如何选（跳过？按顺序？）没有规则；真值表只覆盖“全部缺失”。
- **slip_risk 未穷尽**：规则 4 对“≥2 条保、其中一条非最后保的 ratio 缺失”没有覆盖
  （不满足高/中/低/无法判断任何一档）。
- **data_coverage 口径误导**：§8.3.5 只统计 `pathTier` 已知条目数（spec:741-742）。
  行 7 全部 ratio 缺失时 coverage 仍是 1.0，会被翻译成“数据完整”，而实际
  无法判断 upside/downside。

**为什么阻塞**

J2a-T2 的验收是“9 行真值表全绿”。按当前文本，同一行既要满足规则又要满足表，做不到；
不同实现者会给出不同的 `base`/`slip_risk`。这是用户可见的核心输出，不能靠实现时
自行裁决。

**最小修复**

1. 把规则 4 改成**互斥且穷尽**的分档（建议按优先级：无保→高；全部保 ratio 缺失→高；
   恰好 1 条保或最后保缺失→中；≥2 条保且全部已知→低；其余→无法判断）。
2. 修正行 5/7/9，或在表中写明“允许两值”的判定条件；把 `data_coverage` 改为
   `pathTier 已知且 ratio 已知（至少对 upside/downside 需要的条目）/ 总数`，
   或拆成 `tierCoverage` + `ratioCoverage`。
3. 明确 `base` 的 unknown：建议“unknown 跳过，不计入 base”；`base` 只能落在稳/保，
   删掉不可达的 unknown 分支。
4. 明确 upside 在部分 ratio 缺失时的选择规则；补充“混合缺失”fixture。
5. 删除 §8.3.3 的“历史证据支持”或改为“历史只进 drivers，不进 band”，与 §8.2/§8.3.8
   保持一致。

### N3. 规范性“结论/验收脚本”仍保留 v1 的 `system.action`、自动动作和“最可能”

**证据**

- spec:66（“〇、结论（先看这一段）”）仍写：“**J3 系统动作卡**：自动生成/审查/重排
  产生可叙述的 `system.action` 事件与回执卡。”
- spec:991-994（§10.4“一条完整对话示例（验收脚本）”）仍写：
  “系统（自动）：方案生成完成……自动审查完成……出 system.action 卡”，并写
  “按当前档位，**最可能**在第 14 志愿的稳档被接住”。
- spec:221（§3.5 `interpret` 主持话术）写“先给**‘最可能落点’**”。
- 这些与 v2 的明确决策冲突：spec:20/896/939/1051/1090 均写“不新增 `system.action`”；
  spec:756-757/963/1082 明确禁止“最可能”；§10.1（spec:932-935）承认 codex 写路径
  没有自动生成/重排入口。
- 代码侧也没有自动动作源：网关写路径只有 `prepare`
  （`service.py:2875-2884`），审查只在 apply 时随 `rerunReview` 返回
  （`conversation_actions.py:1035-1053`）。

**为什么阻塞**

§10.4 是验收脚本（spec:976“验收时按这条脚本逐轮检查”）。照它验收会要求一个不存在
的事件和一个不存在的自动动作；同时“最可能”违反本设计自己的措辞规则。实现者若按
§〇 的结论做 J3，会重新引入被 B6 否决的 `system.action`。

**最小修复**

1. 重写 spec:66 的 J3 描述为“扩展现有 `conversationAction.result` 回执”。
2. 重写 §10.4：删除“系统（自动）”与 `system.action` 卡；把落点摘要改写为
   “基准情景”；若保留自动摘要，明确由 apply 后的续接回合（`server.py:1230-1305`）
   调用解读工具产生，而不是新事件。
3. 把 spec:221 的“最可能落点”改为“基准情景/落点摘要”。
4. 增加一条文本检查：v2 文档中 `system.action` 只允许出现在“不新增”的否定句里，
   `最可能` 只允许出现在用户原话/反例中。

### N4. 解读卡明细链路不可实现（artifact 只存引用、前端无取数、卡片未挂载）

**证据**

- spec:905-911 定义：“网关把它存成 `admission_interpretation` artifact……前端
  `InterpretationCard` 按 `artifactRef` 取明细。”
- `SqliteArtifactStore.issue` 的 `record` 只含身份字段（tenantId/sessionId/
  artifactType/stateVersion/toolName/paramsDigest/payloadDigest/threadId/时间戳），
  **不保存 payload**（`artifact_store.py:140-160`）；`get_many` 返回的也是这份身份
  记录（`:165-190`）。payload 只用于 digest，不能当明细取回。
- 前端没有 artifact 取数接口：`conversation.ts:18-34` 只有
  `ConversationArtifact` 类型；`WorkspacePanel/index.tsx:221,633` 的
  `conversationArtifacts` 默认 `{}`，父组件 `pages/sessionDetailV2/index.tsx:582-600`
  从不传入；`resolveArtifact`（`conversationEvents.mjs:234-245`）只在这张表里查找。
- `MessageList/index.tsx:1690-1712` 的 renderable gate 只认 `turn.answer/proposal/
  steps/error`，渲染块只画 `turn.proposal`（`:1938-1946`）；没有
  `interpretation.preview` 分支。计划 J2c 只创建 `InterpretationCard.tsx`，没有列
  `MessageList` 或取数接口的修改。
- 类型也不覆盖：`contracts.py:154-156` 的 `ArtifactRef.artifactType` 只允许
  `candidate/comparison/plan_draft/review`；前端 `conversation.ts:24` 同样没有
  `admission_interpretation`。

**为什么阻塞**

事件 payload 只有 `artifactRef, planVersion, scenarioCount, baseLabel, slipRisk,
caveatCount`，没有 4 条场景路径、落点条目和证据缺口；artifact 又取不到明细，
卡片的验收要求（spec:832-833）无法满足。J2c 只能退化成一行摘要。

**最小修复（三选一，写进设计与计划）**

- **A（推荐，改动最小）**：事件 payload 携带**有界**的 `scenarios` 摘要
  （每场景只带 `label/likelihood/landingEntry{schoolName,majorName,position}/caveatCount`，
  不带完整 `path`），并同步扩展 `conversationEvents.mjs` 白名单、reducer、
  `MessageList` 渲染与类型；完整明细仍留在工具结果/正文。
- **B**：给 artifact store 增加 payload 内容存储（独立表/行、大小上限、按会话鉴权），
  并在 agent 或 Java 增加 `GET artifact` inner 接口，前端按 ref 拉取后填充
  `conversationArtifacts`。
- **C**：把完整 `AdmissionInterpretation` 作为 assistant 消息的附件/artifactRef 走
  现有历史落库路径（需先证明该路径对前端可读）。

无论哪条，都要补：`ArtifactRef`/`ConversationArtifact` 类型、`MessageList` 渲染分支、
事件顺序（在 `turn.completed` 前）和 16KB 上限测试。

### N5. MCP 工具名 `plan.interpret_admission` 违反只读命名空间不变量

**证据**

- `zhiyuan-agent/tests/unit/test_domain_mcp_tools.py:45-46` 明确断言：
  `assert not any(name.endswith("apply") or name.startswith("plan.") for name in server.tools)`。
- `tools_readonly.py:86-93` 的 `WRITE_TOOL_NAMES` 包含 `plan.propose_changes`/
  `plan.propose_finalize`；`plan.` 前缀是写/提案命名空间。
- spec:861、plan:109 均把新工具命名为 `plan.interpret_admission`。

**为什么阻塞**

按计划把工具加进 `CAPABILITIES` 后，现有 `test_server_registers_exactly_the_readonly_tools`
必挂；更重要的是 `plan.` 前缀会让模型/后续维护者把只读解读与写提案混在一起，破坏
“只读工具里没有 plan.*”的安全约定。

**最小修复**

统一改名为 `planning.interpret_admission`（与 `planning.get_working_plan` 同族，
且不会触发 `admission.` 前缀的模式校验），同步改 spec/plan/skill/tests；
或 `admission.interpret_plan`（需确认不会与 `admission.*` 的 admissionMode 参数处理
冲突）。

### N6. MCP 注册缺 `TOOL_INPUT_SCHEMAS`，按计划实施会让工具清单直接崩溃

**证据**

- `zhiyuan-agent/app/mcp_server/server.py:433-453` 的 `tool_listing()` 对
  `READONLY_TOOL_NAMES` 的每个名字执行 `TOOL_INPUT_SCHEMAS[name]`；该字典在
  `:220-383`，没有新工具的条目。
- 计划 J2b-T2 的文件列表只有 `tools_readonly.py`、`internal_client.py` 和测试，
  **没有 `server.py`**；它要求“工具在 CAPABILITIES/READONLY_TOOL_NAMES”，但没有要求
  输入 schema。
- `_kind_for` 对未登记工具默认 `catalog`（`tools_readonly.py:136-138`），
  `TOOL_OUTPUT_SCHEMA.kind` 的 enum（`server.py:405`）也没有解读类 kind。

**为什么阻塞**

`tool_listing()` 是 stdio 与 SDK server 的唯一清单来源；缺 schema 会在 ListTools 时
抛 `KeyError`，整个 MCP server 不可用（不是“新工具不可用”，而是所有工具都不列）。
即使用 `catalog` 绕过，kind/标签也是错的，下游会把解读结果当目录数据。

**最小修复**

1. `TOOL_INPUT_SCHEMAS["planning.interpret_admission"]`：`planVersion` required
   integer（>=0），`counterfactual` optional object，仅
   `removeEntryRefs:[{level,id}]`，`additionalProperties:false`。
2. `TOOL_DESCRIPTIONS` 增加描述；`TOOL_KINDS` 增加 `interpretation`（或明确复用
   `candidate` 并说明理由），同步 `TOOL_OUTPUT_SCHEMA.kind.enum`。
3. 计划 J2b-T2 增加 `server.py` 与 `test_domain_mcp_tools.py` 的改动；测试必须调用
   `tool_listing()`。

### N7. B4 的“仅本次”口径与 §6.2/§6.3/§10.4 的“默认持久”互相矛盾

**证据**

- 正确的一侧：spec:368（“学费持久化未落地前标‘仅本次’”）、spec:1120-1121
  （“scope/学费持久化未落地前……不得宣称‘以后都生效’”）、plan:174（提示词写“仅本次”）。
- 错误的一侧：spec:482（“学费上限：`tuition_budget_scope`，默认持久”）、
  spec:500（“学费 ≤3 万：默认持久……卡面写‘后续生效’”）、spec:985（验收脚本
  “出‘偏好确认’卡（persist）”）。
- 代码确认持久化未实现：`PlanningStateService.java:1075-1111` 不含
  `targetScopes`/`negativeScopes`/`tuitionRange`；`ChatSessionBizService.java:216-245`
  的 `updateTuitionRange` 只改 `userScoreDetail`，不 bump planning version、不标 stale。

**为什么阻塞**

这正是 B4 原 blocker 的用户可见形态：卡片/正文承诺“以后都生效”，但 J4a 未落地，
重新生成后 scope 会丢。§10.4 是验收脚本，按它验收会把这个承诺当成预期行为。

**最小修复**

- 在 J4a 落地前，把 spec:482/500/985 改为“仅本次/本次生效”，或把相关示例整体移到
  J4a 之后；
- 给 J1b 的提示词/契约校验器加一条断言：J4a 未合入前，fixture/文案不得出现
  “默认持久/后续生效/以后都生效”。

## 四、仍然存在的 majors / minors

### Majors

1. **M1 `statePhase` 派生仍不完整。** spec:180-205 的信号表混用了 pre-turn 状态与
   用户本轮意图；`stale` 出现在 statePhase 取值里（spec:196）但
   `JourneyContext.phase` 的 Literal 没有它（spec:280）。`hasProfile`/`hasCandidates`
   没有派生定义；`ConversationSnapshotService.java:130-140` 的 `missingFacts` 只有
   province/score/rank，而 §3.4 的 discover 条件含年份/科类/批次/选科。建议补一张
   statePhase 真值表（输入：missingFacts、candidatePool.summary.total/statusCode、
   working/ordered 条目数、review.sourceVersion、staleFlags），`stale` 只做独立布尔，
   并明确 `hasCandidates = summary.total>0 || statusCode != not_generated`。
2. **M2 join 会解析整份候选池，与“不重扫/缓存”承诺冲突。**
   `PlanningStateService.java:5861-5869` 的 `loadPlanningStateReadOnly` 会调用
   `backfillCandidatePoolFromSplitRow`（`:5930-5955`），后者把
   `planningCandidatePool` 整行（spec:1110-1111 自述 4–29MB）解析进内存。spec:884-885
   说“不需要每次重扫”，spec:1110-1111 要求按
   `planVersion + candidateSourceVersion + dataVersion + admissionMode` 缓存，但
   J2b 没有任何缓存/索引任务。建议：先建按 `volunteerId` 的派生映射（或池行内索引），
   或明确接受一次解析并加进程内 LRU + 失效测试。
3. **M3 解读证据的 dataVersion 组成不可算。** spec:704-708 要求
   `hash(planVersion, candidateSourceVersion, historyDataVersion)`，但
   `CandidatePoolStateDTO` 没有 `dataVersion`（只有 `sourceVersion`），
   `historyDataVersion` 在未调用 `admission.get_history` 时不存在；同时 drivers 会
   引用 `reviewState.checks`，而 hash 没含 `reviewState.sourceVersion`。建议写死为
   `hash(planVersion, candidateSourceVersion, dataFreshnessState.dataVersion,
   reviewState.sourceVersion)`，历史明细不进入主证据或单列。
4. **M4 J3 任务不可执行。** 计划 J3 只有三条勾选，没有文件清单；实际要改
   `server.py:1083-1104` 的 `_action_result_payload` 和
   `conversationEvents.mjs:43-46` 的 payload 白名单，否则 `origin/actionType/scope/
   receipt` 会被静默过滤。补文件、去重规则（同一 `operationId`）、一张卡的测试。
5. **M5 `PlanReceipt.tradeoffs/reason_codes` 仍无生产者。** spec:599-620 把它定为
   “取舍解释的唯一来源”，但当前 apply 结果（`conversation_actions.py:60-75`）只有
   actualChanges/reviewState。要么 J3/J4a 让 Java 产出，要么明确“取舍可来自
   structure_before/after 对比”，否则 §10.2 的“一句取舍解释”无法执行。
6. **M6 方案变更后的默认落点摘要没有生产者。** spec:959-963 要求方案首次生成/变更/
   审查完成三类回复都带落点摘要。apply 后确有续接回合
   （`server.py:1230-1305`），但计划没有要求续接提示词调用
   `planning.interpret_admission`；不补的话，摘要在真实链路里不会出现。
7. **M7 解读结果体积未约束。** `LandingScenario.path` 是完整 `EntryRef` 列表
   （spec:788-796）；45 条方案 × 4 场景可能几十 KB，既进模型上下文又可能撞
   artifact/event 的 16KB 限制。建议 `path` 只保留到 `landing_entry`（或前 N 条），
   完整方案用 artifact/按需查询；写清上限。
8. **M8 B5/B9 文案残留。** spec:343 仍列 `prefer`；spec:406-409 仍把风险姿态/优先级
   写成已生效；spec:323 的 `review_plan` 仍写“能力开关待修”。与 §5.1b/§13.8 对齐。
9. **M9 `workingPlanState` 没有 `position`。** `DraftItemDTO.java:6-14` 只有
   volunteerId/tier/schoolName/majorName/locked/source；spec:693 说“模式不明确时按
   orderedPlanState.items 的 position 扫描”，但若只有 working plan，顺序只能取列表
   索引。请写死回退规则，或要求解读必须有 orderedPlanState。
10. **M10 J4a 学费持久化有双源风险。** 计划把 `tuitionRange` 持久化到 PlanningState，
    但现有 `ChatSessionBizService.updateTuitionRange` 写的是 `userScoreDetail`
    （`:216-245`）。J4a 必须定义唯一事实源、迁移/回读规则和 stale 标记，否则
    fill/scope/initial 会读两份不同的预算。
11. **M11 `JourneyAction` 不存在。** plan J1b-T1 要求“动作在 `JourneyAction` 里”，
    但全仓没有该枚举，计划也没有创建任务。请在 `journey.py` 定义枚举（或把
    fixture 的 action 枚举写进 schema），并让契约校验器引用它。
12. **M12 tier 与 ratio 冲突没有处理规则。** spec:669-670 允许用
    `OrderedUnitDTO.schoolEnrollRatio` 确认 `pathTier`，但两者矛盾时（候选池刷新后
    tier 过期）没有 caveat/恢复规则。建议输出 `tier_ratio_conflict` caveat（不改
    pathTier），或把冲突条目标 `unknown` 并说明。
13. **M13 `pending_applying` 无来源。** `ConversationSnapshotService.java:142-168`
    只暴露 status=`active` 的 pending；JourneyContext.pending_applying
    （spec:293）无法从快照派生。把 applying 状态放进 journey 块（或 activeProposal
    的 status），否则该字段恒 false。

### Minors

1. spec:666-667 引用 `VolunteerIntervalService.java:96-102`（未使用的三区间分支）；
   实际生产是九区间 `:61-79` + `VolunteerSorterAndMerger.java:59,161-175`。边界结论
   不变，改引用即可。
2. `EntryRef.school_ratio` 写 0–100（spec:784）；`admission/facts.py:47-50` 的上限是
   99，前端 `conversationEvents.mjs:175` 的 admission fact 分档用 `<50/<70`。两套数据
   不要互相复用格式化函数。
3. `scenario_id`/`generated_at` 的生成规则未定义（spec:789,801）。
4. `interpretation.preview` 与 `assistant.completed`/`turn.completed` 的相对顺序未
   定义；frontend reducer 的终态守卫（`conversationSession.mjs:99-110`）要求明确。
5. `TOOL_LABELS` 没有新工具条目（`ui_events.py:43-78`），进度条会显示默认/原始名。
6. `removeEntryRefs` 删除全部条目时的返回未定义（空方案 `no_plan` 还是全滑档？）。
7. `planVersion=workspace.version` 会在补录成绩/偏好变更时也 bump（
   `PlanningStateService.java:617,2927-2937`）；作为保守缓存键可以，但要在文档写明。
8. J1b 的“40 条 fixture”没有给 schema（`ambiguity`/`expected_action`/
   `required_slots` 的具体形状），契约校验器测试无法先写失败测试。

## 五、建议的下一步切片顺序

**阶段 0：设计/计划修订（不改代码）**

1. 修 N1：agent `ConversationTurnSnapshot` + `build_snapshot` + `diff_snapshots` +
   service 注入；写进 J1a 任务。
2. 修 N2：重写 §8.3 规则 4 与真值表行 5/7/9，统一“历史不参与 band”，定义
   base/upside 的 unknown 与 data_coverage。
3. 修 N5/N6：工具改名 + `TOOL_INPUT_SCHEMAS`/`TOOL_KINDS`/`TOOL_OUTPUT_SCHEMA`；
   写进 J2b-T2。
4. 修 N4：选定“有界事件 payload”或“artifact 内容存储 + 取数接口”，并补
   `MessageList` 渲染/类型任务。
5. 修 N3/N7：清理 §〇、§3.5、§10.4、§6.2/§6.3 的旧口径。
6. 补 M1（statePhase 真值表）、M2（缓存/索引）、M3（证据 dataVersion）、M11
   （JourneyAction）。

**阶段 1：J2a（纯函数 + 真值表）**

- 先写 pathTier/join/场景扫描的纯函数；用修正后的 9 行真值表 + 混合缺失 fixture
  锁死；不接 Spring/DB。

**阶段 2：J2b（Java inner + MCP，先文本）**

- 在 N5/N6 修好后加 `planning.interpret_admission`；补证据信封、planVersion 校验、
  join 缺失、stale/no_plan/unsupported_counterfactual；同时决定并实现 M2 的缓存/索引。

**阶段 3：J1a/J1b/J1c**

- 在 N1 修好后做快照 journey 块、agent 派生与注入；再落触发目录/提示词/契约校验器；
  最后做硬不变量校验（一轮一个写、pending 才能 confirm、409 applying、版本守卫）。

**阶段 4：J2c（解读卡）**

- 在 N4 修好后做事件/artifact/取数/MessageList 渲染；先文本后卡片；只发有界摘要。

**阶段 5：J4a → J4b**

- J4a scope/学费持久化 + stale + REPLACE；J4b remove/move/pin。J5/J6 继续另立路线图。
- J3 只做现有回执扩展，且必须先补 M4 的前端白名单/服务端 payload 任务；undo 前不做
  自动改方案。

## 六、审查边界

- 只读代码与文档；未运行测试、未调用模型、未部署。
- 未复核 4–29MB 候选池/1–4MB planningState 的真实规模；M2 的耗时判断基于代码路径，
  不是实测。
- 未验证 `$ref` 在真实库中的具体形态；只确认 `loadPlanningStateReadOnly` 走
  Fastjson 解析 + 池行回填，J2b 应复用该入口。
- 未验证前端 artifact 路径在其它页面是否另有实现；N4 基于当前
  `conversation.ts`/`WorkspacePanel`/`MessageList` 的可见引用判断。
