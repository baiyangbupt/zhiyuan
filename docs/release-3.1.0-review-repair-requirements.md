# Release 3.1.0 Review And Repair Requirements

更新时间：2026-06-17

本文先聚焦 3.1.0 中「方案审查」和「审查后修复」能力的需求调研。目标不是马上改代码，而是把 3.0.3 已有能力、遗留不足、3.1.0 需要补齐的工作流和外部触发协议先定义清楚。

## 1. 背景

3.0.3 已经完成了 Agent 对话质量、确认协议、方案操作预览和 pending confirmation 的主链路收口：

- 高副作用方案动作统一为 `preview -> pendingConfirmation -> confirm -> apply`。
- 方案操作覆盖添加、删除、替换、移动、排序、审查与审查后处理等能力。
- 审查问题已经能够在对话里被解释，并能触发 `FixProposal` 形式的删除、替换、补齐和只读处理预览。
- 前端已有轻量审查入口和审查风险提示。

当前 Agent 方案更新链路的统一口径：

- ChatAgent 主工具链为 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`；历史 `planning_router_tool.handle_planning_request` 已删除，新增能力不再接入旧 `request_type` router。
- `PlanActionPlan` 顶层只作为动作 envelope，承接 `stage`、`action_family`、`atomic_actions`、缺参、确认和刷新标志；复合目标、待写入意向、复合动作、可行性、取舍依据和实体歧义统一放在 `composite_proposal`。
- 新待采纳状态以后端 `pendingConfirmation` 为唯一主状态源，运行时通过 `conversation_phase.pending` 投影到 Agent 上下文。
- 卡片点击是确认主入口；短文本“确认/就按这个来/执行”只作为 active pending 的兜底入口，仍由服务端按 `pendingId / kind / status / version` 校验后执行。
- 历史 `pending_plan_action` payload、history preview 提取和 `planEditCache` 不再作为活动确认状态源。`RequestContext` 已不再携带 `pending_plan_action / pending_intent_change` 字段；`ConversationPhase` 里的旧 pending adapter 也已删除。当前轮工具预览只会被提取为“待生成确认卡片的候选源”，不会从完整历史恢复成可直接消费的 active pending；旧 `interestAnalysisPopup` 点击也只能读取 active `pendingConfirmation`，没有 active pending 时提示上下文已失效。`planEditCache` 只保留为历史脏数据清理 key，不再读取、合并或驱动动作。
- `pin/unpin` 已从用户可触发能力退场；历史 `pinned/pinnedPosition` 只保留 DTO/JSON 兼容，不参与当前移动、排序、修复或 Agent 回复。

但审查与修复还没有成为完整的一等工作流。当前能力能「发现问题」和「局部补偿/局部删除」，但还不能稳定表达：

- 每类审查问题的定义、适用范围、严重等级和证据。
- 哪些问题可以自动修复，哪些只能提示，哪些需要人工决策。
- 修复前如何生成可验证的 proposal。
- 修复后如何自动复审并判断是否真的解决。
- 外部系统如何触发审查、获取修复建议、确认应用、追踪结果。

3.1.0 需要把这部分从「分散工具能力」提升为「审查问题 -> 修复方案 -> 用户/外部确认 -> 应用 -> 复审验证」的统一协议。

## 2. 当前实现梳理

### 2.1 后端审查

当前主要入口在 `PlanningStateController`：

- `GET /session/review`：获取审查结果。
- `POST /session/review/run`：执行方案审查。
- `POST /session/review-workflow/run`：执行审查并生成处理建议。
- `POST /session/fix-proposals/generate`：基于审查结果生成可展示/可确认的处理建议。
- `POST /session/fix-proposals/apply`：唯一正式的审查后高副作用修复入口。
- `POST /session/plan-adjustment/analyze`：分析方案调整建议。
- `POST /session/plan-adjustment/apply`：旧半成品入口已废弃，当前返回 410；真实应用修复应走 `fix-proposals/apply`。

旧 `POST /session/compensation/preview` 和 `POST /session/compensation/apply` 对外入口已删除。Java `CompensationPreviewDTO/buildCompensationPreview()` 只作为 `runReview()` 与 `generateFixProposals()` 内部素材，用于把数量缺口、安全垫、梯度等可补齐方向转换成 `FixProposal`；Agent、Web 和外部系统都不能再直接调用旧 compensation preview/apply，也不能绕过 `RepairProposalApplyPolicy` 直接落盘。

`PlanningStateService.runReview()` 当前会生成 `ReviewStateDTO`，并执行以下审查规则：

- `ratio_distribution`：冲稳保比例。
- `safety_guard`：本省/安全垫。
- `probability_inversion`：录取率倒挂。
- `probability_gap`：录取率梯度断层。
- `count_validation`：数量缺口。
- `high_tuition`：高收费。
- `admission_limit`：限报条件。
- `special_enrollment`：特殊类型招生。
- `edge_score`：边缘分。
- `cooperative_program`：中外合作。
- `major_group_safety_intent_alignment`：专业组安全专业与意向不一致。
- `group_inner_safety_guard`：专业组内安全垫不足。
- `plan_update_notice`：招生计划更新提示。
- `adjustment_notice`：调剂风险提示。

`group_inner_safety_guard` 已在 3.1.0 接入正式 `runReview()`，用于识别专业组内缺少录取率不低于组整体录取率的安全垫专业；修复提案支持在同一专业组内补入安全专业，若组内主选专业已达到 `requiredMajorCount`，则优先用安全专业替换一个非安全专业，避免把组内专业数误当成专业组数。

### 2.2 后端修复能力

当前后端修复能力已收敛为一条主链路和两类内部/兼容素材：

主链路是 `fix-proposals/generate` 和 `fix-proposals/apply`：

- 基于 `ReviewStateDTO`、候选供给、补偿素材和用户目标生成 `FixProposalStateDTO`。
- 每个 proposal 都带 `status/strategy/actions/dryRunResult/candidateShortages/blockingReason`。
- `applyFixProposal()` 是正式高副作用入口，必须经过 `RepairProposalApplyPolicy` 的版本、状态、策略和复验门禁。

兼容素材之一是 `plan-adjustment/analyze`：

- 基于部分审查规则生成 `PlanAdjustmentStateDTO`。
- 规则范围包括数量、比例、概率倒挂、梯度断层、安全垫、专业组安全专业意向对齐。
- 会生成 `AddSuggestionDTO`、`RemoveSuggestionDTO`、`ReplaceSuggestionDTO`、`ReorderSuggestionDTO` 等建议。
- `applyPlanAdjustment()` 不再保留半实现语义，当前直接返回 410，避免外部误以为建议已应用。
- Python Agent 主链路和 internal client wrapper 已删除该入口，不再把它作为对话分析事实来源。

内部素材之二是 compensation preview 构造逻辑：

- 能针对数量缺口、安全垫不足、比例失衡、梯度断层生成补偿动作。
- 专业组模式和专业模式分别处理。
- 不再对外暴露旧 `previewCompensation()/applyCompensation()` 路由；补偿动作只作为 `FixProposal` 生成、dry-run 和 apply 分支的内部输入。
- 这不是通用修复引擎，只覆盖「补入/补稳/补数量」类素材，不负责删除、替换、重排、不能满足解释等完整策略；完整策略必须由 `FixProposal.strategy/actions/dryRunResult` 表达。

### 2.3 审查结果对象

当前 `ReviewCheckDTO` 包含：

- `code`
- `level`
- `passed`
- `summary`
- `detail`
- `suggestedAction`
- `affectedUnitIds`
- `affectedVolunteerIds`
- `suggestedCompensations`

这个结构已经具备「审查问题对象」雏形，但还缺少 3.1.0 需要的一些关键元数据：

- `scopeKind`：条目问题、结构问题、信息提示、政策风险等。
- `fixability`：可自动修复、可预览修复、需人工判断、不可修复。
- `supportedFixStrategies`：删除、替换、补齐、重排、重新生成、只提示等。
- `evidence`：规则命中的核心证据，而不是只靠摘要文本。
- `candidateCapacity`：当前候选池是否有足够替代项。
- `postApplyValidation`：修复后如何验证该问题是否消失或缓解。

### 2.4 Agent 侧审查和修复

Agent 当前通过 `plan_next_action -> execute_plan_action` 串起方案动作。相关 action 包括：

- `review_plan`
- `analyze_adjustment`
- `preview_fix_proposal`
- `remove_units`
- `replace_units`
- `sort_ordered_plan`
- `move_ordered_unit`
- `remove_ordered_unit`

`review_issue_registry.py` 已经把审查问题分为四类：

- `item_replacement`：高收费、中外合作，属于用户权衡类条目风险，默认先走只读审查和后端 `FixProposal`，由 `replace_risk_items` 披露替换预览；用户明确要求删除时才走删除预览。
- `item_removal`：限报条件、特殊类型招生，默认可删除/替换。
- `structural`：概率倒挂、梯度断层、冲稳保配比、安全垫、数量缺口、边缘分、非意向托底、组内安全垫，默认分析或补偿。
- `informational`：招生计划更新、调剂风险，默认只提示。

这说明 Agent 侧已经有「review issue 一等对象」的雏形，但仍不是完整主协议：

- 后端规则目录与 Agent registry 仍各自维护，存在漂移风险；当前已先把高收费/中外合作从“默认删除”纠偏为“审查 + 替换优先”。
- review issue 到 fix proposal 的生成不统一。
- 一部分修复靠 compensation，一部分靠 plan execution 的删除/替换预览，一部分停留在 analyze 建议。
- 结构性问题经常只能分析，不能形成一套可验证的修复 proposal。
- 对「候选不足，不能补」的情况没有统一结果类型，容易变成空泛建议。

### 2.5 前端审查展示

前端工作台当前支持：

- 手动点击「审查」。
- 展示审查通过/风险/提醒数量。
- 在 tooltip 和审查详情弹窗中展示风险检查，并在详情里基于后端 `FixProposal` 展示处理建议。

但目前不是完整的审查修复工作台：

- 用户看不到每个问题的证据、影响范围、修复能力和修复预览。
- 旧 `pendingActions` 已从工作台状态和前端展示退场，不能作为可确认修复任务或其他提醒来源。
- 审查和对话 pending confirmation 没有形成统一的前端交互模型。
- 外部系统触发的审查/修复任务也没有对应状态展示。

## 3. 当前核心问题

### 3.1 审查规则没有中心化目录

当前后端规则实现、Agent `review_issue_registry`、前端展示 label 分散维护。新增规则时，容易出现：

- 后端能审查，但 Agent 不知道怎么解释或修复。
- Agent 有 registry，但后端没有返回足够证据。
- 前端展示不认识新 code。

3.1.0 需要后端提供权威 `ReviewRuleRegistry`，Agent 和前端消费该目录或消费后端扩展后的审查结果。

### 3.2 审查与修复没有统一模型

当前 `ReviewCheckDTO` 能表达问题，`CompensationActionDTO` 能表达补偿动作，`PlanAdjustmentStateDTO` 能表达调整建议，但缺少统一的 `FixProposal`。

导致问题：

- 「这个问题能不能修」没有标准字段。
- 「修复会动哪些志愿」没有标准 proposal。
- 「修复后需要怎么验证」没有标准结果。
- 「不能修」和「没有候选可补」没有统一表达。

### 3.3 `plan-adjustment/apply` 已明确退场

`analyzePlanAdjustment()` 能分析并生成建议，但旧 `applyPlanAdjustment()` 曾经只是标记 `pending_apply`，没有真实执行建议。如果前端或外部系统以为它能执行，会造成预期不一致。

3.1.0 当前处理：

- `plan-adjustment/analyze` 仅作为服务端历史/外部兼容只读入口保留；Python Agent 主链路不再调用。
- `plan-adjustment/apply` 服务端返回 410，不再写状态。
- 后续真实应用统一进入 `review -> fix proposal -> apply -> repair report` 链路。

### 3.4 补偿不是完整修复

旧 compensation 动作只负责提供补齐素材，不负责：

- 删除明显冲突项。
- 替换高收费/中外合作/限报等条目。
- 重新排序修复倒挂。
- 处理结构性风险的多策略权衡。
- 候选不足时给出明确不能满足原因。

因此 3.1.0 不能把 compensation 当作 repair 的全部实现，只能作为 repair strategy 之一。

### 3.5 结构性问题缺少可执行策略

例如：

- 冲稳保比例失衡。
- 概率倒挂。
- 梯度断层。
- 保底不足。
- 专业组内安全垫不足。

这些问题不能简单删除 affected ids。它们需要策略规划：

- 保持总数不变，替换多少冲/稳/保。
- 是否允许降低学校层次换安全性。
- 是否放宽地域/专业/院校标签。
- 候选不够时如何说明「无法补」。
- 应用后是否真的改善比例或梯度。

当前系统对这类问题更多是分析或补偿，不是完整自动修复。

### 3.6 外部触发缺少工作流协议

旧版本里外部可以分别调用审查、补偿预览、补偿应用等低层接口，缺少稳定流程；3.1.0 统一为：

```text
run review -> generate repair proposal -> confirm/apply proposal -> rerun review -> get repair report
```

外部系统无法稳定知道：

- 审查是否基于最新方案版本。
- 哪些问题已经生成修复 proposal。
- proposal 是否过期。
- 是否需要用户确认。
- 应用后是否成功修复。
- 修复失败或候选不足的原因。

### 3.7 前端缺少完整审查修复 UX

当前前端是轻量 tooltip，适合快速提醒，不适合承接 3.1.0 的修复流程。后续需要支持：

- 问题列表。
- 每个问题的证据和影响范围。
- 可修复/不可修复状态。
- 修复 proposal 预览。
- 用户确认/拒绝/重新生成。
- 应用后复审结果。

## 4. 3.1.0 目标状态

3.1.0 的目标链路：

```text
方案状态变更 / 用户发起 / 外部触发
  -> runReview
  -> ReviewResult(问题、证据、作用范围、可修复性)
  -> generateFixProposal
  -> dryRunValidation
  -> pendingConfirmationCard / external confirmation
  -> applyFixProposal
  -> postApplyValidation
  -> rerunReview
  -> repairReport
```

核心原则：

- 审查负责发现问题，不直接改方案。
- 修复 proposal 必须是结构化、可验证、可过期的。
- 高副作用修复必须确认后应用。
- 修复后必须复审或至少执行目标规则验证。
- 候选不足、规则冲突、用户约束冲突要作为一等结果返回。
- 专业模式和专业组模式必须统一支持，不能混淆单条志愿和专业组。
- 老版本和过渡代码只保留明确迁移窗口；统一入口切换完成后，删除旧接口、旧 registry、旧状态字段和旧前端入口，避免长期维护多版本和中间层。

### 4.1 旧链路退场原则

3.1.0 的设计不能在现有 `review/analyze/compensation/agent registry/frontend tooltip` 外再叠一套长期并存的中间层。迁移原则：

- 新协议成为主入口：外部、Agent、前端都应逐步切到 review workflow / fix proposal。
- 旧接口只做短期 adapter：用于兼容未迁移调用方，不新增能力。
- 不在旧链路继续补复杂逻辑：新的修复策略、报告、验证和外部协议只进入新链路。
- 每个旧入口必须有退场条件：调用方清零、测试覆盖迁移、线上观察无依赖。
- 退场后删除代码：包括旧 DTO adapter、Agent 侧重复 registry、前端旧 tooltip 操作分支、`plan-adjustment/apply` 这类半实现入口。
- 文档标记状态：`active`、`adapter`、`deprecated`、`removed`，避免不知道哪套是准的。

建议迁移节奏：

| 阶段 | 目标 | 旧链路处理 |
| --- | --- | --- |
| Phase 1 | 新增 registry/result/proposal/report，但保留旧接口 | 旧接口内部可转调新服务 |
| Phase 2 | Agent 和前端主入口切新 workflow | 旧接口仅兼容外部或历史入口 |
| Phase 3 | 外部接口迁移完成并观察稳定 | 标记旧接口 deprecated |
| Phase 4 | 删除旧 adapter 和无调用代码 | 测试只保留新链路和必要历史数据兼容 |

验收标准：

- 同一个 review code 只有一个权威定义。
- 同一个修复策略只有一个生成入口。
- Agent 不再维护独立审查问题分类表。
- 前端不再从 `pendingActions` 和 review checks 里自行拼修复行为。
- 前端不再消费旧 `pendingActions` 字段；审查详情只以 `ReviewCheck + FixProposal` 为用户可见主线。
- `plan-adjustment/apply` 不再以半实现接口暴露。

### 4.2 当前调用链与落盘边界

当前 3.1.0 的审查修复链路已经拆成「审查」「建议生成」「确认应用」「复审报告」四段。各段职责如下：

| 阶段 | 入口/模块 | 主要做什么 | 是否落盘 | 当前边界 |
| --- | --- | --- | --- | --- |
| 审查 | `POST /session/review/run` -> `PlanningStateService.runReview()` | 基于当前方案生成 `ReviewStateDTO`，补齐 `ReviewRuleRegistry` 元数据，并挂载补偿预览到审查问题上 | 会保存 review state、version 和 stale 状态 | 只发现问题，不直接修复方案 |
| 聚合审查 | `POST /session/review-workflow/run` -> `runReviewWorkflow()` | 顺序执行 `runReview()`、`generateFixProposals()`，并返回工作台状态 | 只保存审查结果，不应用 proposal | 给外部和后续前端完整工作流入口；不绕过 apply 白名单 |
| 修复建议生成 | `POST /session/fix-proposals/generate` -> `generateFixProposals()` | 基于 review checks 和 compensation preview 生成 `FixProposalStateDTO`，执行 dry-run，给出 `ready/preview_only/blocked/info` | 不落盘方案内容 | `rebalance_tier_ratio`、`fill_probability_gap` 当前只生成结构替换预览，仍是 `preview_only` |
| 修复确认应用 | `POST /session/fix-proposals/apply` -> `applyFixProposal()` | 校验 `proposalId/sourceVersionGuard/review stale/status/strategy`，通过后执行 mutation、保存、可选重排、可选复审、返回 `RepairReportDTO` | 会改工作台方案，可能重建 ordered plan | 唯一正式高副作用修复入口；必须通过 `RepairProposalApplyPolicy` |
| 内部补齐素材 | `buildCompensationPreview()` | 生成 `CompensationPreviewDTO`，用于补数量、补保底、补梯度等方向，并转换为 `FixProposal` 动作素材 | 不单独落盘 | 不是对外 API；不能生成独立 pending，也不能绕过 `fix-proposals/apply` |
| 旧调整分析 | 服务端兼容 `POST /session/plan-adjustment/analyze` | 只读分析旧结构建议；Python Agent 已不再封装或调用 | 不落盘 | 保留历史/外部兼容；用户侧和 Agent 展示统一消费 `reviewState + fixProposals` |
| 旧调整应用 | `POST /session/plan-adjustment/apply` | 已废弃 | 不落盘 | 返回 410，避免半实现入口继续被误用 |

这里需要严格区分三类名字：

- `strategy`：规则层或 proposal 层的修复策略，例如 `rebalance_tier_ratio`、`fill_probability_gap`、`remove_risk_items`。
- `action`：本次 proposal 中具体要怎么改，例如 `replace_volunteers`、`remove_volunteers`、`fill_total_count`。
- `apply policy`：是否允许进入真实落盘。当前只有 `fill_missing_count`、`sort_by_probability`、`remove_risk_items`、`replace_risk_items`、`adjust_major_group_inner_safety` 在白名单中。

因此 `rebalance_tier_ratio` / `fill_probability_gap` 不是“自动 apply 的 action”。它们当前是结构性修复策略：可以生成 `replace_volunteers` 预览、dry-run 和影响说明，但不会通过 `fix-proposals/apply` 自动落盘，也不能通过旧 compensation 对外入口以追加候选的方式绕过容量保护。

#### 跨 Java / Python / Web 的统一协议

3.1.0 的审查修复和复合方案调整不能在 Java Server、Python Agent、Web 前端各维护一套原子动作语义。统一边界如下：

- Java Server 是 `ReviewCheck -> FixProposal -> AtomicAction -> DryRun -> ApplyPolicy -> Mutation -> RepairReport` 的权威实现。审查规则、修复策略、候选选择、替换配对、候选不足归因、dry-run、apply 白名单、真实落盘和复审报告都以 Java 返回为准。
- Python Agent 负责用户自然语言理解、场景归类、`PlanGoal` 提取、实体歧义提示、只读解释和确认引导。Python 可以把用户目标、范围、取舍边界和来源审查问题传给 Java，但不能自己生成最终可执行的 `removeVolunteerIds`、`candidateVolunteerIds`、`replacementPairs`、`dryRunResult` 或 `applyable` 结论。
- Web 前端负责展示、用户确认和状态刷新。Web 不根据中文摘要自行拼修复动作，不从 review 文案反推出可执行按钮；所有可执行修复入口必须来自 Java 返回的 `FixProposal.status/strategy/actions/sourceVersionGuard`。
- Agent 和 Web 消费同一套 `fix-proposals/generate` 与 `fix-proposals/apply` 协议。当前 `FixProposal` 可视为第一阶段的 `PlanChangeProposal`：`source=review_check` 时由审查问题触发；`source=user_goal` 时由用户复合目标触发。两类来源都由 Java proposal engine 生成候选选择、替换配对、dry-run 和 apply 门禁，Python 不再维护一套只读 proposal 镜像或候选选择实现。
- Python 侧不再保留 `LinkedRepairProposal / LinkedRepairAction / CompositePlanProposal.linked_fix_proposals` 中间层。`CompositePlanProposal` 只承载 Agent 对用户目标的理解、待写入意向、保守原子动作草案、实体歧义、取舍依据和用户可见影响；可执行 proposal 始终是 Java `FixProposalDTO`，通过 pending `executionPayload` 保存 `proposalId/sourceVersionGuard/proposalSource/userGoalRequest` 后受控 apply。
- ChatAgent 当前只开放 `generate_planning_fix_proposals` 作为只读解释入口，不开放 `apply_planning_fix_proposal` 给模型自由调用。对话侧正式应用已经改为 service active pending 桥：`ready` proposal 保存 `proposalId/sourceVersionGuard` 到 `pendingConfirmation(kind=plan_mutation, actionFamily=apply_fix_proposal)`，用户点击卡片或短文本确认后由 `ChatService` 内部调用 Java apply，并把 `RepairReport` 转成用户回复和工作台刷新事件。
- 简单直接编辑仍可由 Agent 生成 action envelope，例如移动第 N 个、删除用户明确点名的志愿、按录取率排序；但最终执行仍走受控 Java 接口和版本/确认门禁。涉及候选选择、替换权衡、风险修复、结构调稳、只保留/必须有等复杂目标时，Agent 只能生成 `PlanGoal` 或进入 service pending 桥请求 Java proposal，不能自行拼可落盘动作。

这条边界的目的不是把 Agent 弱化成转发器，而是避免同一个业务策略在 Python 和 Java 两边各自实现：Agent 做理解和沟通，Java 做可验证的方案变更，Web 做用户确认和结果展示。

#### 对话路由优先级与恢复边界

3.1.0 后续不再通过叠加多个兼容路径来兜底用户表达。对话侧只有一条主链路：模型/语义层理解用户输入，产出结构化的 Intent、PlanGoal、ReviewCheck 或只读查询意图；执行层只消费结构化结果，并进入对应的确认、预览或只读回复协议。

当前需要明确的优先级如下：

1. active pending 优先：如果已有待采纳/待确认内容，用户短文本确认、取消或追问影响，只能围绕这个 active pending 处理，不能从历史 preview 或自然语言重新猜动作。
2. 只读查询优先保持只读：候选查询、当前方案查询、专业/职业比较这类请求不能被语义 plan action 抢成方案调整；即使用户加了筛选条件，也应进入 `query_volunteer_plan` 或 Explore 工具，由主模型整合回复。
3. 普通意向更新优先进入 Intent：例如“倾向 A/B，但 C 不要”默认是报考参考的偏好/要求确认，不应直接升级为 `only_keep_scope` 或方案批量调整。只有结构化结果明确是“只保留/必须有/排除并调整当前方案”时，才进入 user-goal proposal。
4. 复合方案目标再进入 PlanGoal：用户明确要调整当前方案、修复风险、只保留某范围、必须包含某范围、排除并处理当前命中项时，才进入 `Scenario -> PlanGoal -> Strategy -> Proposal -> Action`。
5. 审查修复只走 FixProposal：审查发现的问题和修复建议不能降级成旧 compensation、旧 adjustment apply 或 Python 自己拼的可执行 action；只能通过 Java `FixProposal` 预览、pending、apply 和 RepairReport。
6. recovery 是协议保护，不是第二套业务流程：模型没有调用工具、只读工具吞掉明确意向、或模型口头承诺了确认但没有真实 pending 时，Service 可以把本轮重新送回 Intent preview 或 user-goal proposal 主入口；一旦某个更高优先级主入口已经恢复成功，后续 recovery 必须停止，不能继续触发另一类卡片。

这意味着“补丁逻辑”只能存在于边界保护层，且必须满足两个条件：触发依据来自结构化运行状态或工具协议，而不是用户话术字符串；输出必须回到现有主入口，而不是新增兼容 action、兼容 pending 或兼容 apply。若某个问题需要靠多处字符串补丁才能兜住，应视为框架层路由/状态协议缺口，而不是继续补 case。

Repair 与复合方案调整框架的关系：

- Repair 不是 Plan 之外的另一套系统，而是“审查问题触发的复合计划”已经落地的一条链路。
- `ReviewCheck` 在这条链路里相当于系统发现的目标来源：例如高收费、数量缺口、比例失衡、梯度断层。
- `FixProposal.strategy` 相当于策略层：描述本次要按什么方法修，例如替换风险项、补齐数量、重排、补断层、调冲稳保。
- `FixProposal.actions` 相当于动作计划层：把策略落成具体可预览动作，例如 `replace_volunteers`、`remove_volunteers`、`fill_total_count`。
- `RepairDryRunSimulator` 相当于预执行验证层：判断数量、冲稳保、风险、硬要求、软偏好、推荐系数、院校层次等是否改善或恶化。
- `RepairProposalApplyPolicy` 相当于执行门禁层：判断这个策略和状态是否允许真实落盘。
- `RepairReport` 相当于执行闭环：说明改了什么、复审后结果如何、还有什么没解决。

但需要分清层级：用户自然语言触发的是更上层的「情景/目标」，不是直接触发 repair strategy。Repair 提供的是已落地的底层策略实践和执行保护，而不是高层场景分类本身。

统一分层应是：

```text
Scenario（用户/系统情景）
  -> PlanGoal / ReviewCheck（目标或问题）
  -> Strategy（处理方法）
  -> Proposal（可解释预览）
  -> Action（原子动作）
  -> DryRun / ApplyPolicy / Report（验证、门禁、闭环）
```

因此后续用户自然语言触发的 `Scenario -> PlanGoal -> CompositePlanProposal` 不应重新发明一套底层策略和动作模型。合理方向是：

1. 用户表达本身不要求分层。用户可能说“整体更偏体制内”这种宽泛情景，也可能说“把第 8 个志愿移到第 12 位”这种接近原子动作的具体诉求；系统不能要求用户按内部枚举表达。
2. 分层发生在系统理解和路由之后：宽泛表达先落到 `Scenario -> PlanGoal`，再选择 strategy；具体表达可以直接靠近 `PlanAtomicAction`，但仍要经过同一套预览、确认、版本和 dry-run 门禁。
3. 用户触发的复合调整和系统审查触发的 repair 都进入同一套 `Goal/Check -> Strategy -> Proposal -> Action -> DryRun -> ApplyPolicy -> Report` 抽象。
4. 高层情景先拆成一个或多个 `PlanGoal`，再选择可用底层 strategy。例如“整体更偏体制内”先拆成发展导向、院校层次、专业方向、地域/稳定性和风险边界，再决定是否链接候选查询、排序、替换、补稳或只读分析。
5. 已实现的 Repair 策略优先复用为复合计划的底层子策略，例如 `reduce_risk` 可链接 `replace_risk_items/remove_risk_items`，`rebalance_structure` 可链接 `rebalance_tier_ratio/fill_probability_gap/add_safety_items/fill_missing_count`。
6. 复合目标需要真实变更方案时，必须通过 service pending 桥串联 Java `FixProposal`，不要把 repair 结果重新翻译成一套新的临时 action。
7. 当前不开放自动 apply 的 repair 策略，在用户复合计划里也不能绕过白名单；只能作为预览和取舍说明。
8. 随着框架收口，旧 compensation、旧 adjustment suggestion、Agent 临时 action scope 都应逐步退到 adapter 或删除，避免同一策略多处实现。

高层情景与底层能力复用关系：

| 高层情景 | 目标拆解 | 可复用的底层能力 | 边界 |
| --- | --- | --- | --- |
| 整体更偏体制内/考公考编 | 发展导向偏体制内；院校层次、专业公共属性、地域稳定性、读研/资格路径、风险控制 | `analyze_current_career_direction`、候选/当前方案承接分析、必要时 `sort_by_probability`、`replace_risk_items`、结构调稳类 preview | 本期不动态改 rank 权重；不能把“体制内”直接翻译成删除所有非体制专业；应先给分析和可确认预览 |
| 更稳一点/保底多一点 | `rebalance_structure`、安全垫、本省/保区、数量缺口 | `add_safety_items`、`fill_missing_count`、`rebalance_tier_ratio`、`fill_probability_gap`、dry-run | 结构替换当前只预览；候选不足要说明范围，不空泛承诺补齐 |
| 处理高收费/中外合作/限报 | `reduce_risk` | `replace_risk_items`、`remove_risk_items`、dry-run、apply policy | 高收费/中外合作默认替换优先；用户明确删除时才生成删除预览；完整替换配对才可受控 apply |
| 只保留某方向 | `only_keep_scope` | 目标/非目标识别、候选补位、风险处理、dry-run、必要时 linked fix proposal | 不能直接展开成所有其他专业负向项；需要当前方案反向校验后才可能形成复合 proposal |
| 至少要有某方向 | `must_include_scope` | 候选补入、满容量 replacement planner、dry-run | 不删除其他方向；如果当前方案已有目标范围，不应重复调整 |
| 避开某专业/院校/地域 | `exclude_scope` | 当前方案命中项预览、`remove_units`、删除后补数量策略 | 同步写入后续报考参考；无命中项时不应伪造删除动作 |
| 多目标组合调整 | `mixed_adjustment` | 多个 goal + 多个 proposal 的组合 | 必须披露部分可处理和不可处理项，不能承诺一次性全部修好 |

2026-06-12 第一阶段落地状态：

- `UserGoalFixProposalReq` 已作为 Java 侧复合目标输入协议，消费 `goalType`、`targetScopes/negativeScopes`、`sourceVersionGuard`、`qualityGuards/tradeoffGuards` 等结构化字段。Java 不从用户整句自然语言里猜专业、院校或地域。
- `UserGoalProposalBuilder` 已能为 `only_keep_scope`、`must_include_scope`、`exclude_scope` 生成 `proposalSource=user_goal` 的 ready proposal：识别当前方案命中项、可移出项、候选池中可承接项，并输出 `FixProposalActionDTO(remove_volunteers/add_volunteers/replace_volunteers)` 作为可确认调整依据。
- `only_keep_scope` 如果当前方案已经全部落在目标范围内，会返回 `info`；`must_include_scope` 如果当前方案已经有目标范围，会返回 `info`；`exclude_scope` 如果当前方案没有命中避开范围，也返回 `info`。这类结果只表示“当前不用动方案”，不代表后续推荐权重或报考参考已经写入。
- 如果 `targetScopes/negativeScopes` 缺少明确 `entityType/scopeType`，或携带 `resolutionStatus=unknown/multiple_match/needs_clarification/ambiguous`，Java 只返回 `blocked` 澄清，不生成移出或补入动作。实体消歧仍由 Agent/语义层完成，Java 只消费明确结构化范围。
- `user_goal` proposal 的策略名统一进入 `RepairProposalTaxonomy`：`only_keep_scope`、`must_include_scope`、`exclude_scope` 进入受控 apply 白名单，但必须通过 service pending 桥携带 `userGoalRequest`、`proposalSource=user_goal` 和最新 `sourceVersionGuard`；不能由模型直接调用 apply。
- `PlanningStateService.generateUserGoalFixProposals()` 已作为内部生成入口读取当前 planning state 并调用 Java proposal engine，并通过内部 controller `POST /session/fix-proposals/user-goal/generate` 暴露给 Agent/内部调用。该接口本身不运行审查、不保存 pending、不修改方案；对话侧由 service 选取 ready proposal 后生成 active pending，用户确认时先写入偏好/要求，再读取最新 planning version 重建 user-goal proposal，最后调用 Java apply。

回归验证也要按层级覆盖，而不是只测底层 action：同一批用例需要同时包含“整体更偏体制内/考公考编”这类高层情景、“只保留/必须有/避开”这类复合 goal，以及“移动第 N 个、删除某个志愿”这类原子动作。预期不是让用户话术固定，而是确认系统能把不同粒度的输入路由到正确承接链路，并且不暴露 `stage/action_family/payload` 等内部协议。

#### 当前未安全落地项与推进节奏

截至 2026-06-12，框架层已经完成了“统一分层”和“安全边界”的主要收口，但仍有几处不能算完整落地：

| 范围 | 当前状态 | 未安全落地部分 | 下一步 |
| --- | --- | --- | --- |
| 对话触发审查 | `review_plan` 已能触发后端审查并读取 `fix-proposals/generate`，回复里可解释处理方向；`preview_fix_proposal` 的 `ready` proposal 已能生成 active pending 确认卡，确认后由 service 内部调用 Java apply 并返回 `RepairReport` | ChatAgent 仍不能直接调用 apply；`blocked/preview_only` 只读；live WebSocket 和前端卡片状态仍需继续走查 | 继续验证 `preview -> pending card -> confirm -> RepairReport -> workspace refresh`，并扩大 user-goal proposal 的前端/对话回归 |
| 工作台审查修复 | 前端轻量弹窗已消费 Java `FixProposal`，`ready` proposal 可确认应用 | 仍不是完整审查工作台；历史报告、规则证据、多方案比较和 blocked/preview-only 的用户解释还需完善 | 保持 Web 使用 Java proposal 协议；继续优化问题详情、处理建议和执行后报告 |
| 复合用户目标 | `PlanGoal`、实体消歧、`CompositePlanProposal` 模型、`decisionReferences` 已落地；`UserGoalFixProposalReq` 已作为 Java 输入协议；`UserGoalProposalBuilder` 已能为 `only_keep_scope/must_include_scope/exclude_scope` 生成 `proposalSource=user_goal` 的 ready proposal；service 可生成 `apply_fix_proposal` pending，确认时先写入意向，再按最新 planning version 重建 proposal 并 apply | 更高层、多目标的 `Scenario -> PlanGoal -> 多 proposal` 规划仍需继续完善；only_keep 的复杂补足、招生计划展示名歧义和用户可见 RepairReport 还需更多回归 | 继续扩展复合 goal 的策略组合和用户侧报告，但不再恢复 Python 只读 proposal 镜像或本地候选选择逻辑 |
| `only_keep / must_have / exclude` 方案联动 | 已能基于当前方案生成安全的待确认 `plan_mutation`，避免“只保留 X 却误删 X” | `only_keep` 还缺完整候选补足、dry-run、结构复验和统一 RepairReport；大区范围只记录目标，不自动反向删除 | 先补专业/院校/省份级闭环，再开放大区/复合范围；所有动作必须有命中披露和不可满足说明 |
| Repair 与复合计划统一 | Repair 已作为 `ReviewCheck -> FixProposal -> Action -> DryRun -> ApplyPolicy -> Report` 的落地实践 | 高层用户情景还不能直接复用同一 proposal engine；Agent 不能自己拼 `replacementPairs` 或 applyable | 以 Java strategy/action taxonomy 为底层唯一来源；Agent 只传 `Scenario/PlanGoal/targetScopes/tradeoffGuards` |
| 旧链路退场 | 旧 router 已删除，`plan-adjustment/apply` 已废弃，前端旧 compensation API wrapper 已清理，Agent action family 已移除 `preview_compensation/apply_compensation`，Python Agent 已删除旧 `plan-adjustment/analyze` wrapper | `review_issue_registry.py` 仍作为后端元数据缺失的兜底；Java reviewState 仍保留 `compensationPreview` 作为 FixProposal 内部候选素材和旧状态字段；服务端 `plan-adjustment/analyze` 仅兼容保留 | 后续继续用后端 metadata 替代本地 registry，并评估服务端旧 analyze 入口是否还有外部调用 |

对话侧开放修复 apply 的必要门禁：

1. 对话生成的修复建议必须保存为 active `pendingConfirmation`，并包含 `proposalId`、`sourceVersionGuard`、`proposalSource`、用户可读摘要和 `RepairReport` 展示目标。
2. 用户点击卡片或短文本确认时，只能消费当前 active pending；不能让模型根据自然语言重新猜 proposal 或修复范围。
3. apply 前必须重新校验当前 planning version、review stale、proposal status、strategy 白名单和 dry-run 目标复验。
4. apply 后必须刷新工作台方案、审查状态、proposal 列表，并把 `RepairReport` 回传给对话和前端。
5. 如果 proposal 已过期、只可预览、阻塞或部分不可处理，只能给出解释和重新审查/重新生成建议入口，不能降级成普通 `remove_units` 或 `replace_units` 绕过 apply policy。

补充确认语义：

- `review_plan` 或 `analyze_adjustment` 只给出处理方向、并询问用户是否继续看调整预览时，系统还没有 active pending，也没有可执行 apply payload。用户回复“可以/确认/要看”只能被理解为“继续生成预览”，应回到 Agent 结合上一轮结构化审查结果继续规划 `preview_fix_proposal` 或澄清范围；不能返回“没有上一轮待确认动作”，也不能直接应用方案。
- 只有已经生成 active `pendingConfirmation` 的场景，短文本“确认/执行/就按这个来”才可以作为按钮点击之外的兜底确认入口，并且必须经过 `pendingId/kind/status/version` 校验。
- 没有 active pending、上一轮也不是结构化审查/调整建议的裸“确认/执行”，不能执行任何更新；本轮继续进入语义路由或 full Agent，执行层仍必须依赖 `confirmed_via_pending=true` 防止历史文本或模型自然语言被误当成可执行动作。

推进节奏按风险从低到高：

1. **先固化只读审查**：补测试确认“帮我审查/看看怎么修”只触发 review + proposal facts，不修改方案；`blocked/preview_only` 不生成执行卡。
2. **定义 Java `source=user_goal` proposal 协议**：已完成主链路，包括 `proposalSource`、`UserGoalFixProposalReq`、`only_keep_scope/must_include_scope/exclude_scope` proposal 生成、service pending 桥、确认时先写意向再按最新 version 重建 proposal 并 apply。下一步继续完善候选补足、replacement pair、专业/专业组粒度复验和不可满足原因。
3. **扩展复合目标编排**：`only_keep / must_have / exclude` 当前方案联动已经进入 Java `user_goal` proposal/apply 主链路；下一步补齐更高层、多目标的 `Scenario -> PlanGoal -> 多 proposal` 编排，完善候选补足解释、专业/专业组粒度、招生计划展示名歧义和 apply 后报告。
4. **补对话 pending 桥**：review_check 来源的 `ready` 修复建议已落成 active pending；卡片点击和短文本确认共用 `handle_pending_confirmation`，不会让模型重新猜 proposal 参数。
5. **对话修复 apply 只在 service 内部开放**：不把 `apply_planning_fix_proposal` 暴露给 ChatAgent 主路径；后续扩大修复范围时只扩 Java apply policy 和 service pending bridge。
6. **最后清理兼容层**：移除旧 compensation 主路径、旧本地 review registry fallback 和旧分析入口中不再需要的部分，避免长期双轨维护。

2026-06-12 本地 focused live 验证补充：

- 问题复现：会话 130 输入“我想让这版方案整体更偏体制内和考公考编，先看看应该怎么调整，不要直接改”时，旧回复曾优先走普通方案审查，最终内容被风险/提醒报告主导，没有真正回答“发展方向导向下怎么调整”。
- 修复边界：这类请求按高层发展导向情景处理，不新增固定话术匹配。调度规则明确先走 `analyze_current_career_direction`，必要时补 `query_state`；只有用户明确要审查风险时才走 `review_plan`，且最终回复必须围绕当前承接、短板、取舍和是否生成调整预览组织。
- 方向事实口径：`analyze_current_career_direction` 中的方案匹配数量是基于院校性质、专业名称和标签的宽口径承接线索，不是精确适配或互斥统计；回复不能把它写成“几乎全部严格合适”，也不能和风险/冲突项做简单加减。
- 验证结果：`/private/tmp/dialog_regression_310_public_service_existing_plan_cases.json` 复跑通过。第一轮工具链为 `analyze_current_career_direction`，未调用 `review_plan`，回复给出体制内/考公方向的当前承接、专业结构、院校性质、地域取舍和后续预览入口；第二轮“把第8个志愿移到第12位”仍生成 `move_ordered_unit` 确认预览，未直接修改方案。
- 性能记录：早期复跑输出 `/private/tmp/zhiyuan_310_public_service_existing_plan_live_after_wording_fix.json`，两轮耗时约 15.9s / 8.7s。后续在清理历史后复跑暴露出两个边界：一是模型可能在只读 Explore 后写出无依据的“确认后调整”话术，服务层安全兜底会把它剥离；二是如果剥离后正文为空，必须回退展示只读 Explore 工具返回的分析正文，而不是只剩“本轮不改方案”的边界句。已补服务层兜底和回归测试，focused live `/private/tmp/zhiyuan_310_public_service_existing_plan_live_after_explore_fallback_fix.json` 确认第一轮保留完整分析，第二轮仍生成 `move_ordered_unit` 确认预览。

2026-06-12 生产抽象对话集回归补充：

- 首轮用固定 session 复跑时出现 2 个失败：`5901` 的“临床医学”已存在于本地旧报考参考，导致后续“确认”无 pending；`5905` 的“不要医学类的”没有调用专业意向预览工具。
- 处理结果：
  - `5901` 用 `--session-offset 200000` 的干净 session 复跑后正常生成待采纳内容，后续“确认”正常采纳，确认该失败是本地状态污染，不是协议回退。
  - `5905` 已修复为“明确排除专业/专业类/门类的短口语表达必须进入专业意向预览”。focused live `/private/tmp/zhiyuan_310_negative_major_short_live_after_fix.json` 通过，工具链为 `preview_current_major_intent_confirmation`，返回“排除专业门类：医学”的待采纳内容。
- offset 全量回归通过：`/private/tmp/zhiyuan_310_production_abstracted_live_after_negative_major_fix_offset.json` 覆盖 17 个 case / 22 步，内容断言失败 0，耗时 median 约 10.6s，p95 约 30.3s，max 约 33.5s。
- 补充优化：新增只读综合画像工具 `analyze_current_interest_profile`，用于一次性承接“多个兴趣方向 + 排斥方向 + 薪资/稳定/沟通强度”等复杂画像问题，避免模型在 `analyze_current_career_direction` 与 `analyze_current_major_interest` 之间来回试探。focused live `/private/tmp/zhiyuan_310_interest_profile_live_after_generic_profile_tool.json` 确认该工具被命中，复杂画像回复覆盖航天、能源、心理学、薪资、人际沟通、读研必要性和下一步。
- 遗留优化：`310-prod-open-career-long-input` 已从重复同名 Explore 下降为综合画像 + 额外一次职业方向工具，耗时约 25s，质量可接受但仍偏慢；`310-prod-scenario-public-service-existing-plan` 在模型选择补 `analyze_adjustment` 时仍可能到 30s 级。后续方向应是同轮只读事实复用/去重与模型综合链路收敛，而不是用用户话术关键词做快路由。
- 协议边界：本轮新增的少量文本标记只用于模型输出安全检查，例如识别“模型声称已经列出待采纳内容/点击采纳”但本轮没有真实 pending/card 的情况；它不用于解释用户自然语言，也不决定 `Intent` 或 `Plan` 路由。真正的业务动作仍以工具返回的结构化 pending、`PlanActionPlan` 和服务端确认状态为准。

### 4.2.1 候选不足的产品判定协议

当前系统里的“候选不足”不是单一含义，必须先标记不足发生在哪一层，再决定是否能修、能说什么、是否需要用户确认。默认定义如下：

1. 外部候选池边界：`volunteerBizService.recommendVolunteerList()` 从高途返回的候选，本身已经按用户分数、批次、位次、选科和上下浮动范围取过一段可选空间。这是“当前可规划候选范围”，不是全国全量，也不是所有可能院校专业。
2. 基础硬条件过滤：高途接口和服务端候选构建过程中会受到批次、分数线、选科、身体限报、专项资格、政策风险等硬条件影响。当前 `CandidatePoolQualityStatusBuilder.riskHints` 已能提示身体条件、专项资格、接近批次线、冲稳保分布不足等风险，但还不能给出每个候选被过滤的明细计数。
3. 规划候选池：`candidatePoolState.items/summary/requiredTierCounts` 是初始推荐、补偿预览和审查修复的主要数据源。这里不足时，只能表述为“当前系统可用于规划的候选池不足”。
4. 面板/上下文筛选：`candidateViewState.filters` 是候选面板展示筛选和用户当前查看条件。它影响用户看到的候选列表，但默认不改变完整规划候选池，也不直接影响审查修复 selector；只有 proposal 明确 `selectionScope=current_view` 时，才能说“当前筛选视图下不足”。
5. 已确认硬要求：`constraintState.hardConstraints` 才可能收窄候选或阻止某个补位/替换。未确认的自然语言表达不能直接作为硬过滤依据。
6. 软偏好：`constraintState.softPreferences` 只影响推荐系数、优先级和专家优选排序。软偏好不能被解释为候选被筛掉，也不能作为 `cannot_satisfy` 的主因。

不足归因需要按以下口径落地：

| scope | 含义 | 可面向用户说明 | 不允许说明 |
| --- | --- | --- | --- |
| `candidate_pool` | 当前规划候选池内目标候选不足 | 当前可用于规划的候选池里，目标层级/区间候选不足 | 高途全量没有、全国没有、这个方向不存在 |
| `policy_or_profile_constraints` | 选科、身体、专项、批次线等硬条件可能限制候选 | 可能和选科、身体条件、专项资格或分数段边界有关，需要核验或放宽条件 | 在没有过滤明细时断言就是某一项导致 |
| `current_view` | 当前面板筛选或用户明确要求的筛选范围下不足 | 当前筛选视图下不足，取消筛选后结果可能不同 | 把当前视图不足说成完整候选池不足 |
| `hard_constraints` | 已确认硬要求收窄了候选 | 已确认要求收窄了范围，如需补齐需要调整要求并重新确认 | 把未确认对话或软偏好当作硬过滤 |
| `soft_preference` | 只是偏好导致优先级变化，不是候选不足 | 这会影响推荐系数和优先级，不会直接筛掉候选 | 说候选被偏好过滤掉 |
| `capacity_or_replacement` | 方案已满或找不到完整一进一出 pair | 当前不是没有候选，而是缺少可安全替换的配对 | 承诺可以直接补入或自动替换 |
| `objective_validation` | 有候选但 dry-run 后目标没有改善 | 预览后没有让目标指标变好，所以不能作为修复 | 把无改善说成已修复 |

默认产品边界：

- 初始生成、审查修复、结构补偿默认使用完整规划候选池和已确认硬要求，不使用当前候选面板筛选条件。
- 用户说“按当前筛选结果补”“只从这个列表里选”时，proposal 才能显式进入 `selectionScope=current_view`。
- 用户表达偏好时，只影响推荐系数和优先级；只有表达排他要求并通过确认卡片/文本确认进入 `hardConstraints` 后，才能作为硬过滤。
- 当前没有全量外部检索证据时，所有候选不足都必须带上范围限定，不能做全局断言。
- 如果候选池本身确实不足，系统应解释边界和可选下一步，而不是继续建议“再补几个稳/保”这种无法执行的动作。

当前 3.1.0 候选不足归因开放边界：

- 已开放确定性归因：`candidate_pool`、`hard_constraints`、`capacity_or_replacement`、`objective_validation`。
- 暂不开放 `current_view`：候选面板筛选当前只存储在 `candidateViewState.filters`，查询接口能按筛选返回当前视图，但修复 selector 默认不消费这些筛选条件，也没有 proposal 级 `selectionScope=current_view`。因此不能因为用户界面上筛了某个条件，就把审查修复不足说成“当前筛选视图不足”。后续只有当用户明确说“按当前筛选结果补/只从这个列表里选”，并且 proposal 记录了 `selectionScope=current_view` 和完整候选池总量/当前视图命中量，才允许输出该 scope。
- 暂不开放 `policy_or_profile_constraints`：高途返回前和服务端候选构建中确实会受到选科、身体、专项、批次线、分数段边界等影响，但当前只有 `riskHints` 和候选最终结果，没有每类政策/画像过滤前后的明细计数。系统可以提示“可能和这些条件有关，需要核验”，但不能断言就是某一项导致候选不足。2026-06-10 已将候选池质量文案统一为“可能限制/需要核验”的保守口径，并补测试确认这些风险提示不会升级成 `candidateShortages.scope=policy_or_profile_constraints`。后续必须补候选来源统计和过滤摘要后再开放。
- `soft_preference` 不是 shortage scope：软偏好不会减少基础候选池，也不参与修复 selector 过滤；它只能解释推荐系数、优先级或专家优选排序变化，不能用来解释“为什么候选不足”。

### 4.2.2 `rebalance_tier_ratio` / `fill_probability_gap` 产品边界

这两类都是结构性修复策略，不能只看“候选池里有没有某个候选”，还必须看来源边界、容量、替换代价和用户预期：

- `rebalance_tier_ratio`：目标是让冲稳保结构更接近 `requiredTierCounts`。如果缺保或缺稳，候选来自当前候选池中的对应 tier；满容量时必须形成一进一出的 replacement pair。它可能牺牲院校层次、专业匹配、地域偏好或推荐系数，因此必须先预览。
- `fill_probability_gap`：目标是缩小录取率梯度断层。候选必须落在断层两端录取率之间，且 dry-run 后断层数量或最大断层确实改善。满容量时不能只追加，必须替换断层边界中相对低性价比的项。
- 两者当前保持 `preview_only` 是正确边界：候选不足来源还没有结构化分层，替换代价也没有完整产品披露，不能贸然开放自动 apply。
- 它们不能被包装成“系统一定会帮你补齐”。当目标 tier、录取率区间或 replacement pair 不足时，正确输出是“当前候选池范围内暂不能满足这个结构目标”，并给出下一步选择。
- 结构性替换不是专业等价替换，不能简单套用“同专业类”硬门槛；否则会把本来用于修冲稳保结构或录取率断层的候选全部挡掉。当前策略是保持只预览，并在预览中披露换出/换入对象、冲稳保区间、录取率、推荐系数、院校排名等关键变化，让用户判断取舍。
- 后续如果开放 apply，必须先满足：
  - proposal 明确使用完整 `replacementPairs`，不能 partial 自动应用；
  - dry-run 证明目标改善；
  - 不能破坏硬要求；
  - 必须披露牺牲项：推荐系数、院校层次、专业热度、地域/专业偏好；
  - `candidateShortages` 或同等结构能说明不足来源是候选池边界、硬条件过滤、当前视图筛选还是用户硬要求；
  - 前端确认卡片能让用户看懂“为什么换、换掉什么、补进什么、还有哪些风险没解决”。

3.1.0 当前结论：`rebalance_tier_ratio` / `fill_probability_gap` 不开放自动 apply；继续作为结构性预览和解释能力。下一步优先补 `candidateShortages` / `shortageAttribution` 结构，再考虑是否开放其中低风险、完整 replacement pair 的子场景。

2026-06-11 补充实现：`RepairReplacementActionBuilder` 在生成满容量结构 replacement action 时，会把最多 3 条具体配对写入 action detail，例如“换出 A -> 换入 B（录取率、推荐系数、院校排名变化）”。该改动不改变 `preview_only` 边界、不把结构替换加入 apply 白名单，只解决用户看不到替换代价的问题。

2026-06-11 进一步补充：结构性修复的候选选择和配对排序已补齐显式质量因子：

- `fill_probability_gap` 的补入候选不再只按“离断层中点最近”排序；同等接近时继续看推荐系数、意向分、院校排名和录取率，避免补入信息量相近但整体质量更差的候选。
- `rebalance_tier_ratio` / `fill_probability_gap` 满容量转 replacement preview 时，会按换出项和候选项的替换成本重排 candidate 侧：优先专业相似度，再看院校排名下降代价、推荐系数损失、意向分损失、候选本身推荐系数/录取率/意向分和院校排名。
- 专业组模式下，如果 compensation action 只有组内 `volunteerIds`、没有显式 `unitIds`，结构替换 builder 会先从候选明细反解 `unitId`，再生成 unit 级 replacement pair，避免满容量专业组断层修复因为 `unitIds` 为空被错误阻断。
- 这仍不是自动 apply。排序和配对只提升结构性预览的合理性和可解释性；`RepairProposalApplyPolicy` 仍不允许 `rebalance_tier_ratio` / `fill_probability_gap` 落盘。

结果矩阵：

| 场景 | `rebalance_tier_ratio` | `fill_probability_gap` | 用户侧表达 |
| --- | --- | --- | --- |
| 候选充分且有剩余容量 | 可展示补入方向，但 3.1.0 不作为自动 apply；如果本质是数量缺口，应转由 `fill_missing_count` 或 `add_safety_items` 承接 | 可展示中间录取率候选，但不直接自动补入 | “可以看到一些改善方向，仍需你确认是否接受结构调整” |
| 方案已满且有完整 replacement pair | 生成 `replace_volunteers` 预览，说明换出/换入和取舍 | 生成断层中间候选替换预览，说明断层是否缩小 | “这是结构调整预览，不会自动生效” |
| 只找到部分候选或部分 pair | `preview_only` 或 `blocked`，披露未覆盖缺口 | `preview_only` 或 `blocked`，披露未覆盖断层 | “只能覆盖一部分，不能说已经修完” |
| 找不到目标候选 | `blocked/cannot_satisfy`，scope 默认 `candidate_pool` 或更具体归因 | `blocked/cannot_satisfy`，scope 默认 `candidate_pool` | “当前可用于规划的候选池里暂时不足” |
| 找不到可替换来源 | `blocked/capacity_or_replacement` | `blocked/capacity_or_replacement` | “不是没有候选，而是当前方案已满且缺少合适的一进一出替换” |
| dry-run 后目标没改善 | `blocked/objective_validation` 或保持只读预览 warning | `blocked/objective_validation` 或保持只读预览 warning | “预览后没有让结构指标变好，所以不建议执行” |

这两类策略在产品上解决的是“结构是否更合理”，不是“用户明确要加/删某个志愿”的直接操作。用户明确说“删掉某个学校/专业”“加进某个候选”“把某个志愿移到第 N 位”时，应走对应的明确方案操作链路，不应借 `rebalance_tier_ratio` 或 `fill_probability_gap` 解释。

3.1.0 对这两类策略的最终产品口径：

- 允许生成结构修复方向和 replacement preview，用于解释“如果要修，可能需要换掉什么、补进什么”。
- 不允许自动 apply。即使有完整 `replace_volunteers` pair，也仍是 `preview_only`，除非后续版本明确开放高副作用结构替换。
- 如果候选不足，先按确定性 scope 解释：硬要求导致的说硬要求，满容量缺 pair 说配对不足，dry-run 无改善说目标没变好，其余只说当前可用于规划的候选池不足。
- 不允许承诺“系统可以直接补稳/补保/补梯度”。当当前候选池没有对应供给时，正确建议是“接受当前结构风险、调整硬要求后重新确认、重新生成候选/方案，或人工查看是否放宽方向”。

### 4.2.3 专业组模式下条目风险替换边界

2026-06-10 使用本地会话 132 验证高收费和中外合作修复时，发现两个容易误判的问题：

- 真实候选并不为空。`replace_risk_items` 已经能为高收费生成 9 个替换配对、为中外合作生成 10 个替换配对。
- 这些 proposal 仍为 `blocked` 是当前产品边界导致的：在专业组模式下，条目级风险命中的是组内专业，但当前替换候选来自其他专业组；如果直接替换单个专业，会改变专业组数量和组内专业结构，因此 dry-run 阶段阻断，返回 `scope=objective_validation`，具体原因是“替换预览会改变专业组数量，暂不允许确认应用”。

本次修正和确认：

- `RepairCandidateSelector.isCompensationSafeCandidate()` 不再把 `special_score:0`、`degree_score:0`、`evaluate_score:0` 这类算法评分标签当作特殊招生/限报风险；只有明确风险标记才会阻断候选。
- `PlanningStateService` 复用同一套安全候选判断，避免补偿和修复候选选择出现两套风险解释。
- `RepairDryRunSimulator` 的新增候选风险提示同样只消费明确风险标记，避免前端出现 `特殊类型招生:special_score:0` 这种拼接文本。
- `candidateShortages` 在 `objective_validation` 场景下优先使用具体 `blockingReason`，不再只显示泛化的“目标未改善”。
- 对 `objective_validation` 未通过的 blocked proposal，后端不再把 dry-run 过程中产生的临时替换动作作为 `actions` 返回，避免外部或前端把“未通过验证的候选尝试”理解为可采纳修复建议。
- 前端修复弹窗对非候选不足的 blocked proposal 显示为“暂不能自动修复的原因”；blocked 状态下不展示 dry-run 的移出/补入统计和替换预览，避免把不可应用结果展示成可执行方案。

2026-06-11 本地复验会话 132：

- `修复高收费`：`status=blocked`，`actionCount=0`，`pairCount=0`，阻断原因为“替换预览会改变专业组数量，暂不允许确认应用”。
- `修复中外合作`：`status=blocked`，`actionCount=0`，`pairCount=0`，阻断原因同上。
- `修复非意向托底`：`status=blocked`，`actionCount=0`，原因是当前专业组缺少可补入的组内安全垫专业。

这说明最新链路已把“找到了但不可应用的候选尝试”从用户可见修复建议中剔除，只保留可解释的阻断原因；同时也确认当前还没有开放专业组整组替换或同组内风险专业替换。

后续如果要让会话 132 这类高收费/中外合作自动修复真正可应用，需要补齐以下策略之一：

- 同组内替换：只在同一专业组内寻找低风险可替代专业，不改变专业组数量和组结构。
- 整组替换：把风险专业所在专业组作为整体替换对象，候选选择需要比较专业组录取率、组内可选专业、托底专业、冲稳保层级、推荐系数、硬要求和新增风险。
- 人工确认保留：当替换代价过高或没有安全替换时，保留风险项但明确提示高收费/中外合作/限报等风险。

在上述策略没有补齐前，“暂不可用”是正确状态；但展示必须说明这是专业组替换边界，不应再表述成“没有安全候选”或输出多层重复的候选不足文案。

### 4.2.4 当前替换逻辑 review 结论

当前替换能力需要区分三类：

- 条目风险替换：`replace_risk_items`，用于高收费、中外合作、限报、特殊招生等落在具体志愿上的风险。
- 结构性替换：`rebalance_tier_ratio`、`fill_probability_gap`，用于方案满容量时的一进一出结构预览。
- 组内安全垫调整：`adjust_major_group_inner_safety`，用于专业组内部补入或替换安全专业。

2026-06-10 review 发现的问题：

- `replace_risk_items` 当前已增加第一阶段质量门禁：候选必须同 tier、风险更低、当前方案未选中、满足已确认硬要求，并且专业至少同专业类或同专业子类，院校排名不能出现严重退化；排序优先专业相似度，再看院校层次代价、推荐系数、录取率和意向分。它仍未完成专业组整组替换、地域/层次取舍披露和更细的相似度评分。
- 专业组模式下，条目风险通常命中组内专业，但外部候选替换往往来自另一个专业组。直接替换单个专业会改变专业组数量，因此必须 blocked，不能展示成可执行修复。
- 会话 132 曾出现会计/金融类中外合作被替换成法学的候选尝试；第一阶段门禁已阻止这类跨专业类替换继续作为候选对外展示，但专业组模式下仍需要同组内替换或整组替换策略才能真正开放自动修复。
- 风险替换排序曾在 `finalScore` 相同后按录取率升序，语义上会偏向更低录取率候选。已修正为录取率降序，再按意向分降序。
- 2026-06-11 重点回归确认：质量门禁会阻断跨专业类替换和严重院校层次下降；原有“多条风险完整替换”和“部分替换只预览”场景在补齐同专业类 fixture 后仍通过，说明门禁没有破坏完整 replacement pair / partial preview 的状态语义。

当前产品口径：

- `objective_validation` 未通过的 blocked proposal 不返回 `actions`，前端也不展示替换预览或 dry-run 移出/补入统计。
- 条目风险替换只有在 proposal 通过 dry-run、目标验证和 apply policy 后，才允许作为用户可确认修复展示。
- 专业组模式下，高收费/中外合作这类风险的自动修复暂不开放；后续要补同组内替换或整组替换策略。

后续替换策略仍要补的质量约束：

- 专业相似度：当前已阻断跨专业类替换；后续还要细化同专业、同专业子类、同专业类之间的差异和代价披露。
- 院校层次和地域代价：披露学校层次、地域、推荐系数、专业热度的变化。
- 专业组整体质量：整组替换时要比较专业组录取率、组内可选专业、托底专业、硬要求和新增风险。
- 用户意向：软偏好影响优先级，硬要求必须过滤；替换建议需要说明是否牺牲了偏好。
- 结果验证：替换后必须证明原风险减少，且不引入更高等级风险、数量缺口或结构退化。

后续落地项：

1. `CandidatePoolStateDTO` 增加候选来源/过滤摘要：
   - 外部返回总量、冲稳保返回量、服务端规范化后总量。
   - 可观测硬条件提示：分数边界、批次线、身体限报、专项资格。
   - 不要求第一期记录每个候选被过滤原因，但要能说明“当前候选池本身偏窄”。
   - 2026-06-10 已完成第一阶段候选来源计数：新增 `candidatePoolState.sourceSummary`，记录外部返回 entry/unit 总量、外部返回冲稳保 entry/unit 计数、服务端规范化后 entry/unit 总量和冲稳保 entry/unit 计数。该字段只用于解释和观测，不参与候选选择、修复 proposal、dry-run、apply、保存或审查编排。
   - 第一阶段 `sourceSummary` 只说明“当前规划候选池来源规模”和“专业模式规范化前后规模”，不做每条候选被政策/画像/筛选过滤的归因。因此仍不能把 `policy_or_profile_constraints` 或 `current_view` 作为精确 shortage scope；后续需要补齐过滤前后计数和 proposal 级 `selectionScope` 后再开放。
2. `CandidateViewStateDTO` 或查询结果增加当前筛选命中统计：
   - 完整候选池总量 vs 当前筛选后总量。
   - 如果用户要求“按当前筛选范围调整”，proposal 需要记录 `selectionScope=current_view`；否则默认 selector 不受面板筛选影响。
   - 2026-06-10 已完成第一阶段查询观测：`CandidatePoolQueryRes.viewSummary` 返回完整候选池 entry/unit 总量、当前筛选视图 entry/unit 总量和当前页加载 entry/unit 数。该字段只用于前端/Agent 区分“候选池本身不足”和“当前筛选视图命中少”，不参与修复候选选择、proposal 归因、dry-run、apply 或审查编排。
   - 前端工作台查询候选时会保留 `viewSummary`，其中本地累计加载数会按已合并分页重新计算；Agent 候选查询摘要会展示“当前筛选视图 / 完整候选池”的只读对照，帮助后续回复避免把筛选视图命中少误说成候选池本身不足。
   - 第一阶段仍不开放 `candidateShortages.scope=current_view`：即使查询结果能看到当前筛选视图命中少，修复 selector 默认仍基于完整规划候选池和已确认硬要求；只有后续 proposal 明确 `selectionScope=current_view` 时，才能把不足归因为当前筛选视图。
3. `FixProposalDTO` 增加 `candidateShortages` 或 `shortageAttribution`：
   - `strategy`、`targetTier`、`requiredCount`、`availableCount`、`scope`。
   - `scope` 可先枚举：`candidate_pool`、`current_view`、`hard_constraints`、`policy_or_profile_constraints`、`capacity_or_replacement`、`objective_validation`、`unknown`。
   - `message` 只做展示，不参与逻辑判断。
   - 2026-06-10 已完成第一阶段落地：新增 `CandidateShortageDTO` 并挂到 `FixProposalDTO.candidateShortages`；当前由 `RepairProposalStateBuilder.populateCandidateShortages()` 在 proposal 最终状态和 dry-run 后统一从 `blockingReasonCodes + state/check` 生成。该字段只做解释和观测，不参与 selector、dry-run 状态判断、apply 白名单、保存、ordered regenerate 或复审编排。
   - 第一阶段已覆盖确定性 scope：`candidate_pool`、`hard_constraints`、`capacity_or_replacement`、`objective_validation`、`unknown`。`current_view`、`policy_or_profile_constraints` 仍需要后续在候选来源、视图筛选和政策/画像过滤链路上补充更精确归因后再开放，避免伪精确。
   - 第一阶段计数字段保守生成：数量缺口会填 `requiredCount/currentCount/shortageCount/availableCount`；冲稳保缺口会在能确定 `targetTier` 时填层级计数；梯度断层会只统计当前候选池中断层区间可用候选；无法可靠计算时字段留空或只给 `scope/message`。
   - 2026-06-10 已完成已确认硬要求的最小闭环：新增 `RepairCandidateEligibility`，修复候选选择会在补齐数量、补保底、补梯度、风险替换和专业组内安全垫补入时过滤 `constraintState.hardConstraints`；`constraintState.softPreferences` 仍只影响推荐系数/排序，不参与过滤。专业组模式下，候选 item 会先按硬要求过滤再成组；unit 级准入优先按实际会选入方案的 `selectedMajors` 判断，只有 selected 为空时才用 `allMajors` 兜底，避免因为同一专业组里未选中的专业误伤整组补位。`candidateShortages` 会比较“应用硬要求前后”的可用候选数，只有在原候选足够而硬要求过滤后不足时输出 `scope=hard_constraints`。
4. `RepairCandidateSelector` 返回统一 selection result：
   - 不只返回候选 id，也返回 `shortageReasons`。
   - 每个 strategy 都能说明是“目标 tier 不足”“断层区间不足”“无可替换来源”“只找到 partial pair”。
   - 2026-06-10 已完成第一阶段内部诊断字段：`RepairCandidateSelector.Selection` 现在会保留 `targetTier/requiredCount/selectedCount/shortageCount/availableCount/availableCountWithoutHardConstraints/shortageCausedByConfirmedHardConstraints`。当前这组字段先用于 selector 层回归和后续收口，不改变 `FixProposalDTO.candidateShortages` 的权威输出，也不参与 apply 白名单、dry-run 状态或保存编排。
   - 第一阶段已覆盖 `fill_missing_count`、`add_safety_items`、`rebalance_tier_ratio` 的补入候选选择，以及 `fill_probability_gap` 的断层区间补入候选选择。风险替换和满容量 replacement source 仍保留现有 pair/missing 计数，后续再统一成同一套 selection diagnostic，避免一次改变高副作用替换语义。
5. Agent 回复规则：
   - 若 scope=`candidate_pool`，说“当前可用于规划的候选池不足”。
   - 若 scope=`current_view`，说“当前筛选视图下不足，可尝试取消筛选”。
   - 若 scope=`hard_constraints`，说“硬性要求收窄了可选范围，若要补齐需要调整要求并重新确认”。
   - 若只是软偏好，不说“筛掉”，只说“优先级降低/推荐系数变化”。
6. 回归：
   - 专业模式/专业组模式各覆盖候选池不足、当前筛选不足、硬要求导致不足、软偏好不减少候选。
   - `rebalance_tier_ratio` 和 `fill_probability_gap` 各覆盖完整 pair preview、partial pair blocked/preview_only、无候选 blocked、dry-run 无改善 blocked。

当前真实 apply 编排位置：

```text
applyFixProposal
  -> RepairProposalApplyPolicy.validate*
  -> generateFixProposals / findProposal
  -> applySupportedFixProposalStrategy
     -> RepairApplyMutationBuilder(纯内存增删/替换)
     -> saveWorkingPlanState
     -> generateOrderedPlan(可选)
     -> runReview(可选)
  -> RepairReportBuilder.build
```

这个编排保持在 `PlanningStateService` 内，是因为保存、ordered plan 重建和复审都属于高副作用流程；已经抽出去的 builder/policy/selector 只承担纯内存、纯校验或纯组装职责。

## 5. 需求拆解

### 5.1 ReviewRuleRegistry

后端提供权威审查规则目录，每条规则包含：

- `code`
- `label`
- `description`
- `category`
- `severityDefault`
- `scopeKind`
- `targetMode`：专业模式、专业组模式、两者都支持。
- `fixability`
- `supportedFixStrategies`
- `evidenceSchema`
- `postApplyValidationRule`

初始分类建议：

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| `item_risk` | 风险落在具体条目上，可删除/替换 | 高收费、中外合作、限报、特殊类型 |
| `structure_risk` | 结构失衡，需要补齐/替换/重排 | 冲稳保比例、数量缺口、梯度断层 |
| `ordering_risk` | 顺序不合理，需要重排 | 概率倒挂 |
| `major_group_risk` | 专业组内部风险 | 非意向托底、组内安全垫不足 |
| `policy_notice` | 信息提示或外部核验 | 招生计划更新、调剂风险 |

### 5.2 ReviewResult 扩展

审查结果需要从「摘要」升级为「可解释、可修复」对象。

建议字段：

- `code`
- `level`
- `passed`
- `summary`
- `userMessage`
- `evidence`
- `affectedTargets`
- `sampleTargets`
- `scopeKind`
- `fixability`
- `supportedFixStrategies`
- `recommendedStrategy`
- `blockingReason`
- `sourceVersion`
- `ruleVersion`

`affectedTargets` 要明确区分：

- `volunteerIds`
- `unitIds`
- `majorIds`
- `schoolIds`
- `positions`

专业组模式下，必须清楚说明动作粒度是专业组、组内专业，还是单个专业。

### 5.3 FixProposal

新增统一修复 proposal 模型，用于替代当前散落的 compensation action、adjustment suggestion 和 agent 临时 action scope。

建议字段：

- `proposalId`
- `sourceReviewId`
- `sourceCheckCodes`
- `sourceVersion`
- `status`
- `strategy`
- `summary`
- `impact`
- `actions`
- `dryRunResult`
- `requiresConfirmation`
- `expiresAt` 或 `sourceVersionGuard`
- `postApplyValidationPlan`

#### 5.3.1 全局 Repair Strategy / Action Taxonomy

3.1.0 起，Repair 相关策略和动作按三层统一定义，避免后端、Agent、前端继续各自维护字符串：

1. `RepairStrategy`：表示“这个问题准备用什么策略处理”，是 Review/Repair/CompositeProposal 共享的策略层。
2. `RepairActionType`：表示“这个 proposal 具体会怎么动”，复用后端 `FixProposalActionDTO.actionType`。
3. `PlanActionPlan.action_family`：表示 Agent 当前调用的方案工具动作 envelope，不能与 Repair strategy 混用。

当前全局 `RepairStrategy`：

| Strategy | 语义 | 当前 apply 边界 |
| --- | --- | --- |
| `fill_missing_count` | 补齐方案数量缺口 | `ready` 时可 apply |
| `add_safety_items` | 补保底/安全垫候选 | 当前默认 preview only |
| `rebalance_tier_ratio` | 调整冲稳保比例 | 当前 preview only，即使有 replacement pair 也不自动落盘 |
| `fill_probability_gap` | 补录取率梯度断层 | 当前 preview only，即使有 replacement pair 也不自动落盘 |
| `sort_by_probability` | 按录取率/风险梯度重排 | `ready` 时可 apply |
| `remove_risk_items` | 移出高收费、限报等具体风险项 | `ready` 时可 apply |
| `replace_risk_items` | 用低风险候选替换具体风险项 | `ready` 且 pair 完整时可 apply |
| `adjust_major_group_inner_safety` | 专业组内补入/替换安全专业 | `ready` 时可 apply |
| `no_op` | 仅提示，不需要处理 | 不可 apply |
| `cannot_satisfy` | 当前候选或约束下无法满足 | 不可 apply |

当前全局 `RepairActionType`：

| ActionType | 语义 | 常见来源 |
| --- | --- | --- |
| `fill_total_count` | 补足缺口数量 | `fill_missing_count` |
| `add_volunteers` | 补入候选，但不一定补总数 | `add_safety_items` |
| `remove_volunteers` | 移出具体风险项 | `remove_risk_items` |
| `replace_volunteers` | 一进一出替换，必须带 replacementPairs 或等价 remove/candidate 列表 | `replace_risk_items`、结构性 preview |
| `reorder_volunteers` | 调整现有顺序，不新增候选 | `sort_by_probability` |
| `adjust_major_group_inner_safety` | 专业组内补入/替换安全专业 | `adjust_major_group_inner_safety` |
| `no_op` | 无动作，仅提示 | `no_op`、`cannot_satisfy` |

历史/补偿层别名统一映射：

| 旧/上游字符串 | 统一到 |
| --- | --- |
| `fill_total_count` strategy | `fill_missing_count` |
| `add_local_protect` | `add_safety_items` |
| `rebalance_protect_ratio` | `rebalance_tier_ratio` |
| `sort_ordered_plan` repair action | `reorder_volunteers` |
| `add_units` repair action | `add_volunteers` |
| `remove_units` repair action | `remove_volunteers` |
| `replace_units` repair action | `replace_volunteers` |
| `blocked` status/strategy alias | `cannot_satisfy` |
| `info` status/strategy alias | `no_op` |

`cannot_satisfy` 是必要的一等状态，避免候选不足时继续空泛建议。`no_op` 和 `cannot_satisfy` 都不生成可确认动作。

Agent 侧不再镜像 Repair proposal DTO。`RepairStrategy / RepairActionType / applyable / preview_only` 的运行期判断以 Java `RepairProposalTaxonomy` 和 `FixProposalDTO` 为准；Python 只保存 pending apply 所需的 `proposalId`、`proposalSource`、`sourceVersionGuard`、`userGoalRequest` 和用户可见摘要，不在 `CompositePlanProposal` 里挂接一份 repair proposal 副本。

后端 Java 侧已补充 `RepairProposalTaxonomy` 作为运行期统一定义：

- `RepairProposalTaxonomy.Strategy` 是后端 proposal 生成、dry-run、apply policy、action builder、report 的统一 strategy 来源。
- `RepairProposalTaxonomy.ActionType` 是后端 action 计数、dry-run 模拟、mutation apply 的统一 actionType 来源。
- `RepairProposalTaxonomy.CompensationActionType` 承接旧补偿层 action type，例如 `add_local_protect`、`rebalance_protect_ratio`；这些旧值仍可出现在 compensation preview 中，但进入 repair 层会统一映射到 `RepairStrategy`。
- `RepairProposalTaxonomy.isApplyableStrategy()` 和 `isPreviewOnlyStrategy()` 是后端 apply 边界的唯一判断来源。`rebalance_tier_ratio` / `fill_probability_gap` 即使有 `replace_volunteers` 预览，也仍不能绕过 apply policy 自动落盘。

`replace_risk_items` 的 action 需要能表达 remove + candidate 的配对关系，至少包含：

- `removeUnitIds`
- `removeVolunteerIds`
- `candidateUnitIds`
- `candidateVolunteerIds`
- `replacementPairs`

其中 `replacementPairs` 用于前端披露“用谁替换谁”和原因，避免只给出一组候选列表但无法解释替换关系。专业组模式下，pair 需要同时保留专业组粒度和组内专业粒度，不能把组内专业数误当成专业组数。

### 5.3.0 用户复合方案调整计划

3.1.0 不能继续把用户的方案调整诉求压成少数几个特例。`only_keep`、`must_have` 只是常见表达，真实用户还会把多个目标混在一句话里：

- “只保留临床医学，其他都不要。”
- “方案里至少有一个临床医学，但别把稳的都删了。”
- “不要中外合作，省内优先，保底多一点。”
- “我不想学工商管理，金融可以保留，学校层次别降太多。”
- “这版太冲了，专业尽量别偏离孩子想学的方向。”

这类诉求的合理处理方式不是继续加字符串分支，而是引入一层 `PlanGoal -> CompositePlanProposal`：

```text
用户自然语言
  -> Agent 理解为 PlanGoal
  -> 实体解析与歧义识别
  -> 候选/当前方案/已确认偏好与要求读取
  -> 拆解为原子动作计划
  -> dry run / 可行性验证
  -> 复合操作预览
  -> PendingConfirmation
  -> 用户确认后执行
  -> 复审和 RepairReport
```

这里的 `PlanGoal` 是系统理解后的结构，不是对用户表达的限制。用户可以宽泛地说“整体更偏体制内、稳一点”，也可以具体到“删掉第 40 位之后几个保的学校”或“把第 8 个志愿移到第 12 位”。系统需要先判断这句话落在高层情景、复合目标还是原子动作附近；越宽泛越需要补充目标拆解和取舍依据，越具体越可以直接进入对应原子动作预览，但所有会改变意向或方案的结果都必须保持确认和验证门禁。

#### 5.3.0.1 `PlanGoal`

`PlanGoal` 表达用户到底想达成什么，不直接等于底层 action。

建议字段：

```json
{
  "goalType": "only_keep_scope | must_include_scope | exclude_scope | prefer_scope | rebalance_structure | reduce_risk | mixed_adjustment | clarify",
  "targetScopes": [],
  "negativeScopes": [],
  "structureTargets": [],
  "qualityGuards": [],
  "userOriginalText": "",
  "confidence": "high | medium | low",
  "needsClarification": false,
  "clarificationQuestions": []
}
```

字段边界：

- `goalType` 由模型基于上下文理解，不靠“想去/不想去/只要/必须”等少数词硬匹配。
- `targetScopes` 表示用户希望保留、补入或优先考虑的范围。
- `negativeScopes` 表示用户明确排除或降低优先级的范围。
- `structureTargets` 表示冲稳保、保底、数量、录取率梯度、排序等结构目标。
- `qualityGuards` 表示用户不希望牺牲的边界，例如院校层次别降太多、专业别偏太远、别增加高收费。
- `confidence=low` 或存在关键歧义时，不生成可执行 proposal，只生成澄清问题或只读分析。

当前实现状态：

- 后端模型层已落地 `PlanGoal`、`PlanEntityResolution` 和 `CompositePlanProposal`。`PlanActionPlan` 顶层只保留当前动作 envelope：`stage`、`action_family`、`atomic_actions`、缺参、确认和刷新标志；复合目标、待写入意向、复合动作、取舍依据、可行性和歧义说明统一放在 `composite_proposal` 内。
- `IntentFrame` 已增加 `plan_goal_type` / `constraint_intent_type` / `plan_goal_confidence`，用于接收上游模型明确输出的复合目标类型。
- `ActionResolver` 只负责把结构化 `IntentFrame` 映射成动作族、阶段、缺参、确认门禁和类型化原子 action；它不再输出 `plan_goal` / `intent_updates` 镜像，避免复合目标在 resolver 和 plan envelope 两处不同步。
- `plan_next_action` 已能接收 `plan_goal_type`、`constraint_intent_type`、`goal_target_scopes`、`goal_negative_scopes`，并在 `PlanActionPlan.composite_proposal` 中输出 `goal`、`intent_updates`、`plan_actions`、`decision_references`、`feasibility`、`impact_summary` 和 `tradeoffs`。这一步仍是元数据和预览协议铺底，不直接写入用户意向，也不直接执行方案修改。
- `plan_next_action` 已对模型传入的结构化 scope 做实体消歧：专业复用 `major_entity_resolver`，地域复用 `region_entity_resolver`，院校复用 `school_entity_resolver`。解析结果写入 `PlanGoal.entity_resolutions` 和 `CompositePlanProposal.entityResolutions/impactSummary`；无歧义时，`PlanGoal.targetScopes/negativeScopes` 与待确认的 `intent_updates` 使用标准名，用户原话保留在 `rawText`；多解或未知实体会让复合 proposal 进入 `needs_clarification`，不生成可采纳的 `intent_updates`。
- `plan_next_action` 已开始输出保守的复合动作拆解：`exclude_scope` 可生成结构化 `remove_units` 计划，`must_include_scope` 可生成结构化 `add_units` 计划；`only_keep_scope` 在 `plan_next_action` 本身仍不凭空生成“删除所有非目标范围”的反向动作，必须先拿到当前方案事实再计算。
- 当前服务层已把确认后的 `only_keep / must_have / exclude` 约束接到 Java `user_goal` proposal/apply 主链路：从已确认的 intent preview 读取结构化范围，生成 `UserGoalFixProposalReq`，调用 Java `UserGoalProposalBuilder` 生成 ready proposal，保存 `plan_mutation` 待确认卡，并把本次 intent 更新作为同一个 pending 的 `intentPayload` 一起保存。用户确认时先写入报考参考，再按最新 planning version 重建 proposal 并调用 Java apply。它解决线上“仅保留临床医学却误删临床医学”的问题；后续新增复合场景不要继续在 service helper 里扩本地候选选择分支，应进入统一 `Scenario -> PlanGoal -> Java FixProposal` 链路。
- `CompositePlanProposal` 已落地为模型层和工具输出字段，用于把目标、意向更新、方案动作、可行性、影响说明、执行后验证计划聚合为一个预览单元。它不是新的 apply 接口，不绕过 `PlanActionPlan.stage`、缺参检查、pending confirmation 或 review stale 保护。
- 旧的 `PlanActionPlan.goal` / `intent_updates` / `plan_actions` / `feasibility` 等顶层复合字段已经退场。历史 payload 如果带这些字段，执行 envelope 不再读取；需要进入复合计划的内容必须放在 `composite_proposal`，避免同一事实在两处不同步。
- 约束兼容映射已统一：`constraint_intent_type=only_keep` 对应 `goalType=only_keep_scope`；`constraint_intent_type=must_have` 对应 `goalType=must_include_scope`。普通 `default` 不会自动推断复合目标。
- 明确禁止仅凭 `userGoal` / `rawUtterance` 里的中文短语推断 `goalType`。如果模型没有输出结构化字段，系统按普通原子 action 处理或要求补充信息。

典型 goal 映射：

| 用户诉求 | goalType | 预期拆解 |
| --- | --- | --- |
| 只保留临床医学 | `only_keep_scope` | 识别临床医学范围；保留命中项；移出非命中项；如数量不足，尝试从候选补入临床医学；不能满足时说明边界 |
| 方案里必须有临床医学 | `must_include_scope` | 检查当前方案是否已有；没有则从候选补入或替换；不删除其他方向 |
| 不要中外合作 | `reduce_risk` 或 `exclude_scope` | 命中当前方案中外合作项；优先替换，必要时删除；同步披露数量/结构影响 |
| 省内优先，保底多一点 | `mixed_adjustment` | 写入或引用地域偏好；调整保底/安全垫；生成结构预览 |
| 只要电气和气象，其他方向都不要 | `only_keep_scope` | 只把电气/气象作为正向范围；不得把“其他方向”展开为全部专业门类负向项 |

当前拆解边界：

- `exclude_scope`：如果 scope 是专业/院校/地域，可生成 `remove_units` 计划，执行层再读取当前方案并定位命中项。
- `must_include_scope`：如果 scope 是专业/院校/地域，可生成 `add_units` 计划，执行层再查候选并生成补入预览。
- `only_keep_scope`：不能仅凭自然语言或目标实体直接生成反向删除计划。当前过渡实现已在 intent 确认后读取当前方案并计算目标命中项与非目标项，再生成待确认的移出预览；仍缺“候选补足目标范围、dry-run 结构校验、统一 CompositePlanProposal apply/report”这几步，因此后续要迁入复合计划链路，而不是继续扩 service 旁路。

#### 5.3.0.2 实体解析与歧义消除

复合计划必须把“用户说了什么”和“系统能执行什么范围”分开。专业、院校、地域都需要结构化 entity resolution，特别是专业：

| 实体类型 | 示例 | 风险 | 处理 |
| --- | --- | --- | --- |
| 标准具体专业 | 工商管理、临床医学、经济与金融 | 可能被模型扩大成专业类 | 默认按具体专业理解 |
| 标准专业类 | 工商管理类、临床医学类 | 可能被用户当成泛称 | 若用户明确说“类/方向/这一类”，按专业类 |
| 标准门类 | 工学、医学 | 范围很大 | 必须在预览中披露范围较宽 |
| 招生计划展示专业类 | 工商管理类（含工商管理、市场营销、人力资源管理） | 不是标准目录意义上的唯一专业类，可能包含多个专业 | 预览中披露“当前方案里有专业类包含该专业，是否也一起处理” |
| 用户简称/俗称 | 计科、财会、气象、工科 | 需要映射到标准实体 | 先走公共别名/目录解析，不能由 action 层临时猜 |

专业歧义处理原则：

- 用户说具体专业时，不默认扩大到整个专业类。
- 当前方案中如果只有“包含该专业的招生计划专业类”，必须在预览里注明。
- 如果一个词可能是具体专业、专业类、职业方向或招生计划描述，且处理结果差异大，先澄清。
- 如果用户明确说“这一类都不要”“相关方向都不考虑”，可以扩大到专业类，但仍需披露范围。
- 后端规范化只做目录和候选事实校验，不重新推断用户正负向。

当前实现状态：

- 已完成：结构化 scope 的目录级消歧，覆盖专业、院校、地域。示例：`计科 -> 计算机科学与技术`、`内蒙 -> 内蒙古`、`广西师大 -> 广西师范大学`。无歧义对象会用标准名进入待采纳更新，避免把简称写入长期报考参考。
- 已完成：宽泛或多解实体阻断确认。示例：`财会` 会披露可能对应工商管理类、会计学、财务管理、审计学等，不直接生成可采纳更新。
- 待补齐：把当前方案和候选中的招生计划展示名接入消歧证据，用于识别“具体专业 vs 招生计划专业类（含若干专业）”这类执行范围差异。

用户侧披露示例：

> 我先按“具体专业工商管理”理解。当前方案里还有一些“工商管理类”专业组，里面可能包含工商管理、市场营销、人力资源管理等方向；这类是否也一起避开，需要你确认。

#### 5.3.0.3 `CompositePlanProposal`

`CompositePlanProposal` 是面向用户确认的复合预览，不替代 `FixProposal`，而是把多个 intent 更新、保守 plan action 草案、实体歧义和取舍依据组合成一个说明单元。真正可执行的 repair/user-goal proposal 通过 service pending 桥保存 Java `FixProposal` 的 `proposalId/sourceVersionGuard/proposalSource/userGoalRequest`。

建议字段：

```json
{
  "proposalId": "uuid",
  "sourceVersion": 12,
  "goal": {},
  "entityResolutions": [],
  "intentUpdates": [],
  "planActions": [],
  "decisionReferences": [],
  "dryRunResult": {},
  "feasibility": "ready | preview_only | blocked | needs_clarification",
  "impactSummary": [],
  "tradeoffs": [],
  "requiresConfirmation": true,
  "postApplyValidationPlan": []
}
```

组合规则：

- `intentUpdates` 只负责写入后续偏好或要求，例如把“只保留临床医学”记为已确认报考要求。
- `planActions` 只承载 Agent 能安全表达的保守动作草案，例如已结构化的查看、补入、移出或排序意图；复杂候选选择、替换配对、dry-run 和真实 mutation 必须交给 Java `FixProposal`。
- `decisionReferences` 负责记录本次比较和取舍的依据，既包括用户显式说出的目标/要求，也包括系统隐式使用的推荐系数、录取率、冲稳保层级、院校层次、专业热度、意向匹配、审查风险和候选容量。
- 一个复合预览可以包含多个原子动作，但必须作为一个 pending 确认，确认前不执行。
- 如果一部分可执行、一部分不可执行，不能包装成“已完整处理”；应显示为部分可处理，并说明剩余问题。

`decisionReferences` 的定位：

- 用户显式意图是高优先级输入。用户确认后的硬性报考条件优先于推荐系数；软偏好只影响优先级和推荐系数，不直接过滤基础候选池。
- 系统隐式参考是比较和排序输入。推荐系数、录取率、冲稳保、院校层次、专业热度、意向分等用于判断“保留谁、移出谁、补谁、替换谁更合适”，也用于解释为什么某个高推荐项被保留或被牺牲。
- 审查风险和候选容量是安全输入。高收费、中外合作、限报、候选不足、结构风险等不能被推荐系数覆盖，必须在 dry run 或预览里披露。
- 这些参考点只提供证据，不是 apply 权限。是否能执行仍由 stage、缺参检查、pending confirmation、版本保护、dry run 和 apply 白名单共同决定。

复合计划在涉及对比时的基本比较顺序：

1. 先校验硬条件：已确认必须满足/必须避开的范围、政策限制、禁选、版本有效性。
2. 再处理用户本轮显式目标：例如 only_keep 的目标范围、must_have 的至少保留范围、exclude 的移出范围、quality guard。
3. 再比较系统参考：推荐系数、录取率、冲稳保、院校层次、专业热度、意向匹配、风险标签、候选容量。
4. 最后形成 tradeoff：如果为了用户目标或风险修复牺牲了高推荐系数、强意向、院校层次或安全性，必须在预览里说明。

典型例子：

- `only_keep_scope`：如果非目标志愿推荐系数很高，也不能静默保留；但预览必须提示“这些高推荐项会因只保留 X 被移出”，让用户知道代价。
- `must_include_scope`：只要求至少有 X，不应删除其他高推荐项；如果需要腾位置，应优先选择低推荐、低意向或风险较高的项，并披露代价。
- `exclude_scope`：若当前方案命中排除范围，优先生成移出/替换预览；若移出会导致数量不足，要同步说明补位能力。
- 结构修复：保数量、保安全、保偏好、保院校层次之间需要比较，不能只按某一个指标排序。

#### 5.3.0.4 与现有框架的统一关系

这层不是新旁路，应复用现有主链：

- 对话确认继续复用 3.0.3 `PendingConfirmation` 协议，卡片是主入口，短文本确认只消费 active pending。
- 当前方案修改继续通过 `plan_next_action -> execute_plan_action` 或后端 `fix-proposals/apply` 受控执行。
- 审查问题修复继续以 `ReviewCheck -> FixProposal -> dryRun -> apply -> RepairReport` 为准。
- 推荐系数、候选/方案刷新沿用当前 stale 和 refresh 逻辑，不在复合计划里重新定义。
- `only_keep` / `must_have` 不再作为零散特殊路径扩展，而是 `PlanGoal.goalType` 的两个子类。

#### 5.3.0.5 不允许的实现方式

- 不允许用固定话术或少数关键词决定 `goalType`。
- 不允许模型直接输出“已删除/已加入/已生效”。
- 不允许把“其他方向都不要”展开成用户没有点名的全部负向专业门类。
- 不允许因用户说“只保留 X”而删除 X。
- 不允许跳过实体歧义披露，直接把具体专业扩大到专业类。
- 不允许在没有 active pending 的情况下，靠模型自然语言里的“请确认”触发执行。

### 5.3.1 风险后的修复策略矩阵

风险后的修复不能只有一个「补偿」动作，也不能简单把命中的条目删掉。3.1.0 需要按风险类型选择不同策略，并且每个策略都要经过 dry run 和确认。

通用决策顺序：

1. 判断风险类型：条目风险、结构风险、排序风险、专业组内部风险、政策/提示风险。
2. 判断用户目标：只读询问、要求修复、要求删除、要求替换、要求调稳、要求保留某些偏好。
3. 生成一个或多个 `FixProposal`。
4. dry run 验证：数量、冲稳保、硬要求、软偏好、候选容量、是否引入新风险。
5. 给用户确认；高副作用动作不直接应用。
6. 应用后重新验证 source check，必要时 full review。

策略矩阵：

| 风险类型 | 典型 code | 默认策略 | 备选策略 | 不能修时的返回 |
| --- | --- | --- | --- | --- |
| 条目风险 | `high_tuition`、`cooperative_program`、`admission_limit`、`special_enrollment` | `replace_risk_items`，优先同层次/同 tier 替换 | `remove_risk_items`、保留但标记提醒 | 候选不足、删除会导致数量不足、替代项引入更大风险 |
| 数量缺口 | `count_validation` | `fill_missing_count` | 放宽软偏好后补齐、提示无法达标 | 候选池不足或硬约束过强 |
| 安全垫不足 | `safety_guard` | `add_safety_items` 或替换部分高风险项 | 增加本省/高录取率保底，降低院校层次换安全 | 没有足够保底候选，需要说明是候选池限制 |
| 冲稳保比例失衡 | `ratio_distribution` | `rebalance_tier_ratio` | 替换 surplus tier 到 shortage tier、重新生成局部方案 | 调整会显著损失用户偏好或候选不足 |
| 概率倒挂 | `probability_inversion` | 先 `sort_by_probability`；若排序不能解决，再替换异常项 | 局部重排、替换倒挂边界项 | 倒挂由用户强制保留或数据缺失导致 |
| 梯度断层 | `probability_gap` | `fill_probability_gap` 或替换断层两侧低性价比项 | 引入中间录取率候选、局部重排 | 没有中间概率候选，保留断层并提示 |
| 边缘分风险 | `edge_score` | 增加稳/保候选或降低冲项占比 | 保留高价值冲项但提示风险 | 分数段导致安全空间不足 |
| 专业组内安全垫 | `group_inner_safety_guard` | 优先补选组内安全专业 | 替换整个专业组、标记调剂风险 | 该组没有安全专业或组内专业选择受限 |
| 专业组安全专业与意向不一致 | `major_group_safety_intent_alignment` | 在安全专业中优先选择更贴近意向的专业 | 替换专业组、保留但提示托底专业不理想 | 安全专业和意向天然冲突 |
| 政策/信息提醒 | `plan_update_notice`、`adjustment_notice` | 不自动改方案，只提示核验 | 用户明确要求时转为条目/结构修复 | 需要外部官方信息或人工判断 |

条目风险的默认策略建议优先「替换」而不是直接「删除」：

- 如果直接删除会导致数量不足，必须优先找替代项。
- 如果替代项会显著变差，需要披露 tradeoff。
- 如果用户明确说「先删掉」，可以生成删除 proposal，但 dry run 里必须提示数量和结构影响。

结构风险的修复不能直接操作 `affectedVolunteerIds`：

- `affectedVolunteerIds` 只是风险证据或上下文，不等于应删除范围。
- 结构风险需要按目标函数规划：保数量、保安全、保偏好、保层次之间做权衡。
- 如果无候选可补，必须返回 `cannot_satisfy`，而不是建议用户继续补稳。

专业组模式必须明确动作粒度：

- 组内专业问题，先在组内专业层面修。
- 专业组整体风险，才替换或删除专业组。
- 专业组整体录取率和组内专业录取率要分别校验。

修复后的用户说明应包含：

- 本次修复针对哪个风险。
- 将会动多少个志愿/专业组/组内专业。
- 修复后哪些指标预计改善。
- 会牺牲什么，例如推荐系数、院校层次、地域偏好或专业匹配。
- 哪些风险仍无法解决，以及原因。

### 5.3.2 候选选择策略层

当前初始化推荐、补偿预览、审查修复、用户手动加入方案都可能从候选池读取候选，但它们的责任不同：

- 用户手动加入方案：用户已经指定 `volunteerIds`，系统只负责校验已选、禁选和候选存在性，不重新替用户排序选择。
- 初始方案生成：系统可在授权范围内自动选择和替换候选，目标是生成一版结构尽量合理的初始方案。
- 审查后修复：系统只能先生成可解释、可确认、可回滚理解的 `FixProposal`；高副作用动作必须用户确认。
- 只读分析/审查：只能披露候选空间和可修复性，不能直接改变方案。

因此 3.1.0 需要把「如何从候选中选」抽象成统一策略层，而不是继续让每个 action 自己临时 `filter + limit`。

建议统一模块：

- `CandidateSourceResolver`：统一返回合并 overlay 后的有效候选，并保证专业模式、专业组模式 ID 规范一致。
- `CandidateEligibilityFilter`：统一过滤已选、禁选、硬要求不满足、明显高风险候选；不同策略可以声明是否允许保留某类风险。
- `CandidateScoringPolicy`：按策略输出显式 comparator，避免依赖上游列表顺序。
- `ReplacementPlanner`：满容量或需要替换时生成 remove/add pair，而不是只给新增候选。
- `CapacityGuard`：统一判断当前数量、目标数量、剩余容量和是否允许替换。
- `DryRunEvaluator`：对候选选择结果做数量、冲稳保、录取率梯度、硬要求、软偏好、风险引入校验。
- `FixActionBuilder`：把选择结果转成 `FixProposalActionDTO`，并保留 `replacementPairs`、原因、取舍说明。

候选选择通用顺序：

1. 确定动作粒度：专业模式按单条志愿；专业组模式先判断是专业组整体问题还是组内专业问题。
2. 确定目标数量：优先使用 `CandidatePoolState.requiredTierCounts` 和省份/模式的目标数量；没有目标时才使用经验比例兜底。
3. 计算当前状态：以 ordered 为准；ordered 为空时用工作台方案（旧 draft 状态）快照，但不能把工作台方案总量和 ordered summary 混用。
4. 构建可用候选：排除已选、禁选、缺少 ID、硬要求冲突、明显风险候选；专业组模式还要排除已选 unit。
5. 显式排序：按该策略的目标函数排序，而不是依赖 rank 返回顺序。
6. 处理容量：有剩余容量时生成 add；满容量时必须生成 replacement pair；如果找不到可替换项，返回 `cannot_satisfy`。
7. dry run：只要指标没有改善或引入更大风险，就不能给出 `ready` 状态。

策略级选择规则：

| strategy | 选择对象 | 目标数量 | 候选排序策略 | 满容量处理 | 不能满足时 |
| --- | --- | --- | --- | --- | --- |
| `fill_missing_count` | 缺口志愿/专业组 | `requiredCount - currentCount` | 低风险前提下优先 `finalScore desc`、意向匹配、同 tier 目标缺口 | 不应触发，数量缺口天然有容量 | 返回候选不足，说明缺口数和可补数 |
| `add_safety_items` | 本省/保底候选 | 本省保底至少 2 个，或规则目标数 | `tier=保`、本省、低风险、录取率高、推荐系数高 | 替换非本省保底或低分高风险项 | 返回保底候选不足，不建议空泛“继续补保” |
| `rebalance_tier_ratio` | 缺口 tier 候选 | 优先 `requiredTierCounts[tier] - currentTierCount`，否则经验比例兜底 | 缺口 tier、低风险、录取率/推荐系数/意向综合；保区不足时安全性权重更高 | 从 surplus tier 中移除非锁定、非本省保底、低意向/低推荐项，形成 pair | 返回目标 tier 候选不足或无可替换项 |
| `fill_probability_gap` | 断层区间候选 | 默认 1-2 个，或按断层数量限制 | 录取率位于断层区间，优先接近中点，再看推荐系数、意向、院校排名和录取率 | 替换断层两侧低性价比项，不能只追加；配对时按专业相似、院校层次代价、推荐/意向损失排序 | 返回中间录取率候选不足 |
| `replace_risk_items` | 风险项替代候选 | 每个风险项一个替代项 | 同 tier/相近层次、低风险、硬要求满足；推荐系数和安全性同时不能明显变差 | 天然 pair 替换 | 返回未匹配风险项数量和缺少替代原因 |
| `remove_risk_items` | 风险项本身 | 命中的风险项 | 不选候选；如果删除导致数量不足，串联 `fill_missing_count` | 删除后补齐，或提示数量不足 | 返回删除影响和补齐不足 |
| `adjust_major_group_inner_safety` | 同专业组内专业 | 每个命中专业组至少 1 个安全专业 | 同 unit、未选、未禁选、专业录取率不低于组录取率；优先兼顾安全和意向 | 如果组内专业数已满，替换非安全、低意向、低推荐的组内专业 | 返回该组没有安全专业或组内均被锁定 |
| `sort_by_probability` | 已有方案顺序 | 不新增候选 | 不选候选，只按录取率/院校层次/推荐系数排序 | 不涉及容量 | 如果用户锁定或数据缺失导致不能改善，返回说明 |

这里的 `strategy` 不是最终落盘 action，而是审查问题对应的修复策略。当前实现需要区分四层：

1. `ReviewRuleRegistry.supportedFixStrategies/defaultFixStrategy`：规则层描述“这个问题可以怎么修”，例如 `ratio_distribution -> rebalance_tier_ratio`、`probability_gap -> fill_probability_gap`。
2. `CompensationPreviewDTO.actions`：候选补偿层描述“可以补哪些候选”，例如 `rebalance_protect_ratio`、`fill_probability_gap`、`fill_total_count`。
3. `FixProposalDTO.actions`：确认卡片层描述“本次建议具体怎么改”，例如满容量结构修复会把 add-only 补偿动作转换为 `replace_volunteers`，并携带 `replacementPairs/removeVolunteerIds/candidateVolunteerIds`。
4. `RepairProposalApplyPolicy.isSupportedStrategy()`：高副作用 apply 白名单。只有 `status=ready` 且策略在白名单内，才允许进入 `applyFixProposal()`；进入后再由 `RepairApplyMutationBuilder` 执行内存 mutation，`PlanningStateService` 负责保存、可选重新生成 ordered plan、可选复审和报告。

因此，“自动 apply `rebalance_tier_ratio` / `fill_probability_gap`”不是直接执行这两个名字的 action，而是指是否允许这两类结构修复 proposal 通过 apply 白名单。当前它们即使已经生成 `replace_volunteers` pair，也仍保持 `preview_only`，只披露修复方向和 dry-run 影响，不进入自动落盘。

专业组模式的特殊约束：

- `requiredCount` 表示专业组数量时，不能把组内专业数量算成专业组数量。
- `requiredMajorCount` 只约束每个专业组内保留几个专业。
- 专业组整体补齐使用 unit 级选择；组内安全垫使用同 unit 内专业选择。
- unit 的代表录取率应使用专业组整体录取率；组内专业录取率只用于组内安全和专业展示。
- replacement pair 要同时表达 `fromUnitId/toUnitId` 和 `fromVolunteerId/toVolunteerId`，避免前端无法说明“换的是专业组还是组内专业”。

当前代码与目标策略层的差距：

- `buildInitialRecommendationState` 已经有较完整的选择和替换逻辑，但还没有沉淀为可复用 selector。
- `buildCompensationPreview` 的 add 侧候选选择已迁入 `RepairCandidateSelector` 并补充显式排序；仍需继续把初始方案生成和事后修复的权重配置统一。
- `rebalance_tier_ratio` 已优先使用 `requiredTierCounts`，没有明确目标时才回退经验比例。
- `rebalance_tier_ratio` / `fill_probability_gap` 在满容量时已能生成完整 `replace_volunteers` pair；当前仍保持 `preview_only`，不开放自动 apply。
- 候选不足已能通过 `cannot_satisfy` / `blocked` 输出规则级原因，并通过 `CandidateShortageDTO` 暴露 proposal 级解释；selector 层已开始携带内部诊断字段，但还没有把所有风险替换/满容量替换统一迁移到同一结果模型。
- 初始生成和事后修复对风险过滤、排序权重、取舍披露还不一致。

### 5.4 Dry Run Validation

所有修复 proposal 在给用户确认前，需要执行 dry run。

校验维度：

- 方案数量是否达标。
- 冲稳保比例是否变好或不恶化。
- 硬要求是否满足。
- 软偏好是否尽量保留。
- 专业组模式下组内专业数量和托底专业是否合理。
- 候选是否足够。
- 是否引入新的高收费/限报/中外合作等风险。
- 是否与当前方案版本一致。

dry run 输出不能只说「可以修」，要说明：

- 会删除/替换/新增多少项。
- 典型影响项是什么。
- 哪些风险会改善。
- 哪些风险仍保留。
- 如果不能修，原因是什么。

### 5.5 Apply And Post-Apply Review

应用 proposal 后，需要统一执行：

1. 检查 proposal 是否仍然有效。
2. 执行 actions。
3. 写入行为事件和操作日志。
4. 刷新 ordered/working-plan/recommendation overlay。
5. 对 source check 做目标规则验证。
6. 必要时 rerun full review。
7. 生成 `RepairReport`。

`RepairReport` 建议包含：

- `applied`
- `appliedActions`
- `changedTargets`
- `resolvedChecks`
- `remainingChecks`
- `newChecks`
- `warnings`
- `candidateShortage`
- `nextSuggestions`

用户侧表达要避免系统术语，重点说：

- 刚才改了什么。
- 原来哪个问题改善了。
- 还有什么需要注意。

### 5.6 外部触发协议

3.1.0 需要提供稳定外部接口，而不是让外部系统拼低层接口。

建议新增或收口接口：

```text
POST /session/review-workflow/run
POST /session/review-workflow/proposals
GET  /session/review-workflow/proposals/{proposalId}
POST /session/review-workflow/proposals/{proposalId}/apply
GET  /session/review-workflow/reports/{reportId}
```

也可以保留当前低层接口，但文档中明确：

- 低层接口用于内部和兼容。
- 新工作流接口用于外部稳定对接。

外部触发需要支持：

- `triggerSource`：user、agent、frontend、external、scheduled。
- `reviewScope`：full、changedOnly、specificChecks。
- `proposalMode`：none、previewOnly、autoGenerate。
- `confirmationMode`：userRequired、externalConfirmed、systemAllowed。
- `async`：是否异步执行。
- `sourceVersion`：版本保护。

### 5.7 前端交互

3.1.0 前端需要从「轻量审查提示」升级到「审查修复入口」，但不一定一开始做重型页面。建议分两层：

轻量层：

- 保留顶部审查按钮和风险提示。
- Tooltip 中只展示摘要和入口。

详情层：

- 展示问题列表。
- 每个问题展示证据、影响范围、严重程度。
- 可修复问题展示「查看修复建议」。
- 修复 proposal 以确认卡形式展示。
- 应用后展示复审结果。

对话层：

- 用户说「帮我审查」「这版太冲了」「太贵的去掉」「帮我修最严重的问题」时，进入同一套 review workflow。
- 对话只负责解释和确认，不绕过后端 proposal。

2026-06-11 前端工作台交互收口设计：

- PC 工作台不再把「审查」和「修复建议」作为两个平级按钮。主入口统一为审查按钮：
  - 没有审查结果时显示「审查」，点击触发 `review-workflow/run`。
  - 已有审查结果时显示「重新审查」，点击重新执行 `review-workflow/run`。
  - 主按钮不承载「查看审查结果」，避免用户把查看详情和重新审查混成同一个动作。
- 风险提示图标保留为快捷入口。hover 继续展示轻量摘要，tooltip 底部提供「查看详情」文字链；点击风险提示图标或「查看详情」文字链都打开同一个「方案审查结果」弹窗，并按需调用 `fix-proposals/generate` 刷新建议。
- 方案顺序栏只保留当前顺序说明和审查入口，不再在「当前顺序」提示下额外展示“方案有提醒 / 风险 N / 提醒 N”摘要。用户需要查看审查细节时，通过风险提示图标或 tooltip 内「查看详情」进入弹窗。
- 审查请求进行中时，弹窗内容区展示「正在审查当前方案」，不能落入“当前审查没有需要处理的问题”的空态；只有审查完成且确实没有风险/提醒/处理建议时才展示空态。
- 弹窗以审查问题为主线，而不是先列一组孤立修复按钮：
  - 每个 `ReviewCheck` 独立展示问题名称、风险/提醒等级、摘要、明细和影响项数量；默认不直接展示处理动作，避免把每个提醒都表达成必须处理。
  - 与该问题关联的 `FixProposal.sourceCheckCodes` 作为二级内容收在「查看处理建议」下，用户主动点开后才展示。
  - 展开后的信息分两层：`ReviewCheck.suggestedAction` 作为「处理方向」，说明用户可以从哪类取舍入手；`FixProposal` 作为「可选处理」，只展示系统已经形成的可预览或可确认实施方案。
  - 前端不展示 `ready/preview_only/blocked/info/empty` 这类 proposal 状态标签。可执行项靠「处理前预览」和「立即执行」按钮表达；不能直接执行的项只说明影响、取舍和下一步，不额外贴“需要判断/仅供参考”等状态。
  - `ready` proposal 在二级内容中显示「处理前预览」和「立即执行」，点击后仍走 `fix-proposals/apply` 的版本、stale、status、strategy 白名单校验。
  - `preview_only` 只展示预览、取舍和影响，不提供落盘入口。
  - `blocked` 不展示 `blocked`、dry-run、验证失败、版本保护等系统状态；只转译成用户能理解的影响和下一步，例如“当前没有合适的一进一出替换方案，建议先看受影响志愿再手动调整”。
  - `info` 只展示提醒内容，不提供执行按钮。
  - 没有关联 proposal 的问题默认只展示审查发现；如果有 `suggestedAction`，也放在「查看处理建议」下。
  - 没有挂到具体审查项的 proposal 统一收在「其他需要关注的问题」下，并同样通过「查看处理建议」二级展开，不直接铺开处理卡。
- 弹窗底部「重新审查」始终重新执行 `review-workflow/run`，不会只重新生成修复建议，避免用户以为审查结果也刷新了。
- 应用修复后弹窗展示最近一次 `RepairReport`，并重新拉取工作台状态和 proposal，确保前端审查结果、工作台方案和修复状态同步。
- 用户侧措辞统一为“处理建议”“可选处理”“处理前预览”“立即执行”“最近一次处理结果”。前端不直接展示“硬约束”“修复建议”“暂不可用”“预览验证未通过”“不能直接应用”等系统化语言；`hard_constraints` 这类内部 scope 在用户侧转译为“已确认的筛选条件或报考要求让范围变窄”，引导用户调整筛选或报考要求后重新审查。
- 用户侧最终只展示几类结果，不展示内部状态名：审查进行中、当前没有需要处理的问题、可立即执行的处理建议、有预览但暂不直接执行的取舍建议、暂时没有稳妥处理方案的原因说明、只读提醒、最近一次处理结果。
- 候选不足不再使用单一泛化文案。前端按 `candidateShortages.scope/reasonCode/sourceCheckCode` 转译：冲稳保配比不足说明目标区间候选或可替换方案不足；梯度断层说明缺少断层中间候选；数量多于要求时提示精简；部分专业组内稳妥性不足时说明哪些可处理、哪些暂时没有合适补位，不再展示“人工确认”“组内安全垫”等系统化说法。
- 审查结果新增 `ReviewCheck.reasonCode`，用于表达审查命中的结构化原因，不从中文 `summary/detail` 反推。当前覆盖：
  - 数量校验：`count_missing`、`count_over_limit`。`count_over_limit` 会在 fix proposal 中映射为 `candidateShortages.scope=current_plan/reasonCode=count_over_limit`，前端展示为“当前方案数量高于要求，需要精简”，不再误说成候选池不足。
  - 冲稳保配比：`protect_tier_missing`、`sprint_tier_missing`、`sprint_tier_over_limit`。修复建议按 reasonCode 决定目标区间和建议类型，避免继续通过“冲区占比过高/保区占比过低”等中文文案判断。
- `count_validation` 规则 label 改为中性的“数量校验”。“数量不足/数量超出”由 `ReviewCheck.reasonCode` 和 `summary/detail` 展示，避免数量超出时仍显示“数量缺口”。

当前产品边界：

- 修复入口必须挂在具体审查问题或后端 proposal 下，不能再独立放一个不知道针对什么问题的「修复建议」按钮。
- 结构性策略 `rebalance_tier_ratio`、`fill_probability_gap` 仍保持只读预览；前端只披露换出/换入和取舍，不提供确认修复。
- 专业模式和专业组模式都只消费后端返回的 unit/volunteer 计数与 pair，不在前端自行推断“换的是专业组还是组内专业”。
- 前端不调用旧 `compensation/preview` / `compensation/apply`；旧补偿对外入口已删除，补齐素材只在 Java 内部生成 `FixProposal` 时复用。

### 5.8 初始方案生成阶段的结构性规划

当前初始化方案生成不是简单按推荐系数取前 N 个。后端已经在 `buildInitialRecommendationState` 内做了一些局部结构修复：

- 按目标冲/稳/保数量从候选池选取。
- 对数量缺口做补齐。
- 对低分段或安全垫不足做本省保底修复。
- 对录取率倒挂做替换修复。
- 对录取率梯度断层做 gap fill 修复。
- 对冲稳保比例做 rebalance。
- 专业组模式下会评估专业组代表项质量，并关注组内是否有安全专业。

但这套逻辑目前仍是初始化推荐内部的选择策略，不是统一的 review/repair 协议：

- 结构修复规则没有和 `runReview()` 的规则目录完全统一。
- 修复动作只记录为 reason code、repair count、unresolved rule code，不形成可解释的 tradeoff report。
- 用户看不到为了降低风险移除了哪些高推荐系数、强意向或高层次机会。
- 结构性修复失败时，只能通过 unresolved rule code 间接体现，不能清楚说明是候选不足、约束太强，还是策略选择不允许牺牲某些维度。

3.1.0 需要把「初始生成」纳入同一套规划框架，而不是只在生成后做事后审查。

建议新增 `InitialPlanStrategyReport`：

- `targetProfile`：目标数量、冲稳保目标、本省保底目标、专业组内安全目标。
- `objectiveWeights`：推荐系数、录取安全、意向匹配、院校层次、专业热度、地域/费用约束等权重。
- `selectedSummary`：最终选入项统计。
- `tradeoffs`：为了修复某个风险，替换/放弃了哪些高分项或意向命中项。
- `appliedStructuralRepairs`：生成阶段已经处理的问题。
- `unresolvedRisks`：生成阶段无法解决的问题。
- `candidateShortages`：候选不足或约束冲突。
- `needsUserAttention`：需要用户关注的问题，用于概览和对话解释。

2026-06-10 第一阶段已落地：

- 后端新增 `InitialPlanStrategyReportDTO.candidateShortages`，复用 `CandidateShortageDTO` 结构描述初始生成阶段未解决的数量缺口、冲稳保缺口、本省/保底安全垫不足、录取率断层、录取率倒挂和专业组内安全垫不足。
- 后端新增 `InitialPlanStrategyReportDTO.tradeoffs`，并在 `AppliedRepair.tradeoffSummary` 中同步一条面向用户的取舍摘要。当前先覆盖生成阶段自动替换类修复，例如为了缓解录取率梯度断层，把高风险/低改善价值候选替换成中间录取率候选时，会记录换出、换入、收益、代价和指标变化。
- 后端新增 `InitialPlanStrategyReportDTO.objectiveWeights`，用于披露初始生成阶段当前实际平衡的目标：冲稳保结构、偏好/专家优选、录取安全和梯度、发展前景、推荐系数、本省保底，以及专业组模式下的组内安全专业。该字段是相对目标优先级说明，不是新的数学打分权重。
- 后端新增 `InitialPlanStrategyReportDTO.actions`，复用 `FixProposalActionDTO` 的只读动作结构表达生成阶段已经发生的替换，例如 `replace_volunteers + replacementPairs`。这不是可确认、可 apply 的 proposal，只用于让初始生成和审查修复在动作描述层复用同一套字段。
- 该字段只做解释和观测，不参与初始候选选择、排序、review、fix proposal、dry-run 或 apply。
- `tradeoffs` 和 `tradeoffSummary` 同样是只读解释字段，不参与初始候选选择、排序、review、fix proposal、dry-run、apply 或保存编排。
- `objectiveWeights` 同样是只读解释字段，不参与初始候选选择、排序、review、fix proposal、dry-run、apply 或保存编排。
- `actions` 同样是只读解释字段，不参与初始候选选择、排序、review、fix proposal、dry-run、apply 或保存编排。
- 当前 scope 仍按确定性边界保守输出：缺目标候选时使用 `candidate_pool`，有候选但缺少安全一进一出配对时使用 `capacity_or_replacement`，不输出 `current_view` 或 `policy_or_profile_constraints`。
- PC 概览已优先展示生成阶段结构化候选不足说明；没有结构化不足时才回退到未解决风险 detail、第一条取舍摘要或已应用结构修复数量。

生成阶段的目标不是消灭所有风险，而是明确表达权衡：

- 如果降低风险会损失推荐系数，需要让用户知道。
- 如果保底不足是候选池客观不足，需要明确说明不能硬补。
- 如果为了满足硬要求导致冲稳保结构变差，需要在概览中提示。
- 如果保留了高风险但高匹配项，需要说明这是推荐收益和风险之间的选择。

这部分应与 5.3 的 `FixProposal` 共用底层动作模型。区别只是：

- 初始生成阶段可以在系统授权范围内自动应用部分低风险结构修复。
- 高争议 tradeoff 不应静默处理，需要形成提醒或可选 proposal。

### 5.9 概览风险提醒和 stale 触发时机

当前前端概览里的风险提醒主要来自后端 `workflowStatus.reviewStatus` 和 `staleFlags.review`：

- `not_reviewed`：方案尚未审查。
- `stale`：已有审查结果，但方案后来发生变化。
- `has_risk`：审查发现风险。
- `has_warning`：审查有提醒。
- `passed`：审查通过。

后端当前在多数方案变更动作后会设置 `staleFlags.review=true`。本轮已先把重复赋值收口到 `ReviewInvalidationPolicy`，避免继续在每个变更方法里散落维护：

- `markPlanStructureStale()`：方案内容或排序变化后，统一标记 `planAdjustment/review` 过期。
- `markCandidatePoolDependentsStale()`：候选池刷新后，统一标记初始推荐、排序方案、调整建议和审查需要重算。
- `markPreferenceIntentStale()`：软偏好采纳后，统一标记推荐覆盖、初始推荐、排序方案、调整建议和审查需要重算。
- `markConstraintIntentStale()`：硬要求采纳后，额外标记候选池过期。
- `markCandidateViewStale()`：候选筛选视图变化后，只标记初始推荐和调整建议过期，不把审查结果标记为过期。

当前已覆盖的动作包括：

- 工作台方案保存或同步。
- 生成候选池。
- 更新候选筛选视图。
- 移动志愿。
- 移动专业组。
- 删除专业组。
- 排序方案。
- 保存 ordered state。
- 补偿应用后重新生成或复审。

当前需要特别区分两类容易混淆的状态变化：

- 候选筛选视图变化：只代表用户当前在候选面板里看哪个范围，例如筛地域、专业、标签。它会让初始推荐和调整建议待更新，但不改变当前方案事实，也不应让已经审查过的方案显示为“审查待更新”。服务级回归已锁定：`updateCandidateViewState()` 后 `staleFlags.review=false`，工作台 `reviewStatus` 仍按原审查结论显示。
- 方案内容/顺序变化：包括加入、删除、移动、排序、专业组整体移动、专业组删除、工作台方案保存同步等。这些动作会改变审查基准，必须让已有审查结果进入 `reviewStatus=stale` 或待审查状态。服务级回归已锁定：已审查方案执行 `moveOrderedItem()` 后，工作台 `planStatus=pending_review`、`reviewStatus=stale`，原因是 `plan_structure_changed`。

但 3.1.0 仍需要把「为什么需要重新审查」继续细化成可展示、可审计的 reason。当前 `ReviewInvalidationPolicy` 已经统一 stale flags 的触发语义，并在 `StaleFlagsDTO` / `PlanningWorkflowStatusDTO` 输出基础 `reasonCode/message/affectedReviewCodes`；后续还需要继续补全事件模型和精确 affected review codes。

当前 `staleFlags.reasonCode/message` 仍是多个待更新状态共享的原因字段，不是单独的审查原因字段。前端和 Agent 在展示审查 stale 时必须以 `workflowStatus.reviewStatus=stale` 或 `staleFlags.review=true` 为准，再读取 reason；不能只因为 `reasonCode=candidate_view_changed` 就把审查提示成待更新。后续如果要同时展示“推荐待更新原因”和“审查待更新原因”，需要拆分为更细的 `reviewReason`、`planAdjustmentReason`、`recommendationReason` 或引入 `PlanningMutationEvent` 事件模型。

当前 `ReviewInvalidationPolicy` 的目标规则：

| 变更类型 | 是否 stale review | 原因 |
| --- | --- | --- |
| 新生成候选池 | 是 | 候选基础变了，所有审查需重算 |
| 初始方案生成 | 是，随后可自动 runReview | 方案内容新生成 |
| 添加/删除/替换志愿 | 是 | 数量、结构、风险项可能变化 |
| 移动/排序志愿 | 是 | 倒挂、梯度、顺序风险可能变化 |
| 专业组内专业调整 | 是 | 组内安全垫和意向匹配可能变化 |
| 只改展开/折叠/UI 状态 | 否 | 不影响方案事实 |
| 导出 | 否 | 只记录行为，不改变方案 |
| 意向/要求采纳 | 是，至少 planAdjustment/recommendation stale | 推荐系数和方案检查参考变化 |
| 政策/说明类对话 | 否 | 不改变方案事实 |

同时要明确概览显示策略：

- 如果 `reviewStatus=stale`，概览不能继续强调旧风险结论是当前事实，只能提示「方案已调整，建议重新审查」。
- 如果刚生成方案后自动复审成功，概览显示最新风险/提醒。
- 如果自动复审失败，概览显示「审查暂未完成」，并保留重新审查入口。
- 如果有 `InitialPlanStrategyReport.unresolvedRisks`，即使还没 full review，也应在概览中展示为「生成阶段需要关注的问题」，但要区分它不是完整审查结果。

3.1.0 还需要统一前端刷新行为：

- 用户手动移动/删除/排序后，工作台应立即看到 `reviewStatus=stale` 或相应 pending review 状态。
- 点击「审查」后刷新为最新 `has_risk/has_warning/passed`。
- 对话侧应用方案动作后，也应刷新同一份 workspace state，不能有对话显示已复审、工作台仍显示旧提醒的情况。

## 6. 典型场景

### 6.1 只读审查

用户：这份方案稳不稳？

预期：

- 运行审查。
- 返回风险数量、核心问题和代表例子。
- 不自动改方案。
- 如果有可修复项，提示可以查看修复建议。

### 6.2 处理条目型风险

用户：太贵的先去掉。

预期：

- 定位 `high_tuition` 审查问题。
- 生成 `remove_risk_items` 或 `replace_risk_items` proposal。
- 披露命中总量和代表项。
- 用户确认后执行。
- 执行后复审高收费问题是否消失或减少。

### 6.3 结构性调稳

用户：这版太冲了，帮我调稳点。

预期：

- 运行或读取最新审查。
- 命中 `ratio_distribution`、`safety_guard`、`probability_gap` 等结构问题。
- 生成综合 proposal：减少高风险项、补稳/保项、必要时重排。
- dry run 说明候选是否足够。
- 若候选不足，返回 `cannot_satisfy`，说明是分数段/候选池限制，不空泛承诺。

### 6.4 专业组组内风险

用户：专业组里托底专业合理吗？

预期：

- 运行专业组内部审查，包括 `group_inner_safety_guard`。
- 区分专业组整体录取率和组内专业录取率。
- 如果只是问情况，返回分析。
- 如果要求调整，生成组内专业层面的 proposal，不能误删整个专业组。

### 6.5 外部系统触发

外部系统：用户完成一次自动生成方案后，触发审查和修复建议生成。

预期：

- 外部调用 workflow run。
- 系统返回 reviewId 和 proposal 列表。
- 外部可以展示给用户确认，或在授权范围内调用 apply。
- 应用后可拉取 repair report。

### 6.6 初始方案生成后的取舍说明

用户：生成一版方案。

预期：

- 生成候选池和初始方案。
- 同步生成 `InitialPlanStrategyReport`。
- 告诉用户这版方案大体满足哪些目标，例如数量、冲稳保、保底、本省安全垫。
- 如果系统为了降低风险替换了高推荐项，需要说明「为了补保底/拉平梯度，牺牲了部分推荐系数或院校层次」。
- 如果仍有风险未解决，需要以「需要关注」形式披露，而不是让用户误以为初始方案天然无风险。

### 6.7 人工移动后概览风险变 stale

用户在工作台把第 20 个志愿移到第 3 位。

预期：

- 后端将 `staleFlags.review=true`。
- 前端概览风险提醒切换为「方案已调整，建议重新审查」。
- 旧审查问题可以保留在详情里，但需要标记为基于旧版本。
- 用户点击审查后重新计算概率倒挂、梯度断层和结构风险。

### 6.8 复合方案调整

用户：只保留临床医学，其他专业先不要。

预期：

- Agent 输出 `PlanGoal(goalType=only_keep_scope)`，正向范围是临床医学。
- 系统先解析实体，确认是标准具体专业、专业类还是招生计划展示专业。
- 当前方案中命中临床医学的项不能被移除。
- 当前方案中非临床医学项可以进入移出预览。
- 如果移出后数量不足，系统从候选池查找临床医学补入项；没有候选时说明当前候选池范围内不足。
- 预览中明确“确认前不会改方案”。
- 用户确认后，写入报考要求，并执行当前方案变更；执行后复审。

用户：方案里必须有临床医学，其他先保留。

预期：

- Agent 输出 `PlanGoal(goalType=must_include_scope)`。
- 当前方案已有临床医学时，只写入报考要求，不生成删除其他方向的动作。
- 当前方案没有临床医学时，生成补入或替换预览。
- 候选不足时返回无法满足原因，不误删其他专业。

用户：不要中外合作，省内优先，保底多一点。

预期：

- Agent 输出 `PlanGoal(goalType=mixed_adjustment)`。
- 拆成风险处理、地域偏好/要求承接、结构调稳三个子目标。
- 风险处理优先复用 `replace_risk_items/remove_risk_items`。
- 结构调稳复用 `rebalance_tier_ratio/add_safety_items/fill_missing_count`，但当前未开放自动 apply 的结构策略只给预览。
- 预览披露取舍，不承诺一次性全部修好。

### 6.9 专业实体歧义

用户：不想学工商管理。

预期：

- 系统默认按标准具体专业“工商管理”理解。
- 如果当前方案中有“工商管理类（含工商管理、市场营销、人力资源管理）”这类招生计划展示专业类，必须在预览中说明：
  - 确定命中的具体专业有哪些。
  - 哪些是包含工商管理的专业类。
  - 是否要把这些专业类也一起处理，需要用户确认。
- 不能静默扩大为排除整个工商管理类。
- 如果用户明确补充“这一类都不要”，才扩大到专业类。

## 7. 与 3.0.3 的关系

3.0.3 保留：

- pending confirmation 主协议。
- 高副作用动作 preview/confirm/apply。
- 软偏好和硬要求区分。
- Agent 质量评估和对话回归框架。
- 现有审查、补偿、方案动作能力。

3.1.0 新增/升级：

- 后端权威审查规则目录。
- ReviewResult 可修复性和证据模型。
- 统一 FixProposal / RepairReport。
- 初始方案生成阶段的结构性规划报告。
- plan adjustment apply 的重新定义或废弃。
- compensation 纳入 repair strategy。
- 统一 ReviewInvalidationPolicy 和概览风险 stale 语义。
- 外部稳定 review workflow 接口。
- 前端审查修复交互。
- 用户复合方案调整计划：`PlanGoal -> CompositePlanProposal -> PendingConfirmation -> Apply -> Review`。
- 专业实体歧义披露，特别是具体专业、专业类、门类和招生计划展示专业类的边界。
- 审查后修复的端到端回归用例。

### 7.1 与当前实现框架的整合边界

复合方案调整不新增一套独立执行链。统一整合如下：

| 层 | 现有机制 | 复合计划如何接入 |
| --- | --- | --- |
| Agent 理解 | `collect_plan_context_inputs -> plan_next_action` | `plan_next_action` 输出 `PlanGoal`、实体解析、原子动作计划和可行性 |
| 方案预览 | `execute_plan_action(stage=preview)`、`FixProposal` dry-run | 复合计划先执行 dry-run，不落盘 |
| 确认协议 | 3.0.3 `PendingConfirmation` | 复合计划作为一个 pending 确认单元，短文本确认仍只消费 active pending |
| 方案执行 | `execute_plan_action(stage=apply)`、`fix-proposals/apply` | 原子动作按白名单和版本保护执行 |
| 意向/要求写入 | `apply_selected_intents`、`constraintState` | 复合计划中的 `intentUpdates` 确认后同步写入 |
| 审查复验 | `runReview`、`RepairReport` | 执行后必须复审或执行 source check 验证 |
| 刷新联动 | 现有 stale / refresh 逻辑 | 不重新定义刷新；沿用当前方案、推荐系数和工作台刷新规则 |

不做的事：

- 不在旧 `plan-adjustment/apply`、旧 `compensation/apply` 或旧 Agent registry 中继续扩展复合逻辑。
- 不让前端根据文案自行拼复合动作。
- 不把模型自然语言回复作为执行依据。
- 不把 `only_keep` / `must_have` 写成独立旁路。

## 8. P0 / P1 建议

### P0

- 定义 `ReviewRuleRegistry` 和审查问题分类。
- 扩展 review result，至少补齐 `scopeKind/fixability/supportedFixStrategies/evidence/sampleTargets`。
- 定义统一 `FixProposal`。
- 定义 `InitialPlanStrategyReport`，披露生成阶段已处理和未解决的结构风险。
- 定义 `ReviewInvalidationPolicy`，统一方案变化后的审查 stale 行为。
- 将 `compensation`、条目删除/替换、重排纳入 proposal。
- `plan-adjustment/apply` 已按废弃处理；后续只清理残留文档和潜在外部调用。
- `group_inner_safety_guard` 已进入正式 `runReview()`；旧 `analyzePlanAdjustment()` 暂不扩大暴露面。
- 新增外部 workflow 最小接口：run review + generate proposals + apply proposal + report。
- 定义 `PlanGoal` / `CompositePlanProposal` schema 和复合预览确认协议。
- 补齐专业实体消歧协议，至少覆盖具体专业、专业类、门类、招生计划展示专业类。
- 增加端到端回归：专业模式、专业组模式、条目风险、结构风险、初始生成 tradeoff、review stale、候选不足、外部触发。
- 增加复合方案调整回归：`only_keep_scope`、`must_include_scope`、`exclude_scope`、`mixed_adjustment`。

### P1

- 前端审查修复详情面板。
- 修复 proposal 多方案比较。
- 异步任务和进度事件。
- 官方政策/招生章程风险与审查规则结合。
- 审查规则配置化和版本化。
- 外部系统 webhook/callback。
- 更丰富的模型结构化评估集，覆盖真实用户口语化、多目标、简称、反复修正和歧义确认。

## 9. 落地模块设计

### 9.1 Backend: ReviewRuleRegistry

后端需要成为审查规则和修复能力的 source of truth。建议新增 `ReviewRuleRegistry`，先用代码内 registry 起步，后续再考虑配置化。

规则定义建议：

```json
{
  "code": "probability_gap",
  "label": "录取率梯度断层",
  "category": "structure_risk",
  "severityDefault": "warn",
  "targetModes": ["major", "major_group"],
  "scopeKind": "structure",
  "fixability": "preview_fixable",
  "supportedFixStrategies": ["fill_probability_gap", "replace_risk_items", "rebalance_tier_ratio"],
  "defaultFixStrategy": "fill_probability_gap",
  "requiresConfirmation": true,
  "evidenceSchema": "probability_gap_v1",
  "postApplyValidationRule": "probability_gap"
}
```

迁移方式：

- 第一阶段：保留现有 `reviewXXX` 方法，把 code/label/category/fixability 从 registry 读取。
- 第二阶段：`ReviewCheckDTO` 增加 registry 派生字段，Agent 和前端不再各自维护 label 和分类。
- 第三阶段：新增规则必须先注册，再接入 `runReview()` 和 proposal 生成。

### 9.2 Backend: InitialPlanStrategyReport

初始方案生成需要输出结构化策略报告，避免用户只看到结果但不知道系统做了什么取舍。

建议挂在 `PlanningStateDTO.initialRecommendationState.strategyReport` 或独立 `initialPlanStrategyState` 下。

核心字段：

- `targetProfile`：目标数量、冲稳保目标、本省保底目标、专业组内安全目标。
- `objectiveWeights`：推荐系数、安全性、意向匹配、院校层次、专业热度、地域/费用等权重。
- `appliedRepairs`：生成阶段实际执行的结构修复。
- `tradeoffs`：被替换/放弃的高分项和原因。
- `unresolvedRisks`：生成阶段无法解决的规则。
- `candidateShortages`：候选不足或约束冲突说明。
- `userAttentionMessages`：概览和对话可直接使用的用户侧提醒。

当前已有的 `gapFixCount/unresolvedGapCount/appliedRepairCount/unresolvedRuleCodes/reasonCodes` 可以作为迁移起点，但需要补足被替换对象、替换原因和影响指标。

2026-06-10 进展：

- `InitialPlanStrategyReportDTO` 已挂在 `InitialRecommendationStateDTO.strategyReport`，并随 `PlanningWorkspaceStateRes.initialRecommendationState` 返回。
- `objectiveWeights` 已补第一阶段目标说明，按当前规则优先级输出 `code/label/relativeWeight/priority/description`。由于初始推荐当前不是加权求和算法，`relativeWeight` 只用于解释相对关注度，不作为排序输入。
- `appliedRepairs` 已记录生成阶段执行的结构替换，包括 `ruleCode/actionType/reasonCode/from/to/detail`。
- `actions` 已复用 `FixProposalActionDTO` 结构描述生成阶段已执行替换，当前主要输出 `replace_volunteers`、`removeVolunteerIds`、`candidateVolunteerIds`、`removeUnitIds`、`candidateUnitIds` 和 `replacementPairs`。该列表只读返回，不生成 `FixProposalDTO`，也不能进入 `fix-proposals/apply`。
- `tradeoffs` 已记录生成阶段替换产生的取舍，包括 `ruleCode/actionType/reasonCode/from/to`、推荐系数/录取率/热度/院校排名变化、偏好升级或降级、`gains/costs` 和用户侧 `summary`。
- `appliedRepairs.tradeoffSummary` 会复用同一条取舍摘要，便于前端在轻量概览里展示，不需要自行拼接 from/to 和指标变化。
- `candidateShortages` 已补齐第一阶段结构化不足说明，来源于初始生成确定性状态和未解决规则，不从模型或用户自然语言猜测。
- 前端类型 `PlanningInitialPlanStrategyReport` 已补 `objectiveWeights`、`actions`、`candidateShortages?: PlanningCandidateShortage[]` 和 `tradeoffs`，工作台概览优先使用候选不足，其次使用未解决风险或取舍摘要。
- 当前 tradeoff 仍只覆盖初始生成阶段已发生的自动替换，不改变选择结果，也不和后续 `FixProposal` 共享 action model。
- 尚未完成：真正的多目标权重配置化、更多非替换类取舍量化，以及与后续 `FixProposal` 的统一 action model 复用。

### 9.3 Backend: FixProposal

新增统一 proposal 生成服务：

```text
ReviewState + PlanningState + CandidatePool + UserIntent/Constraints
  -> FixProposalService.generate(...)
  -> FixProposal[]
```

proposal 类型：

- `remove_risk_items`
- `replace_risk_items`
- `fill_missing_count`
- `add_safety_items`
- `rebalance_tier_ratio`
- `fill_probability_gap`
- `sort_by_probability`
- `adjust_major_group_inner_safety`
- `regenerate_plan_with_constraints`
- `cannot_satisfy`
- `no_op`

每个 proposal 必须包含：

- source review version。
- source check codes。
- 具体 actions。
- dry run result。
- 影响范围。
- 预计改善。
- 预计损失。
- 是否需要确认。

现有 `CompensationActionDTO` 和 `PlanAdjustmentSuggestionDTO` 不直接删除，先作为 proposal action 的来源之一；但新接口不再让外部直接拼这些低层对象。

### 9.4 Backend: Repair Apply And Report

新增统一 apply 服务：

```text
FixProposal -> version guard -> apply actions -> refresh state -> validate -> RepairReport
```

必须处理：

- proposal 过期。
- 当前方案已变更。
- 候选已失效。
- 应用过程中部分成功/失败。
- 应用后产生新风险。
- 专业模式和专业组模式不同粒度。

`RepairReport` 要成为外部系统和前端共同消费的结果对象，而不是只靠聊天回复。

### 9.5 Backend: ReviewInvalidationPolicy

把 `staleFlags.review=true` 从分散赋值升级为显式策略服务：

```text
PlanningMutationEvent -> ReviewInvalidationPolicy.evaluate(...) -> stale flags + reason
```

输出建议：

- `reviewStale`
- `planAdjustmentStale`
- `recommendationOverlayStale`
- `reasonCode`
- `message`
- `affectedReviewCodes`

这样前端概览能解释为什么需要重新审查，而不只是显示一个状态。

### 9.6 Agent Integration

Agent 不应自己发明审查问题分类。3.1.0 后：

- `review_plan` 读取后端增强后的 review result。
- `analyze_adjustment` 已迁移到 `reviewState + fix-proposals/generate` 事实源。
- `preview_fix_proposal` 是 Agent 侧统一修复预览入口；旧 compensation 不再是独立 action family。
- 用户说「修最严重的问题」「太贵的去掉」「调稳」时，Agent 调 workflow proposal，而不是自己拼 action。
- 对话回复只做解释、澄清和确认，不绕开 proposal apply。

当前代码接入状态：

- `review_plan` handler 当前会先调用 `/session/review/run`，再调用 `/session/fix-proposals/generate`，把 proposal 的 `status/strategy/impact/candidateShortages/blockingReason` 归一进回复 facts。
- `analyze_adjustment` handler 当前会触发 `/session/review/run`，再读取 `/session/fix-proposals/generate` 和当前方案事实，用同一套 proposal/status/shortage 信息解释“怎么调”；不再调用旧 `/session/plan-adjustment/analyze`。
- `generate_planning_fix_proposals` 和 `apply_planning_fix_proposal` 已在 Agent workflow tool / internal client 中存在；`apply_planning_fix_proposal` 受 `user_confirmed` 保护，并最终由后端 `RepairProposalApplyPolicy` 做版本、stale、status、strategy 白名单校验。
- ChatAgent 主工具列表当前仍不直接开放 `apply_planning_fix_proposal`；对话侧已通过 `pendingConfirmation(actionFamily=apply_fix_proposal)` 稳定保存 `proposalId/sourceVersionGuard`，确认后由 `ChatService` 内部调用 apply，并在回复中展示 `RepairReport` 的标题、对应问题、增删数量、影响范围和复验结果。
- Agent Python 侧已删除 `preview_planning_compensation/apply_planning_compensation` wrapper，`PlanActionPlan.action_family` 也不再接受 `preview_compensation/apply_compensation`。历史消息里出现旧 action 时只能作为 legacy fallback 被忽略或拒绝，不能生成新的 pending。
- Java 侧仍保留 `compensationPreview` 内部素材，定位为 FixProposal 内部候选/动作来源和旧状态字段；`/session/compensation/*` 对外兼容接口已删除，不作为 Agent、Web 或外部主路径。
- Agent 本地 `review_issue_registry.py` 当前只应作为后端元数据缺失、老会话和测试 fixture 的兜底；主路径优先消费后端 `ReviewCheck` metadata 或 `FixProposal`。

因此，对话侧目前是“模型只读预览，service 受控确认应用”：用户可以在对话里看到处理方向；如果后端 proposal 为 `ready`，会收到确认卡，确认后由 service 应用并刷新工作台。工作台审查结果弹窗仍是同一套 Java proposal 协议的前端入口，两边共享 apply policy。

### 9.7 Frontend Integration

前端至少需要支持：

- 概览风险状态：not reviewed / stale / risk / warning / passed。
- 审查详情入口。
- proposal 列表。
- proposal 确认卡。
- repair report 展示。
- stale 旧审查结果标记。

第一期可以不做复杂大面板，但不能只停留在 tooltip；至少要能让用户看到「这个风险怎么修、修了会损失什么」。

2026-06-11 第一阶段已落地为轻量弹窗：

- 主审查按钮只承接审查/重新审查，不承载查看结果。
- 风险提示图标点击进入同一弹窗，hover 保留摘要，并在 tooltip 内提供「查看详情」文字链。
- 弹窗按 `ReviewCheck -> FixProposal` 分组展示；修复动作不再作为独立入口悬浮在审查结果之外。
- 旧 `pendingActions` 展示分支已删除；前端审查弹窗只消费 `ReviewCheck` 和 Java `FixProposal`。
- 应用 proposal 后展示 `RepairReport` 并刷新工作台状态。

## 10. 完整测试保障

3.1.0 这块需要按层次建立测试保障，避免再次出现「某个 case 修了，别的链路退化」。

### 10.1 后端单元测试

覆盖对象：

- `ReviewRuleRegistry`
- 每个 `reviewXXX` 规则。
- `FixProposalService`
- `ReviewInvalidationPolicy`
- `InitialPlanStrategyReport` 生成。
- `RepairApplyService`

最低要求：

- 每个 review code 至少 1 个 passed case、1 个 failed case。
- 每个 fix strategy 至少 1 个成功 proposal、1 个 `cannot_satisfy`。
- 专业模式和专业组模式分别覆盖。
- 结构风险不能把 `affectedVolunteerIds` 直接当删除范围。
- 条目风险删除/替换后数量和冲稳保不应异常退化。

### 10.2 后端集成测试

按真实 workflow 测：

```text
generate candidate pool
-> generate initial plan
-> run review
-> generate fix proposal
-> apply proposal
-> rerun review
-> assert repair report
```

必须覆盖：

- 高收费替换。
- 中外合作移除/替换。
- 数量不足补齐。
- 保底不足但候选足够。
- 保底不足且候选不足。
- 概率倒挂重排。
- 梯度断层补中间项。
- 冲稳保比例调整。
- 专业组组内安全垫。
- 意向/硬要求导致无法满足。

### 10.3 初始方案生成回归

专门验证生成阶段权衡：

- 高推荐系数优先时结构是否失衡。
- 结构修复是否替换了部分高分候选。
- 替换是否记录 tradeoff。
- `unresolvedRisks` 是否和后续 review 结果一致。
- 专业组内安全专业是否被选入。
- 候选不足时是否给出明确 shortage。

这组测试要比较：

- 生成前候选池分布。
- 初始选择。
- 被替换/放弃项。
- 最终风险。
- 用户可见提醒。

### 10.4 前端状态测试

覆盖：

- 初始未审查。
- 审查通过。
- 审查有风险。
- 人工移动后 stale。
- 点击重新审查后状态恢复。
- proposal pending。
- proposal applied。
- proposal expired。
- repair report 展示。

重点验证概览不要显示旧风险为当前事实。

### 10.5 Agent 对话 E2E

新增 3.1.0 场景集，至少覆盖：

- 「这版稳不稳」
- 「太贵的去掉」
- 「中外合作不要」
- 「这版太冲了，调稳」
- 「保底够不够，不够帮我补」
- 「为什么这几个推荐系数高的没进方案」
- 「生成方案后有什么需要注意」
- 「把最严重的问题修一下」
- 「这个专业组里面托底专业合适吗」
- 「候选不够还能怎么弄」

每个 case 断言：

- 是否调用正确 workflow。
- 是否生成 proposal 或只读 review。
- 是否需要确认。
- 回复是否披露影响和 tradeoff。
- 不能修时是否明确说明原因。
- 不出现空泛建议。

### 10.6 外部接口契约测试

为外部 workflow 接口补契约测试：

- request/response schema。
- version guard。
- proposal 过期。
- external confirmed apply。
- user required confirmation。
- async job 状态。
- report 可追踪。

### 10.7 回归数据集

建议沉淀固定测试数据：

- 专业模式高分段。
- 专业模式低分段候选不足。
- 专业组模式普通组。
- 专业组模式组内安全专业不足。
- 高收费/中外合作密集。
- 强硬地域/专业约束导致候选不足。
- 历史老会话导入。

这批数据需要进入 repo 中的脱敏 fixture，避免只依赖临时 session。

### 10.8 质量门禁

进入 3.1.0 发布前最低门禁：

- 后端 review/repair 单测全通过。
- review workflow 集成测试全通过。
- Agent 3.1.0 review-repair e2e 全通过。
- 旧 3.0.3 对话回归不能退化。
- 前端状态测试覆盖 stale 和 proposal。
- 专业模式、专业组模式至少各完成一轮本地人工走查。
- 外部接口有完整文档和契约测试。

## 11. 待进一步确认的问题

- 哪些审查问题允许系统在用户授权下自动修复，哪些必须人工确认？
- 条目型风险默认是删除，还是优先替换？
- 结构性问题是否允许重新生成整份方案，还是只在现有方案内局部调整？
- 候选不足时，是否允许放宽用户软偏好？是否必须再次确认？
- 是否仍有外部系统调用旧 `plan-adjustment/apply`？当前代码搜索未发现前端或 Agent 主路径依赖，若线上网关日志发现调用，需要迁移到 `fix-proposals/apply`。
- 审查规则是否需要面向运营配置，还是先代码内 registry？
- 外部触发是否需要异步 job 和回调，还是 3.1.0 先同步接口？
- 初始生成阶段哪些结构修复可以静默应用，哪些 tradeoff 必须给用户披露？
- 人工移动/排序后是否立即自动复审，还是只标记 stale 并由用户手动触发？

## 12. 当前落地进展

### 12.1 已完成：ReviewRuleRegistry Phase 1

完成时间：2026-06-08

本阶段只做低风险语义统一，不改变现有审查判定、补偿、调整分析和方案操作行为。

已完成内容：

- 新增后端权威 `ReviewRuleRegistry`。
- 新增 `ReviewRuleMetadataDTO`。
- `ReviewCheckDTO` 增加规则元数据字段：
  - `label`
  - `category`
  - `severityDefault`
  - `targetModes`
  - `scopeKind`
  - `fixability`
  - `supportedFixStrategies`
  - `defaultFixStrategy`
  - `requiresConfirmation`
  - `evidenceSchema`
  - `postApplyValidationRule`
- `PlanAdjustmentRuleResultDTO` 增加规则元数据字段，便于调整分析结果和审查结果使用同一套语义。
- `PlanningStateService.runReview()` 生成审查结果时自动补齐 metadata。
- `PlanningStateService.analyzePlanAdjustment()` 生成 rule result 时自动补齐 metadata。
- `PlanningStateService.getPlanningState()` 读取旧状态时也会补齐 review/adjustment metadata，降低旧会话迁移成本。

当前 registry 已覆盖：

- `ratio_distribution`
- `safety_guard`
- `probability_inversion`
- `probability_gap`
- `count_validation`
- `high_tuition`
- `admission_limit`
- `special_enrollment`
- `edge_score`
- `cooperative_program`
- `major_group_safety_intent_alignment`
- `group_inner_safety_guard`
- `plan_update_notice`
- `adjustment_notice`

### 12.2 验证结果

已跑后端目标测试：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：

- `Tests run: 130`
- `Failures: 0`
- `Errors: 0`
- `Skipped: 3`

补充测试：

- `ReviewRuleRegistryTest` 验证结构风险、信息提示、registry defensive copy。
- `PlanningStateServiceTest` 验证 `runReview()` 输出带 `probability_gap` metadata。
- `PlanningStateServiceTest` 验证 `generateFixProposals()` 能从 `count_validation` 补偿动作生成只读 `fill_missing_count` proposal。
- `PlanningStateServiceTest` 验证条目型风险能从已有 review state 生成 `replace_risk_items` proposal。
- `PlanningStateServiceTest` 验证完整配对的 `replace_risk_items` 可通过 version guard 应用，部分配对仍保持 `preview_only`。
- `PlanningStateServiceTest` 验证 `fill_missing_count` proposal 可通过 version guard 应用。
- `PlanningStateServiceTest` 验证过期 proposal apply 会被 409 拒绝。
- `PlanningStateServiceTest` 验证旧 `plan-adjustment/apply` 返回 410 且不再写入 `pending_apply`。
- `PlanningStateServiceTest` 验证 `remove_risk_items` 在专业组模式下按专业组计数补位，不把组内专业数误当专业组数。
- `PlanningStateSuggestionMappingTest` 验证 `analyzePlanAdjustment()` 输出 rule metadata。

### 12.3 已完成：FixProposal 只读生成 Phase 2

完成时间：2026-06-08

本阶段先打通统一修复 proposal 的只读生成，不执行 apply，不改变现有方案、候选、补偿、审查和调整分析行为。

已完成内容：

- 新增 `FixProposalDTO`、`FixProposalActionDTO`、`FixProposalDryRunResultDTO`、`FixProposalStateDTO`。
- 新增后端内部接口：

```http
POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/fix-proposals/generate?chatSessionId={chatSessionId}
```

- `generateFixProposals()` 会在 review 缺失或 stale 时先触发 `runReview()`，再基于 review checks 和 compensation preview 生成 proposal。
- 当前 proposal 只读返回：
  - `sourceVersion`
  - `sourceReviewVersion`
  - `sourceVersionGuard`
  - `sourceCheckCodes`
  - `strategy`
  - `affectedUnitIds`
  - `affectedVolunteerIds`
  - `actions`
  - `dryRunResult`
  - `requiresConfirmation`
- 已覆盖的可执行映射：
  - `count_validation` + `fill_total_count` action -> `fill_missing_count`
  - `safety_guard` + `add_local_protect` action -> `add_safety_items`
  - `ratio_distribution` + `rebalance_protect_ratio` action -> `rebalance_tier_ratio`
  - `probability_gap` + `fill_probability_gap` action -> `fill_probability_gap`
- 已覆盖的非直接补偿映射：
  - 条目型风险存在 affected ids 时 -> `replace_risk_items`
  - 信息提示型规则 -> `no_op`
  - 没有候选或没有可执行动作 -> `cannot_satisfy`

边界说明：

- 当前 `FixProposal` 生成复用已有 `buildCompensationPreview()`，因此会继承旧补偿容量保护。
- `sourceReviewVersion` 表示审查证据基于哪个方案版本；`sourceVersionGuard` 表示后续 apply 前必须匹配的当前状态版本。
- 例如 `probability_gap` 在方案已满、或剩余容量被数量补齐动作占用时，不会硬生成新增补位动作；这时会返回 blocked/cannot_satisfy，避免向用户承诺无法执行的补位。
- `probability_gap` 的“替换断层边界项”后续需要统一 action 模型支持 remove + add + reorder 的组合动作，放入后续 Phase 3。
- Phase 3 已补充最小 apply 入口，当前支持 `fill_missing_count`、`sort_by_probability` 和受限 `remove_risk_items`；前端和 Agent 仍不应把该接口当作完整风险修复入口。

### 12.4 已完成：FixProposal 最小应用 Phase 3

完成时间：2026-06-08

本阶段先打通低风险、可复验的执行链路。目标是验证新 proposal 协议的版本保护、动作应用和 RepairReport 闭环，不把所有旧补偿/调整能力一次性迁移。

新增内部接口：

```http
POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/fix-proposals/apply?chatSessionId={chatSessionId}
```

请求体：

```json
{
  "proposalId": "fp_xxx",
  "sourceVersionGuard": 12,
  "regenerateOrderedPlan": true,
  "rerunReview": true
}
```

当前行为：

- 必须提供 `proposalId`。
- 必须提供并命中当前 `state.version` 的 `sourceVersionGuard`。
- 当前 review 必须存在且未 stale；执行入口不会在用户点击确认后隐式刷新审查证据。
- 服务端会重新生成当前 proposal 列表，并确认 `proposalId` 仍存在。
- 只允许已接入的 `status=ready` proposal 自动应用。
- 未接入自动应用的策略保留 proposal 信息，但标记为 `status=preview_only` / `dryRunResult.status=preview_only`，用于解释方向，不允许误点击应用。
- 当前已接入自动应用的策略：
  - `fill_missing_count`：复用统一的工作台方案添加、去重、同步和日志逻辑。
  - `sort_by_probability`：复用现有 `sortOrderedPlan(admissionRatio)`，保留专业模式/专业组模式、行为事件和 stale 标记语义。
  - `remove_risk_items`：第一期只支持 registry 默认策略为 remove 的条目型风险，例如 `admission_limit`、`special_enrollment`；执行时先移除命中志愿，再按当前模式补足数量并复验。
  - `adjust_major_group_inner_safety`：专业组模式专用；在同一专业组内补入或替换安全垫专业，执行后重排并复审 `group_inner_safety_guard`。
- apply 返回中新增 `repairReport`：
  - 记录 proposal / strategy / sourceVersion / resultVersion。
  - 记录动作数量、影响专业组/志愿数量、新增/删除数量。
  - 记录执行前后 review risk/warn 数。
  - 记录 `postValidationPassed`，用于判断源审查问题是否已被复验通过。
  - `fill_missing_count`、`sort_by_probability`、`remove_risk_items`、`adjust_major_group_inner_safety` 已有 report/复验测试覆盖。
- 应用动作复用 `RepairApplyMutationBuilder.applyWorkingPlanAdditionActions()` 的工作台方案添加逻辑，避免并行维护两套添加规则。
- 其他 strategy 暂时返回明确错误，不做半自动处理。
- 旧 `plan-adjustment/apply` 已明确退场：服务端返回 410，不再写入 `pending_apply`，避免调用方误以为已真实应用调整。`plan-adjustment/analyze` 仅作为服务端历史/外部兼容只读入口；Python Agent 已删除对应 wrapper。

错误边界：

- `sourceVersionGuard` 不匹配：409，提示重新生成修复建议。
- review 缺失或 stale：409，提示重新生成修复建议。
- proposal 不存在或已失效：404。
- proposal 非 ready：400。
- strategy 暂不支持：400。

仍未完成：

- `replace_risk_items`、`rebalance_tier_ratio`、`fill_probability_gap` 等复合 apply。
- apply 后按 `postApplyValidationRule` 定向复验。
- 独立 `RepairApplyService` 抽取。

条目型风险 apply 边界：

- 旧 `applyPlanAdjustment()` 曾经只把调整状态置为 `pending_apply`，并没有真实执行 remove/replace；当前已改为返回 410，因此新链路不复用该空壳。
- `remove_risk_items` 已完成第一期受限支持：仅处理默认策略就是 remove 的规则；移除后会尝试使用安全候选补足数量。
- 条目型审查会补齐 `affectedVolunteerIds` 和 `affectedUnitIds`，保证 proposal、RepairReport 和前端展示能区分影响志愿数与影响专业组数。
- 默认替换类条目风险已接入受控 apply：只有全部风险志愿都有完整 from/to replacement pair，且 dry-run 复验确认风险志愿全部移除、志愿数量保持不变时，proposal 才保持 `ready` 并允许用户确认应用。
- `replace_risk_items` 当前支持生成多条替换配对：每个风险志愿优先找同层次、风险更低、专业相近、院校层次代价可接受且当前方案未选中的候选；专业组模式还会避免重复引入当前已选专业组。
- 如果只找到部分替换项，proposal 保持 `preview_only`，并在 `dryRunResult.warnings` 中说明未覆盖条目；如果完全找不到替换项，proposal 为 `blocked` 且 `requiresConfirmation=false`。
- 专业模式按志愿条数补位；专业组模式按专业组数量补位，避免把组内专业数量误当成专业组数量。
- 专业组模式回归边界：
  - 删除组内一个风险专业但该专业组仍有其他专业时，不补新专业组。
  - 删除风险专业后导致整个专业组消失时，才按专业组缺口补一个安全候选组。
- `replace_risk_items` 在专业组模式下不会把条目风险的 unit 字段当成整组替换执行语义；unit 信息只用于披露。若替换单个风险专业会导致专业组数量变化，dry-run 会阻断应用，等待后续更完整的整组替换 selector。
- 如果候选不足，`repairReport` 会保留执行结果和复验状态，后续仍需通过审查结果提示用户。
- 高收费、中外合作等默认 replace/用户权衡类风险仍不自动删除，避免把可接受但需确认的志愿误删。

### 12.5 已完成：replace_risk_items 预览配对 Phase 4

完成时间：2026-06-08

本阶段只强化替换类风险的 dry run，不开放自动应用。

已完成：

- `FixProposalActionDTO` 新增替换动作字段：`removeUnitIds`、`removeVolunteerIds`、`candidateUnitIds`、`candidateVolunteerIds`、`replacementPairs`。
- `high_tuition`、`cooperative_program` 等默认替换类风险会生成 `replace_volunteers` action，披露 from/to 配对。
- 多个风险志愿会生成多条配对预览，并避免复用同一个替代志愿；专业组模式会避免复用同一个候选专业组。
- 找不到替换项时保持 `blocked`，不会被后续“未支持自动应用”逻辑覆盖成 `preview_only`。
- 部分可替换、部分不可替换时，通过 `dryRunResult.warnings` 披露未覆盖范围。

验证：

```bash
mvn -Dtest=ReviewRuleRegistryTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：`Tests run: 132, Failures: 0, Errors: 0, Skipped: 3`。

### 12.6 已完成：后端规则目录接口 Phase 5

完成时间：2026-06-08

背景：

- Agent 本地 `review_issue_registry.py` 仍维护一份规则目录。
- 这份本地目录已经与后端新 `ReviewRuleRegistry` 出现策略冲突：例如 `high_tuition`、`cooperative_program` 在后端是默认 `replace_risk_items`，属于需要用户权衡的替换/提醒类风险；Agent 本地仍默认映射到 `remove_units`，容易把“处理风险”引导成直接删除。
- 按 3.1.0 原则，规则语义应由后端统一维护，Agent 和前端只消费 metadata 或 `FixProposal`。

已完成：

- 新增只读接口：

```http
GET /gaotu-assistant-bot/inner/planning/{tenantId}/review/rules
```

- 返回 `List<ReviewRuleMetadataDTO>`，包含 `code`、`label`、`category`、`scopeKind`、`fixability`、`supportedFixStrategies`、`defaultFixStrategy`、`requiresConfirmation`、`evidenceSchema`、`postApplyValidationRule`。
- Agent internal client 新增 `list_planning_review_rules()`，作为后续迁移前置能力。
- `ReviewRuleRegistryTest` 增加 list 验证，锁定高收费默认策略为 `replace_risk_items`。

当前边界：

- 本阶段没有切换 Agent resolver 主路径，避免在未完成对话回归前改变所有审查修复路由。
- 后续迁移时，Agent 不应继续从本地 registry 推断默认 action，而应优先读取后端 metadata 或直接调用 `fix-proposals/generate`。

### 12.7 已完成：Agent FixProposal 消费前置能力 Phase 6

完成时间：2026-06-08

已完成：

- Agent internal client 新增：
  - `generate_planning_fix_proposals(tenant_id, chat_session_id)`
  - `apply_planning_fix_proposal(tenant_id, chat_session_id, proposal_id, source_version_guard, regenerate_ordered_plan, rerun_review)`
- Agent workflow tool 新增只读预览包装：
  - `generate_planning_fix_proposals(ctx)`
  - 会展示 proposal 数量、状态、预计移除/补入数量、warnings、blocked reason。
- Agent workflow tool 新增受确认保护的应用包装：
  - `apply_planning_fix_proposal(ctx, proposal_id, source_version_guard, user_confirmed, ...)`
  - 未确认时不会调用后端。
  - 成功后格式化 `RepairReport`，披露新增/删除数量和复验结果。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py -q
```

结果：`32 passed`。

当前边界：

- 后续阶段已把 ChatAgent 只读修复预览切到 `preview_fix_proposal` / `fix-proposals/generate`。
- `preview_compensation/apply_compensation` 已从 Agent action family 和 Python wrapper 中退场；纯补齐、补保底、梯度断层等诉求统一由后端 `FixProposal` strategy 披露。
- `analyze_adjustment` 仍作为只读结构分析兜底；Agent 本地 `review_issue_registry.py` 仍用于老会话、测试 fixture 或后端元数据缺失时的降级。

### 12.8 已完成：Agent 审查/调整只读主路径消费 FixProposal Phase 7

完成时间：2026-06-08

背景：

- Phase 6 只新增了 Agent 调用 `fix-proposals/generate/apply` 的工具包装；后续 Phase 已把 ChatAgent 只读修复预览收口到 `review_plan`、`analyze_adjustment`、`preview_fix_proposal` 和后端 `FixProposal` facts。
- 本地 registry 旧语义曾把 `high_tuition`、`cooperative_program` 映射为 `remove_units`，会把“处理高收费/中外合作”误导为整批删除。
- 这类风险本质上是用户权衡类风险：可能需要替换、保留提醒或明确删除，不应默认删除。

已完成：

- Agent `review_plan` 和 `analyze_adjustment` handler 已读取后端 `fix-proposals/generate`，并把归一化后的 `fix_proposals` 写入 `facts`。
- 只读审查回复新增“可处理方向”，披露 proposal 的 `status`、`strategy`、预计移出/补入数量、warnings、blocking reason。
- `review_plan` / `analyze_adjustment` 的 `reply_focus` 增加 `fix_proposals`，提示最终回复优先按后端修复建议解释，不再只靠本地旧规则。
- Agent 本地 `review_issue_registry.py` 纠偏：
  - 新增 `item_replacement` scope。
  - `high_tuition`、`cooperative_program` 改为 `item_replacement`。
  - 本地默认 action 从 `remove_units` 改为 `review_plan`，真正替换策略由后端 `replace_risk_items` proposal 披露。
  - 支持动作顺序保留为 `replace_units`、`remove_units`，但只有用户明确要求替换/删除时才进入具体动作预览。
- `plan_next_action` 对 `item_replacement` 的处理：
  - “处理/解决高收费”这类泛化请求不再默认删除，回到 `review_plan`。
  - “去掉/删除/移出高收费”仍可生成 `remove_units` 预览。
  - “替换/换成正常收费”仍可生成 `replace_units` 预览，但需要明确替换范围或后端 proposal 支撑。
- `execute_plan_action` 增加替换优先保护：
  - 对 `item_replacement` 的无范围替换请求，不再自动降级为整批删除。
  - 回复会提示先补充替换范围或查看修复预览，确认前不改动方案。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py tests/unit/test_plan_context_tool.py tests/unit/test_action_resolver.py tests/regression/test_keyword_matchers.py tests/unit/test_plan_orchestration_tool.py tests/integration/test_full_plan_flow.py -q
```

结果：`355 passed`。

当前边界：

- ChatAgent 工具列表仍未直接开放 `apply_planning_fix_proposal` 主链路；避免没有前端 proposal 确认卡和 proposal_id 状态管理时误触发自动修复。
- 本地 `review_issue_registry.py` 仍作为兼容层存在；后续应继续收敛到后端 `/review/rules` metadata 或 `fix-proposals/generate`。
- `replace_risk_items` 后端完整配对场景已可由 `fix-proposals/apply` 应用；Agent 侧仍不直接绕过前端确认卡触发 apply。
- 旧 `planAdjustment/analyze` 仍只做分析；`group_inner_safety_guard` 的正式应用已收敛到 `fix-proposals/apply`。

### 12.9 当前剩余边界

以下仍是后续阶段，不属于本次已落地范围：

- 独立 `FixProposalService` 抽取：当前先落在 `PlanningStateService`，后续应迁出，避免继续扩大单类复杂度。
- `RepairApplyService`
- `RepairReport` 完整化：当前已具备最小执行报告，后续需要补齐更细的 tradeoff、失败分项和审查规则级复验。
- `InitialPlanStrategyReport`
- Agent 从本地 `review_issue_registry.py` 彻底迁移到后端 metadata 或 `FixProposal`：当前已优先消费后端元数据，但本地 registry 仍作为老会话、测试 fixture 和后端缺字段时的兼容兜底。
- 前端审查修复详情和 proposal 确认入口。
- 外部 review workflow 接口。

### 12.10 已完成：Agent 审查问题元数据优先后端 Phase 8

完成时间：2026-06-08

背景：

- Phase 7 已让 `review_plan` / `analyze_adjustment` 读取后端 `fix-proposals/generate`，但 Agent `PlanContextInputs.review_issues` 和 `ActionResolver` 仍可能从本地 `review_issue_registry.py` 解释审查 code。
- 这会造成两类风险：
  - 后端新增或调整规则后，Agent 仍按旧本地分类决定 action。
  - 同一个 code 在审查回复、plan_next_action 和 execute_plan_action 中被不同来源解释。

已完成：

- `ReviewCheckDTO` 已返回的后端元数据成为 Agent 审查问题分类的优先来源：
  - `scopeKind`
  - `fixability`
  - `supportedFixStrategies`
  - `defaultFixStrategy`
  - `requiresConfirmation`
  - `evidenceSchema`
  - `postApplyValidationRule`
- `build_review_issue_scopes()` 现在会把后端元数据归一为 Agent 侧 action 语义：
  - `scopeKind=item + defaultFixStrategy=replace_risk_items` -> `item_replacement`
  - `replace_risk_items` -> 默认 `review_plan`，由 FixProposal 披露替换预览。
  - `remove_risk_items` -> `remove_units`
  - `fill_missing_count` / `add_safety_items` / `fill_probability_gap` -> `preview_fix_proposal`
  - `sort_by_probability` -> `sort_ordered_plan`
  - `rebalance_tier_ratio` / `adjust_major_group_inner_safety` -> `analyze_adjustment`
- `ActionResolver` 在已有 `review_issue_code` 时，优先读取 `PlanContextInputs.review_issues` 中的后端元数据，再决定是否覆盖 action。
- 本地 `review_issue_registry.py` 仍保留，但定位降级为老会话缺字段、测试 fixture、后端元数据缺失时的兼容兜底。
- 没有把自然语言关键词匹配作为主路径；本阶段只处理已经结构化出来的 `review_issue_code`。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_instructions.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_planning_workflow_tool.py tests/e2e/test_internal_client.py tests/unit/test_config.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_context_tool.py tests/unit/test_action_resolver.py tests/regression/test_keyword_matchers.py tests/unit/test_plan_orchestration_tool.py tests/integration/test_full_plan_flow.py -q
```

结果：`445 passed, 2 skipped`。

当前边界：

- `review_issue_registry.py` 尚未删除，因为老会话缺少后端元数据、部分测试 fixture 和无后端上下文的 resolver 单测仍需要兜底。
- ChatAgent 主路径仍不直接开放 `fix-proposals/apply`；应用 proposal 仍需要后续前端确认卡、proposal_id 状态管理和 apply 后复验展示。
- Agent action family 已移除 `preview_compensation/apply_compensation`；Java `compensationPreview` 只作为 reviewState/FixProposal 内部素材和旧状态兼容字段保留；旧 compensation 对外接口已删除。

旧补偿链路当前状态：

| 能力 | 当前入口 | 仍保留的原因 | 不能再承接的能力 | 退场方向 |
| --- | --- | --- | --- | --- |
| 补齐素材 | Java reviewState `compensationPreview` / `buildCompensationPreview()` | `generateFixProposals()` 内部仍会复用补齐候选和结构动作素材；旧状态也可能携带该字段 | Agent、Web、外部不再直接规划或调用；不能作为完整审查修复协议，也不能生成 pending | 仅保留为 Java 内部 helper/旧字段；用户侧统一通过 `preview_fix_proposal` / `fix-proposals/generate` 看处理建议 |
| 补齐应用 | `FixProposal` apply 分支内部复用补齐动作执行能力 | `fill_missing_count` 等 ready proposal 需要落盘时复用同一套工作台添加、同步和日志能力 | 不再有独立 `/session/compensation/apply` 对外路由；不允许绕过 `RepairProposalApplyPolicy` | 对话和前端统一走 `fix-proposals/apply` |
| 调整分析 | Agent `analyze_adjustment` -> `review/run + fix-proposals/generate` | 只读解释当前审查问题、可处理方向、候选不足和需要用户取舍的边界 | 不落盘、不生成可确认修复任务、不替代 dry-run | 已统一消费 `ReviewState + FixProposalState`；服务端旧 `plan-adjustment/analyze` 仅兼容保留 |

这意味着 Agent 当前不会再规划 `preview_compensation` / `apply_compensation`。补齐数量、补保底、梯度断层、安全垫等诉求统一进入 `preview_fix_proposal`，由后端 `FixProposal` 披露 `fill_missing_count/add_safety_items/fill_probability_gap` 等 strategy 的可处理性、候选不足和阻塞原因。

Agent 本地审查 issue fallback 对齐：

- 背景：正常链路应优先消费后端 `ReviewCheckDTO` 的 `scopeKind/defaultFixStrategy/supportedFixStrategies`；但老会话、测试 fixture 或后端缺字段时，Agent 仍会回退到本地 `review_issue_registry.py`。
- 本轮把 fallback 默认动作对齐到后端 `ReviewRuleRegistry`：
  - `probability_inversion`：`sort_by_probability` -> `sort_ordered_plan`，仍然是需要确认的排序预览，不会直接落盘。
  - `probability_gap`：`fill_probability_gap` -> `preview_fix_proposal`。
  - `edge_score`：`add_safety_items` -> `preview_fix_proposal`。
  - `high_tuition/cooperative_program`：继续保持 `item_replacement -> review_plan`，由后端 `replace_risk_items` proposal 披露替换预览，避免默认删除。
- 这不是用户话术字符串匹配，只是结构化 review code 到 action family 的兼容映射；目的是让“有后端 metadata”和“缺 metadata fallback”两条路径语义一致。

本轮验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/regression/test_keyword_matchers.py tests/unit/test_action_resolver.py tests/integration/test_resolver_vs_legacy.py -q
.venv/bin/python -m pytest tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py tests/regression/test_execution_preview.py tests/regression/test_execution_apply.py -q
.venv/bin/python -m pytest tests/unit/test_plan_context_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_planning_plan_scenarios_sync.py -q
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py::test_apply_planning_fix_proposal_requires_confirmation tests/unit/test_planning_workflow_tool.py::test_apply_planning_fix_proposal_formats_repair_report -q
```

结果：分别通过 `177 passed`、`296 passed`、`67 passed`、`3 passed`。覆盖结构化 review issue fallback、resolver 高副作用确认边界、plan_next_action/execute_plan_action 主链路、内部补齐素材、FixProposal 应用文案和旧补偿确认保护。

前端旧 compensation API wrapper 清理：

- `zhiyuan-web/src/service/apis/sessionDetail.ts` 删除未被调用的 `previewPlanningCompensationApi` / `applyPlanningCompensationApi`，避免 PC 工作台继续暴露旧补偿低层入口。
- `PlanningCompensationPreview` 类型保留，因为 `PlanningState.reviewState.compensationPreview` 仍作为审查结果的一部分被工作台状态消费。
- 后端 `/session/compensation/preview` / `/session/compensation/apply` 已删除；Java 内部仍保留 `buildCompensationPreview()` 和补齐动作执行 helper，定位为 FixProposal 素材和 apply 分支复用能力，不是 Agent/前端完整修复主协议。
- 2026-06-13 已进一步退场：Agent Python 侧删除 `preview_planning_compensation/apply_planning_compensation` wrapper，`PlanActionPlan` 不再接受 `preview_compensation/apply_compensation`。旧历史消息中的相关 action 只能被忽略或拒绝，不能再生成新的补偿 pending。
- Agent 侧已删除 `_build_compensation_preview_facts` 和审查回复中直接展示 `reviewState.compensationPreview` 的分支。Java `compensationPreview` 只作为 `generateFixProposals()` 内部素材和旧状态兼容字段存在；Agent 用户侧审查/调整回复只消费 `ReviewState + FixProposalState`，不再把旧补偿动作包装成另一套“补齐方向”。
- 前端检索确认 `previewPlanningCompensationApi` / `applyPlanningCompensationApi` 已无调用方；PC 工作台处理建议弹窗只调用 `fix-proposals/generate` / `fix-proposals/apply`。
- 修复建议弹窗中只有 `ready` proposal 展示「确认修复」按钮；`preview_only`、`blocked`、`info` 改为右侧只读状态文本，避免用户把不可应用建议理解为禁用但可操作的按钮。
- 2026-06-11 补充：`blocked` proposal 展示进一步收敛，只保留 summary 和一条主要“暂不能自动修复的原因”；不再展示 dry-run 影响、临时替换预览或多条候选不足堆叠。`ready` / `preview_only` 仍保留影响、处理预览和替换配对，便于用户确认或人工判断取舍。
- 前端 `tsc --noEmit --pretty false` 仍未通过，但错误集中在既有 `session/ModalForm`、`pages/userCenter`、`service/index`、`service/request`；本轮清理的 `sessionDetail.ts` 未出现在错误列表中。

### 12.11 已完成：审查 stale 触发点收口 Phase 9

完成时间：2026-06-08

背景：

- 方案移动、删除、排序、候选池刷新、偏好/约束采纳都会影响已有审查结果。
- 3.0.x 代码里 `staleFlags.review=true` 和 `staleFlags.planAdjustment=true` 分散在多个方法里，后续扩展初始生成权衡和 FixProposal apply 时容易漏标。

已完成：

- 新增 `ReviewInvalidationPolicy`，集中维护方案变化后的 stale flags：
  - `markPlanStructureStale()`
  - `markCandidatePoolDependentsStale()`
  - `markPreferenceIntentStale()`
  - `markConstraintIntentStale()`
  - `markCandidateViewStale()`
- `PlanningStateService` 内不再直接散落维护 `staleFlags.review=true` / `staleFlags.planAdjustment=true`，`saveWorkingPlanState()` / `saveOrderedState()` / 手动移动 / 专业组移动 / 删除专业组 / 排序 / 候选池生成 / 老方案导入已统一调用 `ReviewInvalidationPolicy`。
- 语义保持不变：
  - 方案事实变化 -> `planAdjustment=true`、`review=true`。
  - 候选池刷新 -> 初始推荐、排序方案、调整建议、审查都需要重算。
  - 软偏好变化不强制候选池 stale。
  - 硬要求变化会标记候选池 stale。
  - candidate view 这类筛选展示状态只影响初始推荐和调整建议，不把 review 标记为 stale。

验证：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：`Tests run: 133, Failures: 0, Errors: 0, Skipped: 3`。

补充验证：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：`Tests run: 139, Failures: 0, Errors: 0, Skipped: 3`。

当前边界：

- 当前 `ReviewInvalidationPolicy` 已负责修改 `StaleFlagsDTO`，并写入 `reasonCode/message/affectedReviewCodes`。
- `PlanningWorkflowStatusDTO` 在 `reviewStatus=stale` 时透出 `reviewReasonCode/reviewReasonMessage/affectedReviewCodes`；老前端不消费也不影响兼容。
- 工作台概览的审查指标已在 `reviewStatus=stale` 时展示一行简短原因，用户能看到为什么需要重新审查。
- 当前 reason 和 `affectedReviewCodes` 是按变更类型给出的保守解释，还不是完整 `PlanningMutationEvent -> evaluate -> stale flags + reason` 事件评估模型。
- `markPlanStructureStale()` 当前同时服务移动、删除、排序、工作台方案保存等动作，因此 `affectedReviewCodes` 会覆盖结构、排序、条目和专业组内主要审查项；后续需要拆成更细的 mutation event，避免“排序”这类动作披露过宽。

### 12.12 已完成：专业组内安全垫修复闭环 Phase 10

完成时间：2026-06-08

背景：

- 3.0.x 已经确认初始生成会尽量带入专业组内托底专业，但历史方案、手动删除、旧工作台方案状态重建排序方案时，仍可能出现已选专业组内没有安全垫专业。
- 过去 `group_inner_safety_guard` 只能在调整分析里提示，不能形成可确认、可复验的修复动作。
- 专业组模式下必须避免把“补一个组内专业”误算成“新增一个专业组”。

已完成：

- `runReview()` 已返回 `group_inner_safety_guard` 的 `affectedUnitIds`，让风险能准确定位到专业组。
- `generateFixProposals()` 针对 `group_inner_safety_guard` 生成 `adjust_major_group_inner_safety` proposal。
- 当已选专业数低于 `requiredMajorCount` 时，proposal 会在同一专业组内补入安全专业。
- 当已选专业数已达到 `requiredMajorCount` 时，proposal 会优先用安全专业替换一个非安全、未锁定的组内专业，不增加专业组数量。
- `applyFixProposal()` 已支持 `adjust_major_group_inner_safety`，执行后同步工作台方案、重建排序方案并复审。
- dry-run 统计将该动作计为组内专业增删，不计为新增专业组。

验证：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldApplyMajorGroupInnerSafetyFixProposalWithinSameUnit test
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：单测通过；目标后端回归结果为 `Tests run: 141, Failures: 0, Errors: 0, Skipped: 3`。

当前边界：

- 该策略只适用于 `majorGroup` 模式；普通专业模式不会生成或应用该 proposal。
- 如果部分专业组找不到可补入的安全专业，proposal 会整体标记为 `blocked`，不做部分自动应用。
- 如果涉及用户偏好权衡更强的替换，例如高收费、中外合作，不复用组内安全垫路径；只走 `replace_risk_items` 自己的完整配对和 dry-run 复验边界。

### 12.13 已完成：前端轻量 FixProposal 确认入口 Phase 11

完成时间：2026-06-08

背景：

- 后端已经具备 `fix-proposals/generate/apply`，但当时工作台前端仍只展示审查 tooltip 和旧 `pendingActions`，用户无法从方案页直接查看可确认修复建议。
- 完整审查修复工作台还需要问题列表、证据、外部 workflow 状态和更细交互设计；当前阶段只补最小可用确认入口，不扩大 UI 面。

已完成：

- 前端新增 `PlanningFixProposal*` 类型，覆盖 proposal、action、dry-run、repair report。
- API 封装新增：
  - `generatePlanningFixProposalsApi`
  - `applyPlanningFixProposalApi`
- 工作台方案工具条新增「修复」入口：
  - 点击后调用 `fix-proposals/generate`，在弹窗中展示 proposal 列表。
  - `ready` proposal 展示「确认修复」按钮，点击后走 `fix-proposals/apply`，并携带 `proposalId/sourceVersionGuard/regenerateOrderedPlan/rerunReview`。
  - `preview_only`、`blocked`、`info` 只展示状态、影响、阻塞原因或 warning，不允许点击应用。
  - 应用成功后刷新工作台状态，并重新生成 proposal 列表。

2026-06-10 补充：

- 工作台修复弹窗已消费 `candidateShortages`，按 scope/reason/count/message 展示候选不足说明。当前用于解释“当前规划候选池不足、硬要求收窄、容量或替换配对不足、dry-run 后目标未改善”等边界，不参与前端业务判断。
- 工作台修复弹窗会消费 `replacementPairs` 辅助生成替换说明，但用户可见内容必须优先来自已解析的学校/专业名称或后端 `action.detail`。如果前端无法把 pair 中的 ID 解析成可读名称，不展示原始 ID，不再把 `4302026...` 这类执行字段暴露给用户。
- 「确认修复」按钮增加 `requiresConfirmation !== false` 条件。`ready + proposalId + requiresConfirmation` 才允许用户点击；`preview_only/blocked/info` 或明确不需要确认的 proposal 都保持只读。
- `rebalance_tier_ratio`、`fill_probability_gap` 即使生成 replacement pair，也仍按 `preview_only` 只展示预览、候选不足和 dry-run 影响，不展示确认修复按钮。

2026-06-11 前端交互补充：

- 审查入口集中在「方案审查结果」弹窗，审查问题下先展示「处理方向」，用户点击「查看处理建议」后再展开后端 `FixProposal`。
- 可执行 proposal 的按钮文案统一为「立即执行」，放在「调整预览」内容下方，使用小型普通按钮样式；不再展示“可处理”“暂不可用”“预览验证未通过”等系统状态。
- 「调整预览」只保留一层标题，下面展示 dry-run 量化变化和最多 5 条可读动作明细；blocked proposal 不展示临时动作和增删统计。
- `replace_risk_items` 的替换说明在专业模式和专业组模式下都必须展示为“学校/专业 A 替换为 学校/专业 B”或后端可读 detail；如果只剩结构化 ID，则跳过该明细。
- 用户侧展示继续屏蔽历史/系统词：后端仍可能因为兼容字段输出“草稿”“硬约束”“修复”等旧概念，前端展示层统一转译为“方案”“已确认的筛选条件或报考要求”“处理”，避免用户在审查处理建议里看到内部实现语言。

验证：

```bash
cd zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false
```

结果：前端全量 typecheck 被既有错误挡住，错误集中在 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts`；本次新增的 WorkspacePanel / API / 类型文件未出现在错误列表。

补充验证：

```bash
git diff --check
```

结果：通过。

当前边界：

- 这不是完整审查修复工作台，只是把后端已支持的 proposal 确认链路暴露给 PC 工作台。
- 对话主路径仍不直接开放 `fix-proposals/apply`，避免没有前端状态卡时误触发高副作用修复。
- `replace_risk_items` 完整配对场景可通过前端确认入口应用；不会由对话主路径或前端入口自动静默应用。
- 前端当前只做结构化字段展示，不基于 `candidateShortages` 或 `replacementPairs` 自行推导可执行性；可执行性仍以服务端 `proposal.status/requiresConfirmation/sourceVersionGuard` 和 apply policy 为准。

人工前端验收点：

- 完整 `replace_risk_items`：弹窗展示替换配对，且只有 `ready` 卡片可点击确认；点击后刷新工作台、重新生成 proposal，并显示最近一次修复报告。
- 部分 `replace_risk_items`：卡片保持 `preview_only`，展示未覆盖 warning 和候选不足/配对不足说明，不出现确认修复按钮。
- 无替换候选：卡片为 `blocked`，展示 `candidateShortages` 和阻断原因，不出现确认修复按钮。
- 结构修复 `rebalance_tier_ratio` / `fill_probability_gap`：能看到 dry-run 影响、替换配对或候选不足说明，但不允许自动应用。
- 专业模式和专业组模式都要确认展示粒度没有混淆：专业组整体替换看 unit，单专业/组内专业问题看 volunteer，同时不得把组内专业数当作专业组数。

2026-06-11 本地验证补充：

```bash
curl -sS --output /private/tmp/session128_review_workflow.json \
  'http://127.0.0.1:8080/gaotu-assistant-bot/inner/planning/1/session/review-workflow/run?chatSessionId=128' -X POST

curl -sS --output /private/tmp/session130_fix_proposals.json \
  'http://127.0.0.1:8080/gaotu-assistant-bot/inner/planning/1/session/fix-proposals/generate?chatSessionId=130' -X POST

cd zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false 2>&1 | rg "WorkspacePanel|volunteer.ts|sessionDetail.ts"

cd ../zhiyuan-server
mvn -Dtest=RepairApplyMutationBuilderTest,RepairDryRunSimulatorTest,RepairRiskActionBuilderTest,RepairReplacementActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairProposalApplyPolicyTest,RepairReportBuilderTest test

cd ..
git diff --check
```

结果：

- 专业模式 session 128：`replace_risk_items` 生成的 action detail 为可读学校/专业名称；高收费因部分风险未覆盖保持 `preview_only`，中外合作完整覆盖为 `ready`。
- 专业组模式 session 130：`replace_risk_items` 的高收费/中外合作均生成可读 action detail；`replacementPairs` 仍保留执行 ID，但前端不会把这些 ID 作为用户可见替换文案。
- 前端目标类型检查无 `WorkspacePanel`、`volunteer.ts`、`sessionDetail.ts` 相关错误；全量 typecheck 的既有错误仍在 `session/ModalForm`、`userCenter`、`service/index`、`service/request`。
- 后端目标修复回归通过：`Tests run: 55, Failures: 0, Errors: 0, Skipped: 0`。
- `git diff --check` 通过。

### 12.14 已完成：审查-修复聚合入口 Phase 12

完成时间：2026-06-08

背景：

- 外部触发或后续 Agent 编排如果分别调用 `runReview()`、`generateFixProposals()`、`workspace/state`，容易出现状态读取不一致，也会让调用方自行理解多个状态结构。
- 3.1.0 需要一个稳定的“审查 -> 生成修复建议 -> 返回工作台状态”的聚合入口，但不应在这里新增另一套修复逻辑。

已完成：

- 后端新增 `ReviewWorkflowRunRes`，统一返回：
  - `status`：聚合后的本次 workflow 状态。
  - `sessionId`、`sourceVersion`：当前会话与方案版本。
  - `reviewState`：审查结果。
  - `fixProposalState`：修复建议结果。
  - `workflowStatus`：工作台已有 workflow 摘要状态。
  - `workspaceState`：当前工作台状态。
- `PlanningStateService.runReviewWorkflow()` 只做顺序编排：
  - 先调用现有 `runReview()`。
  - 再调用现有 `generateFixProposals()`。
  - 最后读取 `getWorkspaceState()`。
- `ReviewWorkflowStatusResolver` 已承接本次 workflow status 的纯映射：
  - review 未完成或失败 -> `review_failed`。
  - 没有修复建议 -> `review_passed_or_no_fix`。
  - 有 `ready` proposal -> `ready_to_confirm`。
  - 无 ready 但有 `preview_only` -> `preview_only`。
  - 其余 blocked/info -> `blocked_or_info`。
- 新增内部接口：

```http
POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/review-workflow/run?chatSessionId={chatSessionId}
```

- 当前 `status` 语义：
  - `review_failed`：审查未完成或失败。
  - `review_passed_or_no_fix`：审查通过，或没有可展示修复建议。
  - `ready_to_confirm`：存在可直接确认的修复建议。
  - `preview_only`：只存在预览类建议，需要用户理解后再通过其他路径处理。
  - `blocked_or_info`：只存在阻塞或说明类建议。
- 前端 API 层新增 `runPlanningReviewWorkflowApi` 和 `PlanningReviewWorkflowRunRes` 类型，暂不接 UI 行为。

验证：

```bash
cd zhiyuan-server
mvn -q -Dtest=ReviewWorkflowStatusResolverTest,PlanningStateServiceTest#shouldRunReviewWorkflowAndReturnFixProposalsWithWorkspaceStatus test
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过。新增 `ReviewWorkflowStatusResolverTest` 直接覆盖 `review_failed`、`review_passed_or_no_fix`、`ready_to_confirm`、`preview_only`、`blocked_or_info` 映射；服务级用例继续覆盖 `runReviewWorkflow()` 聚合入口返回 `ready_to_confirm` 和工作台状态。核心回归结果为 `Tests run: 202, Failures: 0, Errors: 0, Skipped: 3`。

当前边界：

- 该入口不绕过 `FixProposal` 的 `sourceVersionGuard`，真正应用修复仍必须走 `fix-proposals/apply`。
- 该入口不把 `preview_only` 建议升级为可应用建议；例如高收费、中外合作替换仍只披露预览。
- 当前前端工作台仍使用轻量「修复」弹窗分别拉取和应用 proposal；后续如果要做完整审查修复工作台，可以改为先调用该聚合入口。

### 12.15 已完成：初始推荐策略报告 Phase 13

完成时间：2026-06-08

背景：

- 初始推荐生成阶段已经会尝试处理数量、冲稳保、安全垫、录取率倒挂、梯度断层和专业组内安全垫等结构问题。
- 过去这些处理只压缩在 `summary.gapFixCount/appliedRepairCount/unresolvedRuleCodes` 和 item `reasonCodes` 中，用户或外部系统很难知道系统为了降低风险做了哪些取舍，以及还有哪些问题没有解决。

已完成：

- 后端新增 `InitialPlanStrategyReportDTO`，挂载在 `InitialRecommendationStateDTO.strategyReport`。
- 报告当前包含：
  - `targetProfile`：目标数量、目标冲稳保分布、生源省份、志愿模式、专业组内目标专业数。
  - `objectiveWeights`：当前初始生成的相对目标说明，包含目标 code、展示名、相对权重、优先级和说明。
  - `selectedCount`：初始推荐最终选择数量。
  - `appliedRepairs`：生成阶段执行的候选替换动作，包含规则、from/to 志愿、展示 label 和原因。
  - `actions`：复用 `FixProposalActionDTO` 的只读动作明细，当前覆盖已执行替换的 `replace_volunteers` 和 `replacementPairs`。
  - `tradeoffs`：生成阶段自动替换产生的取舍明细，包含换出/换入、推荐系数/录取率/热度/院校排名变化、收益、代价和用户侧摘要。
  - `unresolvedRisks`：生成阶段仍未解决的审查规则及用户可读说明。
  - `candidateShortages`：生成阶段未解决的候选不足或约束冲突说明。
  - `userAttentionMessages`：可用于概览或对话的简短提醒。
- `AppliedRepair.tradeoffSummary` 已复用第一条对应取舍摘要，方便轻量入口直接说明“为什么换、收益是什么、代价是什么”。
- 当前不改初始推荐选择算法，只把已有目标优先级、修复动作、取舍、不足和未解决规则结构化输出。
- `PlanningWorkspaceStateRes` 已返回 `initialRecommendationState`，前端类型补充 `PlanningInitialPlanStrategyReport`、`objectiveWeights`、`actions`、`tradeoffs` 和 `initialRecommendationState.strategyReport`。
- PC 工作台概览已接入轻量提示：
  - 有生成阶段候选不足时，优先展示不足说明。
  - 有未解决生成阶段风险时，展示风险数量和第一条风险说明。
  - 没有候选不足和未解决风险，但生成阶段做过结构性替换时，优先展示取舍摘要；没有摘要时再展示本次调整候选数量。
  - 概览折叠后不展示该提示，避免占用高频操作区。

验证：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldRepairInitialRecommendationProbabilityGap test
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
mvn -q -Dtest=PlanningStateServiceTest#shouldRepairInitialRecommendationProbabilityGap+shouldFullyRepairInitialRecommendationProbabilityGapWhenCandidateWindowIsEnough+shouldRepairInitialPlanMajorGroupIssuesBeforePlanAdjustmentAnalysis test
```

结果：单测通过；目标后端回归结果为 `Tests run: 142, Failures: 0, Errors: 0, Skipped: 3`。2026-06-10 补充验证通过，覆盖 `objectiveWeights`、`actions`、`tradeoffs` 和 `AppliedRepair.tradeoffSummary` 的生成，确认这些解释字段只随初始推荐报告返回，不改变候选选择和修复应用路径。

当前边界：

- 报告当前记录的是初始推荐阶段实际发生的候选替换和未解决规则，不包含完整目标函数权重。
- `objectiveWeights` 当前是对现有规则优先级的只读说明，不是实际参与排序的加权求和参数；后续如果要做真正可配置目标函数，需要另起算法设计和回归。
- `actions` 只是生成阶段已发生动作的结构化说明，不代表用户可再次确认或外部可 apply；如果后续要把初始生成修复转成可选 proposal，需要明确区分“已执行的生成动作”和“待确认的修复建议”。
- `tradeoffs` 已补第一阶段指标变化，但仍是轻量解释：院校层次暂用排名差异近似，专业热度和推荐系数依赖候选字段质量；完整目标函数权重和多方案比较仍需后续补充。
- PC 工作台当前只展示一行轻量提示；完整的取舍明细、from/to 列表和指标损失仍留给后续审查修复详情面板。

### 12.16 已完成：修复报告动作明细 Phase 14

完成时间：2026-06-09

背景：

- `RepairReport` 已经能返回修复状态、数量变化和修复前后风险数量，但前端或外部系统只能看到汇总结果，无法直接知道本次修复具体执行了哪些动作。
- `FixProposal` 本身已有 action 结构，报告层可以复用该结构，不需要改变 apply 执行逻辑。

已完成：

- `RepairReportDTO` 新增 `actionDetails`：
  - `actionType`
  - `sourceCheckCode`
  - `summary/detail`
  - `unitIds/volunteerIds`
  - `removeUnitIds/removeVolunteerIds`
  - `candidateUnitIds/candidateVolunteerIds`
  - `replacementPairs`
- `buildRepairReport()` 会把 proposal actions 复制到 `actionDetails`，保留原有计数、消息和复验状态。
- 前端 `PlanningRepairReport` 类型同步补充 `actionDetails`。
- 前端修复建议弹窗会在用户确认修复后展示“最近一次修复结果”，包括：
  - 修复结果消息。
  - 新增/移除数量。
  - 风险和提醒数量前后变化。
  - 前几条动作明细和 warning。

验证：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldApplyFillMissingCountFixProposalWithVersionGuard test
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：单测通过；目标后端回归结果为 `Tests run: 142, Failures: 0, Errors: 0, Skipped: 3`。

当前边界：

- `actionDetails` 当前反映 proposal 计划执行动作，不记录每个 action 的实际成功/失败分项；后续如支持部分成功，需要扩展 `applied/failed/skipped` 明细。
- 暂未持久化 `RepairReport`，目前主要通过 `fix-proposals/apply` 响应返回。
- 前端当前只展示最近一次 apply 的报告摘要；关闭弹窗后不保留历史修复报告。

### 12.17 已补充设计：候选选择策略层 Phase 15

完成时间：2026-06-09

背景：

- 当前涉及候选选择的路径包括初始方案生成、候选手动加入方案、补偿预览、审查后修复、专业组内安全专业补齐。
- 初始方案生成内部已经具备目标冲稳保、数量补齐、安全垫、倒挂、梯度和专业组安全专业等规划动作。
- 但事后修复仍主要由 `buildCompensationPreview` 生成 action，部分策略依赖候选池原顺序或只给新增候选，没有完整替换 pair。

本轮文档补充：

- 在 5.3.2 中新增统一候选选择策略层设计。
- 明确候选选择应拆成：
  - 候选来源解析。
  - 可用性过滤。
  - 策略排序。
  - 容量判断。
  - 替换配对。
  - dry run 验证。
  - action 构建。
- 明确每个 strategy 的目标数量、候选排序、满容量处理和不能满足返回。
- 明确专业组模式下 unit 粒度和组内专业粒度不能混用。
- 明确 `rebalance_tier_ratio`、`fill_probability_gap` 等结构修复在满容量时必须生成 remove/add pair，不能只追加候选。

当前进展判断：

- 已完成基础审查规则目录、stale 策略、FixProposal 模型、部分 apply、ReviewWorkflow 聚合入口、InitialPlanStrategyReport、RepairReport actionDetails 和前端轻量修复弹窗。
- 已完成 `RepairCandidateSelector` 第一阶段抽取：覆盖事后修复里满容量结构替换的来源选择，以及补偿预览中的 add 候选选择，包括 `fill_missing_count`、`add_safety_items`、`rebalance_tier_ratio` 和 `fill_probability_gap`。
- 已完成 `RepairReplacementActionBuilder` 第一阶段抽取：`rebalance_tier_ratio` / `fill_probability_gap` 的满容量 `replace_volunteers` action、remove/add pair、专业组 unit 粒度和专业 volunteer 粒度组装已从 `PlanningStateService` 迁出；满方案结构建议入口、add-only 结构动作删除和 replacement pair 为空时 blocked 保护也已迁入 builder。服务层继续负责 proposal 汇总、dry run 和 apply。
- 已完成 `RepairDryRunSimulator` 第一阶段抽取：dry-run action 计数、before/after 快照模拟、冲稳保分布和状态文案已从 `PlanningStateService` 迁出。服务层继续负责 proposal 汇总和 apply。
- 已完成 `RepairReportBuilder` 第一阶段抽取：`FixProposal` 应用后的 `RepairReportDTO` 构建、actionDetails、复验结果、风险数量对比和面向用户的结果消息已从 `PlanningStateService` 迁出。服务层继续负责 apply 编排、保存、重新生成 ordered plan 和重跑审查。
- 已完成 `WorkingPlanMutationSupport` 第一阶段抽取：工作台方案的 volunteer identity 判断、专业组 unit 同步和 summary 重算已迁出为共享纯内存辅助；服务层委托方法已改成 working-plan 命名，底层 DTO 名保留兼容。
- 已完成 `WorkingPlanMutationSupport` 第二阶段抽取：新增 `buildWorkingPlanItem(candidate, source[, locked])` 和 `addWorkingPlanItemIfAllowed(...)`，统一候选转工作台方案项、重复 volunteer、禁用 volunteer 的纯内存判断。手动加入、补偿加入和 fix proposal 组内安全垫补专业已共用该能力；老方案导入和初始自动生成只共用 item 构造，不共用 allowed 判断，因为这两条路径原本不跳过历史已选/禁用项，语义不同。
- 已完成 `RepairApplyMutationBuilder` 第一阶段抽取：`fill_missing_count`、`remove_risk_items`、`adjust_major_group_inner_safety` 和旧 compensation apply 的工作台方案内存 mutation 已从 `PlanningStateService` 迁出。builder 只做内存增删、summary/unit 同步和操作日志构造；sourceVersion guard、保存、ordered plan 重新生成、复审和报告仍留在服务层。
- 已完成 `CandidatePoolStatusResolver` 第一阶段抽取：候选池 `not_generated/empty/low_count/ready` 和目标数量口径从 `PlanningStateService` 迁出，专业模式按 `requiredCount/summary.total` 判断，专业组模式优先按 `requiredUnitCount/summary.unitTotal` 判断，避免把组内专业数当成专业组数。
- 已完成 `CandidatePoolQualityStatusBuilder` 第一阶段抽取：候选池 `statusCode/statusMessage/riskHints` 展示构造从 `PlanningStateService` 迁出，复用统一候选池状态口径。builder 只负责状态文案和风险提示构造，不保存、不排序、不生成或修复方案。
- 已完成 `PlanningWorkflowStatusBuilder` 第一阶段抽取：工作台响应中的候选池状态、方案状态、审查状态和导出状态从 `PlanningStateService` 迁出为纯状态构建器。builder 不读写服务、不保存、不触发修复；导出态只消费服务层传入的 latest export event。
- 已完成 `InitialPlanStrategyReport` 解释增强第一阶段：初始生成报告新增 `objectiveWeights`、`actions`、`tradeoffs` 和 `AppliedRepair.tradeoffSummary`。其中 `actions` 复用 `FixProposalActionDTO` 只读表达已执行替换的 `replace_volunteers/replacementPairs`，但不生成可 apply 的 `FixProposalDTO`，也不进入 dry-run 或 apply 白名单。
- `replace_risk_items` 已能生成替换预览；后续已推进到受控 apply：只有完整 replacement pair、sourceVersion guard、审查未过期、proposal ready、dry-run 复验通过时，才允许通过 `fix-proposals/apply` 落盘。
- `rebalance_tier_ratio` / `fill_probability_gap` 在满容量时已能生成 `replace_volunteers` 预览 pair，但仍保持 `preview_only`，不开放自动 apply。

## 13. 接下来计划

### 13.1 短期必须收口

1. 收口补齐类内部素材的高风险 action。
   - `rebalance_tier_ratio`、`fill_probability_gap` 如果没有 replacement pair，不能直接追加导致超量。
   - `fill_total_count` 这类纯补数量动作只通过 `FixProposal` ready strategy 进入落盘；结构性替换必须迁移到 `FixProposal`。
   - 2026-06-09 已完成容量裁剪收口；当前旧 compensation 对外入口已删除，FixProposal 满容量结构建议已改为 replacement pair 预览。

2. 实现统一 `RepairCandidateSelector` 的最小版本。
   - 先覆盖 `fill_missing_count`、`add_safety_items`、`rebalance_tier_ratio`、`fill_probability_gap`。
   - 输出统一的 selection result：`addCandidates`、`removeCandidates`、`replacementPairs`、`shortageReasons`。
   - 所有策略必须显式 comparator，不再依赖候选池原顺序。
   - 2026-06-09 已先在现有 compensation 内补齐缺口 tier 优先选择和保区候选显式排序，完整 selector 抽取仍待做。
   - 2026-06-09 已完成第一步最小抽取：新增 `RepairCandidateSelector`，把 `rebalance_tier_ratio` / `fill_probability_gap` 的 remove source 选择、专业组/专业模式分支和显式 comparator 从 `PlanningStateService` 迁出。
   - 2026-06-09 已继续完成 add 侧选择迁移：`fill_total_count`、`add_local_protect`、`rebalance_protect_ratio`、`fill_probability_gap` 的 volunteer/unit 候选选择由 selector 输出，`PlanningStateService` 只保留 action type、summary、detail、dry run 和 apply 语义。
   - 2026-06-09 已继续完成结构替换 action 组装迁移：新增 `RepairReplacementActionBuilder`，负责 `replace_volunteers`、`replacementPairs`、`candidate/remove UnitIds` 和 `candidate/remove VolunteerIds` 的组装；后续又把满方案结构建议入口判断迁入该 builder，`PlanningStateService` 不再直接拼结构替换 pair 或处理 add-only 结构动作 blocked。
   - 2026-06-09 已继续完成 dry-run 模拟迁移：新增 `RepairDryRunSimulator`，负责 action 计数、before/after total、冲稳保分布快照和 dry-run 状态文案；同时修正专业模式下 replacement 删除 volunteer 后派生 unit 未清理导致 `afterUnitTotal` 虚增的问题。专业组显式 unit 会被保留，不影响组内专业替换。
   - 2026-06-09 已继续完成修复报告构建迁移：新增 `RepairReportBuilder`，负责应用后的报告字段、动作明细、复验状态和结果消息；`PlanningStateService` 不再直接拼 `RepairReportDTO`。
   - 2026-06-09 已继续完成 working plan mutation 共享辅助抽取：新增 `WorkingPlanMutationSupport`，承接 `containsWorkingPlanItem`、`containsVolunteerId`、`syncWorkingPlanUnitsWithItems` 和 `recalculateWorkingPlanSummary` 的实现。抽取时回归发现 legacy volunteer prefix 不能按第一段截断，必须与原 `CandidateResolver` 一致取前两段，避免 `ps1_m1` / `ps1_m2` 被误判为同一专业。
   - 2026-06-09 已继续完成 working plan item 增加逻辑抽取：`buildWorkingPlanItem()` 统一候选字段映射，`addWorkingPlanItemIfAllowed()` 统一跳过重复/禁用项。当前迁移范围限定在手动加入、补偿加入和 fix proposal 安全垫补专业，避免把老方案导入、初始自动生成这两条不同语义路径误改成跳过逻辑。

3. 修复 `rebalance_tier_ratio`。
   - 目标数优先使用 `requiredTierCounts`。
   - 当前数量以 ordered 为准，ordered 为空才用工作台方案状态，不能混用 working-plan total 和 ordered summary。
   - 有容量时 add；满容量时从 surplus tier 中找可替换项。
   - 找不到候选或替换项时返回 `cannot_satisfy`，说明缺口和原因。
   - 2026-06-09 已完成目标数优先使用 `requiredTierCounts["保"]`，并修复 ordered/draft 计数混用；满容量时已能从 surplus tier 中选择替换来源并输出 replacement pair 预览，自动 apply 仍未开放。

4. 补充 dry run。
   - 对每个 proposal 输出修复前后数量、冲稳保分布、风险数量、是否引入高收费/限报/中外合作。
   - dry run 不改善目标规则时，proposal 不能标记为 `ready`。

5. 增加回归测试。
   - 专业模式：数量补齐、本省保底、保区不足、梯度断层、候选不足。
   - 专业组模式：专业组数量补齐、组内安全垫、满容量替换、不把组内专业数当专业组数。
   - 旧 compensation apply：结构性 replacement action 不允许 add-only 超量。

### 13.2 中期完善

1. 将初始方案生成复用选择策略层。
   - 保留初始生成可自动应用低风险结构修复的能力。
   - 把自动替换产生的 tradeoff 统一进入 `InitialPlanStrategyReport`。
   - 2026-06-10 已完成解释层第一阶段：初始生成自动替换已经进入 `InitialPlanStrategyReport.tradeoffs`，并用 `InitialPlanStrategyReport.actions` 复用 `FixProposalActionDTO` 的只读动作结构。尚未完成的是让初始生成真实复用 `RepairCandidateSelector`、`ReplacementPlanner` 和 dry-run 评价；这一部分涉及选择算法行为，后续需要单独设计和更强回归。

2. 支持 `replace_risk_items` 正式 apply。
   - 2026-06-10 已完成当前阶段：完整 replacement pair 可原子执行 remove + add，部分替换保持 `preview_only`，无替换项保持 `blocked`。
   - apply 前继续要求 `sourceVersionGuard`、review 未 stale、proposal `ready` 和 dry-run 目标复验通过。
   - 专业组模式下如果条目风险替换会改变专业组数量，暂时阻断，后续再设计整组替换 selector。
   - 应用后可按请求触发复审对应风险项。

3. 完整审查修复工作台。
   - 当前前端轻量弹窗只承接最低可用流程。
   - 后续需要展示规则证据、候选不足原因、替换 pair、修复前后指标和历史修复报告。

4. 更精细的 stale reason。
   - 当前 `ReviewInvalidationPolicy` 已统一触发点，但 affected review codes 仍偏粗。
   - 后续按移动、删除、组内专业调整、偏好变更、硬要求变更进一步缩小影响范围。

### 13.3 后续增强

1. 候选选择的权重可配置化。
   - 把推荐系数、安全性、意向匹配、院校层次、专业热度、地域、费用等权重纳入策略配置。
   - 支持按用户策略类型或省份规则调整。

2. 候选不足的一等解释。
   - 候选池本身不足、硬约束过强、用户偏好冲突、容量已满且无可替换项，应分别输出。
   - Agent 和前端都只消费结构化原因，不再拼空泛建议。

3. 外部触发协议稳定化。
   - `review-workflow/run` 继续作为聚合入口。
   - `proposals/apply` 作为唯一高副作用应用入口。
   - 旧低层 compensation 接口逐步退场或限制为兼容只读/低风险动作。

### 13.4 apply 编排边界

当前 `FixProposal` 应用链路可以分成三层：

1. 纯内存 mutation。
   - `fill_missing_count`：把候选 volunteer 加入工作台方案。
   - `remove_risk_items`：从工作台方案删除风险 volunteer，再按补数量 action 补充。
   - `adjust_major_group_inner_safety`：专业组内删除/补充专业。
   - 这层需要统一处理 banned volunteer、重复 volunteer、候选缺失、专业组 unit 同步和 summary 重算。

2. 持久化和 ordered plan 编排。
   - mutation 完成后调用 `saveWorkingPlanState()` 保存工作台方案。
   - 用户要求时调用 `generateOrderedPlan(forceRegenerate=true, regroupByTier=true)`。
   - 这里属于高副作用路径，必须保留 sourceVersion guard 和用户确认。

3. 复审和报告。
   - 用户要求时调用 `runReview()`，然后刷新 state。
   - `RepairReportBuilder` 根据 proposal、修复前 summary 和修复后 state 生成 `RepairReportDTO`。

当前不直接抽 `RepairApplyService` 的原因：

- mutation 层依赖工作台方案的 unit 同步和 summary 重算，这两个能力同时服务手动编辑、补偿、初始推荐和专业组/专业双模式，直接搬迁容易复制出第二套 summary 同步逻辑。
- apply 编排涉及保存、重新生成 ordered plan、复审，属于高副作用路径；在没有更完整的 apply 级回归前，不应一次性迁移。
- 已先把候选选择、结构替换 action、dry-run 和 report builder 迁出，服务层剩余职责更集中，后续可以围绕 mutation 层单独设计。

后续拆分建议：

1. 继续完善 `WorkingPlanMutationSupport`。
   - 已承接 `containsWorkingPlanItem`、`containsVolunteerId`、专业组 unit 同步、summary 重算等纯内存辅助。
   - 后续继续承接按候选构造 `DraftItemDTO`、工作台方案增删 mutation result 和 applied actions 记录。
   - 该类服务手动编辑和 fix apply，避免 fix apply 单独复制一套。

2. 再抽 `RepairApplyMutationBuilder`。
   - 输入 `state + candidates + proposal`，输出 mutation result 和 applied actions。
   - 不保存、不生成 ordered plan、不复审。
   - 先覆盖 `fill_missing_count`、`remove_risk_items`、`adjust_major_group_inner_safety`。
   - 2026-06-09 已完成第一阶段：新增 `RepairApplyMutationBuilder`，承接 fix proposal compensation action、风险项删除后补数量、专业组内安全垫替换和旧 compensation apply 的内存 mutation；`PlanningStateService` 仅保留高副作用编排。

3. 最后再考虑 `RepairApplyService`。
   - 只负责编排 apply、save、ordered regenerate、rerun review 和 report。
   - sourceVersion guard、review stale、proposal 状态和可自动应用策略白名单已先抽到 `RepairProposalApplyPolicy`，后续 service 拆分时继续复用同一入口校验。
   - 保持 `proposals/apply` 为唯一高副作用入口。
   - 在 `replace_volunteers` 从 preview-only 进入可 apply 前，必须补齐原子 remove/add、容量不变、复审改善和硬约束不破坏测试。

### 13.5 最新实现记录

2026-06-09 补偿策略收口：

- `buildCompensationPreview()` 保留补偿候选和结构性建议，用于审查解释、方案分析和后续 replacement pair 迁移，不再把 preview 当成唯一可执行动作列表提前裁剪。
- 历史 `applyCompensation()` 曾新增执行侧 action 副本裁剪：按 action 顺序消费同一份剩余额度，避免多个补偿动作各自使用完整剩余额度导致超量；当前旧 apply 对外入口已删除，这部分容量保护语义已收敛到 `FixProposal` 生成、dry-run 和 apply 分支。
- `fill_total_count` 补数量时优先选择当前目标缺口最大的 tier；如果缺口是保区，会优先本省保底候选，再按推荐系数、录取率、意向分排序。
- `rebalance_protect_ratio` 目标数优先来自 `requiredTierCounts["保"]`；没有明确目标时才回退到 20% 经验值。该策略用于补安全垫，保区候选排序为本省优先、录取率优先、推荐系数、意向分。
- `FixProposal` 生成阶段新增满容量结构替换预览：`rebalance_tier_ratio` 会从 surplus tier 中选择非锁定的低性价比来源，`fill_probability_gap` 会从断层边界中选择可替换来源，统一输出 `replace_volunteers`、`candidateVolunteerIds/removeVolunteerIds` 和 `replacementPairs`。历史 `pinned/pinnedPosition` 只保留兼容字段，不再作为替换来源约束。
- 专业组模式下同样使用 unit 粒度计算目标和当前数量，避免把组内专业数量当成专业组数量。
- 旧的梯度断层结构动作名已收口到当前 `fill_probability_gap`，执行侧容量保护不再识别已废弃的 `replace_probability_gap`，避免新旧动作名并存造成结构性建议被误当普通追加动作。
- `FixProposalDryRunResultDTO` 新增 `before/after` 总量、冲稳保分布、ID 快照和质量取舍快照：`beforeUnitTotal/afterUnitTotal`、`beforeVolunteerTotal/afterVolunteerTotal`、`beforeUnitTierCounts/afterUnitTierCounts`、`beforeVolunteerTierCounts/afterVolunteerTierCounts`、`before/afterUnitIds`、`before/afterVolunteerIds`，以及 `before/afterAverageFinalScore`、`before/afterAverageHotIndex`、`before/afterAverageSchoolRank`。当前先做轻量动作模拟，用于披露结构修复改善方向和可能牺牲的推荐系数/专业热度/院校排名，不把 dry run 结果当真实方案状态。
- `RepairDryRunSimulator` 新增硬要求/软偏好/新增风险/质量下降 warning：新增候选如果命中硬性排除或负偏好、或不满足硬性限定，会追加 dry-run warning；新增候选如果带来高收费、限报标签、中外合作或特殊类型招生，也会提示；替换/移除如果会移除硬性限定命中项或正向偏好命中项，也会提示；修复后平均推荐系数、专业热度或院校排名明显变差时也会提示。该增强只增加披露信息，不改变 proposal status，也不把 `preview_only` 升级为可应用。
- `RepairDryRunSimulator` 新增目标改善校验：`count_validation` 必须让当前数量更接近 `requiredCount`；条目风险修复必须减少本次审查命中的 affected 志愿/专业组；`group_inner_safety_guard` / `major_group_safety_intent_alignment` 必须让目标专业组 dry-run 后出现录取率不低于组整体录取率的安全垫专业；`sort_by_probability` 必须在 dry-run 顺序模拟后减少录取率倒挂；`fill_probability_gap` 会按录取率序列比较修复前后的断层数量和最大断层，未缩小时追加 warning；`rebalance_tier_ratio` 会在存在 `requiredTierCounts` 时比较修复前后冲稳保计数与目标计数的距离，未更接近目标时追加 warning。校验失败时同步把 `proposal.status` 和 `dryRun.status` 标为 `blocked`，避免前端或外部系统把无改善提案当作可确认修复；`rebalance_tier_ratio` / `fill_probability_gap` 当前仍保持 `preview_only`，因此只披露无改善 warning，不开放自动应用。
- `FixProposalStateDTO.status` 汇总逻辑已从固定 `ready` 改为按子 proposal 状态计算：有 `ready` 才返回 `ready`；没有 ready 但有 `preview_only` 返回 `preview_only`；全是 blocked/info 时返回 `blocked_or_info`；空列表返回 `empty`。这样单个 proposal 被 dry-run 阻断后，聚合入口和外部系统不会继续误判为可确认修复。
- `RepairProposalStateBuilder` 第一阶段抽取已完成：服务层调用 `newState()`、`groupCompensationActionsByCheck()`、`buildBaseProposal()`、`resolveStateStatus()` 和 `findProposal()` 处理 FixProposal 外壳、compensation 分组、基础 proposal 字段、状态汇总和 proposal 查找。builder 只承接纯组装逻辑，service 仍负责具体 action builder、dry-run、保存、重排和复审这些带副作用或需要上下文判断的编排。
- `RepairProposalStateBuilder` 已补充 `cannot_satisfy` 的规则级原因：数量缺口、保底不足、冲稳保配比、录取率断层、录取率倒挂、专业组内安全垫、条目风险等场景会分别输出更具体的 `summary/blockingReason`；`RepairDryRunSimulator` 的 blocked message 复用该原因。`cannot_satisfy` 作为不可执行状态会统一设置 `requiresConfirmation=false`，服务层 `generateFixProposals()` 已覆盖真实入口下的候选不足 blocked 场景，避免前端或 Agent 把不可执行建议展示成可确认动作。该增强不扩展 DTO、不开放任何新的自动 apply 策略，只让前端和 Agent 在候选不足时不再只能拿到“缺少可执行动作”的泛化文案。
- 前端轻量修复建议弹窗已消费 dry run 冲稳保分布变化：专业组模式展示专业组粒度结构变化，专业模式展示单条志愿粒度结构变化，避免把组内专业数误展示成专业组数。
- `RepairCandidateSelector` 第一阶段抽取已完成：服务层调用 `selectTierRatioReplacementSources()` 和 `selectProbabilityGapReplacementSources()` 获取可替换来源；调用 `selectTotalCount...Additions()`、`selectLocalProtect...Additions()`、`selectProtectRatio...Additions()`、`selectProbabilityGap...Additions()` 获取补充候选。selector 内部按 volunteerModel 区分专业组 unit 粒度和专业 volunteer 粒度，并保留原有 candidate legacy prefix 解析，避免老数据 ID 影响替换来源定位；当前方案是否已达到目标数也统一通过 `isCurrentPlanAtOrAboveTargetCount()` 判断，供结构 replacement 入口复用同一套专业/专业组计数。
- `replace_risk_items` 的替代候选选择已迁入 `RepairCandidateSelector.selectRiskItemReplacements()`：服务层只负责按 selector 结果组装 proposal/action/warning，不再内联 same-tier、安全候选过滤、当前方案去重和专业组 unit 去重。selector 当前保持既有策略：每个风险志愿优先找同 tier、低风险、当前工作台未选、未在本次 proposal 重复使用的候选；专业组模式还会避免引入当前已选专业组或同一 proposal 内重复引入同一个专业组。新增回归覆盖了同层次安全替换排序、专业组当前/已用 unit 去重，以及候选不足时 partial 仍保持 `preview_only`。
- `RepairRiskActionBuilder` 第一阶段抽取已完成：服务层调用 `populateRemoveRiskItemActions()` 和 `populateReplaceRiskItemActions()` 组装条目型风险 action。builder 内部统一处理 `remove_risk_items` 的去重 affected ids、删除 action、删除后补数量 fallback action，以及 `replace_risk_items` 的 replacement pair、missing source/no replacement warning 和 partial replacement warning。服务层仍保留删除后补足数量所需的上下文计算，不把候选选择和工作台容量判断隐藏到 action builder 里。
- `RepairMajorGroupInnerSafetyActionBuilder` 第一阶段抽取已完成：服务层调用 `populateActions()` 组装专业组内安全垫修复 action。builder 内部统一处理目标专业组定位、已选/禁用专业排除、安全垫专业选择、组内已满时的替换源选择、partial unresolved blocked/warning，以及 `adjust_major_group_inner_safety` action/replacement pair 字段。builder 复用 `WorkingPlanMutationSupport.findCandidate()` 的候选解析和 `RepairCandidateSelector.isCompensationSafeCandidate()` 的安全候选过滤，避免老 ID 兼容和风险过滤规则再分叉。
- `RepairReplacementActionBuilder` 第一阶段抽取已完成：服务层调用 `populateStructuralReplacementActions()` 处理满容量结构建议，builder 内部再按策略调用 `buildTierRatioReplacementAction()` 和 `buildProbabilityGapReplacementAction()` 生成结构替换 action。builder 统一处理已达目标数判断、add-only 结构动作删除、replacement pair 为空时 blocked、pair 数量裁剪、专业组 unit 到组内专业 volunteer 的映射、`replacementPairs.reasonCodes` 和 remove/add 字段填充，避免 `PlanningStateService` 继续堆叠结构 replacement 入口和 pair 组装细节。
- `RepairDryRunSimulator` 第一阶段抽取已完成：服务层调用 `populate()` 填充 `FixProposalDryRunResultDTO`。simulator 内部区分显式 unit 和由 volunteer 推导的 unit：专业模式 replacement 删除旧 volunteer 后不再保留无引用的派生 unit，专业组模式 ordered/working-plan/action 明确携带的 unit 仍作为显式 unit 保留，避免组内专业调整误改专业组总数。
- `RepairDryRunSimulator` 已补充 `sort_by_probability` 结果模拟：dry-run 快照现在保留 before/after 的 ordered id 顺序，排序模拟按专业模式 `admissionRatio` 升序、专业组模式 unit `schoolEnrollRatio/admissionRatio` 升序处理，并忽略历史 `pinned/pinnedPosition` 兼容字段。该增强只用于验证 proposal 是否真正减少倒挂，不改变真实排序 apply、保存、行为事件和复审编排。
- `RepairDryRunSimulator` 已补充 `fill_probability_gap` 预览质量校验：按修复前后候选录取率序列计算断层数量和最大断层，补入中间录取率候选会被识别为改善；补入断层外候选或 replacement 后仍未缩小断层时，会在 dry-run warning 中提示“没有缩小录取率梯度断层”。该增强只提升预览可信度，不改变 `preview_only` 状态和真实 apply 白名单。
- `RepairDryRunSimulator` 已补充 `rebalance_tier_ratio` 预览质量校验：当候选池存在 `requiredTierCounts` 时，按专业模式 volunteer 粒度、专业组模式 unit 粒度比较修复前后与目标冲稳保数量的距离；如果 replacement/add 预览没有让结构更接近目标，会在 dry-run warning 中提示“没有让冲稳保配比更接近目标”。没有明确目标数量时不使用经验比例强行判断，避免误伤只读预览。
- `RepairReportBuilder` 第一阶段抽取已完成：服务层调用 `build()` 生成 `FixProposalApplyRes.repairReport`。builder 内部统一复制 action detail、dry-run 增删计数、修复前后 review summary、source check 复验结果和结果文案，避免 apply 编排里继续堆叠展示/报告逻辑。
- `WorkingPlanMutationSupport` 第一阶段抽取已完成：服务层委托方法已改为 working-plan 命名，实际实现已由 support 统一处理。该 support 使用与原 `CandidateResolver` 一致的 legacy volunteer prefix 规则，避免专业组下多个专业被误判为同一 volunteer；同时统一专业组 unit 同步、组内专业展示排序、安全垫标记和 summary 按 unit/volunteer 双模式计数。
- `WorkingPlanMutationSupport` 继续承接纯内存构造能力：新增 `buildWorkingPlanItem(candidate, source[, locked])`，统一候选转工作台方案项的字段映射。当前已替换手动加入、补偿加入、修复组内安全垫、老方案导入和初始自动生成里的等价手写构造；未迁移保存、重新生成 ordered plan、复审和报告这些高副作用编排。
- `WorkingPlanMutationSupport` 继续承接受控新增能力：新增 `addWorkingPlanItemIfAllowed(draft, candidate, source[, locked])`，内部统一处理空候选、空 volunteerId、已选重复和 banned volunteer 跳过，并使用 legacy volunteer prefix 兼容老数据。当前已替换手动加入、补偿加入、fix proposal 安全垫补专业三处同构逻辑；老方案导入和初始自动生成仍只调用 `buildWorkingPlanItem()`，不调用 allowed helper，避免改变老方案恢复和初始推荐的既有生成语义。
- `WorkingPlanMutationSupport` 新增共享候选解析：`findCandidate(candidates, volunteerId)` 按精确 volunteerId 优先，legacy volunteer prefix 只在唯一时兼容匹配，重复 prefix 时不猜测。`PlanningStateService` 和 `RepairApplyMutationBuilder` 共用该规则，避免 fix apply、补偿 apply、手动编辑各自维护一套老 ID 兼容逻辑。
- `PlanningStateService` 中抽取后遗留的未使用工作台 tier 计数私有方法已删除；仍保留的 `countWorkingPlanSummaryTotal()` 是删除风险后计算补足数量所需，不属于重复 summary 实现。
- `PlanningStateService` 不再暴露旧补偿应用入口；补齐落盘由 `FixProposal` apply 分支进入 `RepairApplyMutationBuilder`。
- `RepairApplyMutationBuilder` 第一阶段抽取已完成：服务层调用 `applyFixProposalCompensationActions()`、`applyRemoveRiskItems()`、`applyMajorGroupInnerSafety()` 和 `applyWorkingPlanAdditionActions()` 完成内存变更。builder 内部统一复用 `WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed()`、工作台 unit 同步、summary 重算和操作日志构造；服务层不再直接拼 `fix_add_items`、`fix_remove_risk_items`、`fix_major_group_inner_safety` 操作日志。
- `RepairApplyMutationBuilder` 已补齐 `replace_volunteers` 原子内存替换能力：先在临时工作台方案上校验替换动作必须具备完整 remove/add 配对，待移除项必须存在于当前方案，待加入候选必须存在、未被禁用且不会与未移除项重复，校验失败则返回 `blocked` 且不改原方案、不写 operation log；校验通过后一次性 remove + add，并重新同步专业组 unit 和 summary。该能力已接入 `replace_risk_items` 完整配对 apply；结构 replacement 仍未进入 `RepairProposalApplyPolicy.isSupportedStrategy()` 白名单，所以 `rebalance_tier_ratio` / `fill_probability_gap` 仍保持 `preview_only`。
- `RepairProposalApplyPolicy` 第一阶段抽取已完成：服务层调用 `safeRequest()`、`validateRequest()`、`validateStateVersionGuard()`、`ensureReviewReady()`、`validateProposalForApply()` 和 `isSupportedStrategy()` 统一处理 apply 前纯校验与自动应用策略白名单。该类不保存、不变更方案、不生成 ordered plan、不复审；只是把缺少 proposalId、方案版本变化、审查过期、proposal 版本变化、非 ready、preview-only/unsupported 策略这些保护条件从 `PlanningStateService` 迁出，避免 proposal 生成和 apply 校验两边维护不同白名单。
- `PlanningStateService` 内的 fix proposal apply 收尾逻辑已做服务内收口：`saveAndRefreshAfterFixApply()` 统一处理工作台方案保存、可选 ordered plan 重生成；`rerunReviewAfterFixApplyIfRequested()` 统一处理可选复审。该调整只减少 `fill_missing_count`、`remove_risk_items`、`adjust_major_group_inner_safety` 三条分支的重复尾段，`sort_by_probability` 仍复用现有排序入口，不把高副作用编排迁出服务层。
- `ReviewWorkflowStatusResolver` 第一阶段抽取已完成：`runReviewWorkflow()` 的聚合状态映射从 `PlanningStateService` 迁出，复用 `RepairProposalStateBuilder.resolveStateStatus()` 的 proposal 状态汇总。resolver 不读写方案、不生成 proposal、不应用修复，只保证外部 workflow status 和 proposal 聚合状态保持一致。
- `CandidatePoolStatusResolver` 第一阶段抽取已完成：服务层生成候选池、工作台状态展示和候选不足提示共用同一套候选池状态判断。专业组模式优先使用 `requiredUnitCount` 和 `summary.unitTotal`；专业模式使用 `requiredCount` 和 `summary.total`；`requiredCount` 缺失时才回退 `requiredUnitCount`，避免不同入口自己复制数量口径。
- `CandidatePoolQualityStatusBuilder` 第一阶段抽取已完成：服务层生成候选池后调用 builder 统一填充 `statusCode/statusMessage/riskHints`。空候选和低数量候选继续披露目标数量、冲稳保短缺、接近批次线、身体限报和专项资格等风险提示；ready 状态会清空旧提示，避免工作台展示历史脏提示。2026-06-10 已将身体/专项类提示从“已按某条件过滤候选”收口为“可能限制可用候选，需要核验”，避免在没有过滤前后计数时形成伪精确归因。该 builder 只做展示状态构造，不读取外部服务、不改变候选、不影响后续排序和修复 apply。
- `PlanningWorkflowStatusBuilder` 第一阶段抽取已完成：服务层调用 `PlanningWorkflowStatusBuilder.build(state, latestExport)` 生成 `PlanningWorkflowStatusDTO`，并删除旧的 `buildWorkflowStatus/apply*WorkflowStatus` 私有方法。builder 覆盖候选池、方案、审查、导出四段展示状态，其中审查 stale 会保留 `reasonCode/reasonMessage/affectedReviewCodes`，导出 stale 按 latest export 的 `planVersion` 与当前 state version 比较。
- `replace_risk_items` 当前已补齐四类边界回归：全部风险条目有替换项时生成完整 replacement pair 并可应用；部分风险条目有替换项时保留 `preview_only` 并披露 warning，未配对风险仍留在 after 快照；完全没有替换项时进入 `blocked` 且不展示可确认动作；专业组模式下如果单专业替换会改变专业组数量，dry-run 会阻断应用。partial 语义继续保持为不可自动应用，避免用户以为全部风险已修完。
- 结构替换类 proposal 继续锁定为只预览：`rebalance_tier_ratio`、`fill_probability_gap` 在专业模式和专业组模式下即使生成完整 `replace_volunteers` pair，也会被 `applyFixProposal()` 的策略白名单拒绝，不会绕过用户权衡和复审保障直接落盘。

验证：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldPreviewAndApplyCompensation,PlanningStateServiceTest#shouldAvoidRiskyCandidatesAndFillProbabilityGapDuringCompensation,PlanningStateServiceTest#shouldCapCompensationActionsByRemainingGapBeforeApply,PlanningStateServiceTest#shouldFillMissingCountByRequiredTierShortage,PlanningStateServiceTest#shouldNotApplyProtectRatioRebalanceAsAddOnlyWhenPlanIsFull test
```

结果：通过，`Tests run: 5, Failures: 0, Errors: 0, Skipped: 0`。后续补充回归验证时，需要同时覆盖“预览保留建议”和“apply 不超量”两个断言。

Dry-run 目标改善阻断验证：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairDryRunSimulatorTest test
mvn -q -Dtest=WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest test
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateSuggestionMappingTest test
```

结果：通过。覆盖数量缺口修复无改善阻断、条目风险未减少阻断、专业组组内安全垫未补成阻断，以及对应成功路径。

Sort by probability dry-run 结果校验目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldApplySortByProbabilityFixProposalAndRerunReview test
```

结果：通过，`RepairDryRunSimulatorTest` 为 `Tests run: 18, Failures: 0, Errors: 0, Skipped: 0`，并通过服务层 `shouldApplySortByProbabilityFixProposalAndRerunReview`。覆盖专业模式排序后倒挂减少、历史 pinned 不再阻断排序模拟、专业组模式 unit 录取率排序模拟，以及真实 apply 后复审通过。

Probability gap dry-run 预览质量回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairDryRunSimulatorTest test
```

结果：通过，`RepairDryRunSimulatorTest` 为 `Tests run: 18, Failures: 0, Errors: 0, Skipped: 0`。新增覆盖 `fill_probability_gap` 在 `preview_only` 状态下的专业模式和专业组模式预览质量：补入断层中间候选/专业组时保持预览且不追加断层 warning；补入断层外候选/专业组时保持 `preview_only`，但 dry-run warning 会提示没有缩小录取率梯度断层。

Tier ratio dry-run 预览质量回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairDryRunSimulatorTest test
```

结果：通过，`RepairDryRunSimulatorTest` 为 `Tests run: 18, Failures: 0, Errors: 0, Skipped: 0`。新增覆盖 `rebalance_tier_ratio` 在 `preview_only` 状态下的专业模式和专业组模式预览质量：有 `requiredTierCounts` 时，修复后更接近目标配比不追加 warning；没有让目标配比更接近时保持 `preview_only`，但 dry-run warning 会提示冲稳保配比没有改善。

结构替换策略 apply 白名单边界回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldApplySortByProbabilityFixProposalAndRerunReview test
```

结果：通过。新增 `RepairProposalApplyPolicyTest#shouldRejectStructuralReplacementStrategiesUntilExplicitlyAllowlisted`，明确锁定 `rebalance_tier_ratio` / `fill_probability_gap` 即使误生成 `ready` proposal，也不能绕过 apply policy 自动应用；这两类满容量结构 replacement pair 仍只做 `preview_only` 披露。

聚合状态回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldResolveFixProposalStateStatusFromProposalStatuses,PlanningStateServiceTest#shouldRunReviewWorkflowAndReturnFixProposalsWithWorkspaceStatus,RepairDryRunSimulatorTest test
mvn -q -Dtest=WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest test
```

结果：通过。覆盖 proposal state 的 empty / ready / preview_only / blocked_or_info 汇总，以及 review workflow 聚合入口仍按 ready proposal 返回 `ready_to_confirm`。

Working-plan item 构造抽取回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=WorkingPlanMutationSupportTest,PlanningStateServiceTest#shouldApplyFillMissingCountFixProposalWithVersionGuard,PlanningStateServiceTest#shouldApplyRemoveRiskItemsFixProposalAndFillMissingCount,PlanningStateServiceTest#shouldApplyMajorGroupInnerSafetyFixProposalWithinSameUnit test
mvn -q -Dtest=WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest test
```

结果：通过。覆盖候选转工作台项字段映射、重复/禁用 volunteer 跳过，以及手动/补偿/fix apply 依赖的工作台方案同步和应用路径未回退。

Repair apply mutation builder 抽取目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairApplyMutationBuilderTest,WorkingPlanMutationSupportTest,PlanningStateServiceTest#shouldApplyFillMissingCountFixProposalWithVersionGuard,PlanningStateServiceTest#shouldApplyRemoveRiskItemsFixProposalAndFillMissingCount,PlanningStateServiceTest#shouldApplyMajorGroupInnerSafetyFixProposalWithinSameUnit test
```

结果：通过。覆盖 builder 直接处理旧 ID 候选解析、banned volunteer 跳过、风险项删除后补数量、专业组内安全垫替换、`replace_volunteers` 专业模式/专业组模式原子替换和 blocked 不改原方案、working plan summary/unit 同步，以及服务层 fix apply 主路径未回退。

```bash
cd zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false
```

结果：未通过，仍为既有 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts` 类型错误；本轮修改的 `volunteer.ts`、`WorkspacePanel/index.tsx` 未出现在错误列表中。

结构替换预览验证：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate test
```

结果：通过，`Tests run: 2, Failures: 0, Errors: 0, Skipped: 0`。

Selector 抽取前保护测试：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked test
```

结果：通过，`Tests run: 4, Failures: 0, Errors: 0, Skipped: 0`。覆盖专业模式满容量 replacement pair、专业组模式 unit 级 replacement pair、dry run 前后分布，以及 surplus 来源被锁定时不能退回 add-only。

核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 148, Failures: 0, Errors: 0, Skipped: 3`。

Selector 抽取后回归：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked test
```

结果：通过，`Tests run: 4, Failures: 0, Errors: 0, Skipped: 0`。

抽取后核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 148, Failures: 0, Errors: 0, Skipped: 3`。

Selector add 侧迁移后补偿目标测试：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldPreviewAndApplyCompensation,PlanningStateServiceTest#shouldAvoidRiskyCandidatesAndFillProbabilityGapDuringCompensation,PlanningStateServiceTest#shouldCapCompensationActionsByRemainingGapBeforeApply,PlanningStateServiceTest#shouldFillMissingCountByRequiredTierShortage,PlanningStateServiceTest#shouldNotApplyProtectRatioRebalanceAsAddOnlyWhenPlanIsFull test
```

结果：通过，`Tests run: 5, Failures: 0, Errors: 0, Skipped: 0`。

Selector add 侧迁移后核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 148, Failures: 0, Errors: 0, Skipped: 3`。

Selector 直接单测：

```bash
cd zhiyuan-server
mvn -Dtest=RepairCandidateSelectorTest test
```

结果：通过，`Tests run: 5, Failures: 0, Errors: 0, Skipped: 0`。覆盖补数量候选、本省保底优先、专业组保区补充、断层补候选、锁定来源跳过和专业组 unit 级替换来源。

包含 selector 单测后的核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,RepairCandidateSelectorTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 153, Failures: 0, Errors: 0, Skipped: 3`。

Replacement action builder 抽取后目标回归：

```bash
cd zhiyuan-server
mvn -Dtest=RepairCandidateSelectorTest,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked test
```

结果：通过，`Tests run: 9, Failures: 0, Errors: 0, Skipped: 0`。覆盖 selector 直接策略、专业模式满容量替换、专业组 unit 级替换、锁定来源跳过和结构建议不退回 add-only。

Replacement action builder 抽取后核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,RepairCandidateSelectorTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 153, Failures: 0, Errors: 0, Skipped: 3`。

Dry-run simulator 抽取后目标回归：

```bash
cd zhiyuan-server
mvn -Dtest=RepairDryRunSimulatorTest,RepairCandidateSelectorTest,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked test
```

结果：通过，`Tests run: 11, Failures: 0, Errors: 0, Skipped: 0`。覆盖专业模式 replacement dry-run、专业组组内专业替换 dry-run、selector 直接策略和满容量结构替换建议。

Dry-run simulator 抽取后核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 155, Failures: 0, Errors: 0, Skipped: 3`。

Repair report builder 抽取后直接验证：

```bash
cd zhiyuan-server
mvn -Dtest=RepairReportBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldApplyFixProposalAndReturnRepairReport,PlanningStateServiceTest#shouldApplySortFixProposalAndReturnRepairReport,PlanningStateServiceTest#shouldApplyRemoveRiskItemsFixProposal,PlanningStateServiceTest#shouldApplyMajorGroupInnerSafetyFixProposal test
```

结果：通过，`Tests run: 3, Failures: 0, Errors: 0, Skipped: 0`。其中直接验证覆盖 report builder；服务层 apply report 场景继续由完整 `PlanningStateServiceTest` 回归覆盖。

Repair report builder 抽取后核心回归：

```bash
cd zhiyuan-server
mvn -Dtest=ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 156, Failures: 0, Errors: 0, Skipped: 3`。

### 方案工作台状态命名收敛

3.0.x 里用户侧已经取消“草稿”概念，但后端规划状态仍使用 `draftPlanState`、`/session/draft/*` 等历史命名，3.1.0 早期抽取的内部 helper 也曾沿用 `DraftPlanMutationSupport`。3.1.0 起把这层语义收敛为“工作台方案”：

- 新主字段：`workingPlanState`，表示工作台里当前已加入/可编辑的方案状态。
- 旧兼容字段：`draftPlanState` 继续返回并可反序列化，用于老会话、3.0.x 前端、历史脚本和未迁移外部调用兜底；它与 `workingPlanState` 指向同一份状态，不允许双写出不同内容。
- 新主路由：`/session/working-plan/*`。
- 旧兼容路由：`/session/draft/*` 暂时保留并委托同一方法，后续 agent 和外部调用全部迁移后再删除。
- 前端工作台优先读取 `workingPlanState`，旧服务只返回 `draftPlanState` 时 fallback；前端请求已切到 `working-plan` 路由。
- Agent 主路径已切到 `workingPlanState` 兼容 helper 和 `/session/working-plan/*` 内部 client。运行代码中不再直接读取 `draftPlanState`，只有 helper 保留旧字段 fallback；查询解析中仍允许识别用户说“草稿里”这类历史表达，但回复和工具文案统一说“方案/已加入方案”。
- 创建会话断点续填里的 `customerDetailDraft` 是表单缓存，不属于方案状态，本轮不改。
- 已标记旧入口：`PlanningStateDTO` / `PlanningWorkspaceStateRes` 的 `draftPlanState` getter/setter、`PlanningStateService` 旧 `*Draft*` public 方法加 `@Deprecated` 和替代入口说明；`PlanningStateController` 的 `/session/draft/*` 路由加兼容注释。Agent 侧旧 `get_planning_draft`、`select_planning_draft_items`、`query_planning_draft` 等 wrapper 已删除，运行路径统一使用 `working-plan` 命名；后续新增代码不得再扩展 draft 命名。

当前没有直接重命名 `DraftPlanStateDTO`、`DraftItemDTO`、`DraftUnitDTO`、`DraftSelectReq` 等老 DTO，因为它们仍被服务层和持久化兼容链路大量引用。验证中直接把 Java 主字段类型切成 `WorkingPlanStateDTO extends DraftPlanStateDTO` 会触发 FastJSON 在新旧别名同时存在时把旧结构解析成 `DraftPlanStateDTO` 后再 cast 到子类，导致老状态加载失败；因此本轮只更正 JSON/API/前端/agent 主命名，底层 DTO 名称留在兼容层。后续清理顺序应是：服务层 public 方法和 DTO 更名 -> 停返/停收 `draftPlanState` -> 删除 `/session/draft/*`。

本轮 agent/server 命名收敛增量验证：

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/unit/test_request_context_new_fields.py tests/unit/test_planning_workflow_tool.py tests/unit/test_planning_plan_scenarios_sync.py -q
./.venv/bin/python -m pytest tests/unit/test_plan_context_tool.py tests/unit/test_plan_execution_tool.py -q

cd ../zhiyuan-server
mvn -q -DskipTests compile
mvn -q -Dtest=PlanningStateDTOCompatibilityTest test
```

结果：agent 两组分别通过 `72 passed`、`132 passed`；server 编译和 DTO 兼容性测试通过。

Working plan mutation support 抽取后目标回归：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateDTOCompatibilityTest,WorkingPlanMutationSupportTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest test
```

结果：通过，`Tests run: 131, Failures: 0, Errors: 0, Skipped: 3`。覆盖 DTO 新旧字段兼容、空旧别名不清空新字段、手动选择专业组、组内托底审查、修复 apply、legacy volunteer identity 和 working plan summary 同步。

Working plan mutation support 抽取后核心回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,RepairApplyMutationBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 185, Failures: 0, Errors: 0, Skipped: 3`。本轮在原有 DTO 兼容、审查规则、stale 策略、selector、dry-run、report builder、服务层回归基础上，补充覆盖 `RepairApplyMutationBuilder` 的内存 mutation 行为，包括专业模式替换、专业组 unit 替换，以及候选被禁用时 blocked 且原方案不变；同时锁定 `replace_risk_items` 部分配对时只能保持预览态并提示未覆盖风险，结构替换类 proposal 在专业/专业组模式下仍不能通过 apply 入口自动落盘。新增 selector 回归覆盖条目风险替代候选选择的 same-tier、安全过滤、排序和专业组 unit 去重；新增 risk action builder 回归覆盖删除风险 action + fallback 补数量动作，以及部分替换 warning；新增 major-group inner safety builder 回归覆盖组内已满时安全专业替换，以及只有部分专业组可修复时 blocked/warning；proposal 基础字段、strategy、状态汇总和 proposal 查找已迁入 `RepairProposalStateBuilder`，由既有 proposal service 回归覆盖。

Repair proposal apply policy 抽取后目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,PlanningStateServiceTest#shouldRejectExpiredFixProposalApply,PlanningStateServiceTest#shouldRejectFixProposalApplyWhenReviewIsStale,PlanningStateServiceTest#shouldApplyReplaceRiskItemsFixProposalWithVersionGuard,PlanningStateServiceTest#shouldApplyFillMissingCountFixProposalWithVersionGuard test
```

结果：通过。覆盖 apply 请求缺 proposalId、sourceVersion guard 缺失/不匹配、review stale、无审查结果、preview-only unsupported、非 ready、proposal 版本变化、ready unsupported，以及当前允许自动应用的策略。

Repair proposal apply policy 抽取后核心回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，`Tests run: 202, Failures: 0, Errors: 0, Skipped: 3`。新增 `RepairProposalApplyPolicyTest` 直接锁定 apply 入口保护条件和自动应用策略白名单；新增 `RepairReplacementActionBuilderTest` 直接锁定满方案结构建议从 add-only 转 replacement pair、无可替换来源时 blocked 且不保留 add-only 动作；新增 `ReviewWorkflowStatusResolverTest` 直接锁定 workflow 聚合状态映射；服务层回归继续覆盖真实 `applyFixProposal()` 对版本保护、过期审查、unsupported strategy 和补数量落盘路径的行为。

Structural replacement action builder 入口迁移后回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairReplacementActionBuilderTest,RepairCandidateSelectorTest,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked test
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，核心回归为 `Tests run: 202, Failures: 0, Errors: 0, Skipped: 3`。本轮只迁移结构 replacement action 的入口判断和满方案 blocked 保护，不改变 `rebalance_tier_ratio` / `fill_probability_gap` 的 preview-only 状态，也不改变 apply 保存、重排和复审编排。

Workflow status builder 抽取后目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,PlanningStateServiceTest#shouldRunReviewWorkflowAndReturnFixProposalsWithWorkspaceStatus test
```

结果：通过。新增 `CandidatePoolStatusResolverTest` 直接覆盖未生成、空候选、专业模式低数量、专业组模式按 unitTotal 低数量、数量足够和 requiredUnitCount fallback；新增 `CandidatePoolQualityStatusBuilderTest` 直接覆盖空候选 fallback 提示、专业组低数量按 unit 计数、冲稳保短缺、接近批次线、身体限报/专项资格提示和 ready 清理旧提示；新增 `PlanningWorkflowStatusBuilderTest` 直接覆盖候选状态 fallback、方案 empty/selected/dirty/pending_review/ready/legacy_readonly、审查 stale/failed/risk/warning/passed 和导出 not_exported/exported/stale。

Workflow status builder 抽取后核心回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，核心回归为 `Tests run: 217, Failures: 0, Errors: 0, Skipped: 3`。本轮只迁移候选池质量提示和工作台展示状态计算，不改变候选生成、方案排序、修复 proposal 生成、apply 保存、ordered regenerate 或复审编排。

Ordered plan positioning support 抽取和 pin 功能清理：

- `OrderedPlanPositioningSupport` 承接纯内存的排序方案位置计算：`rebuildItems`、`resolveMovableTargetIndex`、`moveWithinUnlockedSlots`、`normalizeIndex`、`normalizePosition`。该 helper 不保存状态、不发事件、不触发审查、不改变排序策略，只让 `PlanningStateService` 内部的移动、删除、排序、聚合重建复用同一套位置规则。
- 已删除 ordered pin/unpin 的用户可触发入口：后端 `/session/ordered-plan/pin`、`/session/ordered-plan/unpin` 和 `OrderedPinReq`；前端 `pinPlanningOrderedItemApi` / `unpinPlanningOrderedItemApi`；agent internal client `pin_planning_ordered_item` / `unpin_planning_ordered_item`；workflow mock/no-op helper；以及 `PlanActionPlan`、ActionResolver、execution 层里的 `pin_unit` / `unpin_unit` 可执行动作分支。
- Agent 侧已继续删除 `planning_workflow_tool.lock_planning_draft_items` no-op wrapper、`internal_client.lock_working_plan_items/lock_planning_draft_items` Python client 和对应 fixture/test 入口；ChatAgent 仍有单测保证 `lock_planning_draft_items` 不注册给模型。Java/Web 的 `/session/working-plan/lock`、`locked` 字段和历史 `pinned/pinnedPosition` DTO 字段暂作为兼容和历史状态保护保留，不作为新的对话动作能力扩展。
- 前端工作台文案不再提示“固定志愿”是可用操作，排序弹窗也不再把固定位置作为当前交互能力披露。
- `pinned` / `pinnedPosition` 字段暂时保留为历史数据兼容和老 `_final` 导入标记：当前移动、排序、修复 dry-run、工作台展示和 agent 回复都不再把它作为位置约束，也不会由当前前端或 agent 创建。老字段只用于历史 JSON/DTO 兼容，后续若确认无外部消费，可单独安排字段退场。
- `working-plan/lock` 属于另一条工作方案兼容接口，本轮不随 ordered pin 一起删除；后续若要退场，应单独按 working-plan legacy 清理，先确认外部兼容窗口。

目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=OrderedPlanPositioningSupportTest,PlanningStateServiceTest#shouldGenerateAndMoveOrderedPlan,PlanningStateServiceTest#shouldAllowMoveLockedOrderedItems,PlanningStateServiceTest#shouldMoveAcrossDraftLockedItemsWithoutTreatingThemAsPinned,PlanningStateServiceTest#shouldIgnoreHistoricalPinnedOrderedItemsWhenMoving,PlanningStateServiceTest#shouldSortMajorPlanByAdmissionRatioAndIgnoreHistoricalPinnedPosition,PlanningStateServiceTest#shouldSortMajorGroupPlanByFinalScoreWithoutBreakingGroupMajors test

cd ../zhiyuan-agent
./.venv/bin/python -m pytest tests/regression/test_execution_preview.py::TestGenericPreviewAnalyzeFallback tests/regression/test_determine_stage.py tests/regression/test_execution_apply.py tests/unit/test_plan_orchestration_tool.py::test_plan_next_action_public_actions_do_not_expose_pin_unpin tests/integration/test_resolver_vs_legacy.py::test_pin_unpin_are_removed_from_structured_intent_frame tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_register_redundant_planning_action_tools -q
./.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py::test_execute_plan_action_runs_move_unit_after_resolving_position_ref tests/unit/test_plan_execution_tool.py::test_execute_plan_action_moves_major_group_unit_by_position_ref tests/integration/test_full_plan_flow.py::TestPendingExpiry::test_custom_max_age tests/unit/test_handler_registry.py tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_register_redundant_planning_action_tools -q
```

结果：server 目标回归通过；agent 两组分别通过 `194 passed`、`22 passed`。覆盖 ordered 位置重建、历史 pinned 仅兼容不约束、锁定项移动保护、专业/专业组排序不回退，以及 pin/unpin 不再暴露为工具 action、handler 或执行分支。

2026-06-10 增量校验：

```bash
cd zhiyuan-server
mvn -q -Dtest=OrderedPlanPositioningSupportTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldGenerateAndMoveOrderedPlan,PlanningStateServiceTest#shouldAllowMoveLockedOrderedItems,PlanningStateServiceTest#shouldMoveAcrossDraftLockedItemsWithoutTreatingThemAsPinned,PlanningStateServiceTest#shouldIgnoreHistoricalPinnedOrderedItemsWhenMoving,PlanningStateServiceTest#shouldSortMajorPlanByAdmissionRatioAndIgnoreHistoricalPinnedPosition,PlanningStateServiceTest#shouldSortMajorGroupPlanByFinalScoreWithoutBreakingGroupMajors test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py -q

cd ..
git diff --check
```

结果：通过。server 覆盖 historical `pinned/pinnedPosition` 不再阻断移动、排序和 `sort_by_probability` dry-run；agent `planning_workflow_tool` 为 `32 passed`，确认排序方案查询不再输出 `[固定]`；`git diff --check` 无空白错误。

包含 ordered positioning 后的 server 核心回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，核心回归为 `Tests run: 222, Failures: 0, Errors: 0, Skipped: 3`。本轮没有改动候选生成、方案生成、导出、修复 apply 保存、ordered regenerate 或复审编排。

Strategy / action / apply 编排边界复核：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull test
```

结果：通过。该回归确认 `rebalance_tier_ratio` / `fill_probability_gap` 是审查修复 strategy，不是最终直接执行的落盘 action；满容量时可以由 `RepairReplacementActionBuilder` 转成 `replace_volunteers` pair 用于预览，但最终 proposal 仍保持 `preview_only`，且 `RepairProposalApplyPolicy` 会拒绝这两类结构策略进入自动 apply 白名单。当前允许自动 apply 的是 `fill_missing_count`、`sort_by_probability`、`remove_risk_items`、`replace_risk_items`、`adjust_major_group_inner_safety`。

2026-06-10 增量复核：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,RepairReplacementActionBuilderTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest,RepairApplyMutationBuilderTest,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier,PlanningStateServiceTest#shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate,PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull,PlanningStateServiceTest#shouldNotApplyProbabilityGapAsAddOnlyWhenPlanIsFull,PlanningStateServiceTest#shouldNotApplyProtectRatioRebalanceAsAddOnlyWhenPlanIsFull test
```

结果：通过。该复核确认当前链路分层仍一致：`ReviewRuleRegistry` 定义规则级 `defaultFixStrategy`；`RepairProposalStateBuilder` 把审查问题和补偿动作组装成 `FixProposalDTO.strategy`；`RepairReplacementActionBuilder` 只在满容量结构建议中把 add-only 补偿动作转换成 `FixProposalActionDTO.actionType=replace_volunteers` 预览；`RepairProposalApplyPolicy` 决定哪些 strategy 可以进入高副作用 apply；`RepairApplyMutationBuilder.applyReplaceVolunteers()` 已作为 `replace_risk_items` 的原子执行能力接入，结构 replacement 仍未接入自动 apply 白名单。

历史旧补偿 apply 旁路保护复核：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldNotApplyProbabilityGapAsAddOnlyWhenPlanIsFull,PlanningStateServiceTest#shouldNotApplyProtectRatioRebalanceAsAddOnlyWhenPlanIsFull test
```

结果：通过。该历史回归确认旧 `applyCompensation()` 当时不会把满方案下的 `rebalance_protect_ratio` 和 `fill_probability_gap` 按 add-only 直接追加到工作台方案。当前旧补偿对外入口已删除，结构性替换仍必须走 `FixProposal` 预览、dry-run 和后续白名单控制。

`cannot_satisfy` 解释增强回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalStateBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldGenerateFixProposalFromCountCompensation,PlanningStateServiceTest#shouldBlockCountFixProposalWhenNoCandidateCanSatisfyShortage,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked test
```

结果：通过。新增 `RepairProposalStateBuilderTest#shouldExplainCannotSatisfyReasonByReviewRule`，锁定结构风险在没有补偿候选时会生成具体的候选不足原因且不可确认；新增 `RepairDryRunSimulatorTest#shouldUseCannotSatisfyBlockingReasonAsDryRunMessage`，锁定 dry-run 展示消息复用同一条规则级 blocking reason，避免退回泛化文案；新增 `PlanningStateServiceTest#shouldBlockCountFixProposalWhenNoCandidateCanSatisfyShortage`，覆盖真实 `generateFixProposals()` 入口在数量缺口且候选池没有可补项时返回 `cannot_satisfy/blocked`、不生成空动作、不允许确认。

`cannot_satisfy` / `blocked` 原因结构化：

- `FixProposalDTO` 新增 `blockingReasonCodes`。`blockingReason` 继续作为面向用户的可读说明保留；`blockingReasonCodes` 只用于前端、Agent、回归测试和后续观测区分阻断类型，不参与候选选择、dry-run 状态判断、apply 白名单、保存、ordered regenerate 或复审编排。
- 这些结构化字段不是从用户自然语言或模型回复里猜出来的。来源分两类：用户动作参数仍由 LLM/tool schema 抽取后交给代码校验；修复阻断原因由 server 根据审查规则、候选选择、replacement pair 构造和 dry-run 目标校验阶段确定性生成。
- `RepairProposalStateBuilder` 统一提供 `markBlocked()` / `addBlockingReasonCode()` / `resolveBlockingReasonCode()`，各修复 builder 不再只散落设置中文 `blockingReason`。当前覆盖：
  - 规则级候选不足：`candidate_pool_insufficient`、`safety_candidate_insufficient`、`tier_candidate_insufficient`、`probability_gap_candidate_insufficient`、`no_sort_or_replacement_candidate`、`major_group_safety_candidate_insufficient`、`risk_item_unresolved_or_replacement_missing`。
  - 执行阶段阻断：`replacement_pair_missing`、`volunteer_model_mismatch`、`risk_unit_unresolved`、`partial_major_group_safety_candidate_missing`、`risk_item_unresolved`、`safe_replacement_candidate_insufficient`。
  - dry-run 目标校验阻断：`objective_validation_not_improved`。
- `CandidateShortageDTO` 已作为第一阶段一等候选不足结构加入 `FixProposalDTO.candidateShortages`，字段包括 `strategy/sourceCheckCode/scope/reasonCode/targetTier/requiredCount/currentCount/shortageCount/availableCount/message`。生成来源是后端确定性状态和阻断原因，不从用户自然语言或模型回复中猜测。
- `ReviewCheckDTO.reasonCode` 已作为审查命中原因加入，并由 `PlanningStateService` 在 review 阶段写入；`generateFixProposals()` 会对历史缺失 reasonCode 的旧 review state 做一次结构化补全，仅根据当前 state 的目标数量、当前数量和冲稳保计数推导，不读取中文展示文案。这样老会话打开修复建议时也不会把“数量超出”误归因为“候选池不足”。
- `RepairCandidateEligibility` 已成为修复候选准入的统一保护层：只有已确认写入 `constraintState.hardConstraints` 的排除/限定地域、院校、专业会收窄修复候选；未确认对话和 `softPreferences` 不会减少候选池。该过滤只作用于修复候选补入/替换，不改变候选池展示、面板筛选、推荐 overlay 或软偏好排序。专业组模式下，候选 item 会先过滤再成组；unit 级补位按 `selectedMajors` 判断实际选入专业，只有 selected 为空时才回退 `allMajors`，避免把未选中的同组专业当成整组不可用。
- `candidateShortages.scope=hard_constraints` 采用双口径比较生成：如果不应用硬要求时可用候选足够、应用已确认硬要求后不足，才归因为硬要求收窄；否则仍保持 `candidate_pool`、`capacity_or_replacement` 或 `objective_validation` 等范围，避免把候选池本身不足误说成用户要求导致。
- Agent `_fix_proposal_facts()` 已透传 `candidate_shortages`，`generate_planning_fix_proposals` 工具直出和 `analysis_handlers` 审查回复会优先展示结构化候选边界，例如“当前可用于规划的候选池里，断层中间录取率候选不足”。旧 `blockingReasonCodes` 仍作为兼容兜底。
- Agent `_fix_proposal_facts()` 已透传 `blocking_reason_codes`；PC 前端接口类型 `PlanningFixProposal` 已补 `blockingReasonCodes?: string[]`。当前 UI 仍以服务端 status/blockingReason 为主，不基于 code 自行判断可执行性。
- PC 前端接口类型已补 `PlanningCandidateShortage` 和 `PlanningFixProposal.candidateShortages?: PlanningCandidateShortage[]`。2026-06-10 起工作台修复弹窗已结构化展示候选不足说明，继续保持只读解释语义，不改变 selector、dry-run 状态判断、apply 白名单或保存编排。
- 这次增强解决的是“为什么修不了/为什么不能确认”的一等可观测性问题，不改变“能不能自动修、选哪个候选、能否落盘”的业务判断。

结构化阻断原因目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldBlockCountFixProposalWhenNoCandidateCanSatisfyShortage test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_formats_status_and_warnings -q
```

结果：通过。server 覆盖规则级 `cannot_satisfy`、满方案 replacement pair 缺失、专业组内安全垫部分可修复、dry-run 目标未改善和真实 `generateFixProposals()` 入口；Agent 覆盖 `blockingReasonCodes` 到 `blocking_reason_codes` 的透传。

2026-06-10 `candidateShortages` 边界回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairDryRunSimulatorTest#shouldBlockCountValidationWhenPreviewDoesNotMoveTowardRequiredCount,PlanningStateServiceTest#shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked+shouldExplainTierRatioShortageAsCandidatePoolScopeWhenNoTargetTierCandidateExists+shouldExplainProbabilityGapShortageAsCandidatePoolScopeWhenNoMiddleCandidateExists test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_formats_status_and_warnings tests/unit/test_plan_execution_tool.py::test_execute_plan_action_review_reply_includes_backend_fix_proposals -q
```

结果：通过。新增确认五类用户侧容易混淆的边界：数量缺口没有可补项时输出 `scope=candidate_pool`；`rebalance_tier_ratio` 缺目标 tier 候选时输出 `scope=candidate_pool` 且明确 target tier；`fill_probability_gap` 缺断层中间候选时输出 `scope=candidate_pool`；方案已满但缺少一进一出配对时输出 `scope=capacity_or_replacement`，不说成候选池全量不足；dry-run 后目标没有改善时输出 `scope=objective_validation`，不把无改善预览当成可执行修复。Agent 侧旧 `blockingReasonCodes` 兜底文案也统一限定为“当前可用于规划的候选池”，避免表达成全国或高途全量没有。

2026-06-10 候选来源摘要观测回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairCandidateSelectorTest,PlanningStateServiceTest test
```

结果：通过。`CandidatePoolStateDTO.sourceSummary` 已在候选池生成和 legacy 候选池构建中填充，workspace 响应会透传原候选池来源摘要。新增回归锁定专业组/专业模式下 entry 和 unit 统计口径：外部返回 entry/unit、服务端规范化后 entry/unit、冲稳保 entry/unit 计数均按现有 `resolveInitialRecommendationUnitId` 口径计算。该字段只做来源规模观测，不参与 selector、proposal、dry-run、apply、保存、ordered regenerate 或审查编排。

2026-06-10 候选筛选视图统计回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldExcludeCandidatePoolItemsByNegativeFilters test
```

结果：通过。`CandidatePoolQueryRes.viewSummary` 已返回完整候选池 entry/unit 总量、当前筛选视图 entry/unit 总量和分页加载 entry/unit 数；原有 top-level `total/totalUnitCount/loadedEntryCount/loadedUnitCount` 仍保持当前筛选视图口径。该字段只做查询观测，暂不参与 `candidateShortages.scope=current_view`、修复候选选择、proposal、dry-run 或 apply。

2026-06-10 当前筛选视图不参与结构修复 selector 回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier+shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate test
```

结果：通过。新增确认两类结构策略的边界：候选面板当前筛选视图可以命中 0 条，但 `generateFixProposals()` 默认仍基于完整规划候选池和已确认硬要求；`rebalance_tier_ratio` 仍可从完整候选池找到保区 replacement pair，`fill_probability_gap` 仍可从完整候选池找到断层中间录取率 replacement pair；两者都不会输出 `candidateShortages.scope=current_view`，避免把用户当前筛选视图不足误归因为审查修复候选不足。

2026-06-10 已确认硬要求过滤回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairCandidateSelectorTest,PlanningStateServiceTest#shouldAttributeFixProposalShortageToConfirmedHardConstraints+shouldAttributeTierRatioShortageToConfirmedHardConstraints+shouldAttributeProbabilityGapShortageToConfirmedHardConstraints test
```

结果：通过。新增确认修复候选选择层会过滤已确认硬排除地域/专业；软偏好不参与过滤；专业组 unit 级补位优先看 `selectedMajors`，仅在 selected 为空时用 `allMajors` 兜底；真实 `generateFixProposals()` 入口在“候选池原本有可补项，但已确认硬要求过滤后不可用”时输出 `candidateShortages.scope=hard_constraints`。服务级回归同时覆盖数量缺口、`rebalance_tier_ratio` 缺目标 tier 候选、`fill_probability_gap` 缺断层中间候选三类场景，确认硬要求归因不是只在补数量路径成立。该改动仍不开放 `rebalance_tier_ratio` / `fill_probability_gap` 自动 apply。

Agent 审查/调整回复消费结构化阻断原因：

- `analysis_handlers._fix_proposal_lines()` 已读取 `blocking_reason_codes` 并映射为用户可理解的处理边界，例如候选池不足、断层中间录取率候选不足、方案已满但缺少一进一出替换配对、专业组内缺少安全垫专业、预览没有让审查目标变好等。
- 该映射只发生在回复汇总层，不参与路由、候选选择、proposal 状态计算、dry-run、apply 白名单或保存。这样可以提升用户侧解释质量，同时不把高副作用决策下放给文案。
- `next_step_hints` 也会在存在 blocked proposal 时提醒最终回复不要承诺自动补齐或自动替换，而是先解释系统不能直接执行的边界。
- `planning_workflow_tool._fix_proposal_blocking_guidance()` 已同步优先消费 `candidateShortages`。`hard_constraints`、`capacity_or_replacement`、`objective_validation` 这类结构化 scope 会优先展示；普通 `candidate_pool` 不压掉更具体的 `blockingReasonCodes` 文案，继续保留“断层中间录取率候选不足/目标冲稳保区间候选不足”等细粒度说明。

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_formats_status_and_warnings tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_prefers_hard_constraint_shortage_guidance tests/unit/test_plan_execution_tool.py::test_execute_plan_action_review_reply_includes_backend_fix_proposals -q
```

结果：通过。新增确认 Agent 工具直出在 `candidateShortages.scope=hard_constraints` 时展示“已确认的硬性要求收窄了可选范围”，不会再被旧 `blockingReasonCodes=tier_candidate_insufficient` 泛化成普通候选池不足；同时原有 `candidate_pool` 断层不足仍保留更具体的梯度文案。
- 新增 Agent 回归覆盖 `review_plan` 直接回复包含后端 `fix_proposals` 时，会同时展示 `preview_only` 的可处理方向和 `blocked` 的结构化边界说明，避免只显示“暂不能自动处理”的泛化状态。
- `generate_planning_fix_proposals` 工具直出也已消费 `blockingReasonCodes`，在 `blockingReason` 之后追加“处理边界”说明。这样用户通过审查 handler 或直接生成修复建议两条路径看到的 blocked 解释保持一致。

目标回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py::test_execute_plan_action_review_reply_includes_backend_fix_proposals tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_formats_status_and_warnings -q
```

结果：通过，`2 passed`。

包含 `cannot_satisfy` 解释增强后的 server 核心回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，核心回归为 `Tests run: 235, Failures: 0, Errors: 0, Skipped: 3`。本轮只增强无法修复时的说明文案和 blocking reason，不改变 selector、dry-run 状态机、apply 白名单、保存、ordered regenerate 或复审编排。

修复报告解释字段贯通：

- `RepairReportDTO` 已透传本次应用的 `proposalTitle`、`proposalSummary`、`proposalImpact`、`dryRunStatus`、`dryRunMessage`，用于解释“修的是哪条建议、对应什么问题、影响范围和应用前预览”。
- `RepairReportBuilder` 从已确认应用的 `FixProposal` 和 dry-run 结果中填充这些字段；字段只读，不参与候选选择、dry-run 状态判断、apply 白名单、保存或复审编排。
- Agent `apply_planning_fix_proposal` 的返回文案同步展示修复建议、对应问题、影响范围和应用前预览，避免只返回泛化的“已应用修复建议”。
- PC 工作台“方案修复建议”弹窗中的最近一次修复结果同步展示这些解释字段，同时保留新增/移除数量、风险提醒前后变化、动作明细和 warning。

目标回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairReportBuilderTest test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py::test_apply_planning_fix_proposal_formats_repair_report -q
```

结果：通过。server 覆盖报告字段、dry-run message、动作明细、复验结果和 warning；agent 覆盖修复结果文案会输出修复建议、对应问题、影响范围、应用前预览、数量变化和复验状态。

包含旧补偿 apply 旁路保护和修复报告解释字段后的 server 核心回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过，核心回归为 `Tests run: 236, Failures: 0, Errors: 0, Skipped: 3`。当时新增的旁路保护确认满方案时不会执行 `fill_probability_gap` add-only；当前外部旧补偿入口已删除，保护重心落在 `FixProposal` 生成、replacement pair 预览、apply 白名单、保存、ordered regenerate 和复审编排。

前端类型检查：

```bash
cd zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false
```

结果：未通过，错误集中在既有 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts`，本轮修改的 `WorkspacePanel/index.tsx`、`volunteer.ts` 和 `sessionDetail.ts` 未出现在错误列表中。

剩余边界：

- `rebalance_tier_ratio` / `fill_probability_gap` 满容量 replacement pair 目前只作为 `preview_only` 披露，尚未进入自动 apply。底层 `replace_volunteers` 原子内存替换已具备，但还未接入高副作用 apply 入口。
- `RepairCandidateSelector` 当前已覆盖事后结构修复的 remove source 选择、补偿预览 add 候选选择和当前方案目标数判断；`RepairReplacementActionBuilder` 已覆盖满容量结构 replacement pair 组装和结构建议入口保护；`RepairDryRunSimulator` 已覆盖 dry-run 计数和快照模拟；`RepairReportBuilder` 已覆盖应用后报告构建；`WorkingPlanMutationSupport` 已覆盖 legacy volunteer identity、unit 同步和 summary 重算；`RepairApplyMutationBuilder` 已覆盖当前可 apply 策略的工作台方案内存 mutation；`RepairProposalApplyPolicy` 已覆盖 apply 入口纯校验和策略白名单；`ReviewWorkflowStatusResolver` 已覆盖 review workflow 聚合状态映射；`CandidatePoolStatusResolver` 已覆盖候选池状态和专业/专业组数量口径；`CandidatePoolQualityStatusBuilder` 已覆盖候选池质量提示展示；`PlanningWorkflowStatusBuilder` 已覆盖工作台展示状态。自动 apply 的保存、ordered regenerate、rerun review、response report 编排仍在 `PlanningStateService`，后续再逐步迁出，避免同时改变高副作用执行语义。
- dry run 已输出修复前后总量、冲稳保分布、ID 快照和质量取舍快照，并补充硬要求/软偏好、新增风险、质量下降 warning；数量、条目风险、专业组组内安全垫、录取率倒挂排序已具备目标改善阻断。冲稳保重平衡、梯度断层已具备 preview 质量校验和无改善 warning，但 `rebalance_tier_ratio` / `fill_probability_gap` 仍保持 `preview_only`，暂不作为自动 apply 白名单策略。

当前最终边界：

- `pin/unpin` 已从用户可触发能力中退场。前端、Agent、后端 controller 不再暴露 pin/unpin 操作；`pinned/pinnedPosition` 仅作为历史 JSON/DTO 兼容字段保留，不参与移动、排序、dry-run、候选替换来源选择、工作台展示或 Agent 回复。
- 审查修复链路以 `review -> fix-proposals -> apply -> repair-report` 为主路径。`applyFixProposal()` 仍是唯一正式高副作用修复入口，必须通过 `RepairProposalApplyPolicy` 的版本、stale、proposal status 和 strategy 白名单校验。
- `applyFixProposal()` 的真实执行分支只显式支持 `fill_missing_count`、`sort_by_probability`、`remove_risk_items`、`replace_risk_items`、`adjust_major_group_inner_safety`；没有默认“按补偿动作落盘”的兜底分支。后续如果扩展白名单，必须同步补执行分支和回归测试，否则服务端仍会拒绝应用。
- `rebalance_tier_ratio` / `fill_probability_gap` 当前是结构性修复 strategy，不是可直接落盘 action。即使已经生成 `replace_volunteers` replacement pair，也只用于 `preview_only` 披露和 dry-run 说明，不进入自动 apply。
- `replace_volunteers` 已具备底层原子内存替换能力，并作为 `replace_risk_items` 的执行动作接入白名单。当前底层已锁定完整配对保护：remove/add 必须数量一致且非空，replacement pair 不能缺 from/to，待移除项必须在当前方案中，待补入候选必须存在且未被禁用/重复；任何校验失败都会 `blocked` 且不改原方案、不写 operation log。
- `replace_volunteers` 的 dry-run 与真实 apply 已按场景对齐字段语义：条目风险 `scopeKind=item` 只把 volunteer pair 当成执行语义，unit 字段只用于披露；结构替换仍把显式 unit pair 纳入计数、before/after 快照和 warning 候选解析。这样避免专业组条目风险在预览中被误当成整组替换。
- 旧 `applyCompensation()` 对外入口已删除；补数量/有剩余容量补候选的执行语义只在 `FixProposal` apply 分支内部复用。满方案结构调整不能通过旧补偿入口按 add-only 绕过 `FixProposal` 的 `preview_only` 边界。

当前最终边界回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py -q
```

结果：通过。server 当前核心回归为 `Tests run: 245, Failures: 0, Errors: 0, Skipped: 3`；agent `planning_workflow_tool` 为 `32 passed`。覆盖 `pin/unpin` 用户入口退场、历史 `pinned/pinnedPosition` 不再作为约束、审查/fix proposal/apply/report 主链路、apply 白名单、满容量结构替换只预览、旧补偿入口容量保护、`replace_volunteers` 底层原子保护、专业/专业组双模式 dry-run 和 report 展示。

后续退场方向：

- 旧 `POST /session/compensation/apply` 对外入口已删除；补齐落盘能力只通过 `fix-proposals/apply` 的显式 strategy 白名单进入。内部 helper 已改为 `applyWorkingPlanAdditionActions` 这类中性命名，避免误解为旧 API 仍存在。
- `PlanningStateService` 仍承接保存、ordered regenerate、rerun review 和 response report 编排。短期不再继续拆高副作用 service，避免在结构修复自动 apply 尚未开放前扩大行为面；当前 `replace_risk_items` 已在完整配对、dry-run 复验通过时接入 apply 白名单，结构替换仍保持预览。后续重点转为前端/Agent 场景验证，以及在产品明确允许后再设计 `rebalance_tier_ratio`、`fill_probability_gap` 等结构替换进入白名单的完整复验标准。

兼容补偿入口退场标记回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,PlanningStateServiceTest#shouldNotApplyProbabilityGapAsAddOnlyWhenPlanIsFull,PlanningStateServiceTest#shouldNotApplyProtectRatioRebalanceAsAddOnlyWhenPlanIsFull test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/regression/test_execution_apply.py tests/unit/test_plan_execution_tool.py::test_execute_plan_action_blocks_compensation_apply_when_plan_is_already_full tests/unit/test_plan_execution_tool.py::test_execute_plan_action_allows_major_group_compensation_apply_when_unit_gap_matches tests/unit/test_planning_workflow_tool.py -q

cd ..
git diff --check
```

结果：通过。server 目标回归为 `RepairProposalApplyPolicyTest: 11 passed`、`PlanningStateServiceTest: 2 passed`；agent 目标回归为 `70 passed`；`git diff --check` 无空白错误。该变更只标记旧补偿入口的兼容定位，不改变补偿 apply 执行、FixProposal apply 白名单、结构替换 preview-only 边界或 Agent 高副作用确认协议。

`replace_volunteers` 底层原子保护回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest test
```

结果：通过，`RepairApplyMutationBuilderTest: 10 passed`、`RepairProposalApplyPolicyTest: 11 passed`。新增覆盖缺少待移除项、补入候选不存在、remove/add 数量不一致、replacement pair 缺 from/to 时均 `blocked`，且原工作台方案和 operation log 不变化；同时继续确认 `RepairProposalApplyPolicy` 未把结构替换策略加入自动 apply 白名单。

`replace_volunteers` 自动应用前置保护补充回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairApplyMutationBuilderTest,RepairDryRunSimulatorTest,RepairProposalApplyPolicyTest test
```

结果：通过，`Tests run: 45, Failures: 0, Errors: 0, Skipped: 0`。新增覆盖只携带 `replacementPairs` 的专业模式替换、只携带 `replacementPairs` 的专业组模式替换，以及补入项仍留在当前方案中时必须 `blocked` 且不改原方案、不写 operation log。该回归只补自动应用前置安全网，不把 `replace_volunteers` 加入 `RepairProposalApplyPolicy` 白名单。

`replace_volunteers` dry-run / apply 字段语义对齐回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairDryRunSimulatorTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest test
```

结果：通过，`Tests run: 45, Failures: 0, Errors: 0, Skipped: 0`。新增覆盖专业模式和专业组模式下只携带 `replacementPairs`、不携带显式 remove/add 列表的 `replace_volunteers` action，确认 dry-run 的增删数量、before/after volunteer ids、before/after unit ids 和冲稳保分布都能正确变化；同时复跑真实 apply mutation 和 apply policy，确认该语义对齐不改变自动 apply 白名单。

`replace_risk_items` 服务级自动应用边界回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldGenerateReadyReplaceRiskProposalForMultipleRiskItems,PlanningStateServiceTest#shouldKeepPartialReplaceRiskProposalPreviewOnlyWithWarning,PlanningStateServiceTest#shouldApplyReplaceRiskItemsFixProposalWithVersionGuard test
```

结果：通过。服务级断言覆盖完整多条替换、部分替换预览和真实 apply 三种情况：完整 `replace_risk_items` 生成 `replace_volunteers` pair 后可通过 `applyFixProposal()` 落盘；部分替换仍保持 `preview_only`，不能应用。该回归锁定“完整覆盖 + version guard + dry-run 复验”才是可执行修复，避免后续误把部分替换或结构替换绕过用户权衡、版本保护和复验机制。

`applyFixProposal()` 执行侧无默认兜底回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,PlanningStateServiceTest#shouldApplyReplaceRiskItemsFixProposalWithVersionGuard,PlanningStateServiceTest#shouldApplyFillMissingCountFixProposalWithVersionGuard,PlanningStateServiceTest#shouldApplySortByProbabilityFixProposalAndRerunReview,PlanningStateServiceTest#shouldApplyRemoveRiskItemsFixProposalAndFillMissingCount,PlanningStateServiceTest#shouldApplyMajorGroupRemoveRiskItemsWithoutFillingWhenUnitCountIsKept,PlanningStateServiceTest#shouldApplyMajorGroupRemoveRiskItemsAndFillOnlyWhenUnitCountDrops,PlanningStateServiceTest#shouldApplyMajorGroupInnerSafetyFixProposalWithinSameUnit test
```

结果：通过。覆盖当前可应用策略仍可正常保存、排序、复审或报告；同时确认结构替换等未支持 strategy 不会落入旧补偿兜底。

Agent internal client 兼容入口清理：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/util/internal_client.py
rg -o "^async def [A-Za-z0-9_]+" app/util/internal_client.py | sed 's/^async def //' | sort | uniq -d
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py::test_apply_planning_fix_proposal_requires_confirmation tests/unit/test_planning_workflow_tool.py::test_apply_planning_fix_proposal_formats_repair_report tests/unit/test_planning_workflow_tool.py::test_generate_planning_ordered_plan_requires_confirmation tests/unit/test_planning_workflow_tool.py::test_generate_planning_ordered_plan_formats_ordered_state tests/unit/test_planning_plan_scenarios_sync.py::test_planning_scenario_rejects_legacy_apply_compensation_action_family tests/unit/test_planning_plan_scenarios_sync.py::test_planning_scenario_generate_ordered_plan_requires_confirmation_in_workflow -q
```

结果：通过。`internal_client.py` 中被后续同名多租户函数覆盖的旧单租户 `run_planning_review`、`generate_planning_ordered_plan` 已清理；后续又删除了 Agent Python 侧 `preview_planning_compensation/apply_planning_compensation` wrapper。重复 async 函数扫描无输出，`py_compile` 通过，目标回归覆盖 FixProposal apply 防护、排序生成确认和旧 `apply_compensation` payload 拒绝。该清理降低新旧入口混杂导致的维护误判。

结构替换自动应用开放前置条件：

- 只允许完整 replacement：所有风险项或结构缺口必须有明确 from/to 配对，partial replacement 继续保持 `preview_only` 或 `blocked`。
- apply 前必须重新生成 proposal，并用 `sourceVersionGuard`、proposal `sourceVersionGuard`、review stale 状态共同校验，避免用户基于旧方案确认。
- mutation 必须保持容量不变：专业模式保持志愿数不变，专业组模式保持 unit 数不变；组内专业替换则保持目标 unit 不丢失。
- dry-run 后必须证明目标改善：条目风险命中减少、冲稳保配比更接近目标、梯度断层缩小或概率倒挂减少；无改善时不得 apply。
- 硬要求和负偏好不能被新候选破坏；如果替换会引入高收费、限报、中外合作、特殊类型招生或明显质量下降，需要继续作为 warning 披露，必要时保持只预览。
- apply 后必须保存、可选 regenerate ordered plan、可选 rerun review，并在 `RepairReportDTO` 中展示修复前后变化、未覆盖风险和 warning。

Agent Plan 编排层去字符串兜底：

背景：

- 3.0.3 到 3.1.0 的路由原则已经明确：用户自然语言由模型理解并产出结构化动作，后续编排层只消费结构化字段，不再靠零散中文关键词补丁继续猜路由。
- 本轮检查发现 `plan_next_action` 中仍保留几类历史兼容逻辑：
  - 从 `user_goal` 里的“高收费/中外合作/太贵/去掉/替换”等片段恢复 `review_issue_code` 和动作族。
  - 从 `user_goal` 或 `preview_summary` 里的“推荐系数/院校层次/录取率”推断 `sort_field`。
  - 从 `user_goal` 的“往前/前挪”等片段判断是不是范围移动，进而纠正误传的 `sort_ordered_plan`。
- 这些逻辑能兜住少量 case，但维护成本高，且容易在口语化表达变化时误触发；更重要的是，它会让“模型结构化输出”和“编排层字符串补丁”两套判断长期并存。

本轮已完成：

- 删除 `plan_next_action` 中基于 `user_goal` 的审查问题恢复逻辑：
  - 缺少 `review_issue_code` 时，不再从中文片段猜 `high_tuition`、`cooperative_program`、`admission_limit` 或 `special_enrollment`。
  - 用户确实要按审查问题整批处理时，上游必须显式传 `review_issue_code` 和必要的 `review_issue_scope_mode`；否则会停留在只读审查、补偿预览或缺参分析，不会误生成整批删除/替换预览。
- 删除 `plan_next_action` 中基于原话推断排序字段的逻辑：
  - `sort_ordered_plan` 必须显式传 `sort_field`。
  - 缺 `sort_field` 时返回缺参分析，不生成排序预览。
- 删除执行层从 `user_goal` / `preview_summary` 推断排序字段的兜底：
  - `execute_plan_action` 只读取 `atomic.filters.sort_field/sortField/field`。
  - 如果历史 payload 没有排序字段，执行层按安全默认 `admissionRatio` 处理，不再从自然语言里猜。
- 新增结构化范围保护：
  - 如果 `sort_ordered_plan` 同时携带 `province_keyword`、`school_keyword`、`major_keyword`、`school_tags`、`major_tags` 等局部筛选范围，说明它不是全方案排序请求。
  - 编排层会降级为 `query_ordered`，先查看当前方案命中范围，避免把“把北京/某专业方向往前挪”误执行成全方案排序。
- 保留实体解析能力，但限定为“对象解析”而不是“路由判断”：
  - 加入、移动、删除时，`volunteer_ids` 可以继续携带用户原始学校+专业引用，执行层通过 `resolve_school_major_ref` 去唯一定位真实候选或方案项。
  - 这类解析只负责定位对象；不负责决定动作族、审查问题 code、排序字段或是否应用高副作用动作。
- 补齐 `add_units` 的结构化缺参保护：
  - `add_units` 必须显式携带 `volunteer_ids`，或携带 `province_keyword` / `school_keyword` / `major_keyword` / 标签等结构化筛选范围。
  - 如果模型只给了 `user_goal`，没有把候选目标或筛选范围结构化出来，编排层返回 `selection_scope` 缺参，执行层也会阻断，不再从整句自然语言里反推“学校+专业”引用。
  - 已经传入 `volunteer_ids` 的自然语言引用仍可被解析成真实候选 ID；这是对象定位，不是动作参数补全。

当前行为边界：

- 结构化字段来源：
  - 主来源是模型按 tool schema 输出的字段，例如 `action_family`、`volunteer_ids`、`source_position`、`target_position`、`review_issue_code`、`sort_field`、`filters.major_keyword` 等。
  - 只读查询类工具可以使用上游结构化抽取工具输出的 filters；但落到方案增删改排序时，执行层仍按结构化字段校验。
  - 代码层只做字段归一、对象唯一性解析和安全校验，不再从整句 `user_goal` 里补动作参数。
- 路由/动作族、审查问题、排序字段、位置语义必须来自结构化字段。
- 如果模型没有把用户意图结构化完整，系统应返回缺参、只读审查或查询范围，不再通过字符串兜底自动升级为方案修改。
- ChatAgent 主工具列表仍未开放 `apply_planning_fix_proposal`，不会让模型直接调用 `fix-proposals/apply`；前端工作台仍是当前轻量确认入口。
- `apply_planning_fix_proposal` 底层工具继续保留 `user_confirmed` 防护，并由后端 `RepairProposalApplyPolicy` 进行版本、stale、status 和 strategy 白名单校验。

本轮验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py::test_execute_plan_action_sort_preview_includes_distribution_and_examples tests/unit/test_plan_execution_tool.py::test_execute_plan_action_sort_preview_defaults_to_admission_ratio_when_filters_missing tests/unit/test_plan_execution_tool.py::test_execute_plan_action_sort_preview_uses_candidate_facts_for_flat_items -q
.venv/bin/python -m py_compile app/tools/plan_orchestration_tool.py app/tools/plan_execution_tool.py
.venv/bin/python -m pytest tests/regression/test_keyword_matchers.py tests/integration/test_resolver_vs_legacy.py tests/unit/test_action_resolver.py -q
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py tests/regression/test_execution_preview.py tests/regression/test_execution_apply.py -q
```

结果：通过。目标编排/排序回归 `47 passed`；结构化 resolver 回归 `177 passed`；执行层 preview/apply 回归 `252 passed`。该变更收掉的是 Plan 编排层的字符串路由兜底，不改变候选实体解析、已确认 pending 执行、FixProposal apply 白名单、旧补偿容量保护或前端 `ready/preview_only` 展示边界。

`add_units` 结构化缺参保护补充回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py tests/regression/test_execution_preview.py -q
.venv/bin/python -m pytest tests/unit/test_planning_plan_scenarios_sync.py -q
```

结果：通过。新增边界确认：模型漏传 `volunteer_ids` 且没有结构化筛选范围时，`plan_next_action` 和 `execute_plan_action` 都会以缺少 `selection_scope` / 缺少候选范围阻断；显式传入 `volunteer_ids` 的候选引用仍可解析为真实候选 ID 并生成确认预览。旧 `handle_planning_request(candidate_select)` 已删除，不再作为兼容验证入口。

项目/招生类型 scope 长期收口：

背景：

- 回归发现“中外合作的都排除掉，当前方案里有的话先移出去”不能继续靠短期别名补丁处理。
- `中外合作` 在不同语境里可能是“审查里的中外合作提醒”，也可能是用户明确报考条件“不接受中外合作项目”。
- 如果一律映射到 `review_issue_code="cooperative_program"`，会把长期报考要求和审查修复问题混在一起；如果一律当专业名，又会出现“具体专业：中外合作”。

本轮已按长期结构实现：

- 新增 canonical scope：`program_type`，兼容 `admission_type`、`project_type`、`enrollment_type`、`program`、`project`。
- `program_type` 表示招生项目或培养项目类型，例如中外合作办学、国际项目、校企合作、单列专业等。
- 用户表达“不接受/排除/移出中外合作项目”时，上游模型应输出：

```json
{
  "plan_goal_type": "exclude_scope",
  "goal_negative_scopes": [
    {"entity_type": "program_type", "values": ["中外合作办学"]}
  ]
}
```

- `plan_next_action` 会把该 scope 合并到 `remove_units` 的结构化 filters：`program_types=["中外合作办学"]`。
- `execute_plan_action` 按结构化项目类型匹配当前方案项，匹配院校名、专业名、专业组/候选标签、风险标记、原因 code 等字段；命中后生成确认预览，确认前不改方案。
- 确认后除执行当前方案调整外，还会把 `physical_constraints.special_limits=["不接受中外合作办学"]` 写入规划状态，作为后续报考参考。
- Java `UserGoalProposalBuilder.ScopeMatcher` 同步支持 `program_type`，用户目标型 `FixProposal` 按同一范围匹配当前方案和候选。

审查 issue 边界：

- 只有模型显式输出 `review_issue_code="cooperative_program"`，或上下文明确是“处理审查里的中外合作提醒/风险”时，才走审查问题链路。
- 没有显式 `review_issue_code` 时，编排层不再从中文片段自动猜 `cooperative_program` / `high_tuition`。
- 高收费仍按语义区分：有明确预算上限时走 `tuition_budget_scope`；承接审查高收费提醒时走 `review_issue_code="high_tuition"`；普通结构化标签不会被编排层偷换成审查 issue。

本轮新增保护：

- `test_plan_next_action_exclude_program_type_builds_executable_remove_scope`
- `test_execute_plan_action_remove_program_type_scope_preview_and_intent_update`
- `test_composite_goal_decision_accepts_program_type_scope`
- `UserGoalProposalBuilderTest.shouldBuildExcludePreviewForProgramTypeScope`
- 旧“结构化字段自动归一到审查 issue”的测试已改为防回退测试，确保没有显式 `review_issue_code` 时不会自动偷换语义。

本轮聚焦验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_semantic_action_tool.py -q
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py tests/unit/test_intent_state_tool.py tests/unit/test_dialog_regression_runner.py -q

cd ../zhiyuan-server
mvn -q -Dtest=UserGoalProposalBuilderTest test
```

结果：Agent 方案编排/执行/semantic 聚焦回归 `195 passed`；服务层和意向/pending 相关回归 `532 passed`；Server `UserGoalProposalBuilderTest` 通过。

初始推荐取舍说明补充回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldRepairInitialRecommendationProbabilityGap+shouldFullyRepairInitialRecommendationProbabilityGapWhenCandidateWindowIsEnough+shouldRepairInitialPlanMajorGroupIssuesBeforePlanAdjustmentAnalysis test
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test

cd ..
git diff --check
```

结果：通过。新增断言覆盖 `InitialPlanStrategyReportDTO.objectiveWeights`、`actions`、`tradeoffs` 和 `AppliedRepair.tradeoffSummary`，确认生成阶段会披露相对目标优先级、只读 `replace_volunteers` 动作、自动替换收益、取舍和 from/to 信息；同时回归审查、修复 proposal、候选不足、stale、working plan 兼容和 initial recommendation 主链路。这些字段只用于解释和前端轻量展示，不改变候选选择、排序、dry-run、FixProposal apply 白名单或保存编排。

综合回归补充：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_instructions.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_planning_plan_scenarios_sync.py tests/unit/test_action_resolver.py tests/regression/test_keyword_matchers.py tests/regression/test_execution_apply.py tests/regression/test_execution_preview.py tests/integration/test_resolver_vs_legacy.py -q

cd ../zhiyuan-server
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test

cd ../zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false

cd ..
git diff --check
```

结果：

- Agent planning/路由/执行相关回归通过：`590 passed`。
- Server 方案审查/修复核心回归通过：`Tests run: 247, Failures: 0, Errors: 0, Skipped: 3`。
- `git diff --check` 通过。
- 前端全量 typecheck 仍未通过，但错误集中在既有 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts`；本轮涉及的 `WorkspacePanel/index.tsx`、`volunteer.ts`、`sessionDetail.ts` 未出现在错误列表中。

`replace_risk_items` apply 开放补充回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,RepairDryRunSimulatorTest,RepairRiskActionBuilderTest,RepairApplyMutationBuilderTest,PlanningStateServiceTest#shouldApplyReplaceRiskItemsFixProposalWithVersionGuard+shouldGenerateItemRiskFixProposalFromExistingReview+shouldGenerateReadyReplaceRiskProposalForMultipleRiskItems+shouldKeepPartialReplaceRiskProposalPreviewOnlyWithWarning+shouldKeepReplaceRiskProposalBlockedWhenNoReplacementExists test
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test

cd ..
git diff --check
```

结果：通过。当前 `replace_risk_items` 已从只读预览推进到受控 apply：完整 replacement pair、sourceVersion guard、review 未 stale、proposal ready、dry-run 目标复验全部通过后，才能通过 `fix-proposals/apply` 原子执行 remove + add。部分替换继续保持 `preview_only`，无替换候选保持 `blocked`；专业组模式下如果条目风险的单专业替换会改变专业组数量，dry-run 会阻断，等待后续整组替换 selector 设计。结构性 `rebalance_tier_ratio` / `fill_probability_gap` 仍保持只读预览。

结构性替换预览说明补充回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairReplacementActionBuilderTest,RepairCandidateSelectorTest,RepairDryRunSimulatorTest test
mvn -q -Dtest=RepairReplacementActionBuilderTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairProposalStateBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest test
```

结果：通过。`RepairReplacementActionBuilder` 现在会在结构性 replacement action 的 `detail` 中披露“只做结构调整预览、不会自动应用”，并列出最多 3 条换出/换入配对及录取率、推荐系数、院校排名变化。该改动不改变候选选择、不改变 `RepairProposalApplyPolicy` 白名单，也不开放 `rebalance_tier_ratio` / `fill_probability_gap` 自动应用。

结构性候选排序和配对策略补充回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=RepairCandidateSelectorTest,RepairReplacementActionBuilderTest test
mvn -q -Dtest=RepairReplacementActionBuilderTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairProposalStateBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest test
```

结果：通过。新增覆盖断层候选同等接近中点时按推荐系数/意向/院校排名择优、结构性 replacement pair 先匹配专业相似和院校层次代价更低的候选、专业组结构修复 action 只有 `volunteerIds` 时也能反解 `unitId` 生成 unit 级 pair。该变更只影响 `preview_only` 结构建议的候选顺序和配对解释，不改变 `FixProposal` 状态机、自动 apply 白名单、旧补偿入口容量保护或 blocked proposal 展示边界。

初始方案结构修复候选排序补充回归：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldPreferLowerTradeoffCandidateWhenRepairingInitialRecommendationProbabilityGap+shouldRepairInitialRecommendationProbabilityGap+shouldFullyRepairInitialRecommendationProbabilityGapWhenCandidateWindowIsEnough+shouldRepairInitialRecommendationProbabilityInversion+shouldKeepTierTargetsStableAfterInitialRecommendationRepairs test
mvn -q -Dtest=RepairReplacementActionBuilderTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairProposalStateBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest test
mvn -q -Dtest=PlanningStateDTOCompatibilityTest,ReviewRuleRegistryTest,ReviewInvalidationPolicyTest,ReviewWorkflowStatusResolverTest,CandidatePoolStatusResolverTest,CandidatePoolQualityStatusBuilderTest,PlanningWorkflowStatusBuilderTest,OrderedPlanPositioningSupportTest,RepairApplyMutationBuilderTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairReplacementActionBuilderTest,WorkingPlanMutationSupportTest,RepairCandidateSelectorTest,RepairRiskActionBuilderTest,RepairMajorGroupInnerSafetyActionBuilderTest,RepairDryRunSimulatorTest,RepairReportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

结果：通过。初始推荐阶段的 `probability_gap` / `probability_inversion` 自动替换不再只看是否能降低断层或倒挂；在结构指标改善相同或接近时，会继续比较专业相似度、院校排名下降代价、推荐系数损失、意向分损失，再看补入候选自身推荐系数、录取率、意向分和院校排名。新增回归确认：当两个候选都能修同一个录取率断层时，系统优先选择专业更相近且院校层次代价更低的候选。

实现上，`RepairReplacementTradeoffSupport` 统一承接“专业相似度、院校排名下降、推荐/意向分损失、候选质量”的比较口径；`RepairCandidateSelector` 的结构修复预览和 `PlanningStateService` 的初始推荐自动修复都复用该口径，避免两条链路后续漂移。该改动只影响候选取舍顺序，不改变候选池来源、不改变工作台审查修复 apply 白名单，也不开放结构性 `rebalance_tier_ratio` / `fill_probability_gap` 自动落盘。

本地会话 132 复验：

```bash
curl --noproxy '*' -s -X POST \
  'http://127.0.0.1:8080/gaotu-assistant-bot/inner/planning/1/session/fix-proposals/generate?chatSessionId=132' \
  -H 'Content-Type: application/json' -d '{}'
```

结果：`修复高收费`、`修复中外合作` 均为 `blocked`，`actionCount=0`、`pairCount=0`，阻断原因仍为“替换预览会改变专业组数量，暂不允许确认应用”；`修复非意向托底` 也为 `blocked`，原因是缺少可补入的组内安全垫专业。说明不可应用的专业组条目替换尝试没有重新暴露给前端。

默认全量回归补充：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit tests/regression tests/integration -q

cd ../zhiyuan-server
mvn -q test

cd ../zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false
```

结果：Agent 非 e2e 全量回归通过，`2354 passed`；Server 默认全量测试通过。`InitialPlanEvaluationP0ReportTest` 是真实会话 P0 报告型用例，会拉起 local profile 并连接真实 MySQL，已改为需要显式设置 `-DRUN_P0_REAL_SESSION_REPORT=true` 才运行，避免默认回归依赖本地数据库。前端全量 typecheck 仍失败在既有 `ModalForm`、`userCenter`、`service/index`、`service/request` 类型问题；本轮涉及的 `WorkspacePanel/index.tsx`、`volunteer.ts`、`sessionDetail.ts` 无相关新增错误。

专业组模式院校名称筛选补充：

- 背景：上游 `school_name` 在专业组模式下可能是专业组展示名，例如“天津财经大学珠江学院(01)专业组”。工作区“院校名称”筛选如果直接使用 `schoolName`，会把专业组名当成院校名展示和匹配。
- 短期方案：`CandidateItemDTO` 新增 `displaySchoolName`，语义为“纯院校名称”。生成候选池时优先通过 `schoolId -> SchoolManager.getSchoolById()` 取标准院校名，取不到时 fallback 到上游 `school_name`。
- 使用边界：`schoolName` 继续保留现有展示/分组语义，不改专业组标题、方案分组、导出、排序和已有志愿定位；“院校名称”筛选选项和 `schoolKeywords/negativeSchoolKeywords` 匹配优先使用 `displaySchoolName`，并兼容匹配旧 `schoolName`。
- 长期方向：后续再系统拆分 `schoolDisplayName` / `unitDisplayName` / `volunteerDisplayName`，避免院校实体、专业组单元和完整志愿展示名继续混用。

推荐系数与候选池重算边界补充：

- `finalScore / rankInTier / preferred` 依赖 `VolunteerBizService.recommendVolunteerList()` 返回结果；该链路会经过 `VolunteerSorterAndMerger -> VolunteerRankClient.getRecommendVolunteer()` 调用 rank 服务。
- 软偏好变化只应标记 `staleFlags.recommendationOverlay=true`，通过 `refreshRecommendationOverlay()` 重新调用 rank 并把新的 `finalScore / rankInTier / preferred` 按 `volunteerId` 覆盖到现有候选池交集上；它不应物理重建 `candidatePoolState.items`，也不能对用户表达成“基础候选池变小”。
- 完整候选池重算只在首次生成、显式强制刷新、或 `staleFlags.candidatePool=true` 时触发。普通进入候选面板、查询筛选项、分页查看候选不应传 `forceRegenerate=true`，否则本地 rank 未启动或线上 rank 长尾都会被误放大为“刷新候选池异常”。
- 2026-06-11 已补前端保护：工作台 `ensureCandidatePoolReady(false)` 会按实际 `forceRegenerate` 传参，`generatePlanningCandidatePoolApi` 默认值改为 `false`；后端新增回归确认“已有候选池 + 非强制 + candidatePool 未 stale”不会调用 `recommendVolunteerList()`。

Agent 方案更新链路收口补充：

- 2026-06-12 已同步 `plan_action_orchestration_design.md`：`PlanActionPlan` 顶层只保留动作 envelope，复合目标统一进入 `CompositePlanProposal`；旧顶层 `goal / intent_updates / plan_actions / feasibility` 镜像不再被执行 envelope 消费。
- `ActionResolver` 职责已收口为 `IntentFrame + PlanContextInputs -> ActionResolution`，不再接收 `ConversationPhase`，也不输出 `plan_goal / intent_updates` 镜像。phase/pending 相关状态只在 service、`ConversationPhase` 和 `pendingConfirmation` 链路处理。
- `pending_context` 指令已对齐当前确认协议：模型不能自行调用 `execute_plan_action` 执行上一轮 pending payload；明确短文本确认由服务端 active `pendingConfirmation` 兜底链路校验处理。如果本轮仍进入模型，说明没有安全命中兜底，应引导用户点击当前预览或重新说明。
- `planEditCache` 不再作为旧 explore follow-up action 的事实来源；`interestAnalysisPopup` 只读取 active `pendingConfirmation`，没有 active pending 时返回失效提示。Python 侧 `get_intent_change_cache` 读接口已删除；新会话生成待采纳内容或采纳后仍会 best-effort 清理旧缓存，避免历史脏数据干扰排查。
- `planning_router_tool.handle_planning_request` 已从运行时代码和专用测试中删除；ChatAgent 主路径只保留 Plan 三段主链，新增能力不得恢复旧 router。
- `pin_unit / unpin_unit` 不在 `PlanActionPlan.action_family`、ActionResolver、ChatAgent 工具或执行分支中；文档中只保留退场说明，避免后续误作为新能力扩展。
- 意向确认旧 wrapper 已退场：`update_volunteer_intent_state` 不再作为代码入口保留；当前只走 `pendingConfirmation(kind=intent_change) -> apply_selected_intents`。用户侧文案继续屏蔽内部术语，只提示点“采纳”后生效。

本轮验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py::test_handle_intent_select_interest_candidate_query_prefers_pending_confirmation tests/unit/test_intent_state_tool.py::test_handle_intent_select_interest_prefer_confirm_returns_confirm_preview tests/unit/test_chat_service_history_persistence.py::test_chat_service_interest_prefer_confirm_returns_pending_confirmation_card tests/unit/test_planning_intent_scenarios_sync.py::test_intent_scenario_handle_select_prefer_confirm_returns_confirm_text tests/unit/test_instructions.py tests/unit/test_chat_agent_tools.py tests/unit/models/test_plan_orchestration_models.py tests/unit/test_plan_orchestration_tool.py tests/unit/models/test_conversation_phase.py tests/unit/test_chat_service_history_persistence.py::test_chat_service_applies_active_plan_pending_on_short_text_confirm tests/unit/test_chat_service_history_persistence.py::test_chat_service_applies_active_pending_confirmation_intent_on_short_text tests/unit/test_chat_service_history_persistence.py::test_chat_service_blocks_short_text_confirm_when_latest_assistant_confirmation_type_conflicts -q
.venv/bin/python -m pytest tests/unit/test_instructions.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_orchestration_tool.py tests/unit/models/test_plan_orchestration_models.py tests/unit/test_action_resolver.py tests/regression/test_keyword_matchers.py tests/regression/test_execution_apply.py tests/regression/test_execution_preview.py tests/integration/test_resolver_vs_legacy.py tests/integration/test_full_plan_flow.py tests/unit/test_intent_state_tool.py tests/unit/test_planning_intent_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_chat_agent_tools.py tests/unit/test_dialog_case_evaluation_report.py -q
cd ..
git diff --check
```

结果：目标确认/指令回归 `203 passed`；Agent planning/路由/执行综合回归 `614 passed`；删除 resolver 复合镜像和 phase 入参后，focused resolver/plan 回归 `246 passed`、resolver/full-flow 回归 `237 passed`、综合 Agent/Plan/Intent 回归 `880 passed`；`git diff --check` 通过。综合回归中同步把一处旧断言从“硬性要求”改为用户可理解的“已确认的报考条件”，防止后续文案退回系统术语。

约束意向与方案调整 pending 元数据收口：

- `only_keep / must_have / exclude` 这类约束触发方案调整时，service 已收口到 Java `user_goal` proposal/apply 主链路：基于待确认意向生成 `UserGoalFixProposalReq`，调用 Java `fix-proposals/user-goal/generate`，选中 ready proposal 后写入 `pendingConfirmation(kind=plan_mutation, actionFamily=apply_fix_proposal)`。
- 用户确认时，service 先写入偏好/要求，再按最新 planning version 重建 user-goal proposal，最后调用 Java `fix-proposals/apply`。Python 不再生成旧 `remove_units/add_units` 本地预览，不参与候选选择、替换配对或 apply 放行。
- 统一元数据：约束触发的方案调整卡片会在后端 `pendingConfirmation.compositeProposal` 中保存 `PlanGoal / intent_updates` 等解释和审计信息。真正执行只消费 `pendingConfirmation.executionPayload` 中的 `proposalId/sourceVersionGuard/proposalSource/userGoalRequest/intentPayload`，不绕过版本校验、确认态和 Java apply policy。
- `PendingConfirmation` 运行态模型已显式承载 `composite_proposal`，并兼容后端 `compositeProposal`。普通模型上下文、历史 pending 转换和卡片确认桥接都能保留这份元信息；它只用于解释、审计和后续上下文承接，不参与 apply 放行。
- `conversation_phase.pending` 的主源已进一步收口：普通对话启动、卡片确认和短文本确认时都直接从后端 active `pendingConfirmation` 构建，`RequestContext.pending_plan_action / pending_intent_change` 已删除，`ConversationPhase.from_legacy_context / from_legacy_plan_action / from_legacy_intent_change / to_legacy_plan_action` 已删除。历史 preview 不再恢复为后续文本确认可消费的 active pending；当历史 preview 与后端 pending 不一致时，以后端 pending 为准，避免旧历史工具返回抢占当前待采纳状态。
- 如果约束只形成报考条件、暂时不能安全生成方案动作，也会在 `pendingConfirmation(kind=intent_change)` 中保存同样的 `compositeProposal`。例如“只保留南方”会记录为 `goal_type=only_keep_scope`、`target_scopes=[region: 南方]`，但当前不会自动反向删除所有非南方方案项；大区到省份集合的方案级调整需要后续在执行层补完整展开、命中披露和确认预览后再开放。
- 这次不改变候选选择策略、方案修复白名单、工作区刷新目标或用户确认协议；候选选择、dry-run、复审和真实 mutation 继续由 Java 统一负责。

本轮补充验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py::test_chat_service_only_keep_major_preview_removes_non_matching_plan_items tests/unit/test_chat_service_history_persistence.py::test_chat_service_must_have_major_preview_adds_when_missing_from_plan tests/unit/test_chat_service_history_persistence.py::test_chat_service_must_have_major_keeps_intent_only_when_plan_already_has_scope tests/unit/test_chat_service_history_persistence.py::test_chat_service_only_keep_region_area_preview_keeps_area_scope_metadata tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_preview_with_plan_hit_becomes_plan_mutation_card -q
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py::test_chat_service_only_keep_major_preview_removes_non_matching_plan_items tests/unit/test_chat_service_history_persistence.py::test_chat_service_must_have_major_preview_adds_when_missing_from_plan tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_preview_with_plan_hit_becomes_plan_mutation_card tests/unit/models/test_plan_orchestration_models.py tests/unit/test_plan_orchestration_tool.py -q
.venv/bin/python -m py_compile app/service.py
```

结果：约束方案联动与编排模型 focused 回归 `67 passed`；新增大区 only_keep 边界 targeted 回归 `5 passed`；`service.py` 编译通过。

用户侧“草稿”话术继续收口：

- `plan_chat` skill 中的查看范围从“候选、草稿、排序、审查、补偿”改为“候选、已加入方案、排序、审查、补齐建议”，避免模型从技能提示里继续学习旧“草稿”概念。
- 全局 style rules 的术语映射从“草稿/draft -> 备选方案或候选志愿”调整为“草稿/draft -> 方案或已加入方案”。“备选方案”容易和候选机会混淆，不适合作为当前工作台方案的统一用户侧表达。
- Agent 侧 `query_planning_draft` 等旧 wrapper 已删除；Java `draftPlanState` 字段仍作为兼容字段和 helper fallback 保留。Agent 主链路不再接受 `query_draft` action，新的方案查看统一走 `query_state` 或 `query_ordered`。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_instructions.py tests/unit/test_chat_agent_tools.py -q
```

结果：`83 passed`。

`source=user_goal` 复合目标 proposal 主链路落地：

- 后端新增 `UserGoalFixProposalReq`，作为 Agent/外部把自然语言理解后的 `goalType / targetScopes / negativeScopes / qualityGuards / tradeoffGuards / sourceVersionGuard` 传给 Java proposal engine 的结构化输入。Java 侧只消费结构化范围，不从用户原句中反推实体或动作参数。
- `FixProposalDTO / FixProposalStateDTO` 已保留 `proposalSource`，`RepairProposalTaxonomy` 明确定义 `review_check` 和 `user_goal` 两类来源。`RepairProposalApplyPolicy` 允许 `user_goal` 来源的 `only_keep_scope / must_include_scope / exclude_scope`，但必须携带 `userGoalRequest`、版本保护和 ready proposal，不能绕过 pending、dry-run 和 apply 白名单。
- `UserGoalProposalBuilder` 已支持 `only_keep_scope / must_include_scope / exclude_scope` 三类 ready proposal：
  - `only_keep_scope`：识别当前方案中目标范围和非目标范围；候选池有目标范围候选时生成 `replace_volunteers` 配对预览，候选不足时保留 `remove_volunteers` 只读提示。
  - `must_include_scope`：当前方案已有目标范围时返回 `info`；当前缺少且方案未满时返回 `add_volunteers` 预览；当前已满时生成一进一出的 `replace_volunteers` 配对预览。
  - `exclude_scope`：当前方案无命中时返回 `info`；有命中时优先生成非命中候选的 `replace_volunteers` 配对预览，候选不足时保留 `remove_volunteers` 只读提示。
- Agent 和 service 调用 `UserGoalFixProposalReq` 时会把一个 scope 中的多个值展开成多个 `ScopeDTO`，例如“会计学、审计学”会形成两个 major scope。Java matcher 按单实体 scope 工作，不从 `evidence.values` 里反推额外范围。
- 专业模式和专业组模式都走同一 `FixProposalActionDTO` 协议。专业组模式下 `replacementPairs` 会携带 `fromUnitId / toUnitId`，并跳过已经在当前方案里的同组候选，避免把同一专业组内部专业误当成新增专业组。
- 配对排序复用 `RepairReplacementTradeoffSupport` 的口径：优先专业相似度、院校排名下降代价、推荐系数损失、意向分损失，再看补入候选自身推荐系数、录取率、意向分和院校排名。该逻辑影响候选解释顺序和 dry-run，不改变候选池来源。
- `PlanningStateService.generateUserGoalFixProposals()` 已通过 `POST /session/fix-proposals/user-goal/generate` 提供生成入口；该接口本身不保存 pending、不触发 review、不修改方案。对话侧由 service 生成 `pendingConfirmation(kind=plan_mutation, actionFamily=apply_fix_proposal)`；用户确认时先写入偏好/要求，再读取最新 planning version 重建 user-goal proposal，最后调用 Java apply。

本轮验证：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldGenerateUserGoalFixProposalThroughServiceWithoutApplying,UserGoalProposalBuilderTest,RepairProposalTaxonomyTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/models/test_plan_orchestration_models.py tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_formats_status_and_warnings tests/unit/test_plan_execution_tool.py::test_execute_plan_action_review_plan_does_not_apply_ready_fix_proposal -q
```

结果：后端 focused 回归通过；Agent helper/model 回归通过。新增覆盖包括专业模式 `only_keep/must_include/exclude` 的替换/补入/移出预览、专业组 replacement pair unitId、专业组候选跳过当前同组、scope 缺失/歧义/version guard 阻断，以及 `user_goal` proposal 必须通过 service pending 桥受控 apply。

`plan_next_action` 旧只读挂接链路退场：

- `plan_next_action` 不再调用 `fix-proposals/user-goal/generate`，也不再把 Java proposal 映射为 `CompositePlanProposal.linked_fix_proposals`。
- 该工具只保留 Agent 编排层职责：输出结构化 `PlanGoal`、`intent_updates`、保守 `plan_actions`、实体歧义、决策参考和取舍说明。
- 真正会改变当前方案的 `only_keep_scope / must_include_scope / exclude_scope` 统一由 service 基于确认卡进入 Java `user_goal` proposal/apply 主链路，避免 `plan_next_action` 与 service 双轨。

`user_goal` proposal 接入 service 确认主链路：

- service 里的 `only_keep / must_have / exclude` 不再生成旧 `remove_units/add_units` 本地预览，也不再把后端 proposal 作为镜像字段挂到 `CompositePlanProposal`。
- service 会基于待确认意向生成 `UserGoalFixProposalReq`，调用 Java `fix-proposals/user-goal/generate`，选取 ready proposal 后生成 `pendingConfirmation(kind=plan_mutation, actionFamily=apply_fix_proposal)`。
- pending 保存 `proposalSource=user_goal`、`userGoalRequest` 和 `intentPayload`。用户确认时先写入偏好/要求，再读取最新 planning version 重建 user-goal proposal，最后按新的 `proposalId/sourceVersionGuard` 调用 Java apply。
- 多实体目标会按实体拆分后传给 Java，例如“排除会计学、审计学”会传两个 negative scope，避免只读 proposal 只覆盖第一个专业。
- 独立 `plan_user_goal_fix_proposal` helper 已删除；`goal payload/scope -> UserGoalFixProposalReq` 的结构转换收回到 service 私有函数，不参与意图判断、候选选择或 apply 放行。
- 该链路把候选选择、替换配对、专业组 unit pair、候选不足、dry-run 和真实 mutation 都收口到 Java；Python 不参与候选排序、不生成 replacement pair、不判断 applyable。

旧补偿 apply 旁路继续收紧：

- Agent 不再生成 `preview_compensation/apply_compensation` pending；历史会话中遗留的旧 compensation preview/apply 只作为 legacy 输入被忽略或拒绝，不能触发落盘。
- `review_issue_registry` 对数量缺口、安全垫、梯度断层等结构问题统一映射到 `preview_fix_proposal`。没有明确结构化 `review_issue_code` 时，Agent 不从用户自然语言里恢复整批审查问题，也不把 `preview_only/blocked` repair 翻译成普通 `remove_units/replace_units/apply_compensation`。
- 该保护不改变 Java `FixProposal` apply 白名单，也不开放 `source=user_goal` apply；它只防止旧 compensation 入口绕过后端 proposal/dry-run/apply policy。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/models/test_plan_orchestration_models.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_planning_workflow_tool.py::test_generate_planning_fix_proposals_formats_status_and_warnings tests/unit/test_plan_execution_tool.py::test_execute_plan_action_review_plan_does_not_apply_ready_fix_proposal -q
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py::test_chat_service_only_keep_major_preview_removes_non_matching_plan_items tests/unit/test_chat_service_history_persistence.py::test_chat_service_must_have_major_preview_adds_when_missing_from_plan tests/unit/test_chat_service_history_persistence.py::test_chat_service_must_have_major_keeps_intent_only_when_plan_already_has_scope tests/unit/test_chat_service_history_persistence.py::test_chat_service_only_keep_region_area_preview_keeps_area_scope_metadata tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_preview_with_plan_hit_becomes_plan_mutation_card tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_preview_attaches_backend_user_goal_fix_proposal tests/unit/test_chat_service_history_persistence.py::test_chat_service_mixed_intent_plan_hit_card_keeps_positive_preference_summary tests/unit/test_chat_service_history_persistence.py::test_chat_service_negative_plan_hit_card_keeps_existing_positive_preference_summary -q
.venv/bin/python -m pytest tests/unit/test_plan_orchestration_tool.py::test_plan_next_action_expands_multi_value_scope_for_user_goal_fix_preview tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_backend_preview_expands_multi_value_scope -q
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py::test_execute_plan_action_blocks_compensation_apply_when_preview_contains_structural_actions tests/unit/test_plan_execution_tool.py::test_execute_plan_action_blocks_compensation_apply_when_estimated_fill_exceeds_remaining_gap tests/unit/test_plan_execution_tool.py::test_execute_plan_action_allows_major_group_compensation_apply_when_unit_gap_matches -q
```

结果：Agent 复合预览与 service 约束确认 focused 回归通过；新增确认 `only_keep_scope / must_include_scope / exclude_scope` 通过 Java `user_goal` proposal 生成可确认卡片，确认时先写意向、重建 proposal、再 apply。

方案更新/审查/修复中等范围回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_instructions.py tests/unit/test_chat_agent_tools.py tests/unit/test_action_resolver.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_planning_workflow_tool.py tests/regression/test_pending_protocol.py tests/regression/test_execution_preview.py tests/regression/test_execution_apply.py tests/regression/test_keyword_matchers.py -q
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py::test_extract_pending_plan_action_maps_compensation_preview_to_apply_payload tests/unit/test_chat_service_history_persistence.py::test_extract_pending_plan_action_ignores_compensation_preview_without_legacy_add_action tests/unit/test_chat_service_history_persistence.py::test_extract_pending_plan_action_ignores_compensation_preview_without_actionable_suggestions tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_preview_attaches_backend_user_goal_fix_proposal tests/unit/test_chat_service_history_persistence.py::test_chat_service_constraint_backend_preview_expands_multi_value_scope tests/unit/test_chat_service_history_persistence.py::test_chat_service_requires_card_click_for_pending_compensation_on_text_confirm tests/integration/test_full_plan_flow.py tests/integration/test_resolver_vs_legacy.py -q

cd ../zhiyuan-server
mvn -q -Dtest=RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairDryRunSimulatorTest,PlanningStateServiceTest#shouldGenerateUserGoalFixProposalThroughServiceWithoutApplying,UserGoalProposalBuilderTest,RepairProposalTaxonomyTest test
```

结果：Agent 主链路回归 `691 passed`；service/integration 回归 `109 passed`；server FixProposal focused 回归通过。覆盖 ChatAgent 工具注册、ActionResolver、Plan 编排、执行门禁、旧补偿预览/应用保护、pending 协议、复合目标 user-goal proposal 主链路、router 退场和 legacy resolver 对照。

本地综合门禁补充：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_quality_gate.py --execute --metrics-dir /private/tmp/zhiyuan-agent-dialog-quality-gate-310
.venv/bin/python -m pytest tests/unit/test_dialog_scenario_stability.py tests/unit/test_planning_intent_scenarios_sync.py tests/unit/test_planning_plan_scenarios_sync.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_tool_reply_policy.py tests/unit/test_entity_resolution.py -q
.venv/bin/python -m pytest tests/unit tests/integration tests/regression -q

cd ../zhiyuan-server
mvn -q test

cd ..
git diff --check
```

结果：对话质量门禁 `1140 passed`；场景同步和回复策略 focused 回归 `138 passed`；Agent 非 e2e 全量回归 `2397 passed`；Server 默认全量测试通过；`git diff --check` 无空白错误。

本地 live WebSocket 回归暂未执行：当前 `scripts/status.sh` 显示 web/server/agent/rank 均未运行，MySQL/Redis 未启动，且本机 Docker daemon 不可用；因此这轮只能确认静态、单元、集成、回归和质量门禁通过，不能把真实服务链路视为已验证。后续启动本地服务后，需要继续执行 `examples/dialog_regression_runner.py --cases examples/dialog_regression_310_review_repair_cases.json` 覆盖真实 WebSocket 对话。

Agent 旧补偿 wrapper 退场最终收口：

- Python Agent 侧已删除 `preview_planning_compensation/apply_planning_compensation` wrapper、对应 internal client 调用和 mock endpoint；ChatAgent 工具注册测试锁定这两个工具不会出现在模型可调用列表。
- `PlanActionPlan.action_family` 不再接受 `preview_compensation/apply_compensation`；旧 payload 只能在历史兼容测试中被拒绝或忽略，不能创建新的 `pendingConfirmation`，也不能被短文本“确认”触发执行。
- `ChatService` 不再保留旧补偿专门分支，而是使用通用“非可确认 Plan 结果”保护：`error/no_change/无可行动作的 adjustment_analysis/非当前 action family 的 preview_only` 都会清掉同轮不可靠 pending，并把无依据的“可确认应用”话术改成“没有形成可执行调整预览”。新的修复应用只允许通过 active `pendingConfirmation(actionFamily=apply_fix_proposal)` 调用 `apply_planning_fix_proposal`，不是模型或旧补偿旁路。
- `planning_workflow_tool` 已删除 `_build_compensation_preview_facts`，不再把 Java `reviewState.compensationPreview` 作为 Agent 用户侧 facts；用户侧 review/adjustment 文案统一通过 `fix-proposals/generate` 的 `FixProposalState` 解释处理方向。
- Java `buildCompensationPreview()` 仍作为内部补齐素材保留；旧 `previewCompensation/applyCompensation` 对外入口已删除。满方案结构修复、风险替换、用户复合目标仍必须走 `FixProposal`、dry-run 和 apply policy。

追加验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py tests/unit/test_planning_plan_scenarios_sync.py tests/unit/test_chat_agent_tools.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py -q
.venv/bin/python -m pytest tests/integration tests/regression -q
.venv/bin/python -m py_compile app/service.py app/handlers/analysis_handlers.py app/tools/planning_workflow_tool.py app/util/internal_client.py

cd ../zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest,RepairDryRunSimulatorTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairProposalTaxonomyTest,UserGoalProposalBuilderTest test

cd ..
git diff --check
```

结果：Agent history `199 passed`，Agent 关键 unit `409 passed`，Agent integration/regression `587 passed`，Python 编译通过；Server 修复/审查 focused 回归通过；`git diff --check` 通过。剩余 `preview_planning_compensation/apply_planning_compensation` 文本只在“不注册”测试断言中出现，剩余 `preview_compensation/apply_compensation` 只在 legacy 拒绝/历史兼容测试和历史设计文档中出现；service 运行时不再保留旧补偿专门分支。

对话侧 FixProposal pending/apply 桥补充：

- `ChatService` 不再依赖 recent cache 消费修复预览，而是直接读取本轮 `execute_plan_action` 的 `ToolReturnPart`，避免超时兜底或其他读取提前消费。
- `fix_proposal_preview` 可以直接生成确认卡；`review_result` 只有在用户明确表达“先看怎么处理/怎么调整、别直接动”这类处理预览诉求时，才允许从其中携带的 ready proposal 生成确认卡。普通“只审查/先不要改”的 `review_result` 只展示审查结果，不生成执行入口。
- 只有 `facts.fix_proposals.proposals[]` 中 `status=ready`、有 `proposal_id`、来源不是 `user_goal`，并且 `source_version_guard > 0`，才生成 `pendingConfirmationCard(actionFamily=apply_fix_proposal)`。
- `blocked` / `preview_only` proposal 只保留在回复事实里，不生成确认卡，也不能降级成普通 `remove_units/replace_units/apply_compensation`。
- 用户点击卡片或短文本确认时，`handle_pending_confirmation` 按 `pendingId/kind/status` 校验 active pending，再从 `executionPayload` 读取 `proposalId/sourceVersionGuard/regenerateOrderedPlan/rerunReview`，调用 Java `fix-proposals/apply`。
- apply 成功后 pending 置为 `applied`，卡片状态同步更新，历史中记录内部 `apply_planning_fix_proposal` tool call/return，回复展示 `RepairReport`，并返回 `ordered` 静默刷新事件。
- apply 失败、版本缺失或 proposal 过期时 pending/card 置为失效，提示重新查看审查结果，不允许重复点击旧卡片。

追加验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/models/conversation_phase.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
.venv/bin/python -m pytest tests/unit/test_chat_agent_tools.py -q -k "fix_proposal or apply_tool"
.venv/bin/python -m pytest tests/unit/test_planning_workflow_tool.py -q -k "fix_proposal"
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py -q -k "fix_proposal"
.venv/bin/python -m pytest tests/unit tests/regression -q

cd ../zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest,RepairDryRunSimulatorTest,RepairProposalApplyPolicyTest,RepairProposalStateBuilderTest,RepairProposalTaxonomyTest,UserGoalProposalBuilderTest test

cd ..
git diff --check
```

结果：新增对话侧修复确认桥 targeted 回归 `7 passed`，`test_chat_service_history_persistence.py` 全量 `205 passed`；其中覆盖 `fix_proposal_preview` 出卡、`review_result` 在“先看怎么处理”场景出卡、普通只审查不出卡、blocked/user_goal proposal 不出卡、确认后 service 内部 apply。后续补充 `planning_workflow_tool` focused 回归后，对话侧处理建议相关 targeted 回归为 `11 passed`。Agent `unit + regression` 全量 `2200 passed`，`git diff --check` 通过。ChatAgent 工具注册仍确认 `apply_planning_fix_proposal` 不暴露给模型；场景目录同步把旧 `compensation_apply` 覆盖口径迁到 `fix_proposal_preview/fix_proposal_apply`，保留 `pin/unpin` 退场验证。

本地 live WebSocket 补充：

- 首次在 session 130 的有风险方案状态下跑通 `/private/tmp/zhiyuan_310_review_fix_preview_apply_final2.json`：第一轮 `review_plan -> review_result` 携带 ready proposal，service 生成 `pendingConfirmationCard(actionFamily=apply_fix_proposal)`；第二轮短文本“确认”命中 active pending，service 内部调用 `apply_planning_fix_proposal`，返回处理结果并发送 `planningWorkspaceAction(targetView=ordered, refresh=true)`。
- 本轮同时修正回归 runner：`planningWorkspaceAction(silent=true)` 不再作为用户可见文案参与质量断言，但必须保留为动作 followup，用于校验工作台刷新。
- 该 live case 是有副作用的状态依赖测试：确认执行后会真实修改 session 130 的方案。后续重复跑同一会话时，高收费/中外合作项可能已被替换，后端不再返回同一个 ready proposal；使用 `--session-offset` 也不一定可行，因为偏移会话可能没有正式方案。后续要把这类 e2e 稳定化，需要准备“可重置方案状态”的后端 fixture 或专用会话池，跑前恢复 ordered/review/fixProposal 初始状态，再执行 preview -> pending -> apply -> refresh 链路。
- 用户侧文案已收口：对话回复、确认卡和 apply 结果统一使用“处理建议/处理内容/检查结果/处理前预览”，避免暴露“修复建议、复验结果、preview_only、blocked、action_family”等内部术语。

2026-06-14 review/repair live 回归补充：

- 已复跑 `examples/dialog_regression_310_review_repair_cases.json` 的 9 个审查/处理建议场景，输出 `/private/tmp/zhiyuan_310_review_repair_after_final_cleaning.json`，结果 `9/9 successful`。
- 性能记录：median 约 25.3s，max 约 34.5s；最慢样本仍集中在“解释为什么暂时不能直接处理/怎么调”的审查说明类问题，通常包含审查工具调用和模型二次整合。该链路质量优先于压缩延迟，后续优化方向应放在事实复用、减少重复模型调用和前端等待提示，而不是降低回复信息量。
- 剩余问题记录：个别 live 回复仍可能出现偏系统化或不够自然的表达，例如“系统给不了”“需要你先决定”等。按当前产品决策，本轮先记录为后续话术优化项，不继续逐句打补丁，避免引入新的分支复杂度。
- 当前边界保持不变：`ready` 的后端处理建议可以生成确认卡并由 service 内部 apply；`blocked/preview_only` 继续只读说明；`user_goal` proposal 只通过 service pending 桥受控 apply；ChatAgent 不暴露 `apply_planning_fix_proposal` 给模型直接调用。
- 机制补充：`plan_action_recovery` 只作为 full agent 没有形成有效方案预览时的补救链路；模型误把“补候选/移动/删除”等方案动作走成 Intent 预览时，可以恢复到 `plan_next_action -> execute_plan_action`；但纯粹的偏好/报考条件预览不能被恢复器抢路由，仍由 Intent 确认卡承接。
- 补充回归：新增纯 Intent 预览不被方案恢复器抢占的边界测试，同时保留“误走 Intent 后恢复方案动作”的测试；Agent focused 回归 `459 passed`，Agent unit + regression `2257 passed`，Java 审查/修复 focused 回归通过。

本地采集链路补充：

- 切换省份后进入专业意向页仍出现“系统错误”的当前根因不是草稿恢复，也不是负意向专业接口空选科问题；日志显示 `base-data/unacceptable-majors` 已返回 200，失败发生在 `chat/{tenantId}/major-recommend` 调用 rank `127.0.0.1:5001/gaokao-volunteer-rank/recommend_submajor` 时连接失败。
- `major-recommend` 只用于专业意向页的默认推荐勾选，不应阻塞用户继续手动选择专业；因此后端在该接口 rank 不可用或返回空时降级为空列表，前端同样捕获该默认推荐请求失败并保持页面可继续填写。
- 初始方案生成、候选排序、推荐系数刷新仍依赖 rank 的排序能力，不在这次降级范围内；本地如果需要验证方案生成和排序，仍必须启动 rank 服务，否则应明确暴露排序服务不可用，而不是静默生成不可靠方案。
- focused 验证：`cd zhiyuan-server && mvn -q -Dtest=ChatSessionBizServiceTest test` 通过，覆盖 rank 不可用返回空推荐、正常返回超过 8 个专业时仍截断为 8 个。

## 14. 专业组工作区交互待优化

### 14.1 当前界面行为复核

代码位置：`zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx`。

当前专业组模式下，候选、方案和排序区的交互粒度并不完全一样：

- 候选区会先按 `planSchoolDataId/schoolId/schoolName` 聚合成专业组卡片，卡片头部展示院校和 `组内 N`。
- 候选区专业组默认折叠：`Collapse defaultActiveKey=[]`。用户展开后才能看到组内专业明细。
- 候选区的「加入方案」按钮在每个专业行上，调用 `selectPlanningWorkingPlanItemsApi(..., [volunteerId])`，因此当前能力上支持把专业组内的单个专业单独加入方案。
- 方案浮层展开后，专业组下会列出组内专业，并且支持单个专业删除；组头也支持整组删除。
- 排序方案区按 `orderedPlanState.units[].majorItems` 或候选明细聚合为专业组。默认初始化时只展开第一组，其他组折叠。
- 排序方案区折叠态当前主要展示院校名、院校标签、专业组录取率和院校信息，不稳定展示 `组内 N`，用户第一眼不容易知道该专业组实际包含几个专业。
- 排序方案区展开后，组内每个专业会展示专业名称、计划数、学制、学费、选科、历年分数、专业录取率、推荐系数、区间位次、专业热度、薪酬指数和专业代码，并支持单个专业上移、下移、移动到指定位置、删除。

### 14.2 风险判断

这个问题不是后端数据结构缺失，也不是单专业操作能力缺失，而是默认可见性和折叠态信息不足：

- 用户从默认的排序方案视图进入时，只能立即看到第一组的组内专业，其他专业组需要点击展开。
- 候选区虽然有 `组内 N`，但候选卡默认折叠，用户需要先理解卡片可展开，才会发现每个专业可以单独加入。
- 排序方案折叠态缺少稳定的 `组内 N` 和专业名称摘要，容易让用户误解为“一个专业组只有一个专业”或“不知道当前组里选了哪些专业”。
- 专业组内专业本身参与导出、排序、审查和修复，因此界面上必须持续表达“当前专业组包含哪些专业、当前会操作整组还是组内单个专业”。

### 14.3 建议修复方向

3.1.0 工作区交互建议按低风险方式补齐，不改变后端方案结构和操作接口：

1. 候选区专业组卡片头部保留 `组内 N`，并补充 2-3 个专业名称摘要；超过数量显示“等 N 个专业”。
2. 候选区折叠态增加明确的展开提示，例如“展开查看组内专业并单独加入”。
3. 排序方案区专业组折叠态增加 `组内 N` 标签和专业名称摘要，保证不展开也能知道该组包含多少专业。
4. 排序方案区整组按钮继续使用“整组上移/整组下移/整组删除”，组内专业按钮继续使用“上移/下移/删除”，避免混淆动作粒度。
5. 移动端同样展示 `组内 N` 和专业摘要，避免折叠卡片只剩院校名。
6. 文案上统一使用“专业组”和“组内专业”，不要把组内专业数量展示成专业组数量。

### 14.4 2026-06-13 设计确认：专业组标题数量标签

本次只解决排序方案中专业组数量心智不清楚的问题，不扩大到候选区、方案浮层或组内专业摘要。

问题定义：

- 排序方案区的每个专业组标题处，用户需要一眼知道该专业组全量包含几个组内专业。
- 现有展开态可以看到已选入方案的组内专业明细，但折叠态标题附近缺少稳定数量提示，容易误解为一个专业组只对应一个专业，或误把“已选入数量”理解为“该组总专业数”。

确认解法：

- 仅在排序方案区专业组标题行、现有标签最后新增弱化标签 `该组总共XX个专业`。
- 标签数量使用专业组全量专业数，不使用当前方案已选入专业数；文案固定为 `该组总共XX个专业`。
- 口径优先使用后端 `PlanningOrderedUnit.totalMajorCount`；历史数据缺失时前端才 fallback 到候选池同专业组条目数，再 fallback 到当前已选专业数。
- 后端仅兼容性补充 `OrderedUnitDTO.planSchoolDataId/schoolId/schoolUnitCode/totalMajorCount` 展示字段，不改变选择、删除、移动、排序接口语义，不改变候选区和方案浮层展示。
- 样式沿用当前标题行的 `Tag` 体系，避免占用过多宽度；移动端自然换行，不挤压标题和操作按钮。

实现记录：

- `WorkspacePanel` 在专业组排序方案标题行最后增加 `该组总共XX个专业` 标签。
- 新增轻量灰色标签样式，避免与院校排名、录取率标签抢视觉优先级。
- `OrderedUnitDTO` 补充专业组身份和 `totalMajorCount`，`buildOrderedUnitsFromOrderedItems()` 按候选池同专业组全量专业计数；前端历史 fallback 使用 `planSchoolDataId -> schoolUnitCode -> volunteerId 前缀 -> schoolName` 的专业组级匹配，不再按 `schoolId` 合并。

### 14.5 待验证项

- 新建专业组模式会话：候选区展开专业组后，单个专业加入方案仍然只加入该 `volunteerId`，不会整组加入。
- 历史迁移专业组会话：如果 `units[].majorItems` 存在，排序区和方案浮层能展示所有组内专业；如果只有旧 `orderedItems/items`，前端 fallback 聚合后仍能看到多专业。
- 排序方案默认折叠态：每个专业组不展开也能看到 `该组总共XX个专业`，且数量等于专业组全量专业数，不等于当前已选入方案的专业数。
- 导出：专业组内专业数量和明细与界面一致。
- 审查：`group_inner_safety_guard`、`major_group_safety_intent_alignment` 等规则仍按组内专业粒度工作，不把组内专业数当专业组数。
- 排序和移动：整组移动仍只改变专业组位置，组内专业移动仍只改变组内/条目顺序，不影响专业组总数。
- 删除：整组删除移除该专业组下所有专业；单专业删除只移除目标 `volunteerId`。

## 15. 开放兴趣画像信号保真边界

当前开放兴趣画像问题仍属于只读 Explore，不新增持久状态，不写入后续报考参考，也不直接影响推荐系数或方案调整。

本轮只处理回复质量问题：当用户一轮里同时表达多个兴趣、排斥方向、收入期待、沟通强度或工作方式期待时，`analyze_current_interest_profile` / 泛方向 Explore 工具必须在返回文本里保留这些具体点，避免最终回复被压缩成“市场化就业”“泛方向”之类笼统标签。

当前不落地结构化消费链路：

- 不新增 `userSignals` 状态表或持久字段。
- 不把开放兴趣信号直接接入推荐权重、候选筛选、方案修复或长期偏好沉淀。
- 不在 service 层用用户原话切片、关键词命中或回复包含判断做补偿。

后续扩展点：

- 如果产品确认开放兴趣画像需要参与推荐、方案权衡或长期记录，再引入结构化输出，例如 `positiveInterests`、`negativeInterests`、`jobPreferences`、`tradeoffs`、`uncertainties`。
- 结构化字段应由 Explore 工具或专门语义抽取器输出，并明确消费方；没有消费方前不预留运行时半成品状态。
- 评估上继续用真实对话 case 验证“用户已经说出的具体信号是否被回复承接”，但不通过字符串快路由或逐 case 关键词补丁解决。

## 16. 终态清理记录：旧补偿与 pendingActions 退场

2026-06-15 本轮按“少维护多版本和中间层，统一切换后删除残留代码”的原则继续收口审查修复链路。

已完成：

- 删除 Java 对外 `POST /session/compensation/preview` 和 `POST /session/compensation/apply` 路由，删除 `CompensationApplyReq`。
- `PlanningStateDTO` 和 `PlanningWorkspaceStateRes` 不再携带 `pendingActions`；`PlanningStateService` 不再初始化、清空或向工作台响应写入旧 pending action。
- Web 工作台删除 `pendingActions` 类型和展示分支；审查 tooltip/详情只消费 `ReviewCheck`，处理入口只来自 Java `FixProposal`。
- Agent `PlanningSummary`、规划上下文、查询回复 facts 不再读取或展示 `pending_action_count/pending_action_summaries`；测试 fixture 中的旧字段也已清理。
- Java 内部补齐落盘 helper 改为中性命名 `applyWorkingPlanAdditionActions()`，操作日志类型改为 `fix_add_items`，避免误解为旧 compensation API 仍存在。

当前统一链路：

```text
runReview / review-workflow
  -> generateFixProposals
  -> pendingConfirmation(actionFamily=apply_fix_proposal)
  -> applyFixProposal
  -> RepairReport + workspace refresh
```

边界：

- `CompensationPreviewDTO/buildCompensationPreview()` 仍作为 Java 内部素材存在，用于把数量缺口、安全垫、梯度等补齐方向转换成 `FixProposal`；它不是对外协议，也不能生成独立 pending。
- 历史对话或测试里出现 `preview_compensation/apply_compensation` 只会被拒绝或忽略，不能创建新的 `pendingConfirmation`，也不能绕过 `RepairProposalApplyPolicy`。
- 结构性策略 `rebalance_tier_ratio`、`fill_probability_gap` 仍是 `preview_only`；即使有 replacement pair，也不自动落盘。

本轮验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit tests/integration tests/regression -q

cd ../zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest,RepairProposalApplyPolicyTest,UserGoalProposalBuilderTest,RepairApplyMutationBuilderTest test
mvn -q -Dtest=PlanningStateServiceTest test

cd ../zhiyuan-web
./node_modules/.bin/tsc --noEmit

cd ..
git diff --check
```

结果：

- Agent：`2382 passed`。
- Server focused：通过；`PlanningStateServiceTest` 单独通过。
- `git diff --check`：通过。
- Web `tsc --noEmit`：被既有全局类型问题阻塞，错误集中在 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts`，不是本轮工作台 `pendingActions` 删除引入；本轮修改文件已通过引用搜索确认无 `pendingActions/PlanningPendingAction` 残留。

## 17. 发布前 live 回归收口记录

2026-06-16 本轮在本地固定端口服务上继续 3.1.0 发布前回归：

- Web: `127.0.0.1:3001`
- Server: `127.0.0.1:8080`
- Agent: `127.0.0.1:8000`
- Rank: `127.0.0.1:5001`

本轮修复点：

- `BaseAgent` 重复工具调用 guard 在 `query_volunteer_plan` 触发时，不再用“查询没有稳定收敛”的泛化话术覆盖已经成功拿到的查询结果；guard 会优先读取最近一次成功工具返回，并明确本轮不改方案。失败/异常工具返回仍保留原兜底文案。
- `dialog_regression_runner.py` 的 `assertNoFollowups` 不再把尾随 `thinking` 消息当成用户可见 followup；真实 `pendingConfirmationCard`、非静默工作台动作等仍会被断言捕获。
- `dialog_regression_303_effect_perf_cases.json` 的文本确认断言对齐当前协议：active pending 下用户短文本确认可以生效，成功口径接受“已采纳/已确认/后续推荐/方案检查”等表达，不再退回“只能点击卡片”的旧设计。
- `CompositeGoalDecision` 对模型结构化输出的空可选字段做归一：`scopeType=""`、`maxTuitionPerYear=""` 视为未提供，避免复合目标兜底分类 warning 干扰主链路；后续仍由 `_normalize_composite_goal_decision()` 按置信度和 action/scope 完整性降级。

本轮验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_plan_semantic_action_tool.py tests/unit/test_base_agent.py tests/unit/test_dialog_regression_runner.py -q
.venv/bin/python -m py_compile app/tools/plan_semantic_action_tool.py app/agent/base_agent.py examples/dialog_regression_runner.py

RUN_AGENT_DIALOG_E2E=1 \
AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_310_effect_perf_after_guard_runner_fix.json \
.venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s
```

结果：

- 相关单元回归：`71 passed`。
- `test_agent_dialog_effect_perf.py` live e2e：`14 steps / 14 successfulSteps / failedSteps=0`，pytest `1 passed`。
- 聚焦复跑 `303-quality-plan-local-query-readonly-fast-route / career-fit-readonly-no-workspace / intent-preview-confirm-progress / no-pending-confirm-fast-guard`：`6 steps / 6 successfulSteps / failedSteps=0`。

观察到的非阻断问题：

- `303-quality-plan-status-rich-structured` 耗时 `55.7s`，原因是主模型先 `query_state` 再 `review_plan`，最后又做长文本整合；业务回复正确，但属于性能长尾。
- `303-quality-plan-local-query-readonly-fast-route` 耗时 `20.7s`，主要消耗在首轮模型判断和查询后模型整合；业务回复正确，未误改方案。
- 只读局部查询在有近期审查状态时仍可能附带 silent `planningWorkspaceAction(targetView=review)`，当前测试允许且前端应静默处理；后续如果前端有可感知刷新，再收敛“只读查询不刷新审查面板”的边界。
- 模型侧 `intentSideEffectDecision` 的自然语言 reason 仍会在“倾向法学和财政学，但护理不要”这类表达上出现解释波动；当前 service 以工具产出的确认卡片和 pending 状态为准，最终用户链路稳定。

发布判断：

- 本轮修复未放宽高副作用动作确认协议，也未新增字符串匹配路由；主要是异常收束、回归脚本口径和结构化输出健壮性。
- 当前 effect/perf 主回归已可作为 3.1.0 发布前质量基线之一；后续仍需继续跑 `310_review_repair`、`310_constraint_plan_action`、`303_open_quality`、`303_dialogue_derived`、`310_production_abstracted` 等积累场景，确认审查修复、复合方案动作和真实对话派生 case 没有回退。

## 18. 方案动作 pending 来源收口

2026-06-16 回归 `310_constraint_plan_action` 时再次发现“中外合作的都排除掉，当前方案里有的话先移出去”在整组回归中偶发生成泛化确认卡，确认后又回到自然语言/空引用解析，报“没有唯一匹配到这条志愿”。

原因不是 `program_type` scope 本身失效，而是 service 仍保留了旧旁路：`plan_next_action` 返回 `stage=preview` 后，可以直接被 `_extract_plan_confirmation_candidate()` 提取成 `pendingConfirmation`。这会绕过 `execute_plan_action` 的执行层解析，导致 `facts.resolved_apply_payload` 没有写入 pending，后续确认只能拿泛化 payload 重新解析。

本轮收口：

- `plan_next_action` 只保留编排职责：输出 `PlanActionPlan`、结构化 scope、原子动作草案和可行性说明；它不是可确认预览结果。
- `pendingConfirmation(kind=plan_mutation)` 只能来自 `execute_plan_action` 的执行层 preview 结果，或 Java `FixProposal` pending 桥。
- 如果 full agent 只调用了 `plan_next_action` 但漏掉 `execute_plan_action`，service 会用同一份结构化计划补跑 `execute_plan_action(stage=preview)`；只有补跑得到 `preview_only` 且可执行范围完整时，才生成确认卡。
- 结构化删除范围，例如 `filters.program_types=["中外合作办学"]`，必须先由执行层读取当前方案并解析成稳定 `volunteer_ids`，写入 `facts.resolved_apply_payload`；确认 apply 时消费这份稳定 ID，不再按用户自然语言或泛化 summary 重猜范围。
- `plan_next_action` 的结果仍可作为执行 payload 的补全参考：如果模型把完整结构给了 `plan_next_action`，但传给 `execute_plan_action` 的 payload 较薄，pending 构造会合并完整结构；但 pending 的来源仍是执行层返回。
- 旧测试里“plan_next_action 单独 preview 也能创建 pending”的预期已删除，改为防回退断言。
- pending 里保存的是确认态执行 payload，只能以 canonical `stage` 为准；`current_stage/user_confirmed` 这类旧输入兼容字段不能进入 pending apply payload，避免 `current_stage=preview` 在确认 turn 把 `stage=apply` 重新降级成 preview。
- `handle_pending_confirmation()` 的成功判定必须看执行层 `applied=true`。`preview_only/no_change/error` 都不能把 pending 标成 `applied`，否则会出现“用户看到已确认，但方案没有实际变化”的假成功。

新增/调整保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_chat_service_history_persistence.py::test_extract_plan_confirmation_candidate_ignores_plan_next_action_preview_result_without_execute \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_completes_plan_next_action_preview_before_pending_card \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_applies_completed_plan_next_preview_on_short_text_confirm \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_plan_next_structured_remove_scope_pending_uses_execute_resolved_ids \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_pending_confirm_preserves_plan_next_sort_field_when_execute_payload_is_thin -q

.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py -q
.venv/bin/python -m pytest \
  tests/unit/test_chat_service_history_persistence.py \
  tests/unit/test_intent_state_tool.py \
  tests/unit/test_plan_semantic_action_tool.py \
  tests/unit/test_plan_orchestration_tool.py \
  tests/unit/test_plan_execution_tool.py -q
```

结果：

- focused service tests：`5 passed`。
- Plan execution tool：`130 passed`。
- Agent 服务/意向/语义动作/编排/执行组合回归：`681 passed`。

发布约束：

- 后续新增方案动作时，不允许把 `plan_next_action.preview_summary` 直接展示为确认卡内容。
- 任何高副作用动作都必须先经过执行层解析、版本保护和 pending 确认；执行层不能拿模型自然语言回复作为 apply 范围。
- 对 “中外合作/高收费/预算/仅保留/必须有/排除” 这类多语境诉求，仍按结构化 goal/scope 或 Java user-goal proposal 处理，不再恢复关键词式快补丁。

## 19. 负向约束语义反转修复与约束动作回归

2026-06-16 继续跑 `310_constraint_plan_action` 时发现一个比断言通过更严重的语义问题：

- 用户输入“不要英语相关专业，当前方案里有的话也删掉”。
- 主模型调用 `preview_current_major_intent_confirmation` 时同时传入：
  - 负向：`negative_level3=[英语, 商务英语, 翻译, ...]`
  - 正向父级：`level1=文学`、`level2=外国语言文学类`
  - `constraint_intent_type=only_keep`
- 结果确认卡显示“只保留专业：英语；排除专业：英语”，确认后按 `only_keep_scope` 执行，移除了 88 条非英语志愿。

根因：

- 这不是用户话术匹配问题，而是结构化意向 payload 内部出现正负极性冲突。
- 既有 only-keep 补偿只处理“正向只保留 + 模型臆造负向补集”的情况；没有处理“负向排除 + 模型臆造正向父级/同名项”的反向错误。
- 后续 Java `FixProposal` 按结构化 goal 正确执行，所以错误一旦进入 pending，就会被稳定地执行成错误结果。

本轮收口：

- 在专业意向归一化层新增正负极性冲突净化：
  - 如果正向专业/专业类/门类只是负向范围的同名项、父级或覆盖范围，且用户原话没有明确正向表达该范围，则删除这个正向项。
  - 负向排除场景清理后没有正向值时，`only_keep/must_have` 自动降级为 `default`，不能进入 `only_keep_scope`。
  - 显式正负混合仍保留，例如“我倾向会计学和审计学，但土木工程不要”仍输出正向会计/审计 + 负向土木。
- `resolved_apply_payload` 允许作为父 payload 的增量补全：
  - 执行层 preview 可能只在 `facts.resolved_apply_payload.atomic_actions` 里返回稳定 `volunteer_ids`。
  - service 构造 pending 前会把 resolved payload 继承父级 `action_family/stage/user_goal` 后再校验可执行性。
  - 这样不会因为 resolved payload 没重复带 `action_family` 而丢掉确认卡。
- 对 `310-constraint-exclude-major-preview-and-apply` 的回归断言加严：
  - 第一轮和确认执行结果禁止出现“只保留/only_keep”。
  - 确认结果禁止再次出现“移除88”这类 only-keep 式错误。

新增/调整保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_intent_state_tool.py::test_remove_unstated_positive_major_conflicts_prefers_negative_scope \
  tests/unit/test_intent_state_tool.py::test_remove_unstated_positive_major_conflicts_keeps_explicit_positive_scope \
  tests/unit/test_intent_state_tool.py::test_analyze_intent_change_downgrades_unstated_only_keep_for_negative_major \
  tests/unit/test_chat_service_history_persistence.py::test_extract_plan_confirmation_candidate_accepts_incremental_resolved_apply_payload \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_recovers_exclude_goal_when_agent_misroutes_to_remove_units -q

.venv/bin/python -m pytest \
  tests/unit/test_plan_execution_tool.py \
  tests/unit/test_plan_orchestration_tool.py \
  tests/unit/test_plan_semantic_action_tool.py -q
```

结果：

- Focused unit tests：`5 passed`。
- Plan execution/orchestration/semantic action tests：`197 passed`。

Live 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_constraint_plan_action_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_constraint_plan_action_after_intent_polarity_fix.json
```

结果：

- `310_constraint_plan_action`：`9 steps / 9 successfulSteps / failedSteps=0`。
- “不要英语相关专业”已变为 `exclude_scope`：
  - 预览：当前方案命中英语 6 条，本次可替换 5 条。
  - 确认：移除 6 条、补入 5 条。
  - 不再出现“只保留英语”或大规模移除非英语志愿。
- “中外合作的都排除掉”仍走 `remove_units` 执行层 preview，确认后移出 4 条中外合作志愿，并同步后续报考参考。
- “学费控制在两万以内”走 `tuition_budget_scope` 的 Java user-goal proposal，生成可确认调整预览。

非阻断观察：

- 本组存在模型请求长尾：
  - 学费预算预览：`50.4s`。
  - 中外合作预览：`41.5s`。
  - 英语排除预览：`20.1s`。
- 长尾主要来自 full agent 多轮模型请求和最终整合，不是工具执行失败；当前通过 thinking hint 缓解等待感。
- 后续优化应优先减少不必要的多轮模型请求或让高置信复合目标更稳定进入结构化 proposal 链路，但不能牺牲回复质量或绕开确认协议。

## 20. 审查修复链路回归结果

2026-06-16 在负向约束反转修复后复跑 `310_review_repair`：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_review_repair_after_polarity_fix.json
```

结果：

- `310_review_repair`：`9 steps / 9 successfulSteps / failedSteps=0`。
- 审查总结、候选不足说明、可修复/不可修复分层、专业组兜底预览、旧审查结果重新审查等场景均未出现结构化字段泄露或直接改方案。
- 不可直接处理的提醒已能转成用户可理解的取舍方向，例如高收费/中外合作先确认接受范围，冲稳保/梯度问题先说明候选不足或需要放宽条件。

非阻断观察：

- 审查类链路仍有明显长尾：
  - 审查提醒分层：`48.4s`。
  - 手动移动后重新审查：`40.1s`。
  - 审查总结：`37.8s`。
  - 兜底专业预览：`30.9s`。
  - 候选不足说明：`30.4s`。
- 这些长尾多为 full agent 首轮/末轮模型整合叠加 Java 审查耗时。当前正确性可接受，但 3.1.0 发布前仍需要在完整回归里继续观察是否出现 180s 超时。
- 话术层面仍有少量抽象表达，例如“兜底专业不足”“需要你先取舍或放宽条件”。本轮不作为阻断项，后续统一进入用户语言润色清单。

## 21. Open Quality 回归与目标策略保护

2026-06-16 继续复跑 `303_open_quality` 时发现“就按别太冒险的思路把这版调稳点，先给我看看会怎么动”会被语义路由识别为 `preview_fix_proposal`，目标策略为 `rebalance_tier_ratio / fill_probability_gap`，但后端同轮返回的 `ready` proposal 只有 `fill_missing_count`，风险相关的 `fill_probability_gap` 仍是 `preview_only`。旧选择逻辑在目标策略没有 ready 命中时，会兜底选择第一个 ready proposal，导致给用户生成“处理数量校验”的确认卡，偏离“调稳/风险”的真实目标。

本轮修复：

- `_select_ready_fix_proposal()` 在显式 `target_strategies` 存在时，只能选择策略匹配的 ready proposal；没有命中时返回 `None`，不能退回第一个 ready proposal。
- full agent 自行调用 `execute_plan_action` 的后处理链路，会从本轮工具调用的 `plan_payload.target_strategies` 读取结构化目标，并写回 `latest_plan_result.target_strategies`，确保 service pending 生成逻辑和 semantic route 逻辑使用同一套目标策略。
- `_select_ready_fix_proposal_for_reply()` 和 `_select_ready_fix_proposal_for_user_goal()` 只在目标策略候选范围内做回复语义仲裁；模型仲裁不能把无关 proposal 选回来。
- `_ready_fix_proposal_id_for_strategies()` 同步返回空，避免后续 `selectedProposalId` 误指向无关 ready 项。
- 这不是用户话术关键词匹配，而是复用语义路由/规划层已经产生的结构化 `target_strategies`，符合 `Scenario -> PlanGoal/ReviewCheck -> Strategy -> Proposal -> Action` 分层。

新增保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_chat_service_history_persistence.py::test_select_ready_fix_proposal_requires_target_strategy_match \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_does_not_create_unrelated_fix_card_when_target_strategy_has_no_ready_match \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_selects_fix_proposal_by_ordered_target_strategy \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_full_agent_fix_preview_infers_target_strategy_for_card \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_full_agent_fix_preview_uses_reply_focus_when_strategy_missing \
  tests/unit/test_intent_state_tool.py::test_analyze_current_interest_wrapper_returns_structured_payload_when_semantic_recovery_enabled \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_recovers_confirmable_intent_payload_from_interest_tool -q
```

结果：`7 passed`。

Live 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_open_quality_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_303_open_quality_after_target_strategy_guard.json
```

结果：

- `303_open_quality`：`23 steps / 23 successfulSteps / failedSteps=0`。
- “调稳点，先给我看看会怎么动”不再生成 `fill_missing_count` 确认卡；回复改为解释风险相关的 `fill_probability_gap` 和数量补齐两个方向，并明确风险相关方向需要先定取舍范围，没有 active pending。
- 混合软硬意向、无 pending 后确认保护、专业简称对比、职业方向只读分析、方案查询只读、排序预览确认边界均未回退。

非阻断观察：

- 本组长尾仍明显：median `20.5s`，p95 `43.2s`，max `54.9s`。
- 最慢场景为“中外合作 + 预算一般 + 大白话风险分析”，回复正确保持只读，但内容焦点偏向通用审查摘要，没有充分围绕中外合作数量、费用压力、可替换/不可替换边界展开。该问题记录为回复质量遗留，后续应通过审查结果聚焦和大模型整合提示优化，不用字符串匹配用户话术。
- 候选查询类场景仍有 9-11s 的条件抽取耗时；职业方向多维分析和最终整合也有 30s 级长尾。当前发布前不以牺牲回复质量为代价做快路由，继续通过 thinking hint 缓解等待感，并在后续版本做结构化事实复用和模型调用收敛。

同轮复跑 `310_constraint_plan_action`，确认目标策略保护没有影响约束方案动作：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_constraint_plan_action_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_constraint_plan_action_after_target_strategy_guard.json
```

结果：

- `310_constraint_plan_action`：`9 steps / 9 successfulSteps / failedSteps=0`。
- `only_keep` 与 `must_have` 仍只先写入待采纳报考条件，并提示后续如需改方案会再给调整预览。
- “不要英语相关专业，当前方案里有的话也删掉”仍走 `exclude_scope` 的 plan mutation，确认后移除 6 条、补入 5 条，没有回到 only-keep 语义反转。
- “中外合作的都排除掉”仍走执行层 `remove_units` 预览，确认后移出 4 条并同步后续报考参考。
- “学费最好控制在两万以内”生成 `tuition_budget_scope` 的 user-goal 调整预览，确认前不改方案。

观察：

- 约束组 median `19.5s`，p95/max `38.3s`，最慢为中外合作删除预览。慢点主要来自 full agent 多轮模型请求，不是工具执行失败。
- 预算场景的语义分类 `reason` 中出现“应交给完整 Agent/不应判为 preview”的自我纠正文字，但最终结构化输出仍成功生成预算 user-goal proposal。该现象作为模型裁决解释质量问题记录，执行层仍以结构化 action/result 和 pending 为准。

同轮复跑 `310_review_repair`，确认审查修复链路仍保持统一协议：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_review_repair_after_target_strategy_guard.json
```

结果：

- `310_review_repair`：`9 steps / 9 successfulSteps / failedSteps=0`。
- 审查总结、候选不足说明、费用/中外合作不可直接处理解释、专业组内安全垫预览、重新审查和专业模式导出口径均未出现结构化字段泄露或直接改方案。
- 专业组安全垫场景仍能选择 `adjust_major_group_inner_safety` 的 ready proposal 生成 `apply_fix_proposal` 确认卡，未被策略 guard 误拦截。

待排查/优化：

- `310-review-shortage-honesty` 的回复出现“可选志愿共431个（冲459/稳238/保773）”这种总数与分项不一致的表达。需要确认是模型把不同口径字段混写，还是后端 candidate facts 的 `total/tierCounts` 本身有口径问题。发布前至少要避免输出自相矛盾数字。
- `310-review-fix-preview-then-apply` 在 session 130 下回复“高收费和中外合作没有触发这类提醒”，而其他同 session 审查/移动后审查显示存在相关提醒。需要确认 case 清理后的 planning state 是否不同，或 `analyze_adjustment(targetStrategies=replace_risk_items)` 的 facts 过滤过窄。
- 本组性能仍偏慢：median `30.1s`，p95/max `56.4s`；最慢为“审查提醒分层”和“手动移动后重新审查”。当前正确性可接受，但 long-tail 继续纳入发布观察。

## 22. 候选供给口径与处理建议仲裁修复

2026-06-16 继续排查第 21 节遗留问题，确认 `310-review-shortage-honesty` 的矛盾数字来自 Agent 事实层口径混用，而不是用户话术或最终回复渲染：

- session 132 的 `candidatePoolState.summary` 同时包含：
  - `unitTotal=431`、`unitTierCounts=冲125/稳68/保238`。
  - `entryTotal/total=1470`、`tierCounts=冲459/稳238/保773`。
- 当前会话的 `volunteerModel` 为空，旧逻辑总数优先取 `unitTotal`，分层在模式缺失时取 `tierCounts`，因此给模型的事实变成“431 个候选，冲459/稳238/保773”，属于 Agent 结构化事实错误。

修复：

- `_build_candidate_supply_facts()` 下的候选供给统计新增模式归一：
  - `majorGroup / major_group / group / schoolMajorGroup` 等别名都按专业组单元口径处理。
  - 即使 `volunteerModel` 缺失，只要上游同时给出不同的 `unitTotal` 与 `entryTotal/total`，就认为存在单元/条目双口径，优先使用 `unitTierCounts`，保证总数和冲稳保分项来自同一口径。
- `_filter_review_facts_for_targets()` 修复目标过滤边界：
  - 如果 review examples 没有命中，但 matching `fix_proposals` 已命中用户点名目标，不再把该目标误判为 `target_match_empty`。
  - 这避免“有后端处理建议，但回复说当前没有这类提醒”的错误分支。
- `preview_fix_proposal` 的 ready proposal 选择统一走 `_select_ready_fix_proposal_for_user_goal()`：
  - 只在显式 `selected_proposal_id` 已存在时直接按 ID 选。
  - 多个 ready proposal 同时匹配目标策略时，不再按 `targetStrategies` 顺序拿第一个，而是复用小模型仲裁，从候选 proposal 的 `title/summary/strategy/sourceCheckCodes` 与用户本轮诉求中选择最贴近的一项。
  - 例如“专业组里太悬，补一个安全一点的专业，先看预览”同时涉及 `sort_by_probability` 和 `adjust_major_group_inner_safety` 时，应选择“补兜底专业/组内安全垫”而不是“录取率倒挂排序”。

新增/更新保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_planning_workflow_tool.py::test_build_candidate_supply_uses_unit_tier_counts_for_major_group_alias \
  tests/unit/test_planning_workflow_tool.py::test_build_candidate_supply_prefers_unit_tier_counts_when_unit_and_entry_totals_differ \
  tests/unit/test_handler_registry.py::TestAnalysisHandlerTargetFiltering \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_selects_fix_proposal_by_ordered_target_strategy \
  tests/unit/test_chat_service_history_persistence.py::test_select_ready_fix_proposal_requires_target_strategy_match \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_does_not_create_unrelated_fix_card_when_target_strategy_has_no_ready_match -q
```

结果：

- 候选供给与 target filtering 相关测试：`7 passed`。
- fix proposal 选择相关测试：`3 passed`。

Live 验证：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_review_repair_after_candidate_supply_fix_v2.json
```

结果：

- `310_review_repair`：`9 steps / 9 successfulSteps / failedSteps=0`。
- `310-review-shortage-honesty` 不再输出“431 个候选但冲稳保分项相加超过总数”的矛盾数字；回复改为说明当前没有识别出稳/保数量不足，不承诺强行补齐。
- `310-review-fix-unavailable-guidance` 只围绕高收费和中外合作这两类 matching target 展开，没有混入非目标提醒。
- session 130 现场复查显示当前本地状态下确实没有 `high_tuition/cooperative_program` 审查命中，只有 `probability_gap` 和 `major_group_safety_intent_alignment`；因此该 case 的“没有高收费或中外合作提醒”属于会话事实差异，不作为代码误判。

单条真实验证：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --session 131 \
  --prompts 专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览 \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_major_group_safety_arbitration_probe.json
```

结果：

- `1 step / 1 successfulStep / failedSteps=0`。
- 回复与确认卡选择 `adjust_major_group_inner_safety`，标题为“处理兜底专业不足”，卡片内容包含“补入兜底专业”，不再误选“处理录取率倒挂”。

仲裁修复后完整回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_review_repair_after_arbitration_fix.json
```

结果：

- `310_review_repair`：`9 steps / 9 successfulSteps / failedSteps=0`。
- `310-review-shortage-honesty` 继续保持同一口径候选供给事实，没有再出现总数与冲稳保分项自相矛盾。
- `310-review-major-group-inner-safety` 在完整回归中仍选择 `adjust_major_group_inner_safety`，没有被 `sort_by_probability` 或目标策略顺序误导。
- `310-review-fix-preview-then-apply` 在当前 session 130 本地状态下仍正确按审查事实说明没有高收费/中外合作命中，不再因为目标过滤为空而混入其他审查问题。

剩余观察：

- review/repair 真实回归仍有长尾：最新完整回归 median `25.966s`，p95/max `52.475s`；超过 30s 的场景包括审查总结、候选不足说明、专业组安全垫预览和手动移动后重新审查。
- 当前长尾主要来自 full agent 多轮模型请求和最终整合；本轮不以牺牲回复质量为代价做快路由，继续用 thinking hint 缓解等待感。

## 23. 位置范围删除结构化落地

2026-06-17 继续扩大生产抽象场景回归时，`310-prod-plan-range-remove-safe-zone` 暴露出一个原子动作粒度不足的问题：

- 用户表达的是“第 40 位之后的几个保”，真实目标包含起始位置、方向范围、冲稳保层级和数量。
- 旧 `remove_ordered_unit` 只能表达单个 `source_position`，即便 live 场景通过，也只是删除第 41 个展示单元，不能覆盖“之后 + tier + 多个”的完整语义。
- 这个问题不能通过用户话术字符串匹配解决；需要让模型/恢复器输出结构化范围字段，再由执行层读取当前方案展示单元并解析成稳定 ID。

本轮实现：

- `PlanAtomicAction` 新增 `position_scope`，当前支持：
  - `single`：默认单点位置，保持旧行为。
  - `after`：从 `source_position` 之后开始选取展示单元。
- `plan_next_action` 和 semantic recovery decision 同步支持 `position_scope / positionScope`，并要求范围删除时结构化传入：
  - `action_family="remove_ordered_unit"`
  - `source_position=N`
  - `position_scope="after"`
  - 可选 `tier` 和 `limit`
- 执行层 `_build_remove_ordered_unit_preview_summary()` 负责读取当前 `orderedPlanState`：
  - 院校专业组模式下解析为多个 `unit_ids`，确认后仍走 `remove_ordered_unit`。
  - 专业+大学模式下解析为多个 `volunteer_ids`，preview facts 写入 `resolved_apply_payload(action_family="remove_units")`，确认后执行志愿删除。
  - `resolved_apply_payload` 是确认态唯一可执行范围，确认时不再根据用户原话或模型回复重猜。
  - 范围解析没有命中可删除项时返回 `no_change`，不生成确认卡。
- ChatAgent dispatch 规则只补结构字段要求，不增加用户话术关键词路由。

新增保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_plan_orchestration_tool.py \
  tests/unit/test_plan_execution_tool.py \
  tests/unit/models/test_typed_actions.py \
  tests/unit/test_instructions.py -q
```

结果：`311 passed`。

追加修复：

- 首次 live 复验中，`position_scope=after / tier=保 / limit=5` 已进入 payload，但如果当前 cloned state 的第 40 位之后没有匹配项，执行层仍返回 `preview_only`，service 会误生成确认卡。
- 已将 `range_empty / missing_source_position` 收敛为 `no_change`，并在 service pending 创建兜底里阻断这类不可执行位置范围。
- Focused 回归：`4 passed`，覆盖范围空命中不出确认、范围命中专业组/志愿解析和 no-change 不建 pending。

同轮 targeted production 抽象回归前置结果：

- `310-prod-only-keep-clinical-medicine`：通过，不再把“只保留临床医学”误路由成删除临床医学。
- `310-prod-only-keep-multiple-majors`：通过，断言已加严为同时覆盖“电气”和“气象”，避免只识别一个实体也通过。
- `310-prod-negative-major-then-fill`：通过，“从候选中选择 7 所放入方案里”进入 `add_units`，不再误走 repair proposal。
- `310-prod-plan-range-remove-safe-zone`：复跑通过；当前 cloned state 下生成 `remove_ordered_unit` preview，命中第 41-45 位共 5 个专业组，预览披露“减少 24 个专业 / 5 个专业组”，不再单删第 41 项。

后续回归要求：

- 继续补充范围删除确认后的 apply 验证，重点确认 pending 中消费 `resolved_apply_payload`，不重新解释自然语言。
- 继续跑 `310_constraint_plan_action`、`310_review_repair`、`303_open_quality`、`303_dialogue_derived`；如果出现超时，优先记录模型请求长尾和 thinking hint 表现，不能为了速度绕开确认协议或降低回复质量。

## 24. only_keep 正向范围恢复

2026-06-17 在继续回归 `310-prod-only-keep-multiple-majors` 时，发现一个结构性失败模式：

- 用户表达“只要电气和气象，其他方向都不要”。
- 上游语义抽取有时会把它退化成一整片负向补集，导致只剩“排除全部学科门类”，没有正向目标。
- 这种情况如果直接进入确认，会把 `only_keep` 误降级成普通排除，用户看到的结果也会偏离原意。

本轮修复：

- 新增正向范围恢复逻辑 `_recover_only_keep_positive_scope_from_generated_complement(...)`。
- 仅在语义仲裁已经明确为高置信 `intent_preview` 且 `constraintIntentType=only_keep` 时触发。
- 只有当负向侧退化成宽泛的门类级补集、并且最新话术里能明确识别到正向专业目标时，才从专业目录回收正向 scope。
- 同时继续剪掉由补集生成器带出来的多余负向项，避免“正向恢复后又把自己排掉”。

已验证回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_production_abstracted_cases.json \
  --case-name 310-prod-only-keep-multiple-majors \
  --case-name 310-prod-negative-major-then-fill \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_prod_two_after_only_keep_recovery_fix.json
```

结果：

- `310-prod-only-keep-multiple-majors` 正确恢复为“只保留专业：电气（电气工程及其自动化）、气象（大气科学）”。
- 当前方案/候选池没有对应目标时，回复保持为意向记录卡，不误导成已执行方案调整。
- `310-prod-negative-major-then-fill` 仍稳定保持原有填补/记录行为，没有被这次恢复逻辑误伤。

边界说明：

- 这次修复只处理“高置信 only_keep + 宽泛负向补集”这类结构性退化，不扩展到普通排除、普通偏好或弱语义猜测。
- 只保留、必须有、排除等约束型意向，后续仍以确认卡 + 方案预览为主链路，不回退到纯字符串匹配。

## 25. 对话 recovery 优先级收口

2026-06-17 继续回归 `303_open_quality` 时，发现一个由前期 recovery 保护诱发的优先级重叠问题：

- 普通意向表达“我倾向会计学和审计学，但土木工程不要”应进入 `intent_change` 待采纳卡。
- 当模型没有正确调用意向工具、或只读工具吞掉明确意向时，Service 会尝试恢复到 Intent preview 主链路。
- 但恢复出 `intent_change` 后，后续 no-tool composite goal recovery 仍可能继续运行，把普通意向误升级成 `plan_mutation / only_keep_scope`，形成另一张方案调整卡。

本轮修复边界：

- recovery 仍保留为协议保护，但只能把请求送回主链路，不能成为第二套业务流程。
- 一旦本轮已恢复出 `recovered_pending_intent_card`，后续 no-tool composite goal recovery 必须停止。
- 候选只读查询继续通过 LLM-backed candidate filter extractor 判断是否应绕开 semantic plan action；命中后回到 full agent 的 `query_volunteer_plan(scope=candidate)`，不走方案调整。
- 这不是用户话术字符串匹配：普通意向实体仍由 `analyze_volunteer_intent_change` 抽取；候选查询条件仍由 `extract_candidate_query_filters_async` 抽取；补丁只处理运行态优先级和工具协议边界。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "readonly_compare_misroute or no_tool_explicit_intent or candidate_bypass or recovers_confirmable_intent_payload_from_interest_tool or semantic_plan_route" -q
```

结果：`9 passed`。

Focused live 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_open_quality_cases.json \
  --case-name 303-open-quality-intent-existing-impact-readonly \
  --case-name 303-open-quality-candidate-colloquial-query-readonly \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_303_open_quality_focused_after_intent_priority_fix.json
```

结果：

- `303-open-quality-intent-existing-impact-readonly`：通过。首轮工具链为 `preview_current_major_intent_confirmation`，输出 `pendingConfirmationCard(kind=intent_change, actionFamily=apply_selected_intents)`，没有生成 `plan_mutation`。
- 同 case 第二轮“先不确认，看看影响”保持 active pending 解释，只说明采纳前不生效，不改方案。
- `303-open-quality-candidate-colloquial-query-readonly`：通过。工具链为 `query_volunteer_plan(scope=candidate)`，没有被 semantic `analyze_adjustment` 抢成方案调整。
- 延迟仍有警告：三步 median 约 `22.2s`，max 约 `25.9s`；候选查询里的 `extract_candidate_filters` 耗时约 `8.7s`。这是性能优化项，不影响本轮主链路收口结论。

后续回归关注点：

- 继续跑完整 `303_open_quality`、`303_dialogue_derived` 和 3.1.0 生产抽象场景，观察是否还有普通意向被复合方案 recovery 抢占。
- 如果再遇到同类问题，优先检查 route priority 和 recovery stop condition；不要新增并行兼容 action 或用户话术关键词补丁。

完整 `303_open_quality` 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_open_quality_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_303_open_quality_full_after_intent_priority_fix.json
```

结果：`23 steps / 23 successfulSteps / failedSteps=0`。

覆盖确认：

- 普通意向和混合软硬意向稳定走 `preview_current_major_intent_confirmation -> pendingConfirmationCard(kind=intent_change)`。
- 只读专业比较、职业方向分析、方案查询和候选查询均无 active pending，也没有误生成方案确认卡。
- 只读比较后的“嗯那就这样”走 `readonly_closure_ack`，没有把上一轮分析误当成待确认动作。
- 排序预览走 `plan_next_action -> execute_plan_action(sort_ordered_plan, preview)` 并生成 `plan_mutation` 确认卡，符合高副作用确认协议。
- “调稳点，先看会怎么动”仍走 semantic `preview_fix_proposal`，并受目标策略过滤保护，没有兜底选中无关 ready proposal。

遗留观察：

- 主要问题已从路由正确性转为性能长尾和用户话术润色。慢点为：
  - `303-open-quality-lazy-plan-too-risky-readonly`：`63809ms`，主要是审查解释和最终模型整合。
  - `303-open-quality-budget-risk-colloquial-readonly`：`49549ms`，主要是审查解释和最终模型整合。
  - `303-open-quality-career-parent-colloquial-readonly`：`39406ms`，主要是职业方向分析的模型整合。
- `303-open-quality-intent-no-med-accounting-ok-impact` 通过，但回复仍出现“待确认要求 / 当前只是分析口径”等偏系统化表达。该问题记录为后续文案优化，不影响本轮 route priority 收口。
- 当前不为降低延迟恢复字符串快路由；后续应从事实复用、只读工具结果直出质量、模型整合调用次数和 thinking hint 继续优化。

`310_constraint_plan_action` 回归补充：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_constraint_plan_action_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_constraint_plan_action_after_intent_priority_fix.json
```

结果：`9 steps / 9 successfulSteps / failedSteps=0`。

覆盖确认：

- `only_keep_scope`：只保留临床医学时生成 `intent_change` 卡；当前方案/候选没有可执行调整时只写入条件，不伪造方案修改。
- `must_include_scope`：必须有法学时生成 `intent_change` 卡；当前无补入候选时只写入条件并提示后续可看补入预览。
- `exclude_scope`：排除英语、中外合作等明确要求能生成 `plan_mutation(actionFamily=apply_fix_proposal)`，确认后调用 Java apply 并同步写入报考参考。
- 预算约束能生成 `tuition_budget_scope` proposal，披露当前可替换数量和剩余不可处理数量。

遗留观察：

- `310-constraint-exclude-cooperative-program-preview-and-apply` 首轮耗时 `49338ms`。工具链先走 `remove_units` 预览，再由 `composite_goal_recovery_after_plan_attempt` 桥接到 `user_goal_proposal`；结果正确，但说明复合目标直达 Java user-goal proposal 的路由还可继续收敛，减少先试普通删除再恢复的长链路。

`310_review_repair` 回归补充：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_review_repair_after_intent_priority_fix.json
```

结果：`9 steps / 9 successfulSteps / failedSteps=0`。

覆盖确认：

- 审查总结、候选不足说明、不可自动处理说明、专业组组内安全垫预览、手动移动后重新审查均保持正确链路。
- `preview_fix_proposal` 仍能生成 `apply_fix_proposal` pending 卡；`analyze_adjustment` 保持只读解释，不生成可执行 pending。
- 重新审查请求走 `review_plan`，不消费历史预览，也不把上一轮只读解释误当成待确认动作。

遗留观察：

- 本组 median 约 `28.6s`，max 约 `41.0s`，慢点集中在审查结果解释和最终模型整合。
- 部分用户可见文案仍出现“处理高收费 / 处理中外合作 / 处理方向”等标签化表达；这不影响执行安全，但后续需要继续做用户语言润色。

## 26. only_keep 正负范围结构化冲突清理

2026-06-17 继续跑 `310_production_abstracted` 时，发现 `310-prod-only-keep-medical-not-engineering` 有新的结构化冲突：

- 用户表达“不考虑工科，只考虑医学类”。
- full agent 正确进入 `preview_current_major_intent_confirmation`，但工具 payload 中同时出现：
  - 正向 `major_intents.level1=["医学", "工学"]`
  - 负向 `major_intents.negative_level1=["工学"]`
- service 随后把正向范围转换成 `only_keep_scope.targetScopes`，导致预览文案出现“当前方案中有 0 条符合‘医学、工学’”，把被排除的工学误混入只保留目标。

本轮修复原则：

- 不按“不考虑/只考虑”等用户话术做字符串补丁。
- 在 Intent 工具层和 service 防御层都做结构化净化：同一 payload 中，正向目标如果被同级或更宽的负向范围覆盖，必须从正向目标中剔除。
- 负向子范围不能反向删除更宽的正向目标。例如“只考虑医学，但护理不要”应保留 `target=医学`，同时保留 `negative=护理学`，不能把医学整体删掉。
- `only_keep_scope` 的执行目标只能来自净化后的正向范围；负向范围可以作为报考条件和后续检查依据，但不能混入 `targetScopes`。

实现落点：

- `intent_state_tool._preserve_only_keep_positive_major_scope()` 改为先读取最新 utterance 的结构化正负极性恢复结果，避免把同一句里的负向实体补回正向。
- 新增 `_remove_positive_major_targets_excluded_by_negative_scope()`，统一处理专业门类/专业类/具体专业的父子覆盖关系。
- service 的 `_positive_goal_scopes_from_intents()` 在构造 `UserGoalFixProposalReq.targetScopes` 前做同样的防御性清理，防止旧 payload 或外部 payload 绕过工具层净化。

已验证单测：

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py \
  -k "only_keep_major_payload or only_keep_major_conflict_cleanup" -q
```

结果：`7 passed`。

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "plan_mutation_card_drops_excluded_major_from_only_keep_target_scopes or plan_mutation_card_intent_summary_preserves_user_facing_major_alias or recovers_prepared_direction_text_without_tool_call" -q
```

结果：`3 passed`。

追加 route/约束 focused 回归：

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "readonly_compare_misroute or no_tool_explicit_intent or candidate_bypass or recovers_confirmable_intent_payload_from_interest_tool or semantic_plan_route or only_keep or must_have or exclude_scope" -q
```

结果：`22 passed`。

完整 `310_production_abstracted` live 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. ./.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_production_abstracted_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_production_abstracted_after_conflict_cleanup.json
```

结果：`22 steps / 22 successfulSteps / failedSteps=0`。

覆盖确认：

- `310-prod-only-keep-medical-not-engineering` 首轮已稳定输出“只保留专业门类：医学；排除专业门类：工学”，`latestIntentPreviewPayload` 中不再出现正向 `工学`。
- 第二轮“只要医学”没有生成包含工学的目标范围；当前方案/候选没有医学目标时，仍回退为待采纳报考条件，不伪造当前方案调整。
- `310-prod-only-keep-multiple-majors` 仍能恢复“电气（电气工程及其自动化）、气象（大气科学）”，没有被本轮冲突清理误伤。
- `310-prod-only-keep-region` 仍生成 Java `user_goal` 的 `plan_mutation` 预览，说明专业冲突净化没有影响地域目标链路。
- 通用政策/具体学校专项查询、学校对比、高层体制内方案分析、移动第 N 个专业组等链路均未出现 route 回退。

遗留观察：

- `310-prod-negative-major-then-fill` 第二步“从候选中选择7所放入方案里，先补齐志愿数量”仍返回“未定位到要加入的候选志愿”。这是当前 `add_units` 需要候选 ID 或明确筛选范围的产品边界，不是本轮冲突修复引入的新问题；后续如果要支持“按当前候选池自动补齐数量”，需要新增 `fill_missing_count`/candidate selector 的明确产品规则、排序依据、确认预览和不可满足说明，不能用普通 add_units 临时承接。
- `310-prod-only-keep-medical-not-engineering` 第二轮耗时 `39248ms`，主要是先尝试 plan 工具后再 recovery 到 intent 卡；结果正确，但仍可作为后续“复合目标直达 user-goal proposal / intent fallback”性能收敛项。
- “医学”在部分回复中显示为“专业”而非“专业门类”，属于实体层级展示和用户语言润色问题；不影响当前 target scope 净化和执行安全，但后续应统一显示口径。

## 27. 语义只读边界与审查修复目标选择保护

2026-06-17 在完整 `303_dialogue_derived` 回归后继续检查错误样本，发现两类会破坏统一链路的机制问题：

- 用户只是在问“还能不能选/适不适合/就业怎么样”等只读分析问题时，模型或工具可能返回可采纳的意向 payload。此前如果 `intentSideEffectDecision.honored=false`，service 会放开 pending intent card recovery，导致用户明明是在咨询，却被提示采纳报考想法。
- 用户明确要求处理某一类审查问题时，例如“把太贵的那几个先去掉看看”，如果 Java 返回的 ready proposal 只有其他问题（如录取率倒挂排序），旧逻辑会退回到第一个 ready proposal，生成无关确认卡。

本轮修复原则：

- 不新增用户话术字符串匹配。
- 只读/副作用边界以语义仲裁结果为准：当语义判断为 `analysis_only` 或 `mixed_answer_then_ask` 且置信度足够时，即使工具没有遵守该边界，也不能恢复可采纳卡片。
- 可执行修复必须匹配结构化目标范围：`target_strategies` 与 `target_issue_codes/source_check_codes` 同时参与选择；当用户目标明确但没有匹配 ready proposal 时，不允许选择无关 ready proposal 兜底。
- 约束型意向仍然优先进入统一方案调整链路：能由 Java 生成安全预览时走 `user_goal` proposal，不能生成时再退回报考参考确认，不伪造方案调整。

实现落点：

- `_semantic_intent_decision_requires_readonly()` 不再因为 `honored=false` 放开意向卡恢复。这里的 `honored=false` 表示模型/工具没有遵守语义边界，而不是允许副作用继续发生。
- `_select_ready_fix_proposal()`、`_select_ready_fix_proposal_for_user_goal()`、`_select_ready_fix_proposal_for_reply()` 增加 issue-code 过滤，不再只按 strategy 或第一个 ready proposal 选择。
- `_infer_fix_proposal_target_scope()` 同时返回 strategy 和 issue code，支持“高收费/中外合作/保底不足/倒挂”等审查问题的结构化目标收敛。
- 混合型约束意向（例如“倾向会计和审计，但土木不要”）会保留正向偏好到 `intentPayload`，同时把负向约束交给 `user_goal` 生成方案预览。
- 有显式 `volunteer_ids` 的原子调整预览跳过不必要的 composite override 识别，避免额外模型调用和重复路径。
- 意向卡摘要清理重复标签，并保留用户可理解别名，例如 `气象（大气科学）`。

完整 `303_dialogue_derived` 回归结果：

```text
88 steps / 88 successfulSteps / failedSteps=0
median=22970ms, p95=50035ms, max=71806ms
```

已验证单测：

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
```

结果：`339 passed`。

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/unit/test_plan_orchestration_tool.py -q
```

结果：`66 passed`。

```bash
cd zhiyuan-agent
./.venv/bin/python -m pytest tests/regression/test_keyword_matchers.py -q
```

结果：`32 passed`。

重点样本预期：

- `小语种现在还能选吗，怕就业不好`：只做专业适配和就业风险分析，不生成意向采纳卡。
- `把太贵的那几个先去掉看看`：只允许匹配高收费/中外合作相关 proposal；若当前没有可直接执行的匹配 proposal，不生成录取率倒挂等无关卡片。
- `我倾向会计学和审计学，但土木工程不要`：正向偏好保留为后续推荐参考，负向约束进入方案调整预览。

遗留观察：

- 模型调用仍有长尾，`303_dialogue_derived` p95 约 `50s`、max 约 `72s`。当前不牺牲回复质量做硬截断，后续优先通过前端进度提示和更短的无副作用工具链改善体感。
- 部分审查/调整回复仍有标签化或系统化措辞，需要继续按用户语言润色，但不作为当前执行安全阻断项。
- live 环境仍需在固定端口重新启动后复跑 focused case 和累计场景集，确认本轮单测保护在真实对话链路中稳定生效。

## 28. 审查 0 风险的概率表述边界

2026-06-17 focused live 回归中发现 `保底够不够，别最后滑档` 一类问题存在高风险话术：

- 工具审查结果为 `risk_count=0` 时，模型曾回复“当前方案没有风险项，不会滑档”。
- 这是错误边界。审查 0 风险只表示当前审查规则没有发现明确风险，不等于保证录取，也不能承诺不会滑档。

本轮修复原则：

- 不改用户意图路由，不按用户问法做字符串分流。
- 在提示词中明确审查概率边界：`风险 0 项 / 提醒 0 项` 只能说“暂未发现明确风险”，不能说“不会滑档、保证录取、一定安全、稳了”。
- 在 service 最终回复层增加审查/调整分析安全兜底：只要本轮工具结果是 `review_result` 或 `adjustment_analysis`，最终回复出现录取安全绝对承诺，就改用结构化事实生成保守回复。
- 允许正确的风险提示，例如“不能保证不会滑档”“仍要看录取概率、排序、专业/学费接受度和当年波动”。

实现落点：

- `tool_dispatch_rules.py` 的 Plan 层规则补充概率口径。
- `service._review_reply_overclaims_admission_safety()` 识别审查和方案调整分析回复中的绝对化录取安全承诺。
- 最终回复归一化链路在结构化兜底前应用该保护，避免模型自由发挥覆盖工具事实边界。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "overclaims_admission_safety or rewrites_zero_review_result_absolute_slip_claim or review_reply_needs_structured_fallback or review_result_fallback" -q
```

结果：`4 passed`。

后续 live 复跑重点：

- `保底够不够，别最后滑档`：应说明当前审查未发现明确风险/保底结构看起来相对稳，但不能保证不会滑档，并提示继续看录取概率、排序、专业接受度和当年波动。
- `这版稳了吗 / 会不会滑档 / 兜底够不够`：都应使用概率和审查边界口径，不输出绝对安全承诺。

focused live 复验：

```text
保底够不够，别最后滑档
elapsedMs=41130
tool=execute_plan_action(review_plan/review_result)
结果：返回风险 0 项、提醒 3 项、冲稳保分布和需要关注的高收费/中外合作/非意向托底；未再出现“不会滑档/保证安全”等绝对承诺。
```

## 29. 意向变更不能被无卡方案确认兜底吞掉

2026-06-17 测试环境发现：

- 会话开头系统提示已有 `偏好地域：上海、安徽、山东、江苏、江西`。
- 用户输入 `不想去安徽`。
- 系统回复“这轮还没有生成可执行的调整内容，所以不会改动当前方案……”，且没有弹出待采纳内容。

这说明用户在表达地域意向变化时，被错误落到了“方案调整确认缺少预览”的兜底分支。该兜底本身是为了防止模型用自然语言让用户确认方案改动，但不能把专业/院校/地域等报考参考更新吞掉。

本轮修复原则：

- 不按“不想去安徽”这类用户话术做关键词路由。
- 保持主链路仍然是 Agent 自行调用 `preview_current_region_intent_confirmation` 等 Intent 工具。
- 当模型没有生成可执行 plan preview，却写出“确认后更新方案/偏好/地域”等无卡确认话术时，service 在套用无卡 plan 兜底前，先调用统一的 `analyze_volunteer_intent_change` 结构化恢复。
- 只有结构化恢复确实生成不了待采纳内容时，才保留“当前没有可执行方案调整”的兜底。

实现落点：

- 在 `_guard_unbacked_plan_confirmation_reply()` 前新增一次 pending intent recovery。
- 恢复仍复用 `_recover_unbacked_intent_confirmation()`，由 Intent 工具从当前用户输入中抽取专业/院校/地域/职业意向，不在 service 层枚举自然语言。
- guard 分支增加 `recovered_pending_intent_card is None` 条件，避免已经恢复出的待采纳卡又被无卡 plan 兜底覆盖。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "recovers_region_intent_before_unbacked_plan_confirmation_guard or unbacked_region or claimed_region_card or no_tool_explicit_intent or semantic_readonly or overclaims_admission_safety" -q
```

结果：`6 passed`。

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py \
  -k "existing_negative_preference_can_upgrade_to_constraint or existing_preference_returns_helpful_text or preview_current_region_intent_confirmation" -q
```

结果：`6 passed`。

focused live 复验：

```text
不想去安徽
elapsedMs=19227
tool=preview_current_region_intent_confirmation
结果：返回 pendingConfirmationCard，summary=排除地域：安徽；未出现“这轮还没有生成可执行的调整内容”。
```

后续回归重点：

- 已有正向地域偏好中某一项被用户改为不优先或排除时，必须有待采纳内容。
- 专业、院校、地域、职业四类报考参考更新都不能被 plan 无卡兜底吞掉。
- 如果用户真实表达的是当前方案删除/替换/移动，仍必须走方案预览/确认执行，不应被意向卡误接。

## 30. 预算约束不能被错误意向预览和审查结果混合链路吞掉

2026-06-17 继续跑 `dialog_regression_310_constraint_plan_action_cases.json` 时发现：

- 用户输入 `太贵的学校别放了，学费最好控制在两万以内`。
- 模型先误调用 `preview_current_major_intent_confirmation`，把预算诉求当成专业意向预览。
- 同一轮又调用 `plan_next_action(remove_units/analyze)` 和 `execute_plan_action(review_plan/review_result)`。
- 最终没有生成 `pendingConfirmationCard`，只刷新了审查结果，并追问“需要我现在生成这个预览吗？”。

这类问题不是预算识别缺失，而是混合路径的恢复顺序不完整：已有 `tuition_budget_scope` 的 user-goal proposal 恢复能力，但通用复合目标恢复为了防止误覆盖意向卡，遇到任何 intent preview 会直接退出，导致“错误意向预览 + 方案审查”组合没有机会回到预算方案调整链路。

本轮修复原则：

- 不按“太贵/两万”等用户话术做关键词路由。
- 预算不是专业/院校/地域偏好维度，不能持久化成专业意向。
- 当同一轮存在 intent preview 和 plan attempt 时，只允许结构化复合目标模型判定为 `tuition_budget_scope` 的场景覆盖错误意向预览。
- 普通专业、院校、地域、职业意向仍走 intent card，不因这条恢复路径误升级成方案调整。
- 混合路径优先使用最新审查/分析结果里的方案版本和候选信息；没有审查结果时才退回原始 plan_next_action 尝试上下文。

实现落点：

- `_maybe_recover_composite_goal_after_plan_attempt()` 增加 `allow_intent_preview_mixed_path` 参数，默认关闭，避免扩大影响面。
- 主消息后处理链路在已有 plan attempt、无确认卡、无 pending proposal 时，以 `allow_intent_preview_mixed_path=True` 调用复合目标恢复。
- 该模式下如果 `classify_composite_goal_action()` 返回的 action 不是 `tuition_budget_scope`，立即退出，不生成方案调整卡。
- attempted result 优先级调整为：可执行 fix preview -> 当前轮非动作型 plan result/review result -> mutation attempt -> 其他非动作结果，确保预算 proposal 使用最新方案版本。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "tuition_budget_after_wrong_intent_preview_and_review_result or tuition_budget_after_plain_review_result or overrides_wrong_major_intent_preview_for_tuition_budget or recovers_tuition_budget_after_semantic_adjustment_analysis" -q
```

结果：`4 passed`。

回归重点：

- `310-constraint-tuition-budget-preview` 应生成 `tuition_budget_scope` 的 `pendingConfirmationCard`。
- only_keep / must_have / exclude_scope 仍保持原有链路，不被预算恢复口误接。
- 专业/地域等普通意向预览仍生成意向待采纳内容，不进入预算 proposal。

完整约束场景回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_constraint_plan_action_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_constraint_plan_action_after_budget_mixed_fix.json
```

结果：

```text
9 steps / 9 successfulSteps / failedSteps=0
median=19242ms, p95=65893ms, max=65893ms
```

重点样本结果：

- `310-constraint-tuition-budget-preview` 已生成 `plan_mutation` / `apply_fix_proposal` 卡，`strategy=tuition_budget_scope`，summary 为“当前方案里有 76 条学费超过 20000 元/年；本次能替换 5 条”。
- `310-constraint-only-keep-major-preview-boundary` 和 `310-constraint-must-have-major-preview-boundary` 仍生成 intent_change 卡，没有被预算恢复口误接。
- `310-constraint-exclude-major-preview-and-apply` 首轮生成 exclude_scope 方案调整卡，确认后移出 6 条、补入 5 条并刷新 ordered/candidate/review。
- `310-constraint-exclude-cooperative-program-preview-and-apply` 首轮生成 remove_units 方案调整卡，确认后移出 4 条并刷新 ordered/review。

遗留观察：

- 预算样本耗时 `65893ms`，中外合作排除样本耗时 `56213ms`。结果正确，但模型请求和外层等待仍有长尾，需要在后续整体回归中继续区分“工具执行耗时”和“消息结束/模型整合耗时”。
- 中外合作确认后的结果文案较长，包含方案概况和复审结果，后续可以做用户语言压缩，但不影响本轮执行正确性。

## 31. 候选不足/无 ready 预览不能被通用无预览兜底覆盖

2026-06-17 复跑 `dialog_regression_310_review_repair_cases.json` 时发现：

- `310-review-shortage-honesty` 用户问：`如果稳和保不够，能不能直接帮我补齐？候选不够也要直接说`。
- 工具链已经进入 `preview_fix_proposal` 或 `analyze_adjustment`，结构化结果里包含候选供给/blocked proposal 信息。
- 但最终回复被无卡确认保护改成了“这轮还没有生成可执行的调整内容，所以不会改动当前方案……”，没有回答稳/保、候选、不够、放宽这些关键点。

这类问题本质不是意图识别错误，而是安全兜底覆盖了已拿到的结构化事实。用户问的是“能不能补、候选不够要直说”，即使没有可直接执行的调整卡，也必须把工具已经给出的候选供给和不可处理原因说清楚。

本轮修复原则：

- 不按用户话术做字符串路由。
- 如果当前轮已有 `fix_proposal_preview`，但没有 ready proposal 或 pending card，不能退化成通用“没有生成可执行内容”。
- 用工具结果里的 `fix_proposals`、`candidate_supply`、`candidate_shortages` 生成用户可读说明：能不能直接处理、缺口在哪、需要怎么放宽。
- 仍然保持安全边界：没有 ready proposal 时不生成确认卡，不自动执行方案调整。

实现落点：

- 新增 `_build_fix_proposal_preview_fallback_lines()`，统一渲染 `fix_proposal_preview` 的 ready/blocked/候选不足说明。
- `_build_plan_timeout_fallback_reply()` 对 `result_kind=fix_proposal_preview` 且有 facts 的结果走结构化 fallback，而不是只输出 summary。
- `_non_actionable_plan_preview_boundary()` 在 `preview_fix_proposal/fix_proposal_preview` 场景下复用同一结构化 fallback。
- `_append_plan_preview_confirmation_boundary()` 在模型写出确认/执行话术但没有 pending card 时，把最新 `fix_proposal_preview` 也作为边界来源，避免落到 `_NO_EXECUTABLE_PLAN_PREVIEW_REPLY`。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "preserves_shortage_guidance_when_fix_preview_has_no_ready_card or shortage_boundary or review_result_fallback_groups_repair_options" -q
```

结果：`3 passed`。

关联保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "tuition_budget_after_wrong_intent_preview_and_review_result or recovers_region_intent_before_unbacked_plan_confirmation_guard" -q
```

结果：`2 passed`。

完整 review/repair 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_review_repair_after_shortage_fallback_fix.json
```

结果：

```text
9 steps / 9 successfulSteps / failedSteps=0
median=39472ms, p95=76938ms, max=76938ms
```

重点样本结果：

- `310-review-shortage-honesty` 不再返回通用“没有生成可执行调整内容”，已回答当前方案稳保数量、候选供给、为什么不能一键补齐、需要如何取舍或放宽。
- `310-review-major-group-inner-safety` 仍能生成 `adjust_major_group_inner_safety` 的 `pendingConfirmationCard`。
- `310-review-fix-unavailable-guidance` 仍输出不能直接处理原因和下一步调法，没有生成误导性的执行卡。
- `310-review-repair-after-manual-move-stale` 重新审查链路仍会刷新 review，并说明哪些可先看预览、哪些需要用户取舍。

遗留观察：

- 本组仍有明显模型/工具长尾：`max=76938ms`，慢点集中在审查解释和 full agent 多轮工具尝试。
- `310-review-shortage-honesty` 的 live 回复有一句语病：“当前还缺少足够条件处理绕过你的判断直接替换或。” 不影响机制正确性，但后续文案优化需要处理。
- 部分审查说明仍偏长，尤其用户只问边界时容易展开过多表格和解释；发布前如果时间允许，可以做一轮“审查回复压缩”优化。

## 32. active only_keep 待采纳不能被普通删除预览覆盖

2026-06-17 继续回归 `dialog_regression_310_production_abstracted_cases.json` 时发现一类高风险边界：

- `310-prod-only-keep-medical-not-engineering` / session `5902`。
- 首轮用户输入 `不考虑工科，只考虑医学类` 后，系统已经形成 `intent_change` 待采纳内容，`constraintIntentType=only_keep`，目标是“只保留专业门类：医学”。
- 次轮用户输入 `这个方案还是不行，只要医学`，模型可能重新展开成普通 `remove_units` 预览，把经济与贸易类、金融学类、外国语言文学类等作为负向删除范围。
- 这会把“只保留医学”的正向目标丢掉，变成“删除模型临时列出的非医学项”，风险很高。

本轮修复原则：

- 不按“只要医学/不考虑工科”等用户话术做关键词路由。
- active pending 的优先级高于同轮模型自由生成的普通 plan preview。
- 如果 active pending 是 `only_keep`，后续短文本重复或强化同一目标，应优先确认当前 pending；如果语义分类没有确认，也不能让纯负向普通删除预览覆盖这个 pending。
- 只有结构化 `only_keep_scope` 的 user-goal proposal，才允许替换或推进当前 only_keep 方向；普通 `remove_units` 不能承接这个语义。

实现落点：

- `plan_semantic_action_tool.py` 的 pending 语义分类补充约束：用户重复或强化同一 active pending 目标、且没有引入冲突范围时，分类为 `confirm_pending`；目标不同则返回 `none`，不直接拒绝。
- `service.py` 增加结构化保护：
  - `_pending_state_constraint_intent_type()` 读取 active pending 的约束类型。
  - `_plan_confirmation_candidate_payload()` / `_plan_candidate_intent_update()` / `_plan_candidate_structured_goal_type()` 提取候选方案预览的结构化来源。
  - `_merged_selected_intent_payload()` 汇总候选里携带的意向更新。
  - `_plain_plan_candidate_conflicts_with_active_only_keep_intent()` 判断普通方案候选是否会用纯负向范围覆盖 active only_keep pending。
- 被拦截时保留旧 active pending，回复当前待采纳内容和“如果这就是你想采用的方向，请先点‘采纳’”，不保存新的错误 pending。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "repeated_only_keep_pending_short_text_confirms_current_intent or active_only_keep_pending_blocks_plain_negative_remove_preview or user_goal_apply_rebuilds_after_intent_apply" -q
```

结果：`3 passed`。

邻近保护：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "only_keep or pending_intent_confirmation or user_goal_fix_proposal_confirm_rebuilds_after_intent_apply or active_only_keep_pending" -q
```

结果：`16 passed`。

完整约束场景 live 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_constraint_plan_action_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_constraint_after_only_keep_pending_guard.json
```

结果：

```text
9 steps / 9 successfulSteps / failedSteps=0
median=18619ms, max=23020ms
```

生产抽象场景 live 回归：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_production_abstracted_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_310_production_abstracted_after_only_keep_pending_guard.json
```

结果：

```text
22 steps / 22 successfulSteps / failedSteps=0
median=19707ms, p95=29667ms, max=35699ms
```

重点样本结果：

- `310-prod-only-keep-medical-not-engineering` 不再生成错误的普通删除预览，保留 only_keep 待采纳方向。
- live 第二轮仍可能重新生成“只保留专业：医学”的待采纳卡，而不是直接消费上一轮 active pending。当前机制已安全，不会误删；后续可继续调 pending 语义确认的稳定性。

遗留观察：

- `310-prod-negative-major-then-fill` 第二步“从候选中选择 7 所放入方案里，先补齐志愿数量”仍没有可执行预览。原因是当前 `add_units` 需要候选 ID 或明确结构化筛选范围；要支持“按当前候选池自动补齐数量”，需要单独定义 `fill_missing_count` / candidate selector 的产品边界、排序规则、预览和不可满足说明。
- 政策类问题 `高校专项招生的计划有吗`、`中国海洋大学第005组是不是高校专项` 仍出现 `2024年` 等过期年份口径，需要后续结合通用政策检索、院校招生简章检索和个人适配三类路径继续处理。
- 当前回归最大耗时约 `35.7s`，结果正确但仍需继续跟踪长尾。

## 33. 审查 0 风险不能暗示“不会滑档/结构安全”

2026-06-17 复跑 `dialog_regression_310_review_repair_cases.json` 时发现：

- `310-review-summary-user-friendly` 返回 `风险：0 项 —— 当前方案没有会导致滑档或明显不合理的地方，整体结构是安全的`。
- 这没有直接说“不会滑档”，但仍然把审查 0 风险说成录取安全承诺。
- 正确口径应是“当前审查暂未发现明确风险”，同时保留录取概率、排序、专业接受度和当年波动的不确定性。

本轮修复原则：

- 不改用户路由，不按用户问法做匹配。
- 延续第 28 节的审查安全边界，在最终回复层统一拦截审查/调整分析里的绝对化安全表述。
- `风险 0 项` 可以展示，但不能推导成“不会滑档”“没有导致滑档的地方”“整体结构安全”。

实现落点：

- 扩展 `_review_reply_overclaims_admission_safety()`：
  - 覆盖 `不会导致滑档`、`没有会导致滑档`。
  - 覆盖 `整体结构是安全`、`方案结构安全` 等隐性安全承诺。
  - 保留“不能保证不会滑档”这类正确边界，不误判。
- 触发后仍复用 `_build_plan_timeout_fallback_reply()` 的结构化审查事实回复。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "overclaims_admission_safety or zero_review_result" -q
```

结果：`3 passed`。

本轮 review/repair live 回归结果：

```text
9 steps / 9 successfulSteps / failedSteps=0
median=32856ms, p95=71865ms, max=71865ms
```

观察：

- 机制正确性通过，未发现审查修复确认卡、候选不足说明、重新审查刷新链路失败。
- 慢点集中在审查解释类问题，最大 `71865ms`。模型 agent run 内部约 `27s`，外层完整 websocket 响应约 `72s`，需要继续观察消息结束/前端等待链路。
- 部分标题仍偏硬，例如“处理兜底专业不足”，后续做统一文案压缩时再处理，不作为本轮安全阻断。

## 34. 无工具边界回复不能吞掉意向变化，审查后处理预览必须有明确问题目标

2026-06-17 继续 303 对话积累场景回归时发现两类收敛问题：

- 当前报考参考里已有 `偏好地域：上海、安徽、山东、江苏、江西`，用户输入 `不想去安徽`，模型可能没有调用 Intent 工具，而是直接回复“这轮还没有生成可执行的调整内容，所以不会改动当前方案”。这会让明确的地域意向变化被方案调整兜底吞掉。
- 用户输入 `把太贵的那几个先去掉看看` 时，full agent 可能只执行 `review_plan` 并返回审查摘要。用户这轮不是单纯问风险，而是希望继续处理高收费/预算压力问题，应从结构化 review issue / fix proposal 进入可确认预览。

本轮修复原则：

- 不新增用户话术关键词路由。
- 意向恢复仍由 `analyze_volunteer_intent_change` 负责实体抽取和结构化判定；service 只在“无工具 + 无卡片 + 模型给出无可执行调整边界”时触发一次结构化恢复，抽不到 `ready/items` 就不出卡。
- 审查后处理预览不靠回复文案承诺。只有语义分类器在当前 review/fix proposal 上下文中给出高置信 `preview_fix_proposal`，或给出 `review_plan/analyze_adjustment + 明确 targetIssueCodes` 时，才允许转入 `preview_fix_proposal`。
- 仅有 `targetStrategies` 不足以从“是否需要重新审查/当前审查是否过期”这类问题生成处理卡，避免把只读审查问题误升级成修复动作。
- 当 `review_check` / `preview_fix_proposal` 已经带着显式 `targetStrategies` 或 `targetIssueCodes`，但当前 `ready` proposal 为空或不匹配时，service 只保留这条结构化结果和 `target_match_empty`，不再回退到第一条无关 ready proposal，也不再额外问模型猜目标。

实现落点：

- `_recover_confirmable_intent_from_no_tool_turn()` 将 `_reply_looks_like_plan_action_recovery_boundary()` 纳入触发条件，但最终是否生成卡仍取决于 Intent 工具结构化 payload。
- `_maybe_recover_fix_preview_after_review()` 支持 `review_plan/analyze_adjustment` 的高置信目标恢复，但非 `preview_fix_proposal` 时必须带 `targetIssueCodes`，从而锚定到具体审查问题对象，例如 `high_tuition`。
- `_maybe_recover_unbacked_composite_goal_without_tools()` 在复合目标恢复失败时保留结构化 intent fallback，但只对无可执行边界回复触发。
- `_maybe_recover_atomic_preview_after_agent_interruption()` 处理完整 Agent 在首轮模型请求阶段挂起、还没有任何工具调用的情况。它只调用 `classify_plan_recovery_action` 做结构化动作恢复；高收费/中外合作/限报等审查问题必须输出 `reviewIssueCode`，再回到 `plan_next_action -> execute_plan_action` 生成执行层预览和 pending card。低置信、只读问题、普通意向变化或已有 active pending 时不触发，继续走原有安全兜底。

已验证单测：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "recovers_region_intent_from_no_executable_boundary_without_tools or recovers_explicit_high_fee_removal_after_review_to_fix_preview or recovers_region_intent_before_unbacked_plan_confirmation_guard or recovers_fix_preview_after_review_then_atomic_remove_error or falls_back_to_intent_card_when_only_keep_plan_proposal_blocked or recovers_toolless_exclude_goal_boundary_to_user_goal_proposal or recovers_toolless_only_keep_without_plan_to_intent_card or structured_exclude_goal_falls_back_to_user_goal_proposal or does_not_recover_fix_preview_for_stale_review_question" -q
```

结果：`9 passed`。

审查修复邻近回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "fix_preview or fix_proposal or review_repair" -q
```

结果：`34 passed`。

首轮模型中断恢复补充验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "interrupts_before_tools or interrupts_after_tool_preview or interrupted_readonly or returns_safe_fallback or high_tuition" -q
```

结果：`6 passed`。

邻近恢复/审查修复回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py \
  -k "fix_preview or fix_proposal or review_repair or high_tuition or interruption or interrupted or plan_action_recovery" -q
```

结果：`40 passed`。

后续回归重点：

- `不想去安徽` 一类地域/专业/院校意向变化，在模型未调用 Intent 工具时仍应出现待采纳卡。
- `把太贵的那几个先去掉看看` 一类明确处理高收费/中外合作的问题，应优先锚定 `high_tuition/cooperative_program` 等 review issue；如果 full agent 首轮模型挂起，也应尝试结构化恢复到对应原子预览；如果没有匹配 ready proposal，应说明需要取舍或放宽条件，不得生成无关倒挂/安全垫卡。
- 如果工具结果已经带着明确 target，但没有匹配到 ready proposal，也应直接说明“当前没有可直接执行的调整项”，不要为了凑一张卡而回退到别的 ready 项。
- 如果 full agent 只给出了 `review_plan` 的审查摘要，但用户语义明显是在继续处理高收费/中外合作等问题，后续恢复仍必须先把问题锚定到具体 review issue code，再进入 `preview_fix_proposal`。如果 issue code 抽不出来，就只保留审查摘要，不要勉强升格成修复卡。
- `我刚移动过，现在审查结果还准吗` 仍是重新审查/只读问题，不应因为存在 ready fix proposal 就生成处理卡。
