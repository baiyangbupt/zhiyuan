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
- 补偿预览
- 增删改重排类动作

但当前仍存在四类结构性问题：

### 2.1 入口语义仍偏平铺

当前 `planning_router_tool.handle_planning_request` 仍然以 `request_type` 为中心扩展。

问题：

- 能覆盖高频场景，但不利于承接自然语言多样表达
- 一旦新增动作，容易继续堆 alias
- “分析 / 预览 / 执行 / 复审”四段责任没有显式建模

### 2.2 动作前的预览还不统一

当前部分动作已经有“未确认时先给预览”的能力，但仍然主要依赖 router 内的局部补丁。

问题：

- 不是所有动作都共享同一套预览结构
- 模型无法稳定利用预览结果继续多轮推进
- 缺少统一的“动作计划”中间层

### 2.3 模型与 tool 的责任边界还不够清晰

当前主 Agent 已经是模型主导选 tool，但在 Plan 场景仍存在两种风险：

- 模型直接在多个底层 tool 之间漂移
- router / tool 同时在承担“理解用户想干什么”的职责

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
- Mutation tool：执行增删改、补偿、重排、复审

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
- `planning_workflow_tool`、草稿/排序低层读写 tool、补偿/重排/审查等实现，不再作为模型直连入口注册到 `ChatAgent`

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

第一期建议支持以下动作：

- `add_units`
- `remove_units`
- `move_unit`
- `pin_unit`
- `unpin_unit`
- `replace_units`
- `regenerate_order`
- `apply_compensation`
- `review_plan`

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

### 6.6 apply_compensation

含义：

- 应用当前补偿建议

说明：

- 高风险动作
- 必须明确确认

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
        "query_candidates",
        "add_units",
        "remove_units",
        "move_unit",
        "pin_unit",
        "unpin_unit",
        "replace_units",
        "regenerate_order",
        "apply_compensation",
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
  - 或执行层内部的候选筛选 + `select_planning_draft_items` + 生成排序
- `remove_units`
  - `remove_planning_ordered_items`
- `move_unit`
  - `move_planning_ordered_item`
- `pin_unit`
  - `pin_planning_ordered_item`
- `unpin_unit`
  - `unpin_planning_ordered_item`
- `regenerate_order`
  - 执行层内部直接调用 `generate_planning_ordered_plan` 并自动复审
- `apply_compensation`
  - 执行层内部直接调用 `apply_planning_compensation` 并自动复审
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
- `pin_unit` 缺 `volunteer_id / target_position` 时禁止执行
- `unpin_unit` 缺 `volunteer_id` 时禁止执行
- `replace_units` 缺 `volunteer_ids` 或补入筛选范围时禁止执行
- `add_units / replace_units` 的补入筛选范围不能只靠 `limit` 判断，必须至少包含地域、院校、专业、标签或明确 volunteerIds

### 10.2 确认阻断

以下动作默认必须确认：

- `regenerate_order`
- `apply_compensation`
- `replace_units`
- 大批量 `add_units`
- 大批量 `remove_units`

### 10.3 执行后自动复审

以下动作默认执行后自动进入 `review`：

- `add_units`
- `remove_units`
- `move_unit`
- `pin_unit`
- `unpin_unit`
- `replace_units`
- `regenerate_order`
- `apply_compensation`

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
- 原先由该文件承接的筛选补入 / 重排 / 补偿文案组装，已经合并到 `plan_execution_tool.py`

### 13.2 新增中间编排层

新增：

- `app/tools/plan_context_tool.py`
- `app/tools/plan_orchestration_tool.py`
- `app/tools/plan_execution_tool.py`

### 13.3 逐步缩薄 router

当前 `planning_router_tool` 不立即删除，而是：

- 第一阶段继续作为兼容入口
- 内部逐步把 `request_type` 映射到 `PlanActionPlan`
- 最终退化为老协议兼容层

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

### 15.3 端到端验证

重点看：

- 用户未确认时是否只给预览
- 用户确认后是否真的执行
- 执行后方案 / 草稿 / review 是否同步刷新
- 最终文本是否自然，不复述 tool 原文
- `方案有了么 / 帮我审查一下 / 帮我重排一下` 这类真实问法里，最终回复是否仍然退化成粗体标题、编号菜单、决策题

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

`query_state / query_draft / query_ordered / query_candidates / analyze_adjustment / preview_compensation / review_plan` 这类动作不修改方案，但不能停留在 `analyze` 空阶段。

当前约定：

- `query_state` 默认进入 `apply`，因为它要读取最新 planningState 并返回当前数量、目标数量、风险提醒和状态事实
- `query_candidates` 默认进入 `apply`，并且必须把地域、院校、专业、标签、档位和 limit 写入 `PlanAtomicAction.filters`，否则执行层只能按空条件查询候选
- `review_plan` 进入 `review`，因为它会触发复审并刷新 reviewState
- `analyze_adjustment / preview_compensation` 进入只读执行，产出分析事实或预览事实，但不自动修改方案
- 会修改方案的 `generate_plan / add_units / remove_units / move_unit / regenerate_order / apply_compensation` 默认先 `preview`，用户确认后才 `apply`

这里的 `apply` 对只读动作表示“执行查询/分析工具”，不是“修改方案”。

### 16.6 工作台刷新目标必须以执行结果为准

执行层返回的 `PlanExecutionResult.workspace_refresh_targets` 是工作台联动的事实来源。

服务层不应只根据 `action_family` 猜一个目标，否则会出现：

- 重排后只刷新方案区，审查区仍显示旧结果
- 生成方案后排序区更新了，但顶部风险/提醒没有同步
- 删除/移动/补偿后复审已跑完，但前端仍需手动刷新才看到新审查标签

当前约定：

- `execute_plan_action` 返回多个目标时，`ChatService` 逐条追加 `planningWorkspaceAction`
- `query_state / analyze_adjustment / preview_compensation` 这类只读动作即使内部读取 ordered/review，也不自动触发工作台刷新
- `review_plan` 刷新 `review`
- `generate_plan / regenerate_order / remove_units / move_unit / apply_compensation` 等执行动作按返回结果刷新 `ordered / review / draft`

### 16.7 确认链路必须有 pending action 承接

对于会修改方案的动作，未确认时 `execute_plan_action` 返回 `preview_only`，但下一轮用户只说“确认 / 就按这个来 / 执行”时，不能要求模型重新猜上一轮参数。

当前约定：

- `ChatService` 从历史中最近一次 `execute_plan_action` 的 preview 结果提取待确认动作
- 如果模型在预览轮只调用了 `plan_next_action`，但没有继续调用 `execute_plan_action` 生成 `preview_only`，服务层也会从 `plan_next_action(stage=preview)` 的结果提取 pending 动作
- 注入 `RequestContext.pending_plan_action`
- pending 内容包含：
  - `action_family`
  - `user_goal`
  - `summary`
  - 已经把 `stage` 改成 `apply` 的 `plan_payload`
- 主模型看到用户确认时，应直接调用 `execute_plan_action(plan_payload=pending.plan_payload)`
- 服务层对非常明确的短确认语也可以直接执行 pending `plan_payload`，并写入同等结构的 tool-call / tool-return 历史；这是为了避免模型在“确认”这一轮重新猜参数或漏调工具
- 如果后续历史里已经出现同类 `applied=true` 执行结果，则清空 pending

这层是高副作用动作的稳定性兜底，不替代模型对其他普通对话的理解。

## 17. 推荐落地顺序

1. 定义 `PlanContextInputs / PlanAtomicAction / PlanActionPlan / PlanExecutionResult`
2. 新增 `plan_context_tool`
3. 新增 `plan_orchestration_tool`
4. 新增 `plan_execution_tool`
5. 接通六个高频 action family
6. 让 `planning_router_tool` 逐步复用新中间层
7. 修改 `ChatAgent` 的 Plan skill 指令
8. 再扩展 `replace_units / apply_compensation / pin/unpin`

## 18. 一句话总结

Plan 层后续不应继续围绕“工具名 + request_type”扩展，而应升级为：

- skill 约束能力边界
- Intent 作为现有状态输入进入 `Plan` 决策链
- 模型产出结构化动作计划
- 受控执行层完成门禁与动作映射
- 执行后自动复审并把结果回灌给模型组织最终回复

这样才能真正把 `Intent -> Plan`、局部调整、整体调整和多轮确认统一到一条稳定链路上。
