# 用户旅程、对话控制与录取解读 Implementation Plan（v6）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先把“完整要求 → 约束 → 预览 → 确认 → 执行 → 复查”的语义收口（Batch A），
再按当前可用路径闭环（Batch B），然后评价输入/规则（C）、按动作接规划器（D）、
优化策略（E）、解读增强（F）。确认执行底座、pending/CAS、现有 add_units EXPAND
保留，不重写。

**当前状态：** J2a 的纯函数已按 F04 降级为结构/条件情景（无 likelihood/slipRisk），
15 个测试通过；**已通过 J2b 接入 inner 接口/MCP/解读卡，真栈验证完成**。Batch A 已完成大部分：A1 契约（9 tests）、
A2 源码行为真值表 + 卡面/提示词生命周期文案（Java +6 tests）、A3 纠正优先/确认冲突
校验/applying 不出按钮（Python 7 + Web 46）、A4 结构解读（15）、A5 评价四字段/缓存/输入凭据。Batch B 已完成 B1（IntentDraft
输出/守卫，含 confirm+intentDraft、非 atomic ready、ChangeOperation 完整要求）与
B2（TaskDraft 进程内 + Redis 持久化）；B3 真栈验收已完成点名为主/约束/阻断/
超时语义（证据见 `docs/superpowers/reviews/2026-10-18-b3-true-stack-acceptance.md`），
P1 已修复并复验（数量 postcondition + 回执缺口 + 守卫 UX）；A3 旧卡/重复确认
真栈端到端已完成。J2b/J2c 已接入并真栈验证（工具、解读卡、路由/续接提示词）；
J5.0 评价影子基线与 golden diff 完成；J5.2 主干完成（审查附加评价、摘要派生、修复读 delta、解读消费 findings）；
Batch D0 按范围加入已上线（add_units_by_scope 真栈 45→48 组）。剩余：
D 的 replace/move/remove/fill 规划器、J1 旅程块、checks 最终删除。
**J1 状态：已部署，真栈验收通过（2026-10-18）。**
已实现：Java journey/freshness/可解读事实、upsert 拒绝 applying、applying 对账；
Agent 派生/注入/reconcile/人工审查摘要；40 条触发目录；applying 硬不变量与
planned ChangeSet 收口。
单测：Java J1 相关 55 例通过（snapshot 15 / pending 19 / facade 5 / interpret 16）；
Python 全量 2897 passed / 33 skipped；`PlanningStateServiceTest` 仍有 8 个
**既有** J5.2 相关失败（14→15 probe、策略/计数断言），与本批 J1 改动无关。
部署：Java 18290 pid 19547、Agent 18291 pid 21810；插件
1.0.0+codex.20261018092455；已提交 f66b78a（含前置批次）。
真栈证据：`docs/superpowers/reviews/2026-10-18-j1-true-stack-acceptance.md`
（10041984 snapshot 45/45、900040 只读回合按 freshness、reconcile 接线）。
设计稿：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md`（§12 追加审阅）。

**Architecture:** Java 快照新增紧凑 `journey` 块；agent 派生 `statePhase`，模型输出
`taskIntent` 覆盖；触发目录带载体/状态/失败行为；Java 新增只读
`PlanAdmissionInterpretationService`（`pathTier` 来自校线，专业 ratio 只做证据）；
agent MCP 转发；解读卡走“工具结果 → 有界摘要事件”，不依赖 artifact 明细。

**Tech Stack:** Python ≥3.10 / Pydantic、Java 8 / Spring Boot、Next.js/React、
pytest、JUnit、Node test runner。

**Spec:** `docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`（v6）
**Full-chain review:** `docs/superpowers/reviews/2026-10-18-plan-conversation-system-review.md`
**Semantic map:** `docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`
**Reviews:** `docs/superpowers/reviews/2026-10-18-journey-control-and-admission-interpretation-review*.md`；
`docs/superpowers/reviews/2026-10-18-plan-semantic-authority-review.md`
**Baseline:** `616464c`（工作区含 add_units EXPAND 未提交改动）。

## Global Constraints

- 先写失败测试，再做最小实现；每个任务跑定向测试；未验证不写“已通过”。
- 不新增写工具；写动作仍走 `proposalRequest` → pending → 用户确认 → Java 确认链。
- 一轮一个写；`proposalRequest`/`scoreUpdateRequest`/`careerUpdateRequest` 互斥。
- 录取解读只读：不创建 pending、不写方案；不展示精确概率；缺数据标 `unknown`。
- **数据口径**：`pathTier` 只来自校线 `schoolEnrollRatio`（`<=50 冲`、
  `<=70 稳`、`>70 保`）；专业级 `admissionRatio` 只做组内证据，不改 `pathTier`；
  `OrderedItemDTO` 无 ratio，必须按 `volunteerId` join 候选池，join 不到标 unknown。
- 解读优先读 `orderedPlanState`；候选池拆分用
  `loadPlanningStateReadOnly`/`backfillCandidatePoolFromSplitRow` 回填后的
  `candidatePoolState.items`；**不存在 `$ref` 解析器**，不要自己写；不重扫
  4–29MB 候选池。
- `rankInTier` 不是历史位次；历史只作证据，不参与 MVP 落点判断。
- **J2a/J2b 直接消费 `ReviewStateDTO.checks`**；不先造 `PlanEvaluation`/适配器。
  J5.0 定义 `EvaluationContext` + 14 个 probe 全表 + `PlanEvaluation` + golden diff，
  J5.2 再切换。
- **版本只有一个计数器**：`stateVersion = planningState.version =
  workspace.version = snapshotVersion = sourceVersionGuard`，review/偏好/候选生成
  都会 +1；内容版本另算 `planContentDigest`，不要声称 `planVersion` 只随方案变化。
- **J1a 事实**：`stale` 按 flag 值/reason 判，不按 `staleFlags` 非空；
  `pendingStatus` 要 active+applying 的确定性查询；`hasPlan` 要 items ∪ units。
- **本批不删持久化字段**：ReviewState/checks、`OrderedUnitDTO.admissionRatio`、
  `PlanGoalTypeValue`、`RepairProposalTaxonomy` 执行协议等先停写/读适配；删除在
  J5.5 之后。
- 不新增 `system.action`；`conversationAction.result` 仍是唯一回执。
- 不做 DB migration；不改 legacy `app/zhiyuan_agent/prompt.py`。
- 不提交、不部署、不重启共享服务，直到定向测试全绿且用户确认（用户另行授权除外）。
- 面向用户不出现系数/权重/打分；只讲档位、落点、取舍；`base` 不叫“最可能”。

---

## Phase A：语义与保护边界（先行，纯文档+契约，不写业务）

### Task A1：IntentDraft / ChangeSet 复合要求

**Files:**
- Create `zhiyuan-agent/app/gateway/intent_draft.py`（目标态；或先在 skill 契约里定义）
- Create `zhiyuan-agent/tests/unit/test_intent_draft.py`
- Create `zhiyuan-agent/tests/fixtures/composite_requests.json`

- [x] 定义 `IntentDraft`：对象/强度/范围/有效期/未解决项/依赖；不落有效业务约束。
- [x] 定义 `ChangeSet`：本轮最多一个待确认变更集；服务端必须能真实支持全部操作。
- [x] fixture 覆盖“加六条 + 限地区 + 限学费 + 稳妥”，断言：不丢掉任一硬要求；
  不支持时阻断/协商分步，不先执行子动作。
- [x] 跑定向 pytest：9 tests 通过。

### Task A2：约束生命周期行为真值表

**Files:**
- Create `docs/superpowers/reviews/2026-10-18-constraint-lifecycle-truth-table.md`
- Tests: none（文档 + 后续代码任务引用）

- [x] 逐字段登记：scope/negativeScope/tuition/requirements/priority/tierQuota/
  targetCount，写到哪里、哪些读路径、是否重排、何时失效（见
  `docs/superpowers/reviews/2026-10-18-constraint-lifecycle-truth-table.md`）。
- [x] 删除/改写“J4a 前一律仅本次”的一刀切文案；卡面按真实行为：
  scope/学费 ready 卡写明“确认后写入本会话报考要求并重新生成”，无命中 info 卡
  明确“尚未写入报考要求、后续不会自动过滤”；提示词补同一口径
  （`UserGoalProposalBuilder` +6 tests，`developer_instructions.write.md`）。
  `impact` 已进 `proposal.preview` 白名单并由 `ProposalCard` 渲染；真栈预览
  事件已读到新文案（见 B3 验收记录）。
- [x] 目标态：学费只写 `userScoreDetail` 一个 owner；scope/requirements 只写规划状态；
  草稿仅存在 workingSet/ChangeSet，确认前不进入有效约束（J4a 真栈 900016 验证）。
- [x] 源码核对 5 个待验证项并回填（`2026-10-18-constraint-lifecycle-truth-table.md`）；
  仅“重排时序”留真栈验证。

### Task A3：确认/纠正/取消协议

**Files:**
- Modify `zhiyuan-agent/skills/codex/developer_instructions.write.md`
- Modify `zhiyuan-agent/app/gateway/conversation_actions.py`（校验/文案）
- Tests: `test_gateway_turn_conversation_action.py` 增补

- [x] 删除“用户没反对即确认”；明确肯定+对象唯一+内容未变+有效 pending 才能确认。
- [x] “确认，但……”/“预算改成两万”/“不是替换，是加入” → 不执行原卡，转重新预览：
  提示词 + 网关契约校验（confirm/cancel 不能同轮携带新草稿）已落地。
- [x] 取消只对 active；applying 不展示确认/取消按钮（`proposalNeedsConfirmation`
  已加 applying 门禁，46 个 web 测试通过）；执行中/回滚/撤销仍分开展示。
- [x] 测试覆盖混合确认（`test_confirm_cannot_be_combined_with_a_new_proposal_draft`）；
  旧卡点击/重复确认真栈验收完成（克隆会话 900049）：首次确认 applied 45→46 组；
  再次文字确认被识别为已生效、不重复执行；旧卡点击回 `stale_state /
  proposal_reference_mismatch`，方案与 operation 台账均不再变化。证据见 B3 验收记录 §五。

### Task A4：结构版解读（J2a 修订）

**Files:**
- Modify `zhiyuan-server/.../LandingScenarioDTO.java`（已完成）
- Modify `.../AdmissionInterpretationRes.java`（已完成）
- Modify `.../PlanAdmissionInterpretationService.java`（已完成）
- Modify `.../PlanAdmissionInterpretationServiceTest.java`（已完成）

- [x] 删除 `likelihoodBand`/`slipRisk`；改为 `structureStatus`/`condition`/
  `safetyCoverage`/`dataCompletenessBand`。
- [x] 结构覆盖与数据缺口分开；“有保底档位”不等于风险低。
- [x] 15 个结构/条件情景测试通过；不接 J2b。

### Task A5：评价分类/缓存/输入凭据（目标态定义）

**Files:**
- Modify `docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`
- Modify `zhiyuan-agent/...`（后续任务引用）

- [x] 定义 `resultStatus/ruleStrength/displaySeverity/fixability` 四字段
  （spec §7.8 + 14 probe 表）。
- [x] 个性化缓存 key 加 tenant/session + candidate digest + overlay/mode +
  counterfactual；字节/条目双限（spec §0.5.8）。
- [x] 定义评价/预览/解读的不可变输入清单；旧 findings 不能与新摘要重新认证
  （spec §0.5.8 `EvaluationInputManifest`）。

## Phase J2a：Java 纯函数与真值表（结构版，已完成，归入 A4）

### Task J2a-T1：DTO 与 `pathTier` 分类

**Files:**
- Create `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/AdmissionInterpretationReq.java`
- Create `.../AdmissionInterpretationRes.java`
- Create `.../LandingScenarioDTO.java`
- Create `.../InterpretationEntryDTO.java`
- Create `.../service/biz/PlanAdmissionInterpretationService.java`
- Create `.../service/biz/PlanAdmissionInterpretationServiceTest.java`
**Interfaces:**
- J2a **直接消费现有 `ReviewStateDTO.checks`**（不新建 `PlanEvaluationDTO`/
  `EvaluationFindingDTO`/`StructureVectorDTO` 适配器）；drivers/caveats 从 checks
  的 code/severity/summary/affected ids 映射，保留现有 unit/item 与
  `admissionRatio`/`schoolEnrollRatio` 口径。
- `ReviewStateDTO.checks` 在本批是只读输入；J5.0 先定义 `EvaluationContext` +
  完整 probe 表 + `PlanEvaluation`，J5.2 再替换 J2a 的输入适配，避免 throwaway DTO。
- `EntryRef{level:unit|volunteer, id, position, schoolName, majorName, pathTier,
  schoolRatio, majorRatio}`；`unitId` 取 `volunteerId` **第一个 `_` 前段**。
- `pathTier` **以 `OrderedItemDTO.tier` 为准**（`冲/稳/保`，缺失/非法 → `unknown`）；
  `schoolRatio` 只用于 upside 排序/一致性提示，**不反向覆盖 pathTier**。
- `majorRatio` 只填专业级 join 结果，不参与 `pathTier`。
- unit 模式用 `OrderedUnitDTO`；major 模式用 `OrderedItemDTO` + `volunteerId` join。

- [x] 写测试：边界 50/70（tier 与 schoolRatio 的已知映射）、校线 60/专业 40、
  校线 45/专业 75、ratio 缺失/越界；断言 `pathTier` 不被专业 ratio 改变；
  unit/major 两种模式各一组。
- [x] 实现 DTO 与分类；不依赖 Spring 数据访问。
- [x] 跑 `mvn -Dtest=PlanAdmissionInterpretationServiceTest test`：15 tests 通过。

### Task J2a-T2：顺序扫描与真值表

**Files:**
- Modify `.../PlanAdmissionInterpretationService.java`
- Modify `.../PlanAdmissionInterpretationServiceTest.java`

- [x] 写测试：§8.3 结构真值表 **13 行**（正常梯度/无保/全冲/全保≥2/保在稳前/
  唯一保缺失/全缺失/全 unknown/空方案/major join 缺失/两条保一条缺失/单保/双保），
  断言 base/upside/downside/no_safe 是否存在、structureStatus/condition、
  safetyCoverage、dataCompletenessBand、order_anomaly。
- [x] 实现按实际 `position` 扫描：`base=跳过 unknown 后第一条稳/保`；
  `upside=冲里校线 ratio 最高（全缺取最早冲）`；`downside=最后一条保`；
  `no_safe` 仅在无保底/无法判断时输出。
- [x] 实现 `safetyCoverage`/`dataCompleteness=min(tierCoverage,ratioCoverage)`/
  `dataCompletenessBand`；**不输出 likelihood/slipRisk**。
- [x] 解读直接消费 `ReviewStateDTO.checks` 作为 drivers/caveats；保留现有
  code/severity/affected ids 口径；J5.0 后再换 `PlanEvaluation`，不在本批造适配器。
- [x] 实现 remove-only 反事实：删除指定 EntryRef 后重跑；add/replace/reorder 返回
  `unsupported_counterfactual`。
- [x] 跑定向 JUnit：15 tests，0 failures。

## Phase B：当前可用路径闭环（Batch B）

### Task B1：IntentDraft 输出与网关守卫

**Files:**
- Modify `zhiyuan-agent/app/gateway/contracts.py`（`TurnOutput.intent_draft`）
- Modify `zhiyuan-agent/app/gateway/service.py`（schema + `build_change_set` 守卫）
- Modify prompt/skills（已写）

- [x] TurnOutput 可选 `intentDraft`，进 TURN_OUTPUT_SCHEMA（可空）。
- [x] 复合 `intentDraft` 非 ready **或非 atomic** 且同轮带 proposalRequest → 拒
  `composite_request_requires_staged_preview`，不允许先执行子动作。
- [x] `confirm/cancel` 同轮出现非空 `intentDraft` → 拒
  `confirmation_conflicts_with_new_intent`（确认回合应 `intentDraft=null`）。
- [x] 复合 `intentDraft` 不带 proposalRequest → 允许文本说明“先约束/澄清”。
- [x] `ChangeOperation` 携带完整 `requirements/priorityRules`，后续步骤可还原。
- [x] 测试：schema、复合确认拒绝、confirm+intentDraft、fill+requirements、
  non-atomic ready、纯文本允许。

### Task B2：有界 TaskDraft

**Files:**
- Modify `zhiyuan-agent/app/engine/working_set.py`
- Tests: `test_working_set.py`

- [x] `taskDraft` 只保留最新一页：intentDraft + changeSet + turnId。
- [x] `reconcile_snapshot` 不丢任务；`as_payload` 暴露给模型。
- [x] 测试：composite 任务保留、快照推进后仍在。
- [x] TaskDraft 持久化到 Redis（`RedisTaskLedger`：tenant/session、TTL 7 天、
  ≤16KB；Redis 不可用降级进程内），并有 gateway 跨回合 save/load 测试。
- [x] 用户取消提案时清空 TaskDraft 与 Redis 账本（避免下一轮“继续”复活旧任务）。

### Task B3：继续/失败恢复闭环

- [x] 模型读 `taskDraft.changeSet` 的剩余项；“继续”先推进只读/澄清/预览，
  不自动确认下一次写入（提示词已写）。
- [x] 执行超时返回 `applying`（结果未知/处理中），不把已提交命令显示成失败；
  单测覆盖。operation 台账真栈读数见验收记录（`succeeded` 行可查）。
- [x] 复合要求分步时，每一步都说明覆盖范围与剩余事项（真栈：范围型加入被明确
  阻断并给选项；点名加入 6 条零删除；学费约束后自动续接如实报告 51→36 组缺口）。
- [x] 端到端 fixture（真栈）：点名六条加入 → 确认 → `applied`（45→51 组、零删除）
  → 续接核位；学费上限预览 → 确认 → `applied` → 续接报告未达标与下一步。
  **严格“先约束→再加入”单请求链未复现**：模型把两件事拆成可执行动作，范围型
  加入被正确阻断；待 Batch D 的 add-scope 事务再验。证据见
  `docs/superpowers/reviews/2026-10-18-b3-true-stack-acceptance.md`。
- [x] P1（验收发现，已修复并真栈复验）：纯学费/替换类约束在数量缩水时返回
  `40905 / constraint_count_shortfall` 并整体回滚；回执补 `targetCountBefore/After`
  与 `shortage`，卡面渲染“总数 before→after / 还差 N”。实测 45 组方案、上限 6000：
  `before=45 actual=30 shortage=15`，方案保持 45 组/111 条，自动续接用中文说明并给
  三条路。only_keep/exclude 不套数量判据。详见 B3 验收记录 §四。
- [x] 新发现一并修复：模型自由动作名（`set_tuition_cap_and_preview` 等）+ `replace/fill`
  机制被误判为复合动作 → `normalize_action` + 纯约束机制归并，真栈学费预览恢复。

## Phase J2b：Java 只读接口 + MCP + 证据（2026-10-18 已接入）



### Task J2b-T1：Java inner 接口（无 chatSessionId 入参）

**Files:**
- Modify `zhiyuan-server/.../web/controller/inner/PlanningStateController.java`
  （`POST /session/plan/admission-interpretation`）
- Modify `.../service/biz/PlanningStateService.java`（只读加载；复用
  `loadPlanningStateReadOnly` 的候选池回填，不写 `$ref` 解析）
- Create `.../PlanningStateControllerInterpretationTest.java`

- [x] 写失败测试：缺 planVersion → 400；版本不符 → `stale_interpretation`；
  无方案 → `no_plan`；有方案 → 200 + 场景；`chatSessionId` 只从受信参数取。
  （`PlanAdmissionInterpretationFacadeTest` + `PlanningStateControllerInterpretationTest`）
- [x] 实现 controller/service；join 候选池按 `volunteerId`；join 不到标 unknown。
- [ ] 建 `volunteerId -> CandidateItemDTO` 派生索引并按
  `planVersion+candidateSourceVersion+dataFreshness.dataVersion+objectiveModelVersion`
  做进程内 LRU；缓存失效测试覆盖候选池刷新/方案版本变化。
- [x] 证据边界：MVP 不新签 computed 证据；`evidenceRefs` 只引用本次实际查到的
  上游证据，没有就空数组；推演结论用 caveats/reasonCodes；不伪造
  `sourceLevel=computed`（当前 ledger 不支持）。
- [x] 跑定向 JUnit。

### Task J2b-T2：agent MCP 工具

**Files:**
- Modify `zhiyuan-agent/app/mcp_server/tools_readonly.py`（CAPABILITIES + handler）
- Modify `zhiyuan-agent/app/mcp_server/server.py`（TOOL_INPUT_SCHEMAS/
  TOOL_DESCRIPTIONS/TOOL_KINDS/TOOL_LABELS/TOOL_CONTRACTS/
  TOOL_OUTPUT_SCHEMA.kind/tool_listing）
- Modify `zhiyuan-agent/app/util/internal_client.py`
- Modify `zhiyuan-agent/tests/unit/test_domain_mcp_tools.py`
- Modify `zhiyuan-agent/tests/unit/test_mcp_tools_readonly.py`（或新增）

**Interfaces:**
- `planning.interpret_admission(planVersion, counterfactual?)`；**不收 chatSessionId/
  tenantId/sessionId/userId**；身份由 binding 注入。
- 返回 `AdmissionInterpretation` 原样透传；不做算术、不补值。

- [x] 写失败测试：工具在 CAPABILITIES/READONLY_TOOL_NAMES；`tool_listing()` 不
  KeyError；`_trusted_arguments` 不接受身份字段；参数校验；Java 结果原样透传；
  缺数据 unknown。
- [x] 实现 handler/internal client + 全部 schema/kind/description；单轮只调一次。
- [x] 跑定向 pytest（含 `test_domain_mcp_tools.py` 的 `plan.` 前缀断言）。

### Task J2b-T3：解读技能与提示词（文本先通）

**Files:**
- Create `.../skills/plan-admission-interpretation/SKILL.md`
- Modify `.../skills/planner-routing/SKILL.md`
- Modify `.../skills/plan-final-review/SKILL.md`
- Modify `.../skills/plan-construction/SKILL.md`
- Modify `zhiyuan-agent/skills/codex/developer_instructions.md` / `.write.md`
- Modify `.../.codex-plugin/plugin.json`（cachebuster + 技能说明）

- [x] 写技能：何时调用、四情景、禁止精确概率/“最可能”、缺数据怎么说、
  反事实 remove-only。
- [x] 路由：方案类问题 → 解读；单点事实问题不强制。
- [x] apply 后的续接回合调用一次 `planning.interpret_admission`，正文带摘要；
  调用失败/无方案就不写摘要，不自己推。
- [x] 插件版本 bump（部署时重装）。
- [x] 跑现有 pytest/技能文本检查。

## Phase J1a/J1b/J1c：旅程与触发（agent + Java 快照）

### Task J1a-T1：Java 快照 `journey` 块

**Files:**
- Modify `zhiyuan-server/.../dto/conversation/ConversationTurnSnapshotDTO.java`
- Modify `.../service/biz/ConversationSnapshotService.java`
- Modify `zhiyuan-agent/app/gateway/contracts.py`（`ConversationTurnSnapshot.journey`）
- Modify `zhiyuan-agent/app/gateway/snapshot.py`（`build_snapshot`/`diff_snapshots`）
- Modify `zhiyuan-agent/app/gateway/service.py`（注入紧凑 JourneyContext）
- Tests: `ConversationSnapshotServiceTest.java`, agent snapshot tests

**Fields:** `hasProfile/hasCandidates/candidateSourceVersion/hasPlan/
planEntryCount/planVersion/reviewSourceVersion/admissionMode/staleFlags/
pendingStatus`。
`planVersion = stateVersion`（=planningState.version=workspace.version=
snapshotVersion=sourceVersionGuard，同一计数器；不是内容版本）；另算
`planContentDigest`；`hasPlan` = ordered/working 的 items ∪ units 非空；不新增表。

- [x] 写失败测试：无画像/画像齐/有候选无方案/有方案/补录成绩后 plan 仍在
  （phase 可回 profile_ready，但 `hasPlan=true`）/stale。
- [x] 实现 Java 快照投影；不每轮拉 workspace（J1，提交 `f66b78a`）。
- [x] `stale = any(flag=true) || reasonCode/message 非空`（不能按 `staleFlags`
  非空）；`pendingStatus` 用 `status ∈ {active, applying}` + revision 倒序取最新
  （不要沿用 `getCurrent` 的 `last("limit 1")`）；`hasPlan` 用 items ∪ units。
- [x] `journey` 不再重复 `admissionMode`；用顶层字段。
- [x] agent `contracts.py` 增加 `journey`；`snapshot.py` 透传并进 `diff_snapshots`；
  `StatePatch` 白名单允许 `journey`；`service.py` 注入紧凑 JourneyContext
  （含 `plan_version`，不注入全量）。
- [x] 跑定向 JUnit + `pytest tests/unit/test_gateway_snapshot.py`（或新增）。

### Task J1a-T2：agent JourneyContext 派生

**Files:**
- Create `zhiyuan-agent/app/gateway/journey.py`
- Create `zhiyuan-agent/tests/unit/test_journey_context.py`

- [x] 写失败测试：从 journey 块派生 statePhase；taskIntent 按映射
  （responseType=fact→verify、review→review、调用 interpret 工具→interpret、
  解读后明确改→adjust）；无 last_action；blocked_actions 含 add_units 已知阻断。
- [x] 实现 dataclass/派生函数；不落库。`taskIntent` 没有现成字段，先写映射，
  不假设模型输出 `taskIntent`。
- [x] 跑定向 pytest。

### Task J1b-T1：触发目录契约与提示词

**Files:**
- Create `zhiyuan-agent/tests/fixtures/trigger_catalogue.json`
- Create `zhiyuan-agent/tests/unit/test_trigger_catalogue.py`
- Modify prompt/skills as spec §5.

- [x] 写 fixture，带 `carrier/status/failure_behavior`；planned 动作不得
  在 `available` 集合。pin 退役后为 39 条。
- [x] 契约校验器单测：动作/载体/槽位/状态合法；不冒充模型路由。
- [x] 提示词只列可用动作；planned 动作明确说“待支持”；“必须有”写满方案只替换
  1 组；scope/学费持久化后按 J4a 口径写“写入本会话报考要求”。
- [x] 跑定向 pytest。

### Task J1c-T1：网关硬不变量校验

**Files:**
- Modify `zhiyuan-agent/app/gateway/service.py`
- Create `zhiyuan-agent/tests/unit/test_gateway_journey_invariants.py`

- [x] 写失败测试：一轮一个写；有 pending 才能 confirm；applying 拒绝新写；
  版本守卫；已知阻断给固定文案，不 repair。
- [x] 实现轻量校验；不做 8 状态机。
- [x] 跑定向 pytest。

## Phase J2c：解读卡（事件/reducer/MessageList）

### Task J2c-T1：解读卡事件（有界 payload，无 artifact 明细链）

**Files:**
- Modify `zhiyuan-agent/app/gateway/ui_events.py`（`EVENT_TYPES`）
- Modify `zhiyuan-agent/app/gateway/event_store.py`（类型/16KB）
- Modify `zhiyuan-agent/app/gateway/service.py`（拦截工具结果→有界摘要事件）
- Modify `zhiyuan-agent/app/server.py`（legacy 映射）
- Modify `zhiyuan-web/src/utils/conversationEvents.mjs`
- Modify `zhiyuan-web/src/.../conversationSession.mjs`（reducer）
- Modify `zhiyuan-web/src/.../MessageList/index.tsx`（渲染分支）
- Modify `zhiyuan-web/src/.../conversation.ts`（payload 类型）
- Create `.../ConversationEvents/InterpretationCard.tsx`
- Tests: agent + node.

- [x] 写失败测试：事件白名单接受 `interpretation.preview`；payload 只有有界摘要
  （scenarios 每场景不带完整 path）；16KB 超限截断；reducer 归并；MessageList
  渲染；legacy 映射不丢。
- [x] 实现 tool→有界 summary event；卡片展示 base/upside/downside/no_safe、
  证据缺口、caveat；缺数据 unknown；不按 artifactRef 取数。
- [x] 跑定向 pytest/node tests。

## Phase J3：现有回执扩展（不新增事件）

**Files:**
- Modify `zhiyuan-agent/app/server.py`（`_action_result_payload`）
- Modify `zhiyuan-web/src/utils/conversationEvents.mjs`（payload 白名单）
- Tests: agent + node.

- [x] 扩展 `conversationAction.result` payload：`origin/actionType/scope/receipt`
  摘要；前端仍一张卡；同一 operationId 在 reducer 去重。真栈 900045 的
  move 确认回执：`origin=user`、`actionType=move_units`、`scope=plan`，
  `receipt={operationId, countMode=unit, before=44, after=44, reorderedCount=1,
  postconditionSatisfied=true}`；`reviewState` 仍单独返回，receipt 不重复审查摘要。
- [x] 不做后台自动动作；undo 前不自动改方案。
- [x] 测试：apply 结果只出一张卡；审查摘要不重复；白名单不静默过滤新字段
  （Python + node tests）。

## Phase D0：按范围加入（add_units_by_scope，2026-10-18 完成）

- [x] Agent 契约：新 goalType `add_units_by_scope` + `addCount`；只允许
  scopes/negativeScopes/context/guards，禁止 exactTargets/targetCount/requirements/
  priority/tierQuota。
- [x] ChangeSet：归一为 `add_by_scope`，ready/atomic；忽略冗余
  `additionalMutations=["add"]`；其他附加结构变更才拆步。
- [x] 网关：ready/atomic 草稿允许同轮提案；预览回合误标 recommendation/review
  且无 artifactRefs 时降级 text，不整轮失败。
- [x] Java：按范围筛选（未选/未屏蔽/硬约束合格/范围/学费）、group 按专业组去重取
  前 N 组、major 取前 N 条；复用 dryRun/add 动作/目标数/回执；不足如实阻断；
  prepare 与 add_units 同路冻结。
- [x] 真栈：900058 加三条安徽、学费≤6000 → ready 预览列明 3 组，确认后
  45→48 组、111→114 条、零删除。
- [ ] 后续：每组多专业粒度、fill 规划器、严格“先约束→再加入”
  （replace/remove/move 已在 J4a/J4b 落地）
  分步链。

## Phase J4a：scope/学费持久化 + REPLACE（后续）

- [x] `applyUserGoalTargetToPlanningState` 持久化 targetScopes/negativeScopes/
  tuitionRange；生命周期按目标语义落定：scope/学费目标写会话约束（session），
  `add_units_by_scope` 保持一次性选条（once）。提交 `6f59e27`。
- [x] `updateTuitionRange` 标记约束/规划 stale（`9616633`）：与
  `resolveEffectiveCandidates` 同口径，只标 recommendation/plan/review，不把候选源
  数据本身标脏；目标链在方案写入前以 CAS 落学费。
- [x] 真栈验收（900016）：`exclude_scope=经济学` 应用后
  `mustExcludeMajors=["经济学"]`；强制重生成仍 45 组且经济学 0 条。
  学费 100000→6000 落 `userScoreDetail`，规划状态 6→7 并置
  `constraint_intent_changed` stale（candidatePool 不动）。卡片文案沿用 A2 的
  “确认后写入本会话报考要求并重新生成”。
- [x] REPLACE 按 v6 frozen/预览/后置骨架实现（`f1fb209`）：`add_units` 增
  `addPolicy=expand|replace`；replace 预览列全换入/换出（专业组模式按组原子），
  prepare 冻结 added/removed volunteer+unit 集合，execute 只认冻结命令。
  真栈 900045：45→45 组，移出江西水利电力大学第501组（5 专业）、换入
  安徽师范大学第503组（计算机），未触碰条目全保留，后置条件 satisfied，
  审查重跑；pending complete=applied。
- [x] 真栈抓出并修复 overlay 覆盖未落盘 scope 的顺序缺陷（`a0efb36`）：
  apply 前先刷新推荐 overlay，之后重建工作草案；写 scope 时不再把
  `recommendationOverlay` 标脏，避免 apply 中途再次回填覆盖。
- 备注：900040 验收前快照已备份并从 `state-before.json` 恢复（588 候选/80 组）；
  900045/900016 保留为验收现场。

## Phase J4b：remove/move（pin 已移除）

- [x] `remove_units` / `move_units` 各自冻结命令、预览与后置条件（提交 `910dcd8`）：
  remove 冻结移出集合与总数变化，执行后要求移出集合消失、未确认条目全在、
  零新增、总数一致；move 冻结唯一目标与最终 1-based 位置，要求集合不变、
  只有目标移动、其他相对顺序不变。两项都重跑审查，失败 40907/40905 整笔回滚。
- [x] 真栈验收（900045）：move 45→45 组，目标组从第 44 位移到第 1 位，
  集合不变、仅目标移动、审查重跑；remove 45→44 组，只移出目标组、
  零新增、其余 44 组全保留、审查重跑。WS 卡片确认走网关 `move_units` 早分支，
  回执 `actualChanges.type=move` 带 from/to 与 44→44。
- [x] pin 对外清理：legacy `pin_lock` 动作、prompt 示例、触发目录 T27、
  回归样例、只读投影与 Web 类型全部移除；Java 内部 `pinned` 仍被优先规则/
  求解器用于保护条目，作为兼容字段保留；`lock` 不变。
- [x] 真栈抓到的模型口径问题：模型把 move/remove 的点目标重复写进
  `targetScopes`。ChangeSet 对“仅复述 targets”的 scope 不作为约束，
  ProposalRequest 前置归一；真正的额外范围仍拒绝并要求拆步。

### J5.0 影子基线（2026-10-18 完成，未切换）

- [x] 定义 `EvaluationContext` / `StructureVector` / `PlanEvaluation` /
  `EvaluationFinding` / `ObjectiveDelta` / probe 注册表（14 旧 check → 15 probe，
  `count_validation` 拆分）。
- [x] 定义 `objectiveModelVersion` / `evaluationVersion` / 缓存键；evaluationVersion
  必含 evaluatedStateVersion，缺输入不建缓存。
- [x] 实现 `ReviewEvaluationMapper` 影子映射（不改运行时审查）。
- [x] 选 8 个真实会话做 golden diff（7 个有审查、1 个无审查跳过）：
  14→15 全部可解释，无 pass/fail 漂移；报告见
  `docs/superpowers/reviews/2026-10-18-evaluation-golden-shadow-report.md`。
- [x] 大池样本（10041983，32MB 候选池）纳入 golden：14→15、无 pass/fail 漂移，
  `safety_guard` 与 `count_missing` 硬失败被正确读成 hardFeasible=false。
- [x] `objectiveDelta` 接 ActionCompiler（J5.2 完成，真栈 900055/900056）。
- [ ] ReviewState 变薄视图：`checks` 字段删除**暂缓**。消费者审计结论：不能直接删，
  需分三段——①Web/Agent 双读 findings、checks 回退；②Java 修复/后验改由
  finding+Registry+affectedEntryRefs 生成内存 check 视图；③旧会话回填或重跑审查后
  停写 checks。当前 `checks` 仍是旧会话与修复 builder 的必需回退。

### J5.2 评价接入（第一/二刀，2026-10-18 完成）

- [x] `ReviewStateDTO` 附加 `evaluationVersion/objectiveModelVersion/
  evaluatedStateVersion/evaluationStatus/probesRun/hardFeasible/findings`；
  `EvaluationContextBuilder` + `runReviewInternal` 投影评价；评价失败降级不阻断审查。
- [x] 快照 `preferences` 增加 `reviewEvaluationStatus/reviewEvaluationVersion/
  reviewHardFeasible`（不塞 findings）。
- [x] 解读消费 findings：fail/unknown 按 affectedEntryRefs 进情景 drivers，
  hard/policy 进全局 caveats；pass 不提醒。
- [x] 真栈验证：900053 evaluation completed/15 findings/hardFeasible=true；
  900054 safety 硬失败 → interpretation caveats 出现“审查：本省保底不足”。
- [x] summary 改由 findings 派生（15 probe；旧会话无 findings 回退 checks 14）。
- [x] 未通过/未知 finding 带 `objectiveDelta`；`ActionCompiler` 编译成
  `CompiledActionDTO`（`executable=false`，只产意图，执行仍走确认链）。
  真栈：900055 summary=15/passed 11/warn 3/risk 1；safety delta=add_safety_items。
- [x] `checks` 标注兼容字段；`generateFixProposals` 以 findings/delta 为入口
  （同一 sourceCheck 只出一条；旧会话无 findings 回退 checks）。真栈 900056：
  篡改 probability_gap delta 策略后 proposal strategy 随之变化。
- [x] 解读卡按 hard/soft 分组展示：Java `AdmissionInterpretationRes` 增
  `caveatDetails{text,level,code}`（与扁平 caveats 同源）；agent 事件只带
  最多 5 条 bounded 明细；Web 按“硬性要求/其他提醒”分组，旧 payload 无
  `caveatDetails` 时回退扁平 `caveats`。
- [ ] 删除 checks 字段：**暂缓**，消费者审计见 J5.0 条目；需先完成
  Web/Agent 双读、修复/后验迁移、旧会话回填三段。

## Phase J5/J6（另立路线图：统一目标/评价/优化，含审查）

- J5.0 基线 + 评价输入契约：
  * 给现有生成/fill/add/refill/review 输出 `StructureVector`；
  * 选 5–10 个 golden 会话记录现状（含大池/group/major/学费/配额）；
  * 定义 `EvaluationContext`（逐条 `admissionRatio`/`schoolEnrollRatio`/tuition/
    riskFlags、`selectionTargetCount`、`requiredCount`、`requiredTierCounts`、
    生源省、userScore、admissionMode、candidateSourceVersion）；
  * 把现有 **14 个 check 全量**列成 probe 表（code/layer/允许 severity/metric/
    threshold/affected refs/修复元数据），保留 unit vs item、`admissionRatio` vs
    `schoolEnrollRatio`、`count_validation` 动态 severity 的现有口径；
  * 定义 `PlanEvaluation`/`EvaluationFinding`/`ObjectiveDelta`；
  * 定义 `stateVersion`/`planContentDigest`/`evaluatedStateVersion` 与唯一缓存键；
  * 旧 review 与新 findings 的 golden diff 报告，差异逐条解释后才进 J5.1。
- J5.1 候选统一：`CandidateSnapshot`（eligibility/coverage/utility）；fill/scope/
  add/initial 共用；学费更新标 stale。
- J5.2 目标 + 评价：`ObjectiveCompiler` + `PlanEvaluator`（hard/structure/soft
  三层）；现有 `ReviewStateDTO.checks` 改造成 probe，不另写规则链。
- J5.3 Solver：同一目标下的搜索；软效用/多样性/候选帽；churn/结构偏差优先。
- J5.4 后置条件 + 审查：统一 `UnifiedPlanPostconditionValidator`；审查读同一
  `StructureVector`/`PlanEvaluation`；review tierQuotaGoal 与 solver 一致。
- J5.5 审查→动作：`EvaluationFinding.objective_delta` 编译成同一 `PlanCommand`；
  预览/冻结/后置/回执与普通动作一致；review fix 与 fill 同源。
- J5.6 清理：解释权重、`rank_in_tier` 语义、重复 filter/eligibility 规则。
- J6：风险姿态/目标优先级作为 `ObjectiveModel` 层，依赖 J5；不纳入本批。
- 前置 P0：J4a scope/学费持久化、candidate source 统一、coverage 40905、
  review tierQuotaGoal 口径；未修完不切换 solver。

---

## 验收口径（本批）

1. J2a 真值表 13 行全绿；`pathTier` 与专业 ratio 不混；join 缺失标 unknown。
2. J2b 文本解读在真栈可用；无方案/缺数据/版本不符有明确错误；无精确概率词。
3. J1a 快照 journey 块在补录成绩后仍能识别“有方案”；J1c 硬不变量无回归。
4. J1b 契约校验器全绿；不把 fixture 自检说成模型路由验证。
5. J2c 卡片只发有界摘要；完整 path/drivers 留在工具结果/正文；事件 ≤16KB；
   reducer/legacy/MessageList 有测试；不按 artifactRef 取明细。
6. 现有 add_units/score/career 三条写路径不回归；Python/Java/Web 定向测试全绿。
