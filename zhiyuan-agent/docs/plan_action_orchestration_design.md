# Plan 动作编排与执行链设计

## 1. 目标

本设计文档聚焦 `gaotu-zy-agent-v3` 在 `Plan` 层如何从“零散 request_type + 直接执行”升级为“skill + 模型推理 + 受控 tool 执行”的统一动作编排链。

本设计只讨论 agent 侧的语义理解、动作规划、执行门禁、结果闭环，不改 backend 规则引擎本身。

目标有四个：

- 让用户对方案的直接干预统一走 `analyze -> preview -> apply -> review` 链路
- 让模型负责语义理解和步骤规划，而不是继续扩展硬编码分支
- 让 tool 只承担事实读取和状态执行，不再承担用户话术组织
- 让 Intent 写入后的偏好 / 要求稳定进入 Plan 分析、预览、执行和复审链

这里需要特别强调一条：

- `Intent` 不需要新增一层持久化事实结构，但 `Plan` 编排必须显式读取现有画像 / 状态，把它们作为标准决策输入

## 2. 现状问题

当前 `Plan` 链路已经有以下能力：

- 方案状态查询
- 候选查询
- 草稿 / 排序读取
- 方案审查
- 调整建议
- 修复建议预览
- 增删改重排类动作

但当前仍存在四类结构性问题：

### 2.1 入口语义仍偏平铺

历史 `planning_router_tool.handle_planning_request` 曾以 `request_type` 为中心扩展；3.1.0 已删除旧 router，当前主链统一收口到 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。

问题：

- 能覆盖高频场景，但不利于承接自然语言多样表达
- 一旦新增动作，容易继续堆 alias
- “分析 / 预览 / 执行 / 复审”四段责任没有显式建模

### 2.2 动作前的预览还不统一

当前部分动作已经有“未确认时先给预览”的能力，但仍有历史局部补丁迁移后的边界需要继续收口。

问题：

- 不是所有动作都共享同一套预览结构
- 模型无法稳定利用预览结果继续多轮推进
- 缺少统一的“动作计划”中间层

### 2.3 模型与 tool 的责任边界还不够清晰

当前主 Agent 已经是模型主导选 tool，但在 Plan 场景仍存在两种风险：

- 模型直接在多个底层 tool 之间漂移
- 编排层 / 执行层边界一旦混杂，容易让 tool 重新承担“理解用户想干什么”的职责

### 2.4 执行闭环不够显式

理想链路应该是：

1. 判断动作意图
2. 分析当前状态
3. 给出预览
4. 用户确认
5. 真正执行
6. 自动复审
7. 解释执行结果

当前链路虽然已经开始收口，但这七步还没有形成统一的技术模型。

### 2.5 Intent 仍然更像“外围状态”，不是 Plan 的显式决策输入

当前系统已经能把偏好 / 要求写入：

- `planningState.profileState.explicitProfile`
- `planningState.profileState.latentProfile.futureDevelopment`

但在技术模型上，`Intent` 仍然更像“Plan 结果格式化时顺便参考一下”的外围状态，而不是编排链的一等输入。

问题：

- 模型在计划动作时，不一定显式感知“当前用户画像 / 状态输入”
- preview 阶段不一定总能解释“这次改动与当前偏好 / 要求的关系”
- apply 阶段虽然能执行，但不一定总能说明“是在强化偏好还是触发冲突”
- review 阶段能看到风险，但不一定能稳定区分“结构风险”和“意向冲突”

## 3. 设计原则

### 3.1 skill 负责能力组织

Plan skill 负责告诉模型：

- 当前处于方案阶段
- 哪些问题先分析，哪些问题先补信息，哪些问题先预览
- 哪些动作必须确认
- 哪些动作执行后必须复审

skill 不直接执行，不直接操作状态。

### 3.2 模型负责语义理解与动作规划

模型负责：

- 判断当前请求是不是 Plan 问题
- 判断属于查询、局部修改、整体调整还是复审
- 决定当前应处于 `analyze / preview / apply / review` 哪一步
- 产出结构化动作计划

模型不直接决定调用哪个底层执行接口。

### 3.3 tool 只负责状态读取与执行

tool 分三类：

- Context input tool：读取 `Plan` 决策所需的现有状态输入
- Fact tool：读取状态、候选、草稿、排序、审查、建议
- Mutation tool：执行增删改、修复建议、重排、复审

tool 不应继续承担：

- 用户问法归类
- 最终回复拼装
- 执行策略自由推理

### 3.4 执行门禁必须硬规则化

以下规则不能交给模型主观决定：

- 是否缺少必要参数
- 是否必须先确认
- 是否允许整体重排
- 是否需要执行后自动复审
- 是否需要刷新工作台

这些规则必须放在受控执行层。

## 4. 总体架构

推荐架构如下：

1. `ChatAgent`
2. `Plan Skill`
3. `plan_context_tool`
4. `plan_orchestration_tool`
5. `plan_execution_tool`
6. 现有 `planning_workflow_tool / internal_client`

关系如下：

```text
用户自然语言
  -> ChatAgent
  -> Plan Skill
  -> plan_context_tool.collect_plan_context_inputs()
  -> plan_orchestration_tool.plan_next_action()
  -> 基于“用户目标 + 当前方案状态 + 当前画像 / 状态输入”输出结构化 PlanActionPlan
  -> 若 stage=analyze / preview：模型直接组织回复
  -> 若 stage=apply / review：plan_execution_tool.execute_plan_action()
  -> 受控调底层 workflow / internal_client
 -> 返回 PlanExecutionResult
  -> 模型组织最终回复
```

## 4.0 ChatAgent Tool Boundary

这里要明确一条工程边界：

- `ChatAgent` 对模型暴露的 `Plan` 入口，只保留：
  - `collect_plan_context_inputs`
  - `plan_next_action`
  - `execute_plan_action`
- 审查修复 proposal 的只读生成能力可以作为解释入口开放：
  - `generate_planning_fix_proposals`
  - 只用于读取 Java Server 已生成的 `FixProposal` 方向和边界，不落盘
- `apply_planning_fix_proposal` 不暴露给 `ChatAgent` 主工具列表。对话侧应用修复建议只走 `ChatService` 的 active `pendingConfirmation` 桥：`ready` proposal 生成确认卡，用户确认后由 service 内部调用 Java apply，并把 `RepairReport` 写回对话和工作台刷新事件。
- `planning_workflow_tool`、草稿/排序低层读写 tool、旧补齐素材/重排/审查等实现，不再作为模型直连入口注册到 `ChatAgent`

原因不是这些低层 tool 没有价值，而是它们的职责应当下沉为：

- `plan_context_tool` 的内部事实来源
- `plan_execution_tool` 的内部执行依赖
- 测试与兼容链路中的能力实现

不能继续让模型直接拿到这些低层 tool，原因有三点：

1. 模型容易绕过统一编排链，直接在低层 tool 之间漂移
2. 低层 tool 中仍有较多“已格式化文本摘要”，模型容易复述成系统播报式回复
3. 一旦同时暴露高层编排入口和低层执行入口，`Plan` 的 analyze / preview / apply / review 四段边界会再次被打散

因此当前推荐分层是：

- `ChatAgent`
  - 只感知 `Plan` 的三段式主入口
- `plan_context_tool`
  - 负责读取当前状态、画像、意向承接关系
- `plan_orchestration_tool`
  - 负责把用户目标规划成 `PlanActionPlan`
- `plan_execution_tool`
  - 负责受控执行，并内部复用 `planning_workflow_tool / internal_client`
- `planning_workflow_tool`
  - 作为内部能力库保留，不再作为模型主入口

这条边界的直接目标是：

- 收敛模型的可选动作空间
- 避免旧工具文本模板继续污染最终回复风格
- 保证 `Plan` 场景统一走“先读状态，再规划动作，再执行”的主链

## 4.1 `Intent` 作为 `Plan` 决策输入的定位

在这条新链路里，`Intent` 不再只是“之前写过的状态”，而是 `Plan` 编排默认要读取的一部分输入。

这层输入主要回答：

- 当前用户已经明确表达了哪些长期偏好
- 当前用户已经明确排除了哪些方向
- 当前用户有哪些发展导向
- 当前方案与这些输入是贴近、冲突还是未承接

换句话说：

- `Intent` 仍存于现有状态
- `Plan` 在分析 / 预览 / 执行 / 复审时必须消费这些现有状态输入

而不是：

- `Intent` 写完状态就结束
- `Plan` 继续独立运行

## 4.2 `Plan Context Inputs` 的来源

`Plan` 侧默认要读取以下现有状态输入：

### A. 显式画像事实

来自：

- `planningState.profileState.explicitProfile`

包括：

- `positiveMajors`
- `negativeMajors`
- `positiveSchools`
- `negativeSchools`
- `positiveRegions`
- `negativeRegions`
- `strengthSubjects`

### B. 潜在画像事实

来自：

- `planningState.profileState.latentProfile.futureDevelopment`

包括：

- `careerTypes`
- `industryPreferences`
- `workStylePreferences`
- `organizationPreferences`
- `lifeStylePreferences`
- `stabilityVsIncome`

第一阶段优先消费：

- `careerTypes`

### C. 当前方案承接状态

来自：

- `orderedPlanState.items`
- `draftPlanState.items`
- `reviewState`

这层不是新增状态，而是系统根据当前方案推出来的“承接情况判断”。

包括：

- 当前命中偏好的条目
- 当前命中要求冲突的条目
- 当前尚未承接的偏好方向
- 当前因要求导致的结构风险

## 5. Plan 层四段能力模型

统一把 `Plan` 动作分成四段。

### 5.1 Analyze

作用：

- 判断当前问题是什么
- 判断是否已有足够信息
- 判断用户是不是在真的要改方案
- 给出当前状态和风险摘要
- 显式带出与当前画像 / 状态输入的关系

典型问法：

- 现在方案怎么样
- 这份方案稳不稳
- 这几个位置合不合理
- 如果加北京的会怎么样

输出特点：

- 不改状态
- 不刷新工作台
- 可以给下一步建议
- 必须能回答“当前方案与用户当前偏好 / 要求 / 发展倾向的关系”

### 5.2 Preview

作用：

- 在不执行的前提下说明动作影响
- 明确缺少哪些参数
- 明确是否必须确认
- 明确这次改动是“更贴近当前状态输入”，还是“可能与当前状态输入冲突”

典型问法：

- 把这两个北京的放进去
- 删掉这个学校
- 换成更稳一点的
- 重新排一下

输出特点：

- 不改状态
- 重点说明动作影响
- 明确“确认后执行”
- 必须显式消费当前画像 / 状态输入

### 5.3 Apply

作用：

- 真正执行增删改动作
- 输出执行事实
- 决定是否复审 / 刷新工作台
- 记录这次执行是强化、削弱还是冲突于当前偏好 / 要求 / 发展倾向

输出特点：

- 只返回结构化执行结果
- 不自己组织最终面向用户的话术

### 5.4 Review

作用：

- 对执行后的方案做自动复审
- 返回新风险、已消除风险、剩余建议
- 返回“结构风险”与“意向冲突风险”的组合结果

输出特点：

- 是 Apply 的默认后置步骤
- 也可单独作为显式动作调用

## 6. 原子动作模型

Plan 层最终执行的不是“自然语言动作”，而是受控原子动作。

当前主链路支持以下动作：

- `add_units`
- `remove_units`
- `move_unit`
- `move_ordered_unit`
- `remove_ordered_unit`
- `replace_units`
- `sort_ordered_plan`
- `regenerate_order`
- `preview_fix_proposal`
- `review_plan`

`pin_unit` / `unpin_unit` 已从用户可触发能力中退场；历史 `pinned` 字段只作为旧数据兼容，不参与当前移动、排序、修复或对话动作编排。

### 6.1 add_units

含义：

- 把一批候选加入当前草稿 / 方案

必需参数：

- `volunteer_ids`，或可解析为明确筛选条件

### 6.2 remove_units

含义：

- 从当前方案中删除一批志愿

必需参数：

- `volunteer_ids`

### 6.3 move_unit

含义：

- 调整单条志愿顺序

必需参数：

- `volunteer_id`
- `target_position`

### 6.4 replace_units

含义：

- 删除一批旧志愿，再加入一批新志愿

说明：

- 当前第一阶段不依赖 backend 原生 replace
- 执行层用 `remove_units + add_units by filters + regenerate + review` 组合实现
- 必须同时具备要替换掉的 `volunteer_ids` 与补入筛选范围；只有 `limit` 不算有效筛选范围
- 未确认时只能给预览，确认后才能实际执行

### 6.5 regenerate_order

含义：

- 整体重排当前方案

说明：

- 高风险动作
- 必须明确确认

### 6.6 preview_fix_proposal

含义：

- 读取后端统一修复建议，生成当前方案的只读调整预览

说明：

- 不直接改动方案
- 只消费 Java `FixProposal` facts
- 只有 `status=ready` 且带有 `proposalId/sourceVersionGuard` 的后端 proposal 才能被 `ChatService` 转成 `pendingConfirmationCard`
- 如果语义路由已经带出 `targetStrategies/targetIssueCodes`，候选 proposal 必须匹配该目标；目标没有 matching ready proposal 时只能说明该目标当前不能直接处理以及需要放宽/取舍的原因，不能退到其他 ready proposal 生成无关确认卡
- `blocked` 和 `preview_only` 只作为只读说明，不生成执行卡，也不能被 Agent 翻译成普通增删替换绕过后端 apply policy
- 正式应用 proposal 必须经过 active pending 确认；模型本身不能调用 apply
- 同轮若同时出现意向预览和方案预览，方案预览恢复成功后以方案 pending 为准；旧 Agent 观测里的 `latestIntentPreviewPayload` 不得在后处理阶段再生成独立意向卡。只有方案卡自身显式携带 `intent_update` 时，意向变化才作为同一张方案调整卡的一部分生效。

## 7. 中间结构设计

### 7.1 `PlanAtomicAction`

```python
class PlanAtomicAction(BaseModel):
    action_type: str
    volunteer_ids: list[str] = []
    target_position: int | None = None
    filters: dict[str, Any] = {}
    reason: str = ""
```

### 7.2 `PlanActionPlan`

```python
class PlanActionPlan(BaseModel):
    stage: Literal["analyze", "preview", "apply", "review"]
    action_family: Literal[
        "query_state",
        "query_ordered",
        "query_candidates",
        "generate_plan",
        "analyze_adjustment",
        "preview_fix_proposal",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "remove_ordered_unit",
        "replace_units",
        "sort_ordered_plan",
        "regenerate_order",
        "review_plan",
    ]
    user_goal: str = ""
    requires_confirmation: bool = True
    should_rerun_review: bool = False
    should_refresh_workspace: bool = False
    context_summary: str = ""
    intent_relation: Literal["support", "conflict", "mixed", "unknown"] = "unknown"
    missing_inputs: list[str] = []
    rationale: list[str] = []
    atomic_actions: list[PlanAtomicAction] = []
    preview_summary: str = ""
```

作用：

- 作为模型与执行层之间的中间协议
- 将自然语言动作收敛为结构化计划

### 7.2.1 `PlanGoal` 与复合动作计划

`PlanActionPlan` 不应只表达单个 action。用户经常用一句话同时表达多个目标，例如：

- 只保留临床医学，其他专业先不要。
- 方案里必须有临床医学，但别把稳的都删掉。
- 不要中外合作，省内优先，保底多一点。
- 我不想学工商管理，金融可以保留，学校层次别降太多。

这类场景需要先形成 `PlanGoal`，再拆成一个或多个 `PlanAtomicAction`。模型负责理解目标和拆解计划，执行层负责校验、预览和门禁。

建议中间结构：

```python
class PlanEntityResolution(BaseModel):
    raw_text: str
    entity_type: Literal["major", "school", "region", "career", "tag", "risk"]
    canonical_name: str = ""
    canonical_level: str = ""
    matched_plan_items: list[dict[str, Any]] = []
    matched_candidate_items: list[dict[str, Any]] = []
    ambiguity: Literal["none", "specific_vs_category", "catalog_vs_admission_plan", "multiple_match", "unknown"] = "none"
    user_visible_note: str = ""


class PlanDecisionReference(BaseModel):
    source: Literal[
        "explicit_user_goal",
        "confirmed_intent",
        "system_recommendation",
        "current_plan",
        "candidate_pool",
        "review_rule",
        "dry_run",
    ]
    dimension: str
    label: str = ""
    value: Any = None
    weight_hint: Literal["hard", "high", "medium", "low", "context"] = "context"
    applies_to: list[str] = []
    evidence: dict[str, Any] = {}


class PlanGoal(BaseModel):
    goal_type: Literal[
        "query_state",
        "only_keep_scope",
        "must_include_scope",
        "exclude_scope",
        "prefer_scope",
        "rebalance_structure",
        "reduce_risk",
        "mixed_adjustment",
        "clarify",
    ]
    user_original_text: str = ""
    target_scopes: list[dict[str, Any]] = []
    negative_scopes: list[dict[str, Any]] = []
    structure_targets: list[dict[str, Any]] = []
    quality_guards: list[dict[str, Any]] = []
    entity_resolutions: list[PlanEntityResolution] = []
    confidence: Literal["high", "medium", "low"] = "medium"
    needs_clarification: bool = False
    clarification_questions: list[str] = []
```

`PlanActionPlan` 顶层只表达当前工具链要预览或执行的动作：

```python
    stage: Literal["analyze", "preview", "apply", "review"]
    action_family: str
    atomic_actions: list[PlanAtomicAction] = []
    missing_inputs: list[str] = []
    requires_confirmation: bool = True
    composite_proposal: CompositePlanProposal | None = None
```

字段职责：

- `PlanActionPlan.stage/action_family/atomic_actions`：动作 envelope，承接现有执行、pending、版本保护、刷新和 handler 分发。
- `PlanActionPlan.composite_proposal`：复合目标的唯一结构化容器。`goal`、`intent_updates`、`plan_actions`、`decision_references`、`feasibility`、`entity_resolutions`、`impact_summary` 和 `tradeoffs` 都放在这里。
- `CompositePlanProposal.goal`：表达用户目标，不直接等于底层执行动作。
- `CompositePlanProposal.intent_updates`：用户确认后要写入的偏好或要求，例如“只保留临床医学”。
- `CompositePlanProposal.plan_actions`：复合目标下当前方案要怎么动，例如移出命中排除范围、补入必须保留方向。
- `CompositePlanProposal.decision_references`：本次比较和取舍的参考点，包含用户显式意图、已确认偏好/要求、系统推荐指标、当前方案承接、候选容量和审查风险。
- `CompositePlanProposal.entity_resolutions/impact_summary`：把专业、院校、地域的实体理解和歧义给到用户，不能藏在日志里。
- `CompositePlanProposal.feasibility`：决定是否能进入确认卡片、只读预览、阻断或澄清。

边界：

- `only_keep_scope` 和 `must_include_scope` 只是 `PlanGoal.goal_type` 的两个值，不再作为独立特殊链路扩展。
- 不能用固定关键词直接决定 goal type；模型根据上下文输出结构，系统只校验结果是否可执行。
- 执行层不能因为 `goal_type=only_keep_scope` 自动生成所有“其他专业门类”的负向 intent；只处理用户明确实体和当前方案/候选事实。
- 有歧义时不能直接执行，应进入 `needs_clarification` 或在预览中显式披露用户确认的理解。

当前落地状态：

- `PlanGoal` / `PlanEntityResolution` / `CompositePlanProposal` 已在模型层落地；`PlanActionPlan` 顶层保持动作 envelope，不再保留 `goal` / `intent_updates` / `plan_actions` / `feasibility` 这类复合字段镜像。
- `IntentFrame` 已增加 `plan_goal_type`、`constraint_intent_type`、`plan_goal_confidence`，用于承载上游模型输出的复合目标类型；`raw_utterance` 不参与 goal type 推断。
- `ActionResolver` 只把结构化 `IntentFrame + PlanContextInputs` 转成动作族、阶段、缺参、确认门禁和类型化原子 action；它不接收 `ConversationPhase`，也不输出 `plan_goal` / `intent_updates` 镜像。pending/phase 状态只在 service、`ConversationPhase` 和 `pendingConfirmation` 链路处理，复合目标统一由 `plan_next_action.composite_proposal` 承载。
- `plan_next_action` 已支持显式传入 `plan_goal_type`、`constraint_intent_type`、`goal_target_scopes`、`goal_negative_scopes`，并在 `PlanActionPlan.composite_proposal` 中输出 `goal`、`intent_updates`、`plan_actions`、`decision_references`、`feasibility`、`impact_summary` 和 `tradeoffs`。未传这些结构化字段时，不会仅凭 `user_goal` 文本生成 `only_keep_scope` / `must_include_scope`。
- `plan_next_action` 已对结构化 scope 接入实体消歧：专业走 `major_entity_resolver`，地域走 `region_entity_resolver`，院校走 `school_entity_resolver`。结果写入 `CompositePlanProposal.goal.entity_resolutions`、`CompositePlanProposal.entity_resolutions` 和 `impact_summary`；无歧义时，`goal.target_scopes/negative_scopes` 与待确认的 `intent_updates` 会使用标准名，用户原话保留在解析证据里；多解或未知实体会进入 `needs_clarification`，不会生成可采纳的 `intent_updates`。
- `plan_next_action` 已开始输出保守的复合 `plan_actions` 拆解：`exclude_scope` 生成结构化 `remove_units` 计划，`must_include_scope` 生成结构化 `add_units` 计划。`only_keep_scope` 在 `plan_next_action` 本身不直接生成“删除所有非目标范围”的反向动作，必须先拿当前方案事实做反向范围校验。
- 服务层已经把 `only_keep / must_have / exclude` 方案联动收口到 Java `user_goal` proposal/apply 主链路：先基于待确认意向生成 `UserGoalFixProposalReq`，调用 Java 生成 ready proposal，再保存 `pendingConfirmation(kind=plan_mutation, actionFamily=apply_fix_proposal)`。用户确认时先写入偏好/要求，再按最新 planning version 重建 proposal 并 apply。Python 不再生成旧 `remove_units/add_units` 本地预览，也不再在 `CompositePlanProposal` 里挂接后端 proposal 镜像。
- `plan_next_action` 已开始在 `CompositePlanProposal.decision_references` 中输出比较依据，用于把用户显式目标和系统隐式优先级参考放在同一个预览证据里。当前第一阶段覆盖：目标/排除范围、待写入意向、当前方案承接关系、审查提醒摘要，以及推荐系数、录取率、冲稳保、院校层次、专业热度、意向匹配等通用系统参考。
- `CompositePlanProposal` 已落地为模型/工具输出，用于把 `goal`、意向更新、方案动作、可行性、影响说明和执行后验证计划聚合成一个预览单元；它不是 apply 接口，不绕过 `PlanActionPlan.stage`、缺参检查和确认门禁。
- 尚未完成：模型侧稳定产出 `PlanGoal`、把招生计划展示名与标准专业目录的歧义接入当前方案/候选证据、支持更高层和多目标的 `Scenario -> PlanGoal -> 多 proposal` 编排、补齐 only_keep 的复杂候选补足解释、前端复合预览卡片与确认后报告质量。这些仍需在后续实现阶段接入，但 `only_keep / must_have / exclude` 的方案联动已经统一进入 Java `user_goal` proposal/apply 主链路。

对比和取舍原则：

- 用户显式目标和已确认硬性报考条件优先于推荐系数；软偏好只影响排序和推荐系数，不直接缩小基础候选池。
- 系统推荐指标用于比较不同志愿的相对优先级，包括推荐系数、录取率、冲稳保层级、院校层次、专业热度、意向匹配和风险标签。
- 复合计划不能只按用户一句话机械删除，也不能只按系统推荐系数保留。预览必须说明两类依据如何共同影响保留、移出、补入或替换。
- 如果为了满足 only_keep、exclude、结构修复或风险处理而牺牲高推荐项、强意向项、院校层次或安全性，必须进入 `tradeoffs` 或 dry-run 说明。

与 Repair 链路的统一关系：

- Repair 是审查问题触发的复合计划实践，不是 Plan 之外的旁路。
- `ReviewCheck` 对应系统侧发现的目标来源，`FixProposal.strategy` 对应策略层，`FixProposal.actions` 对应动作计划层，`RepairDryRunSimulator` 对应预执行验证，`RepairProposalApplyPolicy` 对应执行门禁，`RepairReport` 对应执行闭环。
- Java Server 是上述 repair proposal 和原子动作语义的权威来源。Python Agent 只负责把用户自然语言整理成 `Scenario / PlanGoal / targetScopes / tradeoffGuards / sourceReviewIssue`，或通过 service pending 桥请求 Java proposal；不能在 Python 里自行生成最终 `replacementPairs`、可应用状态、dry-run 结论或真实 mutation 方案。
- Web 和 Agent 使用同一套 Java `FixProposal` 协议。当前 `FixProposal` 同时支持 `source=review_check` 和第一阶段 `source=user_goal`：审查问题由 review check 触发，用户复合目标由 `UserGoalFixProposalReq` 触发；两者都复用 Java proposal engine，而不是在 Agent 侧新建并行 repair 执行框架。
- 用户自然语言首先触发的是更上层的 `Scenario`，不是直接触发 repair strategy；`Scenario` 应先拆成一个或多个 `PlanGoal`，再复用这些已经落地的底层策略和 proposal。例如“整体更偏体制内”应先拆成发展导向、院校层次、专业方向、地域稳定性和风险边界，再决定是否链接只读分析、候选承接、风险替换或结构调稳预览。
- 用户表达的粒度不可控，系统内部才需要分层。用户可能宽泛地说“让方案整体更偏体制内”，也可能具体到“把第 8 个志愿移到第 12 位”；前者进入 `Scenario -> PlanGoal -> Strategy`，后者可以直接靠近 `PlanAtomicAction`，但两者都不能绕过预览、确认、版本检查、dry-run 和 apply policy。
- `reduce_risk` 可链接 `replace_risk_items/remove_risk_items`，`rebalance_structure` 可链接 `rebalance_tier_ratio/fill_probability_gap/add_safety_items/fill_missing_count`，但这些是底层子策略，不是高层情景分类。
- repair 里当前只允许预览、不允许落盘的策略，在复合计划里也不能绕过 apply policy。

统一 taxonomy：

- `RepairStrategy` 表示修复策略：`fill_missing_count`、`add_safety_items`、`rebalance_tier_ratio`、`fill_probability_gap`、`sort_by_probability`、`remove_risk_items`、`replace_risk_items`、`adjust_major_group_inner_safety`、`no_op`、`cannot_satisfy`。
- `RepairActionType` 表示 proposal 里的具体动作：`fill_total_count`、`add_volunteers`、`remove_volunteers`、`replace_volunteers`、`reorder_volunteers`、`adjust_major_group_inner_safety`、`no_op`。
- `PlanActionPlan.action_family` 仍只表示 Agent 当前工具动作 envelope，例如 `review_plan`、`preview_fix_proposal`、`replace_units`、`sort_ordered_plan`。它不能替代 Repair strategy。
- 当前可自动 apply 的 repair strategy 由 Java `RepairProposalTaxonomy` 和 `RepairProposalApplyPolicy` 判定。`add_safety_items`、`rebalance_tier_ratio`、`fill_probability_gap` 默认保持 preview only；`source=user_goal` 的 `only_keep_scope/must_include_scope/exclude_scope` 只能通过 service pending 桥受控 apply。
- 后端运行期对应统一定义为 `RepairProposalTaxonomy`，覆盖 `Strategy`、`ActionType`、`CompensationActionType`、apply 白名单、preview-only 策略和旧补偿别名映射。Agent 不能重新发明 strategy/action，也不能把 preview-only repair 翻译成普通 `replace_units` 去绕过后端 apply policy。
- 审查修复的语义目标按“用户希望系统做什么”确定，而不是只按用户提到的风险词确定。例如用户说“专业组里录取率太悬，补一个安全一点的专业”，`录取率太悬` 是风险依据，真正目标是补组内安全垫，应进入 `adjust_major_group_inner_safety`；只有用户明确要求按录取率重排、修正前后顺序或处理倒挂时，才进入 `sort_by_probability`。

验证场景应覆盖高层情景，而不只覆盖底层 action：

| Scenario | Goal 拆解 | 底层能力复用 | 本期边界 |
| --- | --- | --- | --- |
| 整体更偏体制内/考公考编 | 发展导向、院校层次、专业公共属性、地域稳定性、风险控制 | career 分析、方案承接分析、候选机会、必要时风险替换或结构调稳预览 | 不动态改 rank 权重；不直接删除非体制方向 |
| 更稳一点/保底多一点 | `rebalance_structure`、安全垫、数量缺口 | `add_safety_items`、`fill_missing_count`、`rebalance_tier_ratio`、dry-run | 结构 replacement 当前只预览 |
| 只保留某方向 | `only_keep_scope` | 目标/非目标识别、候选补位、替换/移出 proposal、service pending apply | 已迁入 Java `user_goal` proposal/apply 主链路 |
| 至少保留某方向 | `must_include_scope` | 当前命中检查、候选补入、满方案 replacement planner、service pending apply | 已迁入 Java `user_goal` proposal/apply 主链路 |
| 避开某方向 | `exclude_scope` | 当前方案命中项识别、移出/替换 proposal、service pending apply | 已迁入 Java `user_goal` proposal/apply 主链路 |

2026-06-12 focused live 结论：

- “让方案整体更偏体制内/考公考编”已经按高层发展导向情景验证，不再先走普通 `review_plan`。当前链路先调用 `analyze_current_career_direction`，必要时再读取方案状态；最终回复需要回答承接、短板、取舍和下一步预览，而不是复述审查风险清单。
- 方向承接数量仅表示宽口径粗筛线索，来源是院校性质、专业名称和标签等可解释证据。它不能替代专业适配、风险审查或用户接受度判断，也不能和风险/冲突项做互斥统计。
- 同一会话后续具体动作“第 8 个移到第 12 位”仍进入 `PlanAtomicAction -> move_ordered_unit preview -> PendingConfirmation`，说明高层情景路由没有破坏原子动作预览链路。
- 复杂兴趣画像类问题新增只读入口 `analyze_current_interest_profile`：当用户一次性描述多个兴趣、排斥方向、薪资/稳定/沟通强度等期待时，优先用它生成综合方向分析，不再把同一句话拆成多次 career/major Explore 试探。它不写入偏好，不生成 pending，也不修改方案。
- 服务层的少量文本标记只用于最终回复协议保护：当模型在没有真实 pending/card 的情况下写出“待采纳内容”“点击采纳”“确认后调整”等承诺时，只清理这类无依据确认话术，或回退到只读工具已返回的分析正文。该机制不参与用户意图识别，不替代结构化实体解析、`PlanGoal` 或 `ActionResolver`。

`constraint_intent_type` 与 `PlanGoal` 的兼容关系：

| constraint_intent_type | PlanGoal.goal_type | 含义 |
| --- | --- | --- |
| `only_keep` | `only_keep_scope` | 只保留这个范围，其他方向不作为当前方案目标 |
| `must_have` | `must_include_scope` | 至少保留这个方向，其他方向仍可保留 |
| `default` | 不自动生成 PlanGoal | 普通偏好/要求仍按显式 `plan_goal_type` 或 Intent 工具处理 |

### 7.3 `PlanExecutionResult`

```python
class PlanExecutionResult(BaseModel):
    applied: bool
    action_family: str
    stage: str
    executed_actions: list[dict[str, Any]] = []
    affected_volunteer_ids: list[str] = []
    workspace_refresh_targets: list[str] = []
    review_rerun: bool = False
    intent_effect: Literal["strengthened", "weakened", "conflicted", "unchanged"] = "unchanged"
    context_summary: str = ""
    review_summary: str = ""
    state_summary: str = ""
    summary: str = ""
```

作用：

- 承接执行事实
- 为后续模型生成最终回复提供结构化输入

## 8. 新工具设计

### 8.0 `plan_context_tool.collect_plan_context_inputs`

职责：

- 从现有 `planningState / profileState / ordered/draft/review` 读取 `Plan` 编排所需输入
- 给 `Plan` 编排层提供统一的决策上下文

建议签名：

```python
async def collect_plan_context_inputs(
    ctx: RunContext[RequestContext],
) -> str:
    ...
```

返回：

```python
class PlanContextInputs(BaseModel):
    positive_majors: list[str] = []
    negative_majors: list[str] = []
    positive_schools: list[str] = []
    negative_schools: list[str] = []
    positive_regions: list[str] = []
    negative_regions: list[str] = []
    career_types: list[str] = []
    support_examples: list[str] = []
    conflict_examples: list[str] = []
    unresolved_preferences: list[str] = []
    summary: str = ""
```
```

这层的定位不是新增一套持久化事实结构，而是把现有状态读取成 `Plan` 可直接消费的输入摘要。

### 8.1 `plan_orchestration_tool.plan_next_action`

职责：

- 把当前用户话术转成 `PlanActionPlan`

建议签名：

```python
async def plan_next_action(
    ctx: RunContext[RequestContext],
    user_goal: str,
    current_stage: str | None = None,
    volunteer_ids: list[str] | None = None,
    target_position: int | None = None,
    province_keyword: str | None = None,
    school_keyword: str | None = None,
    major_keyword: str | None = None,
    limit: int = 5,
    user_confirmed: bool = False,
) -> str:
    ...
```

该工具要做的事：

1. 判断用户当前是在查状态还是改方案
2. 判断当前应落在哪个 stage
3. 判断信息是否齐全
4. 将当前画像 / 状态输入嵌入到动作计划里
5. 产出原子动作计划
6. 决定是否要确认、是否要执行后复审

该工具不直接执行动作。

### 8.2 `plan_execution_tool.execute_plan_action`

职责：

- 吃掉 `PlanActionPlan`
- 执行受控映射
- 返回 `PlanExecutionResult`

建议签名：

```python
async def execute_plan_action(
    ctx: RunContext[RequestContext],
    plan_payload: str,
) -> str:
    ...
```

该工具要做的事：

1. 校验计划是否合法
2. 检查门禁条件
3. 在执行前后读取当前画像 / 状态输入
4. 调用底层 workflow / action tools
5. 必要时自动复审
6. 返回统一执行结果

## 9. 受控执行映射

执行层不让模型自由决定底层 tool，而采用硬映射。

- `query_state`
  - `query_planning_plan_overview`
- `query_candidates`
  - `query_planning_candidate_pool`
- `add_units`
  - `select_planning_ordered_items`
  - 或执行层内部的候选筛选 + `select_working_plan_items` + 生成排序
- `remove_units`
  - `remove_planning_ordered_items`
- `move_unit`
  - `move_planning_ordered_item`
- `move_ordered_unit`
  - `move_planning_ordered_item`
- `remove_ordered_unit`
  - `remove_planning_ordered_items`
- `sort_ordered_plan`
  - 执行层内部按录取率 / 专业组顺序规则重排
- `regenerate_order`
  - 执行层内部直接调用 `generate_planning_ordered_plan` 并自动复审
- `preview_fix_proposal`
  - 读取后端 `fix-proposals/generate`，返回只读修复建议事实
- `review_plan`
  - `run_planning_review`

说明：

不论映射到哪个底层动作，执行层都应同时拿到：

- 当前画像 / 状态输入摘要
- 执行后的最新方案状态

这样最终结果才能稳定解释：

- 当前动作是否贴近已有 Intent
- 当前动作是否引入新的 Intent 冲突

## 10. 硬门禁规则

以下规则必须放在 `plan_execution_tool` 中。

### 10.1 缺参阻断

- `move_unit` 缺 `volunteer_id / target_position` 时禁止执行
- `remove_units` 缺 `volunteer_ids` 时禁止执行
- `move_ordered_unit` 缺 `volunteer_id / target_position` 时禁止执行
- `remove_ordered_unit` 缺 `volunteer_ids` 时禁止执行
- `replace_units` 缺 `volunteer_ids` 或补入筛选范围时禁止执行
- `add_units / replace_units` 的补入筛选范围不能只靠 `limit` 判断，必须至少包含地域、院校、专业、标签或明确 volunteerIds

### 10.2 确认阻断

以下动作默认必须确认：

- `regenerate_order`
- `replace_units`
- 大批量 `add_units`
- 大批量 `remove_units`

### 10.3 执行后自动复审

以下动作默认执行后自动进入 `review`：

- `add_units`
- `remove_units`
- `move_unit`
- `move_ordered_unit`
- `remove_ordered_unit`
- `sort_ordered_plan`
- `replace_units`
- `regenerate_order`

### 10.4 工作台刷新规则

执行结果里显式返回需要刷新的目标：

- `candidate`
- `draft`
- `ordered`
- `review`

而不是再让 service 层通过中文文案猜。

### 10.5 Intent 冲突保护

执行层应增加一类专门门禁：

- 如果动作会明显命中当前要求冲突，不应直接静默执行
- 即使用户给了模糊确认，也应在 preview 中显式提示

例如：

- 用户已有“排除上海”
- 当前又要求“把上海的两个放进去”

这类情况不应被当作普通 add，而应标记为：

- `intent_relation=conflict`
- preview 阶段显式展示冲突

## 11. Plan Skill 与 Intent 的关系

Plan skill 不应把 Intent 当作“已经写完的历史状态”，而应把它视为本轮动作规划必须消费的现有输入。

也就是说，Plan skill 的输入不只是：

- 当前用户话术
- 当前方案状态

还必须包括：

- 当前画像 / 状态输入

## 11. Skill 层设计

Plan skill 需要明确给模型以下约束：

### 11.1 先判断任务层

- `Explore`：只分析，不改方案
- `Intent`：只确认偏好 / 要求，不直接改方案
- `Plan`：承接当前方案的查询、分析、预览、执行、复审

### 11.2 Plan 内部优先顺序

- 用户只是问“现在方案怎么样” -> `analyze`
- 用户说“把这个加进去” -> 优先 `preview`
- 用户已明确确认 -> `apply`
- `apply` 后必须 `review`
- 在每一步都显式消费当前画像 / 状态输入

### 11.3 不允许的行为

- 不允许模型直接跳过预览去改高风险动作
- 不允许模型直接自由组合底层 mutation tools
- 不允许 tool 输出直接充当最终用户回复
- 不允许模型忽略已有 Intent 事实，把 Plan 当作“与用户态无关的纯排序问题”

## 12. 典型场景链路

### 12.1 加指定志愿

用户：

- 把北京的两个放进去

链路：

1. `plan_next_action`
   - `action_family=add_units`
   - `stage=preview`
   - 同时判断与当前偏好 / 要求 / 发展倾向的关系是 `support / conflict / mixed`
2. 模型给出预览
3. 用户确认
4. `plan_next_action`
   - `stage=apply`
5. `execute_plan_action`
6. 自动 `review`
7. 模型解释结果

### 12.2 删除指定志愿

用户：

- 删掉这个学校

链路：

1. 如果缺 `volunteer_id`
   - `stage=analyze`
   - 提示先明确是哪一条
2. 信息齐全后
   - `stage=preview`
3. 用户确认后
   - `stage=apply`
4. 自动 `review`

并且 review 要能说明：

- 这次删除是否减少了与当前要求的冲突
- 是否削弱了已有偏好承接

### 12.3 移动位置

用户：

- 把这个往前提

链路：

1. 若缺目标位置
   - `stage=analyze`
2. 位置明确但未确认
   - `stage=preview`
3. 确认后
   - `stage=apply`
4. 自动 `review`

### 12.4 整体重排

用户：

- 重新排一下

链路：

1. `stage=preview`
2. 用户确认
3. `stage=apply`
4. 自动 `review`

### 12.5 复合方案调整

用户：

- 只保留临床医学，其他专业先不要。
- 不要中外合作，省内优先，保底多一点。

链路：

1. `collect_plan_context_inputs`
   - 读取当前方案、候选池、已确认偏好/要求、审查结果。
2. `plan_next_action`
   - 输出 `PlanGoal`，例如 `goal_type=only_keep_scope` 或 `goal_type=mixed_adjustment`。
   - 输出 `entity_resolutions`，说明临床医学是具体专业、医学是门类、中外合作是风险标签，是否存在招生计划展示歧义。
   - 拆解 `intent_updates` 和 `plan_actions`：
     - `only_keep_scope`：写入“只保留该范围”的报考要求；当前方案中移出范围外项；候选里有目标范围时尝试补入；候选不足则说明边界。
     - `must_include_scope`：写入“至少要有该范围”的报考要求；当前已有命中则不改方案；没有则补入或替换，不删除其他方向。
     - `mixed_adjustment`：把风险移除/替换、地域偏好、保底增强分别拆成可验证动作。
3. `execute_plan_action(stage=preview)`
   - 只做 dry run 和复合预览，不落盘。
   - 返回将移出、补入、替换、重排的对象，披露无法完成的部分和取舍。
4. 创建 `PendingConfirmation`
   - 作为一个复合确认单元，不拆成多张彼此独立的卡片。
5. 用户确认后进入 `apply`
   - 执行可应用动作。
   - 写入 intent 更新。
   - 刷新工作台，执行复审。

关键要求：

- 如果 “只保留 X” 中 X 当前方案里没有、候选里也没有，不能删除全部方案后告诉用户已完成；应返回 `blocked/cannot_satisfy` 或只读预览。
- 如果一部分可以处理、一部分不能处理，回复必须说清楚“能处理什么、不能处理什么、为什么”。
- 如果实体有歧义，预览必须先披露。例如用户说“不想学工商管理”，当前方案里是“工商管理类（含工商管理、市场营销、人力资源管理）”，需要说明是否把包含该专业的专业类也一起处理。
- 专业组模式下要区分“移出专业组”和“调整组内专业”，不能把组内专业数当成专业组数量。

### 12.6 专业实体歧义

用户：

- 不想学工商管理。

链路：

1. 模型输出 `PlanGoal(goal_type=exclude_scope)`，实体为专业。
2. 实体解析层返回：
   - 标准具体专业：工商管理。
   - 当前方案命中：直接叫“工商管理”的专业；以及包含工商管理的招生计划专业类。
   - 歧义：`catalog_vs_admission_plan`。
3. 如果用户表达足够强烈但歧义影响范围较大：
   - 预览中分开列示“确定会处理的具体专业”和“需要你确认是否一起处理的专业类”。
   - 或进入 `needs_clarification`，先问用户是否包含招生计划里的专业类。
4. 用户确认后再执行。

不允许：

- 直接把“工商管理”扩大为“工商管理类”并删除所有相关方向。
- 因为候选或方案里只有专业类，就把用户的具体专业意图静默改成专业类要求。

## 13. 与当前代码的衔接方式

### 13.1 保留现有基础能力

以下模块继续保留：

- `planning_workflow_tool.py`

它们仍然负责：

- 读取 planningState
- 执行 backend 动作
- 产生结构化事实

说明：

- `planning_action_tool.py` 已在执行层收口后退场
- 原先由该文件承接的筛选补入 / 重排 / 旧补齐文案组装，已经合并或退场到执行层；新的审查修复预览统一走 `preview_fix_proposal`

### 13.2 新增中间编排层

新增：

- `app/tools/plan_context_tool.py`
- `app/tools/plan_orchestration_tool.py`
- `app/tools/plan_execution_tool.py`

### 13.3 删除旧 router

`planning_router_tool` 已从运行时代码中删除：

- ChatAgent 不注册 `handle_planning_request`
- 旧 router 专用测试已迁移到主链路覆盖或删除
- 新增能力只能接入 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`
- 历史会话恢复由 `pendingConfirmation` / `conversation_phase.pending` 和服务端兜底负责，不再保留 request_type 兼容壳

### 13.4 主 Agent 的改造方向

主 Agent 不再直接依赖一长串 `request_type`。

推荐改成：

1. 进入 Plan 场景
2. 先调用 `collect_plan_context_inputs`
3. 再调用 `plan_next_action`
4. 根据 `stage` 决定是否继续 `execute_plan_action`
5. 最终由模型组织回复

## 14. 第一阶段落地范围

第一阶段不建议一次性打全所有动作。

建议只接以下 action family：

- `query_state`
- `add_units`
- `remove_units`
- `move_unit`
- `regenerate_order`
- `review_plan`

原因：

- 覆盖最高频方案干预场景
- 最容易验证多轮链路稳定性
- 能最快观察模型在 Plan skill 下的行为是否收敛

## 15. 测试策略

### 15.1 单测

覆盖：

- `collect_plan_context_inputs` 的读取与摘要正确性
- `plan_next_action` 的 stage 判定
- 缺参场景
- 确认门禁
- 原子动作映射
- 执行后 review 衔接
- Intent 冲突场景
- `PlanGoal` 结构化输出 schema 校验
- `only_keep_scope` 不反向删除目标实体
- `must_include_scope` 只补入目标范围，不删除其他方向
- `exclude_scope` 在具体专业与专业类之间保持边界
- `mixed_adjustment` 能拆成多个原子动作，但未确认前不落盘
- 专业组模式下 unit 级动作和组内专业动作不会混淆
- `entity_resolution_notes` 在存在歧义时必须非空

### 15.2 场景测试

至少覆盖：

- 加指定志愿
- 删指定志愿
- 调位置
- 重排
- 加志愿后自动复审
- 删除志愿后偏好承接摘要变化
- 与现有要求冲突的新增动作预览
- 与现有偏好一致的替换动作预览
- 只保留临床医学：当前方案有命中、候选可补、候选不足三种情况
- 方案里必须有临床医学：当前已有时不改方案；当前没有时生成补入/替换预览
- 不考虑工科，只考虑医学类：正向医学和负向工学都保留，不能互相覆盖
- 只要电气和气象，其他方向都不要：只保留用户点名正向范围，不生成大量负向专业门类
- 不想学工商管理：具体专业、标准专业类、招生计划专业类歧义都要披露
- 不要中外合作，省内优先，保底多一点：风险、地域偏好、结构目标能拆解成复合预览
- 专业模式和专业组模式分别覆盖移出、补入、替换、组内专业调整

### 15.3 端到端验证

重点看：

- 用户未确认时是否只给预览
- 用户确认后是否真的执行
- 执行后方案 / 草稿 / review 是否同步刷新
- 最终文本是否自然，不复述 tool 原文
- `方案有了么 / 帮我审查一下 / 帮我重排一下` 这类真实问法里，最终回复是否仍然退化成粗体标题、编号菜单、决策题

### 15.4 复合计划质量评估

复合动作不能只测“有没有回复”，需要逐 case 评估：

- 意图理解：`goal_type` 是否正确，是否把只读咨询误判为执行。
- 实体边界：具体专业、专业类、门类、招生计划展示名是否区分清楚。
- 动作拆解：是否包含必要的查询、移出、补入、替换、重排、审查动作。
- 可行性判断：候选不足、硬要求冲突、容量不足、目标无法改善是否被识别。
- 预览质量：用户能否看懂会改什么、为什么改、有什么取舍。
- 确认安全：没有确认不落盘；确认后只执行 pending payload。
- 结果验证：执行后方案内容、推荐系数刷新、审查状态和工作台刷新是否一致。
- 回复质量：不用“硬要求、确认卡片、dry-run、preview_only”等系统术语，使用用户能理解的表述。

最低回归集：

| 类型 | 专业模式 | 专业组模式 |
| --- | --- | --- |
| `only_keep_scope` | 保留临床医学，移出非临床医学 | 保留含临床医学的专业组或组内专业，并披露粒度 |
| `must_include_scope` | 至少补入 1 个临床医学 | 在专业组内或新增专业组层面补入，并说明粒度 |
| `exclude_scope` | 排除工商管理具体专业 | 处理包含工商管理的招生计划专业类时必须消歧 |
| `reduce_risk` | 去掉中外合作/高收费 | 专业组内风险优先组内处理；整组替换未开放时说明边界 |
| `rebalance_structure` | 调稳、补保、缩小断层 | 不能把组内专业数当成专业组数量 |
| `mixed_adjustment` | 多目标拆解成复合预览 | 多目标拆解并保持专业组粒度 |

## 16. 风险与边界

### 16.1 不要让模型直接自由调用底层动作 tool

否则容易退化为：

- 顺序混乱
- 重复调用
- 未确认先执行
- 缺参时胡乱补猜

### 16.2 不要让 preview 退化成空文案

preview 必须基于当前 state 给出真正影响，而不是一句“会修改方案”。

### 16.3 不要把 `Intent` 继续当成旁路背景

如果后续实现里 `collect_plan_context_inputs` 只是“结果格式化时顺手看一下”，那这条设计仍然没有真正落地。

正确方式是：

- `Intent` 继续留在现有状态里
- `PlanActionPlan` 显式带上当前输入摘要
- `PlanExecutionResult` 显式带上执行后对当前输入的影响
- `PlanExecutionResult` 还应继续显式带上 `result_kind / reply_focus / next_step_hints`，先由执行层稳定产出“这是状态概览、审查结果、调整分析还是执行结果”的语义边界，再交给模型组织自然回复
- 对真实模型仍偶发输出旧式标题 / 编号 / 选项菜单的情况，服务层可以做只针对 Plan 工具结果的轻量文本 guard：只清理展示格式，不生成新的业务结论，不替代模型对事实和建议的组织

### 16.4 不要把最终用户话术继续塞回 tool 层

否则后面一旦文案要改，业务链和展示链又会重新耦合。

### 16.5 只读 Plan 动作也必须真正执行

`query_state / query_ordered / query_candidates / analyze_adjustment / preview_fix_proposal / review_plan` 这类动作不修改方案，但不能停留在 `analyze` 空阶段。

当前约定：

- `query_state` 默认进入 `apply`，因为它要读取最新 planningState 并返回当前数量、目标数量、风险提醒和状态事实
- `query_draft` 不再是 Agent 主链路可生成的 action；Agent 侧旧 `query_planning_draft` wrapper 已删除，新的方案查看统一走 `query_state` 或 `query_ordered`，底层状态读取只通过 `workingPlanState` helper 对旧字段 fallback
- `query_candidates` 默认进入 `apply`，并且必须把地域、院校、专业、标签、档位和 limit 写入 `PlanAtomicAction.filters`，否则执行层只能按空条件查询候选
- `review_plan` 进入 `review`，因为它会触发复审并刷新 reviewState
- `analyze_adjustment` 进入只读执行，触发 review 并消费 `ReviewState + FixProposalState` 来解释“怎么调/哪些需要取舍”；不再调用旧 `plan-adjustment/analyze`，也不生成可执行确认卡
- `preview_fix_proposal` 进入只读执行，消费 Java `fix-proposals/generate` 的预览事实；只有 service 读取到 `ready` proposal 并创建 active pending 后，用户确认才会应用
- 会修改方案的 `generate_plan / add_units / remove_units / move_unit / regenerate_order` 默认先 `preview`，用户确认后才 `apply`

这里的 `apply` 对只读动作表示“执行查询/分析工具”，不是“修改方案”。

### 16.6 工作台刷新目标必须以执行结果为准

执行层返回的 `PlanExecutionResult.workspace_refresh_targets` 是工作台联动的事实来源。

服务层不应只根据 `action_family` 猜一个目标，否则会出现：

- 重排后只刷新方案区，审查区仍显示旧结果
- 生成方案后排序区更新了，但顶部风险/提醒没有同步
- 删除/移动/修复后复审已跑完，但前端仍需手动刷新才看到新审查标签

当前约定：

- `execute_plan_action` 返回多个目标时，`ChatService` 逐条追加 `planningWorkspaceAction`
- `query_state / analyze_adjustment / preview_fix_proposal` 这类只读动作即使内部读取 ordered/review，也不自动触发工作台刷新
- `review_plan` 刷新 `review`
- `generate_plan / regenerate_order / remove_units / move_unit` 等执行动作按返回结果刷新 `ordered / review / draft`

### 16.7 确认链路必须由统一 pendingConfirmation 承接

对于会修改方案的动作，未确认时 `execute_plan_action` 返回 `preview_only`，但下一轮用户只说“确认 / 就按这个来 / 执行”时，不能要求模型重新猜上一轮参数。

当前约定：

- 预览轮产生可执行调整时，`ChatService` 写入后端 `pendingConfirmation`，并返回 `pendingConfirmationCard`。
- `conversation_phase.pending` 是运行时投影，普通对话启动、只读追问、卡片点击和短文本确认都优先从后端 active `pendingConfirmation` 构建。
- `pendingConfirmation` 内容包含：
  - `pendingId`
  - `kind`
  - `actionFamily`
  - `summary`
  - `executionPayload`
  - `sourceBackendVersion`
  - `compositeProposal`（可选，仅用于复合目标解释、审计和后续上下文承接）
- 卡片点击是主入口；服务端按 `pendingId / kind / status / planning version` 校验后执行。
- 用户短文本回复“确认 / 就按这个来 / 执行”只作为 active pending 的兜底入口；仍进入同一个 `handle_pending_confirmation`，不让模型重新猜上一轮参数。
- 历史 `pending_plan_action` payload 不再作为活动确认状态源；`RequestContext` 不再携带 `pending_plan_action` 字段，`ConversationPhase` 旧 adapter 已删除。当前轮工具预览只会被提取为“待生成确认卡片的候选源”，模型中断 fallback 或上下文解释也不生成可直接消费的 active pending；后续文本确认只能消费后端 active `pendingConfirmation`。
- 旧 `interestAnalysisPopup` follow-up 也只读取 active `pendingConfirmation`；没有 active pending 时提示上下文已失效。`planEditCache` 只保留为历史脏数据清理 key，不再读取、合并或驱动动作。

这层是高副作用动作的稳定性兜底，不替代模型对其他普通对话的理解。

### 16.8 复合目标元数据只做统一承载，不替代执行门禁

`PlanGoal / CompositePlanProposal` 是复合目标的结构化说明层，用来把用户目标、意向更新、方案动作、决策参考和执行后复验计划放到同一处。

当前约定：

- `PlanActionPlan` 顶层仍是动作 envelope，执行层只根据 `stage / action_family / atomic_actions / requires_confirmation / planning_version` 等字段决定能否预览或执行。
- `CompositePlanProposal` 不直接授予执行权限，不能绕过 `pendingConfirmation`、版本校验、确认态或 `execute_plan_action` 的 mutating apply guard。
- 约束意向触发方案调整时，service 会把 `composite_proposal` 写进 `planPayload`，并同步保存到后端 `pendingConfirmation.compositeProposal`，用于审计、卡片状态追踪和后续解释。
- `PendingConfirmation` 运行态模型显式承载 `composite_proposal`，从历史 `plan_payload.composite_proposal`、历史 pending 外层 `compositeProposal` 或后端 active `pendingConfirmation.compositeProposal` 恢复；如果后端 active pending 与历史 preview 不一致，以后端 pending 为准。该字段不进入执行权限判断，真正 apply 仍只消费 `executionPayload`。
- 约束只形成报考条件、暂不能安全形成方案动作时，也可以保存 `pendingConfirmation(kind=intent_change).compositeProposal`。例如大区范围“只保留南方”先记录成 `PlanGoal(only_keep_scope)`，不在执行层未支持前自动删除非南方方案项。
- 后续如果要开放大区、复合场景或 repair 进入自动方案动作，必须先在执行层补齐受控预览、候选/当前方案命中披露、dry-run 或复审校验，再进入同一 pending 确认链路。

### 16.9 对话触发审查与修复的当前开放边界

当前对话侧可以做的是“触发审查、读取后端处理建议、解释下一步”，并且允许对 `review_check` 来源、`status=ready` 的后端 proposal 生成确认卡。真正落盘仍不能由模型自由调用，必须通过 service active pending 确认桥。

已开放：

- `review_plan`：进入后端 `runReview()`，再读取 `fix-proposals/generate`，把 review summary、proposal status、处理方向和阻塞原因交给模型组织回复。
- `analyze_adjustment`：同样基于 `runReview()` 和 `fix-proposals/generate` 输出只读解释，用于回答“怎么调/为什么暂时不能处理/先看哪些方向”；不走旧 `plan-adjustment/analyze`。
- `generate_planning_fix_proposals`：作为只读工具暴露给 ChatAgent，用于解释 Java Server 已生成的处理建议。
- `review_plan/preview_fix_proposal -> pendingConfirmationCard -> apply_planning_fix_proposal`：ChatAgent 只生成审查或预览事实；ChatService 从本轮 `ToolReturnPart` 读取 `fix_proposal_preview`，以及用户明确想“先看怎么处理/怎么调整”时的 `review_result`。只有 `review_check` 来源、`status=ready` 且带 `proposalId/sourceVersionGuard` 的 proposal 才保存 active `pendingConfirmation(kind=plan_mutation, actionFamily=apply_fix_proposal)`。如果用户语义指定了某类处理目标，确认卡只能使用匹配该目标的 ready proposal；目标不可执行时返回只读原因和放宽方向，不能用其他 ready proposal 冒充。普通“只审查/先不要改”的 `review_result` 不生成确认卡。卡片点击或短文本确认命中同一个 pending 后，service 内部调用 Java `fix-proposals/apply`，返回 `RepairReport` 并刷新排序方案。
- 工作台前端：使用同一套 Java `fix-proposals/generate/apply` 协议，让用户在审查结果弹窗里确认 `ready` proposal。

未开放：

- `apply_planning_fix_proposal` 不注册到 ChatAgent 主工具列表。
- 模型不能根据“修一下/确认/就按这个来”自行拼 `proposalId`、`replacementPairs`、`candidateVolunteerIds` 或 `sourceVersionGuard`。
- `preview_only` / `blocked` proposal 不能被 Agent 翻译成普通 `replace_units`、`remove_units` 或旧 `apply_compensation` 绕过后端 apply policy。
- `proposalSource=user_goal` 只通过 service pending 桥受控 apply：service 保存 `userGoalRequest/proposalId/sourceVersionGuard`，用户确认后先写意向，再按最新 planning version 重建 proposal 并调用 Java apply。ChatAgent 仍不能直接调用 apply。

对话侧 repair apply 的固定门禁：

1. Java 返回的 `FixProposal` 能保存成 active `pendingConfirmation`，包含 `proposalId/sourceVersionGuard/sourceReviewVersion/status/strategy/summary`。
2. 对话卡片和短文本确认都只消费 active pending，不让模型重新理解上一轮修复范围。
3. apply 前仍走 Java `RepairProposalApplyPolicy`，校验版本、stale、status、strategy 白名单和 dry-run 目标。
4. apply 后把 `RepairReport` 回写对话事实和工作台状态，刷新 ordered/review/proposal。
5. proposal 过期、不可应用或候选不足时，只返回重新审查、调整条件或人工处理建议，不降级成其他 action。

现阶段的推进节奏：

- P0：固定“帮我审查/看看怎么修”只读链路，补回归确保 preview 本身不落盘。
- P0：已打通对话侧 `ready` review proposal 的 pending/apply 桥；继续补真实前端走查和 live WebSocket 场景，确认卡片状态、RepairReport 回复和工作台刷新一致。
- P0：定义 `source=user_goal` 的 Java proposal 输入协议，让复合用户目标复用 Java 候选选择、dry-run 和 apply policy。当前已完成主链路：新增 `UserGoalFixProposalReq` 输入 DTO；`UserGoalProposalBuilder` 已能为 `only_keep_scope/must_include_scope/exclude_scope` 生成 ready proposal，专业模式和专业组模式都保留 from/to 配对信息；service 可生成 `apply_fix_proposal` pending，并在用户确认时先写意向、重建 proposal、再 apply。
- P0：`plan_next_action` 不再调用后端 user-goal proposal，也不再向 `CompositePlanProposal` 挂接 repair DTO 镜像；它只保留 `PlanGoal/intent_updates/decision_references` 和保守 `plan_actions`。真正会改方案的复合目标统一由 service pending 桥进入 Java proposal/apply。
- P0：Agent action family 已移除 `preview_compensation/apply_compensation`。历史会话里的旧 compensation preview/apply 只作为 legacy 输入被忽略或拒绝，不能生成新的 pending，也不能绕过 Java `FixProposal` 与 `RepairProposalApplyPolicy`。
- P1：不把 `apply_planning_fix_proposal` 注册给 ChatAgent；后续如果要扩大 apply 范围，只扩 service pending bridge 和 Java apply policy，不让模型直接执行高副作用工具。
- P1：Java compensationPreview 仍可作为 `fill_missing_count/add_safety_items` proposal 的内部素材；Agent 用户侧不再读取或展示旧 compensation facts，审查/调整只通过 `FixProposalState` 披露处理方向。

### 16.10 模型误路由后的结构化恢复边界

Plan 主链仍以模型理解为入口，但模型可能在两类情况下走到错误的只读或非动作路径：

- 用户明确要调整方案，模型却先调用 `query_state` 并按方案概览回复。
- 用户明确要补齐、增删或替换方案，模型却调用了 `preview_fix_proposal` 等不匹配的非动作入口，最后没有形成确认预览。

这类问题不能用用户话术字符串兜底，也不能新增第二套执行路径。服务层统一按以下边界恢复：

1. 当前轮没有 active `pendingConfirmation`，也没有已经形成的方案确认卡。
2. 当前轮确实调用过 Plan 链路工具，且最新结果是 `query_state/status_overview` 或非动作错误结果。
3. 服务层只调用 `classify_plan_recovery_action` 做语义恢复；分类器高置信输出 `add_units / remove_units / replace_units / move_unit / move_ordered_unit / remove_ordered_unit / sort_ordered_plan` 之一时，才重新进入 `plan_next_action -> execute_plan_action`。
4. 恢复后仍遵守原执行层门禁：缺少候选范围、缺少当前方案目标、候选不足或版本不一致时，只返回具体缺参/阻断说明，不生成 pending，也不刷新工作台。
5. 如果 `plan_next_action` 已经返回 `missing_inputs=["selection_scope"]`，即使模型后续又传了一个较薄的 `execute_plan_action` payload，也要保留这个缺参事实，向用户提示需要补充学校、专业、地域等范围或先在候选里选中目标。
6. 同一轮如果已经产出 `analyze_current_career_direction` 这类只读探索结果，最终回复合成要优先保留它，再补“不改方案/先看分析”的边界；不能再被 `review_result`、`adjustment_analysis` 或“没有形成可执行预览”的通用兜底覆盖成纯审查概览。
7. 无最近审查结果或处理建议时，`analyze_adjustment` 只允许承接两类明确边界：候选供给不足/补稳补保可行性，以及用户明确追问已知提醒为什么处理不了、需要如何取舍。普通只读风险解释，如“中外合作是不是多、预算一般、说人话看风险、先别动”，即使能推断出高收费或中外合作 issue，也应交回完整 Agent 读取方案事实回答，不能升级成修复不可用说明或替换建议。

这个恢复逻辑只修正“模型选错工具入口”的框架问题，不改变用户确认协议，不允许模型绕过确认卡或 Java proposal apply policy。

## 17. 推荐落地顺序

1. 定义 `PlanContextInputs / PlanAtomicAction / PlanActionPlan / PlanExecutionResult`
2. 新增 `plan_context_tool`
3. 新增 `plan_orchestration_tool`
4. 新增 `plan_execution_tool`
5. 接通六个高频 action family
6. 删除 `planning_router_tool` 和旧 router 专用测试，新增能力只接入 Plan 主链
7. 修改 `ChatAgent` 的 Plan skill 指令
8. 再扩展 `replace_units / review fix proposal / proposal apply pending bridge`

## 18. 一句话总结

Plan 层后续不应继续围绕“工具名 + request_type”扩展，而应升级为：

- skill 约束能力边界
- Intent 作为现有状态输入进入 `Plan` 决策链
- 模型产出结构化动作计划
- 受控执行层完成门禁与动作映射
- 执行后自动复审并把结果回灌给模型组织最终回复

这样才能真正把 `Intent -> Plan`、局部调整、整体调整和多轮确认统一到一条稳定链路上。
