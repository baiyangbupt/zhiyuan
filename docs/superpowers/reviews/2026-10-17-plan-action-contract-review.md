# 方案原子动作进入 codex 写闭环设计（planActionRequest）——独立审查

审查对象：`docs/superpowers/specs/2026-10-17-plan-action-contract-design.md`
代码基线：`616464c`（`wip/2026-09-28-p2-write-loop-green`）
审查日期：2026-10-17
审查方式：逐文件核对代码，不采信设计稿自述；本次不改代码、不改设计稿、不部署。

## 一、结论

**断层次分析成立，方向可行；但现稿不能直接进入实施。**

- “codex 只有只读 MCP、没有 add 动作、`must_include_scope` 不能替代点名加入”的判断，经代码核对**准确**；没有漏掉现成的 plan-action prepare、add_units 网关映射或 MCP 写工具。
- 但设计把两个最关键的权威问题留在了网关：**目标解析用 `preview_candidates`（20 条硬上限、只读重算池、无 unitId）**，以及**确认回执依赖尚未打通的 `actualChanges`/`reviewState` 字段**。按字面实施会出现“六条解析不全/解析结果与执行池不一致/卡片看不到加了几条”。
- Java 侧 prepare 的响应形状、apply 的接入点、review 重跑的事务与版本语义，也各有会导致返工或错误行为的硬问题。
- 更小的接入点存在：**扩展 `ProposalRequest`（新增 `goalType=add_units` + 精确 targets），复用现有 `fix-proposals/user-goal/prepare` 与确认链**；可以省掉新端点、新 PrepareResultDTO、新 pending 格式和一整套幂等/取代代码。详见第五节。

结论：**修订 blocker B1–B6 与 major 清单（M1–M2、M4–M10）后再进入实施；若采纳“复用 proposalRequest + 现有 prepare”的替代方案，实施面可显著缩小。**

## 二、分级问题清单

分级口径：
- **blocker**：按现稿字面实施会直接做错/做不出来，或目标 1–5 中至少一条无法达成。
- **major**：不致命，但会返工、引入回归或让线上语义不确定。
- **minor**：清晰度、健壮性、可运维性问题。

路径缩写说明：为可读性，下文 `zhiyuan-server/.../X.java` 指 `zhiyuan-server/src/main/java/com/ytell/zhiyuan/**/X.java`；`zhiyuan-web/.../X` 指 `zhiyuan-web/src/**/X`；`zhiyuan-agent/...` 为仓库内真实相对路径。

### Blocker

#### B1. 目标解析权威与覆盖不足：网关侧 `preview_candidates` 方案不成立

**问题**
设计 3.2 让网关用 `recommendation.preview_candidates` 按名称/ID 解析 targets。但这条只读预览：

1. **每页最多 20 条**，且 Java 侧硬上限写死；六条目标跨多校多专业时，单次查询可能被截断，设计没有分页/翻页策略。
2. **是“重算出来的一页”**，不是 apply 时用的持久化候选池；prepare 与 execute 的候选来源可能漂移。
3. **响应里没有 `unitId`（也没有专业组代码）**，设计中的 `PlanActionTarget.unit_id` 无法核验。
4. 过滤器是“维度内 OR、跨维度 AND”的**子串匹配**（学校关键词列表内任意命中，专业关键词列表内任意命中），无法直接表达“学校 A 且专业 B”的逐条精确配对；同校多专业/同专业多组会产生交叉命中。
5. `candidate_source_unavailable`（FINISHED 会话/无志愿文件）会被设计误报成 `no_match`，用户看到的是“没有这个专业”，不是“候选来源不可用”。

**证据**
- `zhiyuan-server/.../CandidatePreviewService.java:46-47`：`MAX_PAGE_SIZE = 20` 硬上限；`:127-154` 每次预览重新载入并只返回一页；`:80-125` `loadReadOnlyCandidatePool` 明确是“只读重算”，不落盘。
- `zhiyuan-server/.../CandidatePreviewRes.java:31-50`：Item 只有 `entityId/volunteerId/tier/schoolId/schoolName/majorId/majorName/...`，**没有 unitId、没有 groupCode**。
- `zhiyuan-server/.../CandidatePreviewService.java:183-206`：`applyFilters` 对 school/major 是 `containsIgnoreCase` 的子串匹配（维度内 OR、跨维度 AND）。
- `zhiyuan-agent/app/mcp_server/tools_readonly.py:1622`、`:1683-1690`：MCP 侧再次把 pageSize 截到 20，并明确 `returned_items_are_sample`。
- apply 实际使用的是持久化状态：`PlanningStateService.java:9426-9434`（`resolveEffectiveCandidates` 从 `state.getCandidatePoolState()` + overlay 读取），与 `preview_candidates` 的重算池不是同一份。
- 设计稿 3.2 第 1 条要求“先在 preview_candidates 结果里核验”，第 2 条要求“同一 school 合并一次查询”，均未提分页/持久池一致性。

**要求的修改**
- 目标解析改为 **Java 侧**（在 prepare 内）用与 execute 相同的 `resolveEffectiveCandidates(state)` 做：候选池成员校验、名称/别名匹配、已在方案判断、唯一/歧义判断。网关只传模型给的名称/ID，不承担权威解析。
- 如果坚持网关解析，必须补齐：分页直到 `total`、明确“preview 重算池 ≡ apply 持久池”的证明或切换为同一数据源、`unitId` 的权威来源（不能从 preview 拿）、`candidate_source_unavailable` 独立错误码、以及逐 target 的精确配对算法。成本不低于 Java 侧，且仍多一层漂移。
- 设计稿 3.2 的“唯一 volunteerId 才算 ok”与 legacy 口径冲突，见 M5。

#### B2. Java prepare 响应契约与状态词表不成立

**问题**
设计 3.3 的响应示例把 `title/summary/status=ready/requiresConfirmation/commandType/affectedItems/expiresAt` 放在 prepare 返回的**顶层**，并说“沿用 `PrepareResultDTO` 的形状”。实际 `PrepareResultDTO` 只有 `status/requestId/pendingId/operationId/result/message`；`status` 的真实取值是 `preparing/prepared/superseded`，**不是 `ready`**。如果网关把 `PrepareResultDTO` 直接交给 `_proposal_preview_payload`：

- 卡片 `status` 会变成 `prepared`，前端词表只认 `ready/info/preview_only/blocked`（`proposalCardText.mjs:92-104`），会显示“处理结果未知”；
- `title/summary/affectedItems` 根本不存在，卡片是空壳；
- `expiresAt` 不是 pending 表字段（`PendingConfirmationEntity.java:12-29`），没有来源。

**证据**
- `zhiyuan-server/.../PrepareResultDTO.java:16-23`：字段只有六项，`status` 语义是 prepare 状态。
- `zhiyuan-server/.../ConversationProposalRequestService.java:79-139`：成功时 `dto.setStatus(STATUS_PREPARED)`；`:141-165` replay 返回 `prepared/superseded/preparing`。
- 对照正确做法：`zhiyuan-agent/app/gateway/service.py:1446-1476`（补录 prepare）先取 `data.result`，再**单独构造**前端预览形状，并在 `:1468` 把写模式的 status 明确写成 `ready`；`proposalRef` 取 `data.pendingId`。
- 前端状态表：`zhiyuan-web/.../proposalCardText.mjs:92-104`；未知状态兜底为“处理结果未知”（`:119-126`）。

**要求的修改**
- 明确区分“prepare 状态”与“卡片状态”：Java prepare 返回一个独立的 `PlanActionPreviewDTO`（放在 `PrepareResultDTO.result` 里），或网关按补录 prepare 的模式构造预览对象；卡片 status 必须映射为 `ready`。
- 在设计中写出真实返回形状（嵌套 `result`），并列出 `prepared/duplicate/superseded/preparing` 到网关错误的映射；不要把 `prepared` 透传给前端。
- `expiresAt` 要么删掉，要么由 Java 按 pending 保留策略显式计算；当前 pending 无该字段。
- `commandType` 属于 pending dataValue，不必放在 prepare 顶层。

#### B3. apply 接入点不足：只扩 `_command_for_goal` 会走错路径

**问题**
设计 3.4 只说“`_command_for_goal` 读 active pending 的 commandType/actionFamily，add_units → command_type=add_units + volunteer_ids”。但 `_execute_claimed_command` 在调用 `_command_for_goal` **之前**已经：

1. 构造 `proposal_apply = _proposal_apply_payload(...)`；
2. 如果 `proposalSource == "user_goal"` 且缺 canonical 三件套，调用 `_canonical_metadata_from_producer(...)` 回生产者取元数据；
3. 只有进入 else 分支后才调用 `_command_for_goal`，且 `expected_plan_version` 也是在这个分支里从 `proposal_apply` 推导的。

plan_action pending 没有 `userGoalRequest` 时，`_proposal_apply_payload` 会走默认 `proposalSource="user_goal"`，用 `proposalId=pendingId`、`userGoalRequest=None` 去调生产者；随后 `_command_for_goal` 又因为读不到 `userGoalRequest` 返回 `APPLY_PLAN_CHANGE_PROPOSAL`。结果是：**该走 add_units 的确认被当成 apply_plan_change_proposal 执行**，或者先被一次无意义的 canonical 查询拖慢/报错。

**证据**
- `zhiyuan-agent/app/gateway/conversation_actions.py:873-926`：proposal_apply 构造、canonical 回取、`_command_for_goal` 的顺序。
- `:742-775`：`_command_for_goal` 入口先读 `userGoalRequest`，读不到直接返回 `APPLY_PLAN_CHANGE_PROPOSAL`。
- `:828-835`：`plan_version` 可取 `active.sourceVersion/data.sourceVersion`，但 `expected_plan_version` 只在 `:862-895` 的分支内计算。
- `:801-817`：operationId 只认 Java 产出的；add_units 需要沿用同一套。

**要求的修改**
- 在 `_execute_claimed_command` **最前面**增加显式动作族分支：`active_data.commandType == "add_units"`（或 `kind == plan_action`）时，直接取 `active_data.volunteerIds`、`active_data.sourceVersion`、`operationId`，跳过 `_proposal_apply_payload`、canonical 回取、region/major 解析，再调用 executor。
- 不要只扩 `_command_for_goal`；或者把 `_command_for_goal` 改为先看 `commandType/goalType`，但必须同时把 canonical 回取移出该路径。
- `expectedPlanVersion` 在 plan-action 分支显式取 `active_data.sourceVersion`（或 `active.sourceVersion`），不要走 `proposal_apply.sourceVersionGuard`。
- 设计要写清 `kind/actionFamily/commandType` 三个值分别是什么；建议 `kind=plan_action`、`actionFamily=add_units`、dataValue `commandType=add_units`。

#### B4. 回执字段端到端未打通：`actualChanges`/`reviewState` 目前到不了卡片

**问题**
设计 3.4/3.5 要求 apply 返回并展示 `actualChanges`（逐条加入项）与 `reviewState`。当前链路：

- Java `PendingPlanningCommandRes` **没有** `actualChanges`/`reviewState` 字段；
- `compactResultForReplay` 还会把 `planningState.reviewState` 置空，重放时 review 信息丢失；
- 网关 `ConversationActionResult` 虽有 `actual_changes`，但 `server.py` 的 `_action_result_payload` **只发** `proposalRef/actionStatus/newStateVersion/workspaceVersion/code/message`，明确不带 `actualChanges`；
- 前端 `conversationAction.result` 白名单同样只有上述键，`ProposalCard.actionResult` 类型也没有 `actualChanges/reviewState`。

因此“确认后卡片展示实际加入项与审查摘要”按现稿**无法实现**。

**证据**
- `zhiyuan-server/.../PendingPlanningCommandRes.java:9-25`：无 `actualChanges/reviewState`。
- `zhiyuan-server/.../PendingPlanningCommandBizService.java:294-327`：`compactResultForReplay` 把 `reviewState` 置 `null`。
- `zhiyuan-agent/app/server.py:1083-1105`：`_action_result_payload` 白名单不含 `actualChanges`。
- `zhiyuan-web/src/utils/conversationEvents.mjs:43`：`conversationAction.result` 白名单只有 `proposalRef/actionStatus/newStateVersion/workspaceVersion/code/message`。
- `zhiyuan-web/.../ProposalCard.tsx:101`：`actionResult` 类型只有 `actionStatus/proposalRef/code/message`。

**要求的修改**
- Java：给 `PendingPlanningCommandRes` 增加 `actualChanges`（结构化：added volunteerIds、新增单元数、档位）与 `reviewState`（summary + top checks 的紧凑形状）；`compactResultForReplay` 必须复制这两个字段。
- 网关：`_execute_claimed_command` 读出这两个字段；`ConversationActionResult` 增加 `review_state`；`server._action_result_payload` 放行 `actualChanges/reviewState`。
- 前端：`conversationEvents.mjs` 白名单、`ProposalCard`/reducer 类型与渲染同步；否则旧前端只能看到“已生效”，看不到“加了什么、审查如何”。
- 如果第一期不做完整回执，设计必须把目标 4 降级为“卡片只显示 Java 生成的 summary”，不要承诺逐条 `actualChanges/reviewState`。

#### B5. review 重跑的事务与版本语义自相矛盾

**问题**
设计在 3.4 写“新增 rerunReview”，在 6.1 又写“方案生效、审查失败单独提示、可重试”，但 3.4 同时说“失败整体回滚或按现有失败语义返回”。这三者不是同一件事：

- `PendingPlanningCommandBizService.execute` 是 `@Transactional(rollbackFor=Exception.class)`。如果 `runReview` 抛异常且不捕获，**add_units 也会回滚**，与“方案保持已生效”矛盾。
- 如果捕获异常，外层事务通常可以提交，但在某些数据库/事务标记为 rollback-only 的失败下不保证；而且 `runReview` 会 `state.version + 1`（`PlanningStateService.java:2835`），`executeCommand` 里的局部 `state` 是重跑 review 之前的对象，`resultPlanVersion`（`:219-221`）会**落后于实际版本**。
- 现有 fix apply 的先例是：`rerunReviewAfterFixApplyIfRequested` 调 `runReview` 后**重新 `getPlanningState`** 再返回（`PlanningStateService.java:1254-1262`）；设计没有要求这一步。
- 如果 `runReview` 放在同一事务内且成功，它会把版本再 +1；后续确认/卡片版本必须用重读后的值，否则下一次 `expectedPlanVersion` 必偏。

**证据**
- `zhiyuan-server/.../PendingPlanningCommandBizService.java:63-104`：整个 execute 在一个事务里；`:171-186` add_units 分支目前没有 review；`:219-221` 用局部 `state.version` 设置 `resultPlanVersion`。
- `zhiyuan-server/.../PlanningStateService.java:2777-2792`、`:2833-2838`：`runReview` 独立 CAS 保存并 `version+1`。
- `zhiyuan-server/.../PlanningStateService.java:1254-1262`：现有 fix apply 的 review 后重读范式。

**要求的修改**
- 先做产品语义二选一，并写进设计：
  - **A（与现有 fix apply 一致）**：review 在同一事务内，失败则 add 一起回滚；卡片显示“未生效（审查失败）”。简单、可解释。
  - **B（设计倾向）**：add 先提交，review 在提交后/独立事务执行；失败只写 `reviewStatus=failed`，add 保留。实现上需要把 review 移出 `execute` 的事务，或在独立 `REQUIRES_NEW` 事务中执行并捕获。
- 无论哪种，review 成功后必须 `getPlanningState` 重读，用重读后的 version 作为 `resultPlanVersion`/`stateVersion`；与 `rerunReviewAfterFixApplyIfRequested` 对齐。
- `actualChanges` 应在 add 前后对 working plan 做集合差得到（`selectWorkingPlanItems` 目前丢弃了新增 ID，见 M6），不要用 review 后的 ordered plan 反推。

#### B6. 模型侧 schema 接入未写，且严格 schema 会把“可选字段”变成必填

**问题**
设计只加了 Pydantic 类，没有提 `TURN_OUTPUT_SCHEMA` 的组装。实际模型看到的是手写严格 schema（`additionalProperties:false`），不把 `planActionRequest` 加进 `required`/`properties`，模型一输出就会被自己的 schema 拒；`extra="forbid"` 也会让 `TurnOutput` 解析失败。没有这一步，前面所有契约设计都到不了模型。

更隐蔽的是：`_strict_model_schema()` 会把每个模型的**所有 properties 都设为 required**，并去掉 default。设计里的 `filters/target_position/replacement_spec/review_issue_code` 等“可选/扩展位”在模型侧都会变成必填，模型必须输出一堆 null/空对象；`PlanActionTarget` 的四个字段也会全部必填，但没有“至少一个标识”校验，模型可以输出全 null 的 target。

**证据**
- `zhiyuan-agent/app/gateway/service.py:57-75`：`TURN_OUTPUT_SCHEMA` 手写 required/properties。
- `zhiyuan-agent/app/gateway/service.py:259-295`：`_strict_model_schema` 把 `required` 设为全部 properties，并去 default；`proposalRequest/scoreUpdateRequest/careerUpdateRequest` 逐个追加；`_normalize_nullable_for_upstream` 在 `:348` 统一改写。
- `zhiyuan-agent/app/gateway/contracts.py:11-19`：`extra="forbid"`。
- `zhiyuan-agent/tests/unit/test_turn_output_schema.py:47-64`：现有测试钉住 proposal schema 的 required/additionalProperties 纪律；新契约需要同款测试。

**要求的修改**
- 在 S1 明确：`TURN_OUTPUT_SCHEMA["$defs"]` 合并、`properties.planActionRequest`、`required.append`，且必须在 `_normalize_nullable_for_upstream` 之前完成。
- 第一期把 `PlanActionRequest` 收缩到最小字段：`action`、`targets`、`source_version_guard`、`raw_user_text`。`filters/target_position/replacement_spec/review_issue_code` 等 remove/replace 扩展位不要进第一期 schema；否则模型被迫输出无用字段、修复回合更难。
- `PlanActionTarget` 增加 model validator：四个字段至少一个非空；`targets` 加 `max_length`（例如 20），字符串 strip/长度上限。
- 版本守卫的检查要放进 `validate_turn_output`/`_validate_round`（那里 `stale_state` 在 `_REPAIRABLE_CONTRACT_CODES` 内），否则设计说的“可走现有一次修复回合”不成立：`service.py:2858-2862` 的 proposal 版本检查在修复循环之后，直接硬失败。
- 增加测试：schema 包含 planActionRequest、全部 required、nullable 归一化合法、至少一个 target 标识。

### Major

编号说明：原 M3（模型侧 schema 接入）已提升为 blocker B6，因此 major 从 M4 继续编号，不是缺号。

#### M1. 直接改共享 `add_units` 会改变 legacy 行为，必须加开关/命令类型

**问题**
`add_units` 不只服务新 codex 链路：legacy direct agent 的 `_apply_plan_pending` 也调用同一个 `execute_pending_planning_command(command_type="add_units")`。设计把 rerunReview/版本 +1 直接加进 `PendingPlanningCommandBizService` 的 ADD_UNITS 分支，会让**所有** legacy 加入动作多跑一次审查、多推进一次版本，并可能改变既有测试与用户卡片结果。

**证据**
- `zhiyuan-agent/app/zhiyuan_agent/tools.py:8146-8182`：legacy add_units 执行路径。
- `zhiyuan-server/.../PendingPlanningCommandBizService.java:171-186`：共享分支。
- `zhiyuan-server/src/test/.../PendingPlanningCommandBizServiceTest.java:928-934`：已有 add_units 测试，未覆盖 review。

**要求的修改**
- 给 `PendingPlanningCommandReq` 增加显式 `rerunReview`（或 `reviewAfterApply`）布尔，仅新链路传 true；legacy 默认 false。
- 或者新增 `add_units_with_review` 命令类型；不要静默改变旧命令语义。
- 在测试里钉住“legacy add_units 不跑 review / 版本只推进一次”。

#### M2. prompt/技能更新目标写错文件，且与开关、`developer_instructions.write.md` 不一致

**问题**
设计 3.6 说“运行时 prompt（`app/zhiyuan_agent/prompt.py` 20c 改写）”。但 `prompt.py` 是 **legacy direct agent** 的 prompt（`app/zhiyuan_agent/agent.py:19` 引用），那里 `preview_plan_action` 工具是真实存在的；删改 20c 会削弱 legacy 的点名加入，与“legacy 路径不动”自相矛盾。codex 运行时加载的是 `skills/codex/developer_instructions.md` + `developer_instructions.write.md`（`app/gateway/composition.py:114-147`）。

另外，`developer_instructions.write.md:9` 仍写“写请求出 proposalRequest”，`:115-117` 仍写“proposalRequest/scoreUpdateRequest/careerUpdateRequest 三者互斥”。加入第四种 `planActionRequest` 后，这两处都会与实现冲突；设计只列了 `developer_instructions.md` 和三个 SKILL，没有列 `.write.md`。

**证据**
- `zhiyuan-agent/app/zhiyuan_agent/agent.py:19`：`from app.zhiyuan_agent.prompt import build_zhiyuan_agent_instructions`；`prompt.py:208` 是 20c。
- `zhiyuan-agent/skills/codex/developer_instructions.md:67`：仍要求调用 `preview_plan_action`。
- `zhiyuan-agent/skills/codex/developer_instructions.write.md:9`、`:115-117`：proposalRequest + 三者互斥。
- `zhiyuan-agent/skills/codex-marketplace/plugins/zhiyuan-codex-planner/skills/planner-routing/SKILL.md:56`、`plan-construction/SKILL.md:52`、`candidate-recommendation/SKILL.md:31`：同样引用 `preview_plan_action`。
- `zhiyuan-agent/app/gateway/composition.py:135-147`：写模式会追加 `.write.md`。

**要求的修改**
- **不要改 `app/zhiyuan_agent/prompt.py`**；legacy 的 20c 保留。
- 更新 codex 侧四处：`developer_instructions.md:67`、`.write.md:9` 与 `:115-117`、上述三个 SKILL。
- 开关关闭时，prompt 仍教导 `planActionRequest` 会导致“模型每个点名加入都撞禁用错误”。必须二选一：
  - 开关关闭时注入“本轮不支持点名加入”的运行时指令并让模型走澄清；或
  - 默认开启，回滚时同时回退 prompt/技能版本。
- 设计要明确 `.write.md` 的四方互斥（proposal/score/career/planAction），以及 `responseType=text`、`executionStatus=partial` 的模型指令。
- 在指令/技能里给出 `targets` 的具体对象示例（`{"schoolName":"…","majorName":"…"}`），不要只写 `targets=["学校.专业"]`；新契约是对象数组，旧示例会诱导模型输出字符串数组，直接撞 schema。

#### M4. 幂等 digest 与“网关解析”组合会产生不可重放

**问题**
设计 3.3 要求“requestId + 内容摘要”幂等。如果摘要里包含网关解析出的 `volunteerIds`，而解析基于会变化的 `preview_candidates` 重算池，那么同一 requestId 的重试可能解析出不同 ID/顺序 → digest 不同 → `prepare_request_conflict` 409，用户永远拿不回第一次已生成的 pending。requestId 是按回合派生的（`tenant:session:turn_id`），重试场景真实存在。

**证据**
- `zhiyuan-server/.../ConversationProposalRequestService.java:141-146`：同 requestId 不同 digest → 409。
- `zhiyuan-agent/app/gateway/service.py:1429`、`:2874`：requestId 取 `tenant:session:turn_id`。
- B1 的 `preview_candidates` 重算/分页问题。

**要求的修改**
- digest 只覆盖**模型原始输入**（action、targets 名称/模型给的 ID、raw text、sourceVersionGuard），不覆盖网关解析结果；解析后的 volunteerIds 由 Java prepare 决定并写入 pending。
- 或者把解析放进 Java prepare（B1 推荐），从根上消除“网关重解析”这一层。
- 测试：同 requestId 在候选池变化后重试仍返回同一 pending；不同输入 → 409。

#### M5. 目标语义未定义：已选/部分已选/无方案/禁用/锁定/专业组

**问题**
设计只给了 `ready/blocked(reason)`，没有定义以下真实分支，实施时必然各自发挥：

- **部分 target 已在方案**：六条里两条已在方案，是整体 blocked，还是 ready 只加四条并在卡片说明“2 条已存在”？设计 3.2 把 `already_selected` 写成 info，3.3 又要求 prepare 拒绝 `already_selected`；两处冲突。
- **部分 target 歧义/无匹配**：设计说 blocked 不进 pending；是“全有或全无”，还是“能加的加、不能加的列出”？需明确。
- **当前没有正式方案**：设计目标是“加入现有方案”；没有方案时是澄清“先生成方案”，还是允许 add_units 从零生成？legacy 在无方案时会转成报考要求预览（`tools.py:10395`），新路径没有对应语义。
- **banned/locked**：`addWorkingPlanItemIfAllowed` 对 banned/重复项静默返回 false（`WorkingPlanMutationSupport.java:70-76`）；prepare 不检查就会出“ready 卡点了没变化”。
- **专业组模式**：legacy `_resolve_add_candidate_targets` 在多个匹配共享同一 unitId 时返回 `ok`（`tools.py:6846-6849`），设计却要求“唯一 volunteerId 才算 ok”。同组多专业是否要一次加入？设计风险 4 只把问题留给 Java 测试，没有定语义。
- **unit_id**：`PlanActionTarget.unit_id` 无法用 preview 核验（B1），且 `add_units` 执行只消费 `volunteerIds`（`PendingPlanningCommandReq.java:20-21`；`DraftSelectReq.java:9-12` 只有 volunteerIds），`unitIds` 在 add_units 分支未被使用。第一期应删除该字段，或明确它只用于展示/分组。

**证据**
- `zhiyuan-agent/app/zhiyuan_agent/tools.py:6799-6849`（尤其 `:6843-6849`）。
- `zhiyuan-server/.../WorkingPlanMutationSupport.java:62-83`。
- `zhiyuan-server/.../PendingPlanningCommandBizService.java:171-186`（add 分支只用 volunteerIds）。
- `zhiyuan-server/.../DraftSelectReq.java:9-12`。

**要求的修改**
- 在设计中写一张 target 结果表：`ok / already_selected / ambiguous / no_match / not_in_pool / banned / locked / no_plan`，并规定“部分失败是否整体 blocked”。
- 专业组模式明确沿用 legacy“同一 unit 的多个匹配可一起加入”的口径，卡片按专业逐条展示；或者明确只允许唯一 volunteerId 并说明与 legacy 的差异。
- 第一期从 `PlanActionTarget` 删除 `unit_id`；如果保留，给出权威来源（不能是 preview）和用途。

#### M6. confirm 时不再校验候选有效性，且 actualChanges 无法计算

**问题**
设计 6.3 说“确认时 Java 校验版本 + 候选仍有效；失效 → 409”。实际 add_units：

- 只校验 planning state version（`PendingPlanningCommandBizService.java:80-86`），不校验 volunteerIds 是否仍在候选池；
- `selectWorkingPlanItems` → `applyDraftSelection` 对找不到的 candidate 直接 `continue`（`PlanningStateService.java:2218-2235`；`findCandidate` 返回 null → `addWorkingPlanItemIfAllowed` false），**静默跳过**；
- 然后仍然 `generateOrderedPlan(force=true)` 并返回成功。用户看到的可能是“已生效”，但实际一条都没加/只加了部分；
- `generateOrderedPlan` 还会按已确认硬约束重新 enforcement（`PlanningStateService.java:2391-2398`、`syncWorkingPlanWithEffectiveCandidatesForConfirmedRequirements`）；即使 select 阶段加进去了，若与已确认硬约束冲突，也可能在排序阶段被剔除。设计没有定义“用户点名加入是否优先于已确认硬约束”（例如学费上限）；
- `selectWorkingPlanItems` 丢弃了 `applyDraftSelection` 返回的新增 ID（`:2205-2214`），所以 `actualChanges`/`addedCount` 没有现成来源。

**证据**
- `zhiyuan-server/.../PlanningStateService.java:2194-2215`、`:2218-2235`。
- `zhiyuan-server/.../WorkingPlanMutationSupport.java:36-42`、`:62-83`。
- `zhiyuan-server/.../PendingPlanningCommandBizService.java:171-186`。

**要求的修改**
- 在 add_units 执行前（同一事务、同一 `resolveEffectiveCandidates`）逐个校验 volunteerIds；任一不在池中/不可选 → 409（或明确返回 `target_not_found`），不要静默跳过。
- 明确“点名加入 vs 已确认硬约束”的优先级：若允许点名覆盖，需在 `generateOrderedPlan` 的 enforcement 中为该条开豁免；若不允许，prepare 阶段就用 `RepairCandidateEligibility.isEligibleForConfirmedHardConstraints` 拒绝，不要等到排序阶段被剔除。
- `actualChanges` 用“执行前 working plan volunteerId 集合 − 执行后集合”计算，或在 `selectWorkingPlanItems` 增加返回值；不要依赖 review 后的 ordered plan。
- 测试：候选在 prepare 后被刷掉、banned、locked、部分已选、全部已选、与已确认硬约束冲突。

#### M7. 重复确认的承诺与网关现状不一致

**问题**
设计 3.4 说“同一 operationId 二次 execute 返回同一结果，不双写”。Java 的 replay 确实会返回同一结果，但网关在 pending 变成 `applied` 后，`ConversationSnapshotService.fillActiveProposal` 不再暴露 activeProposal；第二次点同一张卡会在 `execute_conversation_action` 的 `proposal_reference_mismatch` 处直接返回 `stale_state`，**根本到不了 Java execute**。因此用户看到的是“方案已变化”，不是“同一结果”。不双写是满足的，但设计不应承诺“返回同一结果”。

**证据**
- `zhiyuan-server/.../ConversationSnapshotService.java:142-146`：只有 `active` 才填 activeProposal。
- `zhiyuan-agent/app/gateway/conversation_actions.py:145-151`：ref 不匹配 → `stale_state`。
- `zhiyuan-server/.../PendingPlanningCommandBizService.java:260-278`：Java replay 只在 execute 被调用时生效。

**要求的修改**
- 把语义写成“重复确认不会双写；已生效后再次点击返回 `stale_state`/已生效提示”，不要承诺同一结果。
- 如果产品要求“同一结果”，网关需要在 activeProposal 缺失时按 `proposalRef` 查 pending 历史并回放；这是额外设计，不建议第一期做。

#### M8. legacy pending 兼容没有覆盖：`plan_mutation` 没有 operationId

**问题**
legacy `preview_plan_action` 创建的 pending 是 `kind=plan_mutation`、`actionFamily=add_units`，`_create_plan_pending` 不写 `operationId`；legacy 执行时自己用 `uuid5` 派生（`tools.py:7451-7454`）。如果同一会话改由 codex gateway 确认这类旧 pending，`_execute_claimed_command` 会以 `operation_id_missing` 拒绝（`conversation_actions.py:813-817`）。设计只说“legacy 路径不动”“已存在的 plan_action pending 仍可确认”，但没有区分“新 plan_action pending”与“legacy plan_mutation pending”。

**证据**
- `zhiyuan-agent/app/zhiyuan_agent/tools.py:7112-7129`、`:7203-7306`、`:7451-7454`。
- `zhiyuan-agent/app/gateway/conversation_actions.py:813-817`。
- `zhiyuan-server/.../ConversationSnapshotService.java:142-169`：旧 pending 同样会作为 activeProposal 暴露。

**要求的修改**
- 新 pending 使用可区分的 `kind`（如 `plan_action`），并在网关按 kind/commandType 识别；不要和 legacy `plan_mutation` 混用。
- 明确定义旧 `plan_mutation` pending 在 codex 下的处置：过期/清理任务、迁移，或显式“旧预览不支持，请重新生成”。不要让它显示可点但点了必失败。

#### M9. 网关把 `summary/affectedItems` 传给 Java，展示权威倒置

**问题**
设计 3.3 的 prepare 请求里带 `summary` 与 `affectedItems`（学校/专业/档位），由网关生成。Java 只校验 volunteerIds 后把这些展示字段落 pending/返回卡片。这等于让**非权威解析方**决定卡片内容；一旦网关解析与 Java 候选池不一致，卡片会显示 A，执行加的是 B，或者显示的信息与 Java 实际加入项不符。

**证据**
- 设计 3.3 请求体。
- `zhiyuan-server/.../PendingConfirmationBizService.java:36-69`：upsert 对 dataValue 只做 JSON 透传，不校验内容。
- `zhiyuan-server/.../CandidatePreviewRes.java:31-50` 与 `CandidateItemDTO.java:9-64`：Java 有完整的学校/专业/档位/计划数/学费字段，足以自己生成展示项。

**要求的修改**
- Java prepare 用自己解析出的 `CandidateItemDTO` 生成 `affectedItems/summary/addedCount`；网关只传模型输入。
- 如果保留网关展示字段，Java 必须用 volunteerId 重新查候选并覆盖，不能直接采信；设计中写明“展示字段以 Java 为准”。

#### M10. 测试计划未覆盖真实断点，反例不足

**问题**
设计第五节列了方向，但缺少会直接暴露上述问题的测试：

- 模型侧 schema：`planActionRequest` 是否进 `TURN_OUTPUT_SCHEMA`、是否全 required、nullable 归一化是否合法（现有 `test_turn_output_schema.py` 的纪律）。
- 四方互斥：现有测试没有 `conflicting_proposals` 四选一用例（grep 未命中）。
- prepare 状态映射：`prepared/duplicate/superseded/preparing` 各一条；`prepared` 不得透传成卡片状态。
- apply 路由：active_data.commandType=add_units 时**不得**调用 `_canonical_metadata_from_producer`、不得构造 proposalApply、expectedPlanVersion 取 data.sourceVersion。
- 回执：`actualChanges/reviewState` 经 Java → 网关 → v1 事件 → 前端白名单全链；replay 后仍在。
- review 失败语义：add 是否保留、result version 是否等于 DB version。
- 候选分页/截断：>20 条匹配、同校多专业、同名多组、候选来源不可用。
- 部分已选/部分歧义/无方案/banned/locked。
- 开关关闭：模型仍输出 planActionRequest 时的用户可见结果。
- legacy 回归：旧 add_units（不带 review flag）行为不变。
- 安全：模型给别的会话的 volunteerId、跨租户 ID 必须被拒。

**证据**
- `zhiyuan-agent/tests/unit/test_conversation_actions.py:318-357`：现有 apply_plan_change_proposal 映射测试；没有 add_units 映射。
- `zhiyuan-agent/tests/unit/test_turn_output_schema.py:47-64`：proposal schema 测试范式。
- `zhiyuan-server/src/test/.../PendingPlanningCommandBizServiceTest.java:928-934`：add_units 测试只覆盖基本执行。
- `zhiyuan-agent/tests/unit/test_runtime_hard_cut_audit.py:505-510`：禁止重新引入 legacy plan action 执行路径；新网关模块命名要避开这些禁词。

**要求的修改**
- 把上述用例写进 S1–S5 的验收清单；真实栈 e2e 必须用有真实候选文件的会话（`CandidatePreviewService` 对 FINISHED/无文件返回 `candidate_source_unavailable`，合成 900xxx 会话可能没有文件，会得到假阴性）。

### Minor

- **m1. `PlanActionTarget` 字符串未 strip/限长**；`targets` 无上限，模型可输出超长列表。建议 strip + `max_length`（如 20）+ 每字段长度上限。
- **m2. 错误码未成表**：`target_not_found/target_not_in_scope/ambiguous/no_match/already_selected/source_version_mismatch/plan_action_disabled` 分别映射到哪个 `OutputContractError`/用户文案，设计未列。
- **m3. `expiresAt` 无来源**：pending 表没有过期时间字段；要么删，要么用保留任务策略计算。
- **m4. `addedCount` 与 `affectedItems.length`、`changeSummary` 与 `summary` 重复**；选一个权威来源，避免卡片两处不一致。
- **m5. `action: Literal["add"]` 与“其余 action 走 400/blocked”不完全一致**：非 add 会先触发 Pydantic schema 错误/修复回合，不是业务 blocked；设计应写明。
- **m6. `responseType=text` + `executionStatus=partial`** 可行，但要在 `.write.md` 明确写，否则模型可能输出 `recommendation` 并触发 artifactRefs 要求。
- **m7. 观测日志**：设计说不记录用户正文，但 `rawUserText`/targets 会进 pending/日志；明确脱敏边界。
- **m8. 新模块命名**：`app/gateway/plan_actions.py` 可行；不要使用 `app/domain/plan_action_execution.py` 或 `execute_plan_action` 等被 `test_runtime_hard_cut_audit.py` 禁止的 legacy 名称。
- **m9. `requestId` 列长 64**：`tenant:session:turn_id` 与现有 proposal/score 同款，已有先例；但设计应写明沿用，不要新造更长格式。
- **m10. `sourceVersionGuard` 在请求与 pending 各存一份**；明确哪份是执行权威（建议 pending dataValue 的 `sourceVersion`）。
- **m11. 专业组模式卡片粒度**：设计说“逐条专业”，但 `addedCount`/新增单元数/档位分布三个口径要定义清楚（按条目还是按单元）。
- **m12. review 重跑的同步延迟**：`execute_pending_planning_command` 的等待上限是 60s（`internal_client.py:20`、`:1878`）；add_units 现在要多跑一次 `runReview`，可能把原本接近上限的确认推过超时。设计要给出超时/降级策略（超时不等于失败、后续可按 operationId 查询）和真实栈耗时观测。现有 `apply_plan_change_proposal` 也同步跑 review，可参考其超时表现。

## 三、九个审查要点的逐条回答

### 1. 断层分析是否准确？有没有现成但被漏掉的 plan-action prepare / add_units 网关映射 / MCP 写工具？

**准确。**
- codex 工具面确实只有只读 MCP：`zhiyuan-agent/app/mcp_server/server.py:43`（`READONLY_TOOL_NAMES = frozenset(CAPABILITIES)`）；`tests/unit/test_domain_mcp_tools.py:86` 还断言 `plan_apply` 不在工具面。
- `ProposalRequest` 确实只有六个 goalType：`contracts.py:305-312`。
- 网关 prepare 确实只有 user-goal / score / career：`service.py:2871`、`:1426`、`:1546`。
- `_command_for_goal` 确实不认 add_units：`conversation_actions.py:742-775`。
- `must_include_scope` 确实不能替代：`UserGoalProposalBuilder.java:1296-1347`，`:1343` 只取 `candidateMatches.get(0)`。

**没有漏掉的现成入口。** 但设计可以多复用三处既有资产（减少新代码，不改变结论）：
- `internal_client.execute_pending_planning_command` 已支持 `command_type/volunteer_ids`（`internal_client.py:1830-1857`），无需新客户端方法。
- Java `PendingPlanningCommandReq` 已有 `volunteerIds/unitIds`（`PendingPlanningCommandReq.java:10-25`），execute 侧不需要新请求 DTO。
- legacy `_apply_plan_pending` 的 add_units 分支（`tools.py:8146-8182`）与 `proposal_compiler` 的 action family 列表（`proposal_compiler.py:12-24`）可作为 apply 映射与结果形状的参考；它们是 legacy direct agent，不可直接给 codex 用。

**对设计理由的一处修正**：`must_include_scope` 不只是“最多补 1 条”，它的 scope 匹配是 **OR**（`UserGoalProposalBuilder.java:2469-2475` 的 `matchesAny`），所以即使传多个 scope 也无法表达“学校 A + 专业 B”的精确配对。设计应把这条写进断层分析，避免后来者以为“多传几个 scope 就行”。

### 2. 契约设计：planActionRequest 与 TurnOutput/四选一/output schema/修复回合/responseType 是否可行？有没有更小或更正确的接入点？

**可行，但有多个接入点问题（B2/B6/M4/M2）：**
- **schema**：必须把 `planActionRequest` 加入 `TURN_OUTPUT_SCHEMA` 的 `required/properties/$defs`，并在 `_normalize_nullable_for_upstream` 之前；否则模型侧直接拒。`_strict_model_schema` 会把所有可选字段变必填，第一期应收缩字段。
- **四选一**：`_draft_count` 扩为四个是对的，但错误文案、测试和“planActionRequest + conversationAction 同轮”的分支优先级要写清。
- **修复回合**：`source_version_guard` 不符要在 `validate_turn_output`/`_validate_round` 里检查，才能命中 `_REPAIRABLE_CONTRACT_CODES`（`service.py:820-833`）。放在 `service.py:2858` 那种位置是硬失败，设计说的“可走一次修复回合”不成立；且 `stale_state` 的修复提示目前是产物引用提示（`_ARTIFACT_REF_REPAIR_HINT`），对 plan action 不合适，需要专用提示。
- **responseType**：`text` + `partial` 可行，不新增枚举；但要在 `.write.md` 明确，否则模型可能输出 `recommendation` 触发 artifactRefs 要求。

**更小的接入点**：见第五节“扩展 ProposalRequest + 复用 user-goal prepare”。它把 plan action 当作 `proposalRequest` 的一个新 goalType，省掉第四种草稿、新端点、新 PrepareResultDTO、新 pending 格式；`planActionRequest` 可作为后续 remove/replace 的通用动作契约再引入。

### 3. 目标解析与权威：模型信任边界、候选池时效、唯一/歧义/已在方案、批量查询、防 N+1；网关 vs Java 哪种更稳？

**Java 解析更稳。** 详细问题见 B1/M4/M5/M6/M9：
- `preview_candidates` 是 20 条硬上限的只读重算页，不是 apply 使用的持久池；无法保证 prepare 与 execute 同一权威。
- 响应无 unitId/groupCode，`unit_id` 无法核验。
- 过滤器是“维度内 OR、跨维度 AND”的子串匹配，无法逐 target 精确配对；批量查询的“同 school 合并”仍会返回交叉命中，且需分页。
- 网关无法从 snapshot 判断“已在方案”（`ConversationTurnSnapshot` 只有 profile/constraints/activeProposal，没有 working/ordered plan，`contracts.py:534-546`）；要额外调用 `get_working_plan`（`internal_client.py:1318-1330`），设计未提。
- legacy 名称解析依赖 sandbox `plan/candidates.json`（`tools.py:6799-6849`、`:6706-6712`）和 domain resolver（`app/domain/school_major_ref_resolver.py:130` 等），不是可以直接在网关复用的一段函数；设计低估了这层工作量。
- 信任边界：模型给的 ID 必须回池核验；名称/ID 同时给时以核验后的 ID 为准，但展示信息应由 Java 从候选行生成（M9）。

**结论**：prepare 的解析应在 Java 内完成，使用与 execute 相同的 `resolveEffectiveCandidates(state)`；网关只负责把模型输入透传、把 Java 的预览映射成卡片。若坚持网关解析，必须补齐分页、持久池一致性、unitId 来源、确定性 digest 四件事，且仍多一层漂移。

### 4. Java prepare 端点：operationId 权威、幂等、单槽、applying、版本、dataValue、legacy 格式；是否真的需要新端点，能否复用？

- **operationId 权威**：设计正确；Java prepare 产出，网关只复用（`conversation_actions.py:801-817`）。
- **幂等/单槽/applying**：可直接复用 `ConversationProposalRequestService.prepareOnce`（`:79-139`、`:167-181`）与 `PendingConfirmationBizService.upsert`（`:36-69`）；单槽由 DB 唯一键保证（`V7__add_pending_confirmation.sql`），CAS/版本由 upsert 保证。
- **版本**：Java prepare 应以自己的 `state.version` 为准，不要只信网关 snapshot；版本不符应返回明确错误，而不是 blocked 预览。
- **dataValue**：设计列出的键够用，但 `kind/actionFamily` 没写；建议 `kind=plan_action`、`actionFamily=add_units`、`commandType=add_units`，并加 `volunteerIds`（解析后）与 `sourceVersion`。
- **legacy 冲突**：legacy `plan_mutation` pending 没有 operationId，codex 会拒绝（M8）；新 pending 必须用可区分的 kind，并定义旧 pending 的清理/拒绝文案。
- **是否需要新端点**：**第一期不必**。复用 `fix-proposals/user-goal/prepare` + 扩展 `ProposalRequest` 可以完成同一件事（Alternative A）。只有确定要建立“与用户目标并列的通用原子动作契约”（后续 remove/replace/move）时，新端点才有独立价值；即便那时，prepare 的幂等/单槽仍应复用 `prepareOnce`，不要重写。

### 5. apply 路径：`_command_for_goal` 扩展是否够、expectedPlanVersion、claim/重复确认、add_units 幂等、unitIds/volunteerIds、review rerun 放 Java 还是网关、失效/回滚

- **`_command_for_goal` 不够**：见 B3，必须在 `_execute_claimed_command` 前面加显式分支，跳过 proposalApply/canonical 回取。
- **expectedPlanVersion**：取 `active_data.sourceVersion`（prepare 时的 planning version）；不要取 `proposal_apply.sourceVersionGuard`。
- **claim/重复确认**：claim + applying 语义可复用；重复确认不会双写，但已生效后网关会返回 `stale_state`（M7），不要承诺“同一结果”。
- **add_units 幂等**：Java `selectWorkingPlanItems` 对已选项是 no-op（`WorkingPlanMutationSupport.java:73-76`），但会继续 `generateOrderedPlan(force=true)`；如果 prepare 已经拒绝 `already_selected`，正常路径不会走到。若绕过 prepare 直接 execute，重复项会推进版本，需要 before/after diff 报 0 新增。
- **unitIds/volunteerIds**：add_units 只消费 volunteerIds；unitIds 第一期不要放进契约。专业组模式按 volunteerId 选择即可，卡片逐条专业；同组多专业是否一起加见 M5。
- **review rerun**：放 Java 更合理（同一命令返回 state+review），但必须解决 B5 的事务/版本语义；参考 `rerunReviewAfterFixApplyIfRequested`（`PlanningStateService.java:1254-1262`）的 review 后重读。若放网关，apply 成功与 review 之间会有窗口，且 review 失败无法回滚 add；不建议第一期。
- **失效/回滚**：add 本身应整体事务回滚（`generateOrderedPlan` 失败 → 回滚）；review 失败按 B5 的二选一语义。候选失效见 M6，必须显式 409/失败，不能静默跳过。

### 6. 卡片/回执：复用 proposal.preview 白名单是否够、affectedItems/addedCount、冷加载/去重、旧前端兼容

- **预览卡**：`proposal.preview` 顶层白名单只有 `proposalRef/diff/sourceVersion/expiresAt`（`conversationEvents.mjs:39`），但 `diff` 是整对象透传；把 `affectedItems/actionType/addedCount/changeSummary` 加进 `server._proposal_preview_payload` 的 `diff` 字典即可到前端，**这一半够用**。仍需更新 `ProposalCard.tsx:60-91` 的类型和渲染（否则字段到了但没人画）。
- **状态**：卡片 status 必须是 `ready/info/preview_only/blocked` 之一；`prepared` 会显示“处理结果未知”（B2）。
- **回执卡**：`conversationAction.result` 是**另一条白名单**，当前没有 `actualChanges/reviewState`（B4）。设计说“复用 proposal.preview 白名单”不够，必须同时扩 result 事件和前端。
- **冷加载/去重**：`proposalRef` 取 pendingId（`ConversationSnapshotService.java:151-153`）可沿用；应用后 activeProposal 消失，历史卡靠 `actionResult` 转终态，现有 reducer 已按 `proposalRef` 合并（`conversationSession.mjs:96-105`）。新增字段要确保 reducer 原样保留。
- **旧前端兼容**：额外 diff 字段会被忽略，title/summary/status 仍可显示；但 status=`prepared` 不兼容。旧前端也不会显示 actualChanges/reviewState——这是可接受的降级，需在设计中写明。

### 7. 发布/回滚：开关、部署顺序、无 migration、已存在 pending、prompt/技能与 legacy 规则自洽

- **部署顺序**：Java（新能力）→ agent（契约/网关/prompt）→ 前端，合理。
- **无 migration**：pending 与 prepare 幂等表都已存在（`V7__add_pending_confirmation.sql`、`V17__conversation_proposal_request.sql`）；新 DTO 字段是 JSON/响应字段，不需要 migration。设计正确。
- **开关**：`PLAN_ACTION_CONTRACT_ENABLED` 只应在 prepare 处生效；apply 映射要保留，否则回滚后旧 pending 不能确认。设计说“apply 映射保留”，但没写“开关不得拦 execute”。补上。
- **开关与 prompt 不一致（M2）**：默认关 + prompt 仍教 planActionRequest = 点名加入直接失败。必须让 prompt 随开关降级，或默认开启并在回滚时回退技能版本。
- **legacy 规则自洽**：`prompt.py` 20c 是 legacy 的，不要改；codex 侧 `.md`/`.write.md`/三个 SKILL 才是要改的。`.write.md:115-117` 的“三者互斥”必须变四者。
- **已存在 pending**：新 kind 与 legacy `plan_mutation` 区分；旧 pending 在 codex 下没有 operationId，必须清理/拒绝并给明确文案（M8）。
- **共享 add_units 改 review**：必须加 flag（M1），否则 Java 先上线就会改变 legacy 加入语义。

### 8. 测试计划是否覆盖真实断点；缺哪些反例/契约测试

覆盖了主路径方向，但**没有覆盖真正会坏的接缝**。缺的反例/契约测试见 M10，摘要：
- schema 接入与严格 required；
- 四方互斥与 repair turn；
- prepared→ready 状态映射、duplicate/superseded/preparing；
- apply 早分支（不得走 proposalApply/canonical）；
- actualChanges/reviewState 全链与 replay；
- review 失败的事务/版本；
- 候选 >20、同校多专业、同名多组、来源不可用；
- 部分已选/部分歧义/无方案/banned/locked；
- 开关关闭；
- legacy add_units 回归；
- 跨会话/跨租户 ID 安全；
- e2e 用有真实候选文件的会话（避免 `candidate_source_unavailable` 假阴性）。

### 9. 有没有更简单的可行方案？

**有，且推荐作为第一期的首选：扩展 `ProposalRequest` + 复用现有 user-goal prepare。**

思路：
1. 在 `ProposalRequest` 增加 `goal_type` 枚举值 `add_units` 与 `targets`（精确的学校/专业/可选 volunteerId 列表）；模型仍只输出一种草稿，不新增第四种契约。
2. 复用 `POST /session/fix-proposals/user-goal/prepare`：`ConversationProposalRequestService.prepareOnce` 已经提供 requestId+digest 幂等、单槽 supersede、applying 拒绝、operationId 权威；`prepareUserGoalProposal` 已把 `userGoalRequest/sourceVersion/operationId` 落 pending。
3. Java `UserGoalProposalBuilder.buildProposal` 增加 `add_units` 分支：用 `resolveEffectiveCandidates(state)` 解析 targets（与 execute 同池），校验已在方案/歧义/无匹配，构造 `FixProposalDTO`（`status=ready`、`requiresConfirmation=true`、`affectedVolunteerIds`、add action、summary），并让 prepare 把解析后的 `volunteerIds` 写入 dataValue。
4. 网关 `_command_for_goal` 按 `goalType=add_units` 返回 `(ADD_UNITS, {"volunteer_ids": dataValue.volunteerIds})`；`_execute_claimed_command` 早分支跳过 proposalApply。
5. 卡片沿用 `proposal.preview`；Java builder 生成 title/summary；`affectedItems` 可从 `FixProposalActionDTO`/候选行补充。

优点：
- 不新增端点、PrepareResultDTO、pending 格式、幂等/取代代码；
- 请求 digest 是模型输入（确定性），不会因网关重解析漂移（M4）；
- 目标解析与 apply 同池（B1/M6）；
- 复用现有 `proposal.preview` 卡与确认链；旧前端天然兼容；
- 实施面比设计稿小一个数量级。

取舍：
- `ProposalRequest` 的语义从“目标草稿”扩到“目标 + 精确动作”；如果团队坚持“动作契约与目标契约分离”，可以后续再引入 `planActionRequest`，但第一期不必。
- `RepairProposalTaxonomy`/`goalType` 枚举、Java DTO/schema 需要小改；比新端点+新 DTO+新 pending 的全套小。
- `fill_to_count + requirements` **不能替代**：`targetScopes` 是 OR 匹配（`UserGoalProposalBuilder.java:2469-2475`），`requirements` 的 `domain/key/values` 无法表达“学校 AND 专业”的精确配对，`include` 只保证覆盖数量，不保证选到点名条目。不要把它当作 six named add 的捷径。
- **MCP write-preview 工具**不建议：会破坏 `READONLY_TOOL_NAMES` 的只读承诺与 artifact/evidence 信任边界（`mcp_server/server.py:43`、`tests/unit/test_domain_mcp_tools.py:86`），工作量也更大。

## 四、是否可进入实施与建议实施顺序

**结论：不可按现稿直接进入实施。** 方向正确，断层次分析成立；但 B1–B6 必须先修订，major 清单（M1–M2、M4–M10）必须逐条定稿或明确降级，否则会出现“解析不全/卡片空壳/确认走错命令/看不到回执/审查回滚语义不明”的返工。

建议实施顺序（若采纳第五节替代方案，S2 去掉“新端点/新 PrepareResultDTO”部分，只保留 Java resolver/builder 分支）：

1. **S0 决策**：选定目标解析权威（推荐 Java）与 review 失败语义（A 回滚 / B add 保留）；选定“扩展 ProposalRequest 复用 prepare”还是“新 planActionRequest + 新端点”。
2. **S1 契约与 schema**：若走替代方案，只加 `goalType=add_units + targets`；若走新契约，按 B6 收缩字段、加 schema、target validator、四方互斥、repair-turn 位置、测试。
3. **S2 Java prepare/解析**：复用 `prepareOnce`；用 `resolveEffectiveCandidates` 解析与校验；生成 `FixProposalDTO` 或独立 preview DTO；幂等/版本/单槽/applying 测试；legacy pending 兼容。
4. **S3 Java apply**：`add_units` 增加 **gated** review（flag）、actualChanges（before/after diff）、result DTO 字段、replay compact；review 后重读 version；测试 review 失败/重复确认/专业组。
5. **S4 网关 wire**：早分支 `commandType=add_units`；跳过 proposalApply/canonical；expectedPlanVersion 取 data.sourceVersion；status 映射 ready；开关只拦 prepare。
6. **S5 卡片/回执**：`_proposal_preview_payload` 加 affectedItems；`_action_result_payload` + v1 白名单 + 前端类型/渲染加 actualChanges/reviewState；旧前端降级验证。
7. **S6 prompt/技能/发布**：codex 四处（`.md`、`.write.md`、三个 SKILL）改写；不要动 legacy `prompt.py`；plugin cachebuster/重装/重启；开关与 prompt 同步；legacy add_units 回归。
8. **S7 验收**：真实栈六条点名 + 反例（陈旧版本/重复确认/歧义/已选/候选失效/审查失败/开关关闭）；回滚演练（关开关、旧 pending）。

## 五、附：关键证据索引（file:line）

- 契约与 schema：`zhiyuan-agent/app/gateway/contracts.py:301-312`、`:454-485`；`zhiyuan-agent/app/gateway/service.py:57-75`、`:259-295`、`:348`。
- 修复回合：`zhiyuan-agent/app/gateway/service.py:2566-2616`、`:2618-2725`、`:820-833`、`:2857-2862`。
- prepare 现状：`zhiyuan-agent/app/gateway/service.py:1392-1488`（score）、`:1490-1591`（career）、`:2857-2907`（proposal）；`zhiyuan-agent/app/util/internal_client.py:1220-1245`、`:1264-1290`。
- apply 现状：`zhiyuan-agent/app/gateway/conversation_actions.py:742-775`、`:778-937`；`zhiyuan-agent/app/util/internal_client.py:1830-1879`。
- 卡片/回执：`zhiyuan-agent/app/server.py:1015-1065`、`:1083-1105`、`:1192-1197`；`zhiyuan-web/src/utils/conversationEvents.mjs:39`、`:43`；`zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/ProposalCard.tsx:60-101`；`proposalCardText.mjs:92-104`。
- 目标解析：`zhiyuan-server/.../CandidatePreviewService.java:46-47`、`:80-125`、`:127-154`、`:183-206`、`:229-248`；`CandidatePreviewRes.java:31-50`；`zhiyuan-agent/app/zhiyuan_agent/tools.py:6664-6681`、`:6696-6750`、`:6799-6849`；`zhiyuan-server/.../PlanningStateService.java:9426-9434`。
- Java prepare/apply：`zhiyuan-server/.../ConversationProposalRequestService.java:79-181`；`PendingConfirmationBizService.java:36-125`、`:202-216`；`PendingPlanningCommandBizService.java:63-104`、`:171-186`、`:214-237`、`:294-327`；`PendingPlanningCommandRes.java:9-25`；`PlanningStateService.java:2194-2235`、`:2338-2381`、`:2777-2792`、`:2833-2838`、`:1254-1262`；`WorkingPlanMutationSupport.java:62-83`、`:246-289`；`UserGoalProposalBuilder.java:1296-1347`、`:2442-2475`。
- prompt/技能：`zhiyuan-agent/app/zhiyuan_agent/agent.py:19`；`prompt.py:208`；`skills/codex/developer_instructions.md:67`；`skills/codex/developer_instructions.write.md:9`、`:115-117`；三个 marketplace SKILL（见 M2）；`app/gateway/composition.py:114-147`。
- 测试：`zhiyuan-agent/tests/unit/test_conversation_actions.py:318-357`；`test_turn_output_schema.py:47-64`；`test_runtime_hard_cut_audit.py:505-510`；`zhiyuan-server/src/test/.../PendingPlanningCommandBizServiceTest.java:928-934`。
