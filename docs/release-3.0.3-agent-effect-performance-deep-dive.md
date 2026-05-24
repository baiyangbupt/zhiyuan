# Release 3.0.3 Agent Effect / Performance Deep Dive

本文记录 `3.0.3` 针对 Agent 效果和性能的专项分析、优化设计、实施记录和回归结果。

关联文档：

- `docs/release-3.0.2-routing-preview-action-review.md`
- `docs/release-3.0.2-implementation-design.md`
- `docs/release-3.0.1-agent-optimization-design.md`

## 1. 本期目标

`3.0.3` 的核心目标不是继续堆 UI 功能，而是把对话 Agent 的主链路变得更稳定、更快、更可观测：

1. 明确用户一句话如何进入 Explore、Intent、Plan 三层，不再依赖模型反复试工具。
2. 对高置信、低歧义的方案操作建立结构化快路径，降低延迟和误路由。
3. 保留大模型润色和解释能力，但减少无意义的多轮模型调用。
4. 建立可持续的效果与性能 benchmark，后续每次换模型、改提示词、改工具都能量化比较。
5. 在不破坏 `preview -> confirm -> apply` 安全边界的前提下，提高方案查看、排序、移动、删除、审查、意向确认的端到端体验。

不在本期做：

- 不把所有对话改成规则模板回复。
- 不绕过确认机制直接执行高副作用动作。
- 不把 provider 切换当成唯一优化手段。
- 不重写后端方案算法。
- 不删除历史兼容路径，除非已有测试证明无消费方。

## 2. 当前实测表现

基于当前本地真实 WebSocket e2e 验证，`dialog_regression_302_effect_perf_cases.json` 共 11 个步骤全部功能通过，但性能波动明显。

| 指标 | 当前结果 |
| --- | --- |
| 测试步骤 | 11 |
| 功能失败 | 0 |
| 最快 | 2.145s |
| 中位数 | 31.994s |
| p95 / 最大 | 140.709s |

最慢场景：

| 场景 | 用户话术 | 耗时 | 主要问题 |
| --- | --- | ---: | --- |
| 职业方向承接分析 | 当前方案对体制内稳定就业方向承接得怎么样，先不要改方案 | 140.709s | Explore 内部再调 slot 识别和分析生成，最后还要主模型组织回复 |
| 专业对比只读分析 | 法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好 | 111.758s | 模型同时触发专业适配、专业对比、专业介绍等多个工具 |
| 单志愿移动预览 | 把第2个志愿移到第4位 | 69.047s | 明确操作仍先走一次错误 analyze，再重试 preview |
| 专业组移动预览 | 把第4个专业组移到第2位 | 62.857s | 可结构化的专业组移动仍需要多轮模型/工具协调 |
| 方案状态查看 | 看看现在的方案，给我一个结构化一点的结论 | 60.651s | 只读状态仍走完整 Agent 循环，产生多次模型请求 |

快路径表现：

| 场景 | 耗时 | 说明 |
| --- | ---: | --- |
| 无 pending 时用户说“确认” | 2.145s | service 层直接 guard，不进大模型 |
| 单志愿移动确认执行 | 4.461s | 已有 pending 后直连 `execute_plan_action` |
| 专业组移动确认执行 | 5.406s | 已有 pending 后直连 `execute_plan_action` |

结论：

- “确认执行”已经具备有效快路径。
- 性能瓶颈集中在“首次理解 + 预览生成 + 只读深度分析”。
- Provider 延迟会放大问题，但根因不是单纯接口慢，而是单轮对话里模型请求数、输入 token、工具重试次数过多。

## 3. 当前调用链

### 3.1 总入口

```text
WebSocket / HTTP
  -> ChatService.handle_message
     -> load history
     -> extract pending plan action from history
     -> build runtime history
     -> fetch score_detail / init_profile / planning_summary
     -> build ConversationPhase
     -> direct pending confirm guard
     -> ChatAgent.run_with_message_deltas
        -> LLM
        -> tool calls
        -> LLM final answer
     -> post process reply
     -> save history
     -> emit workspace followup cards
```

关键事实：

- `conversation_phase.pending` 已是主 pending 来源。
- `pending_plan_action` / `pending_intent_change` 仍作为旧会话兼容来源存在。
- 短确认已经在 service 层直连工具，不经过完整大模型链路。
- 非短确认仍进入完整 `ChatAgent`。

### 3.2 Plan 当前链路

```text
用户问方案 / 调整方案
  -> LLM 判断工具
  -> plan_next_action
       -> _collect_plan_context_inputs_model
          -> get_planning_state
          -> get_user_profile
       -> PlanActionPlan
  -> execute_plan_action
       -> preview / apply / review / query
  -> LLM 组织最终回复
  -> service 提取 pending / 工作台联动卡片
```

现状问题：

- `tool_dispatch_rules.py` 已要求方案状态直接 `plan_next_action(query_state) -> execute_plan_action`，但真实运行仍可能出现 3 次模型请求。
- 明确移动请求也可能先走错误 `execute_plan_action(stage=analyze)`，拿到 error 后再重走 `plan_next_action`。
- `plan_next_action` 每次都会读取完整 Plan 上下文；如果同一轮被重复调用，会重复后端读取和重复注入上下文。
- `ActionResolver` 已存在，但没有进入主路径；当前主链仍主要靠 LLM 选择 `plan_next_action` 参数。

### 3.3 Explore 当前链路

职业方向分析：

```text
用户问体制内 / 稳定就业 / 读研适配
  -> LLM 选择 analyze_current_career_direction
  -> resolve_career_direction_slots
       -> LLM slot resolver
  -> get_planning_state / candidate facts
  -> _generate_direction_analysis_content
       -> LLM analysis generator
  -> LLM final answer
```

专业适配 / 对比：

```text
用户问 A 专业和 B 专业哪个适合
  -> LLM 可能选择 analyze_current_major_interest
       -> analyze_volunteer_intent_change
       -> 正向/负向专业意向抽取 LLM
  -> LLM 可能再调用 compare_majors
       -> 专业名标准化
       -> query_volunteer_analysis_weight
       -> LLM 对比总结
  -> LLM 可能再调用 get_major_introduction
  -> LLM final answer
```

现状问题：

- “先只分析不要记偏好”仍可能触发意向抽取链路，虽然功能上不写入 pending，但消耗很大。
- 明确的两个专业对比，不需要先泛化为“当前专业兴趣分析”。
- 职业方向中的“体制内 / 稳定就业 / 读研”本来是有限 taxonomy，目前仍会先用 LLM slot resolver。

### 3.4 Intent 当前链路

```text
用户表达偏好或硬要求
  -> LLM 选择 preview_current_*_intent_confirmation
  -> analyze_volunteer_intent_change
       -> 如果未传结构化参数，则触发抽取
       -> 读取方案/候选影响
       -> 生成 pending intent preview
  -> 用户确认
  -> service direct_pending_intent_confirm
       -> update_volunteer_intent_state(action="confirm")
```

现状问题：

- 提示词已要求“用户说清楚时直接传结构化参数”，但模型不稳定，仍可能多发起抽取。
- Intent 预览后，如果用户追问“这个偏好会影响方案吗”，当前会进入较重链路，且回复里可能出现“没有可执行调整预览”的边界提示，用户理解成本偏高。

## 4. 根因分析

### 4.1 主路由仍由大模型自由试探

当前工具清单较多，且 Explore / Intent / Plan 的边界靠提示词约束。对明确、低歧义场景来说，这会带来两个问题：

- 模型可能先选错工具，再通过错误结果自我修正。
- 即使最终结果正确，也会多花一次或多次 LLM 请求。

典型例子：

```text
把第2个志愿移到第4位
```

这是明确的 Plan mutation，理论上应直接进入 `move_unit preview`。当前实测中先出现 `move_unit stage=analyze resultKind=error`，随后再次规划才拿到 preview。

### 4.2 上下文读取和上下文注入重复

`plan_next_action` 内部读取完整上下文，`collect_plan_context_inputs` 也会读取相同状态。虽然提示词要求不要重复调，但真实模型仍可能重复。

影响：

- 后端状态读多次。
- 工具返回内容进入消息历史，下一次模型请求输入 token 继续膨胀。
- 一次简单问题被放大成 3 到 6 次模型请求。

### 4.3 只读分析链路过重

职业方向和专业对比本质上是只读回答，但现在经常组合多个 LLM 子任务：

- 主模型选工具。
- 工具内部再用 LLM 做 slot 识别或内容生成。
- 主模型再用工具结果生成最终回复。

如果当前 provider 延迟较高，三层 LLM 调用会直接把耗时推到 1 到 2 分钟。

### 4.4 工具边界不够强

部分工具既负责事实查询，又负责内容生成；主模型拿到已成文内容后仍会再组织一遍。这样会造成：

- 重复润色。
- 用户可读内容不一定更好。
- latency 和 token 成本成倍增长。

### 4.5 观测数据还不够细

当前 e2e 能记录每步总耗时、消息数、followup，但还不能稳定回答：

- 哪次 LLM 请求最慢。
- 哪个工具最慢。
- 同一轮调用了哪些 action family。
- 输入 token 是来自系统提示、历史、工具返回还是候选/方案事实。

因此需要先把效果和性能观测做细，否则后续只能凭感觉优化。

## 5. 3.0.3 方案设计

### 5.1 总体架构

建议把当前完整 Agent 链路拆成三层：

```text
ChatService
  -> Conversation State / Pending Guard
  -> Typed Pre-Router（高置信结构化入口）
       -> Plan Fast Lane
       -> Explore Fast Lane
       -> Intent Fast Lane
  -> Full LLM Agent fallback
```

原则：

- 高置信、低歧义场景走结构化入口。
- 结构化入口只负责“动作识别和参数装配”，不负责拼模板回复。
- 事实、预览、执行仍走现有 tool / backend。
- 低置信、歧义、开放式咨询继续交给完整 LLM Agent。
- 所有高副作用动作继续强制 `preview -> confirm -> apply`。

这不是把系统改成字符串模板匹配。关键区别是：

- 不用固定字符串直接产出用户回复。
- 不靠关键词决定业务事实。
- 只在能确定结构化动作时生成 typed action payload。
- 回复仍基于 `execute_plan_action` / Explore 工具返回的事实结果。

### 5.2 Plan Fast Lane

优先覆盖下面几类稳定场景：

| 场景 | 示例 | 快路径动作 |
| --- | --- | --- |
| 方案状态 | 看看现在的方案 / 方案怎么样 | `query_state -> execute_plan_action` |
| 数字位置移动 | 把第2个志愿移到第4位 | `move_unit preview` |
| 专业组位置移动 | 把第4个专业组移到第2位 | `move_ordered_unit preview` |
| 排序 | 按院校层次排序 / 按录取率排序 / 按推荐系数排序 | `sort_ordered_plan preview` |
| 审查 | 审查一下方案 / 看看风险 | `review_plan -> execute_plan_action` |
| 无 pending 确认 | 确认 | 已有 guard，保持 |

实现建议：

1. 新增 `PlanFastRouter`，输入 `content + RequestContext + PlanningSummary + ConversationPhase`。
2. 输出 `FastRouteDecision`：

```json
{
  "matched": true,
  "confidence": "high",
  "route": "plan",
  "action_family": "move_unit",
  "stage": "preview",
  "payload": {}
}
```

3. 命中后直接调用：

```text
PlanFastRouter -> execute_plan_action -> service reply renderer
```

4. 未命中或置信不足时回落完整 `ChatAgent`。

注意事项：

- 数字移动可以先覆盖 `第N个志愿/第N条志愿` 和 `第N个专业组`。
- 学校名 + 专业名、简称、模糊指代继续走完整 Agent 或执行层唯一性解析，避免误删误移。
- 快路径只生成 preview，不直接 apply。
- pending 创建仍使用现有 `_extract_pending_plan_action` 或新增统一 pending 写入方法，避免确认链断开。

预期收益：

- 方案状态查看从约 60s 降到 10 到 20s。
- 数字移动 / 专业组移动 preview 从约 60s 降到 10 到 25s。
- 减少模型请求数，降低 provider 慢请求对体验的放大效应。

### 5.3 Plan Context 缓存

问题：同一轮内多次读取 `planning_state / user_profile`。

建议：

- 在 `RequestContext` 增加 per-turn cache，例如 `planning_context_inputs` 或 `state_cache`。
- `_collect_plan_context_inputs_model` 先查 cache，未命中再读后端。
- `plan_next_action`、`execute_plan_action` 的 preview resolver 需要复用同一份状态时，优先用 cache。

边界：

- 只做单轮内缓存，不跨用户轮次缓存。
- apply 成功后必须刷新或失效 cache。
- preview 前读取的 `planning_version` 仍要带入 pending，用于确认前 stale 校验。

### 5.4 ActionResolver 接入主路径

当前 `ActionResolver` 已有 typed action 模型，但还没有接入主路径。`3.0.3` 可以把它从“并行设计”推进到“可观测灰度”。

建议分两步：

1. 影子模式：
   - Full Agent 运行前或运行后，用 `IntentFrame / ActionResolver` 生成 shadow resolution。
   - 只记录日志，不改变行为。
   - 对比 LLM 实际 action_family、stage、missing_inputs。
2. 低风险接管：
   - 只接管 `query_state`、`sort_ordered_plan`、数字移动这类高置信动作。
   - 歧义和复杂动作继续回落 LLM。

需要补齐：

- `IntentFrame` 的生成方式：不能再依赖一个大而慢的通用抽取 prompt。
- 对低风险动作可用轻量结构解析；对开放式表达仍交 LLM schema extraction。
- ActionResolver 输出需能转换为现有 `PlanActionPlan`，复用 `execute_plan_action`。

### 5.5 Explore Fast Lane

#### 职业方向

当前职业方向 slot 是有限集合：

- 体制内 / 考公 / 考编：`system_public_service`
- 稳定就业：`stable_employment`
- 读研 / 深造：`further_study`

建议：

- 对这些有限 taxonomy 做本地规范化识别，命中后跳过 `resolve_career_direction_slots` 的 LLM。
- 仍然调用现有方向分析事实收集和内容生成。
- 对“我适合什么方向”这类开放泛问题，保留 generic direction 路径。

进一步优化：

- `_generate_direction_analysis_content` 如果已生成结构化中文段落，主模型无需再次大幅润色。
- 可以由 service 直接返回工具内容，或只做轻量回复包装。

#### 专业对比

对明确 `A 和 B 哪个更适合` 的场景：

- 直接进入 `compare_majors` 或新增 `compare_majors_for_current_student`。
- 不先调用 `analyze_current_major_interest`。
- 不触发正向/负向专业意向抽取。
- 如果 `compare_majors` 已能返回完整结构化分析，就不要再调用两次 `get_major_introduction`。

需要保留：

- 专业简称和非标准专业名的规范化。
- 无法唯一匹配时给澄清，不编造专业。
- 只读分析不生成 pending intent。

### 5.6 Intent Preview Slimming

目标：用户明确表达偏好时，减少额外抽取。

建议：

- 对“我倾向 A 和 B，但 C 不要”这类单句，先做轻量 entity extraction。
- 能稳定抽出专业/学校/地域时，直接传入 `preview_current_*_intent_confirmation` 的结构化参数。
- 工具内部如果收到结构化参数，必须跳过同类抽取。
- 预览后用户追问影响时，优先复用 pending intent payload 和当前 planning summary，避免重新跑完整抽取。

边界：

- 如果表达含糊，例如“我还是喜欢偏文一点的”，仍进入完整 LLM 解释。
- 软偏向和硬要求要在 payload 中区分，不能为了快而丢语义。

### 5.7 Reply Renderer 收口

当前很多场景是工具已返回面向用户的结构化文本，主模型再写一遍。`3.0.3` 可以先对下面场景收口：

- Plan preview：直接用 `PlanExecutionResult.summary + confirmation boundary`。
- Plan mutation apply：直接用执行结果 summary。
- no pending confirm：现有直接回复。
- Explore 工具已返回完整正文时：允许直接返回或做极轻包装。

注意：

- 不回到粗糙字符串拼接。
- Renderer 只能消费结构化 facts / summary。
- 对开放式问答仍交大模型组织自然语言。

## 6. 可观测性与 benchmark

### 6.1 日志需要补充的字段

现有 `conversation_turn_event` 已记录总耗时、routingPath、actionFamily、模型配置等。`3.0.3` 需要继续补：

```json
{
  "routeDecision": {
    "source": "fast_router|full_agent|direct_pending",
    "matched": true,
    "confidence": "high",
    "fallbackReason": ""
  },
  "llmRequests": 3,
  "inputTokens": 31618,
  "outputTokens": 1200,
  "toolCalls": [
    {
      "name": "plan_next_action",
      "durationMs": 1200,
      "actionFamily": "query_state"
    }
  ],
  "actionFamily": "move_unit",
  "resultKind": "preview_only"
}
```

### 6.2 Benchmark 文件建议

新增或升级：

- `zhiyuan-agent/examples/dialog_regression_303_effect_perf_cases.json`
- `zhiyuan-agent/examples/dialog_regression_303_full_journey_cases.json`
- `zhiyuan-agent/tests/e2e/test_agent_dialog_effect_perf.py` 增加 `303` 配置入口

场景覆盖：

| 模块 | 必须覆盖 |
| --- | --- |
| Plan 状态 | 当前方案结构化查看，不出现内部字段，不触发卡片 |
| Plan 排序 | 录取率、院校层次、推荐系数 preview -> confirm -> apply |
| Plan 移动 | 专业模式单志愿数字移动，学校+专业移动，简称歧义澄清 |
| Plan 专业组 | 专业组整体移动/删除，组内专业不打散 |
| Plan 审查 | 审查入口、审查后异常解释、待重新审查状态 |
| Intent | 软偏好 + 硬排除 preview，确认后写入，拒绝后不写入 |
| Explore | 职业方向、专业对比、学校/地域适配，只读不写 pending |
| 安全边界 | 无 pending 说确认、preview 未确认不执行、pending stale 不执行 |
| 历史污染 | 新会话、老会话、长历史裁剪后均不泄露内部字段 |

### 6.3 性能验收目标

第一阶段目标：

| 场景 | 当前 | 3.0.3 目标 |
| --- | ---: | ---: |
| 无 pending 确认 | 2.1s | <= 3s |
| pending 确认执行 | 4-6s | <= 8s |
| 方案状态查看 | 60.7s | <= 25s |
| 单志愿数字移动 preview | 69.0s | <= 25s |
| 专业组数字移动 preview | 62.9s | <= 25s |
| Intent preview | 21.4s | <= 25s，且不额外抽取 |
| 职业方向只读分析 | 140.7s | <= 60s，后续目标 <= 35s |
| 专业对比只读分析 | 111.8s | <= 60s，后续目标 <= 35s |

模型请求数目标：

| 场景 | 目标 |
| --- | --- |
| 方案状态查看 | <= 1 次主 LLM，最好 0 次主 LLM |
| 数字移动 preview | <= 1 次主 LLM，快路径可 0 次主 LLM |
| pending confirm | 0 次主 LLM |
| 职业明确 slot | <= 2 次 LLM |
| 专业明确对比 | <= 2 次 LLM |

### 6.4 效果质量验收目标

性能优化不能以牺牲对话效果为代价。`3.0.3` 的 benchmark 需要同时检查“快”和“答得好”：

| 维度 | 验收口径 |
| --- | --- |
| 用户可理解 | 回复使用用户侧语言，不暴露 `payload / stage / action_family / volunteerId` 等内部字段，不再出现“草稿”等已废弃概念。 |
| 信息充足 | 方案概览至少包含方案数量、冲稳保结构、审查风险/提醒、当前偏好承接或可操作下一步，避免只给一句薄回复。 |
| 结构清楚 | 复杂回复要有分行和要点，避免长串学校/专业堆叠；专业组操作要明确“按专业组顺序，不是单条志愿位置”。 |
| 边界明确 | 高副作用动作必须先 preview，说明“确认后才会执行”；确认前不得刷新方案，确认后才刷新 `ordered/review`。 |
| 只读不误联动 | “先只分析 / 不要改方案 / 不要记偏好”不得生成无意义工作台卡片或 pending intent。 |
| 歧义不误操作 | 学校/专业简称无法唯一定位时要澄清，不为了快而猜测并执行。 |
| 事实一致 | 执行类回复、`executed_actions`、工作台刷新对象和日志中的目标对象必须一致，尤其是专业组移动后不能按变化后的顺序重新解析目标。 |

当前 runner 用 `assertContains / assertContainsAny / assertNotContains / assertNoFollowups / assertFollowupTarget` 做自动质量门禁；真实效果仍需要抽样人工看完整文本，重点检查是否丰富、是否自然、是否能直接指导用户下一步。

### 6.5 3.0.3 效果/性能复测记录

新增 `zhiyuan-agent/examples/dialog_regression_303_effect_perf_cases.json`，默认作为 `tests/e2e/test_agent_dialog_effect_perf.py` 的真实 WebSocket 场景集合。该集合不只看延迟，也把回复质量作为门禁：

- 方案现状必须结构化、信息充足，不能暴露内部字段或旧“草稿”概念。
- 专业组移动必须解释“专业组顺序”语义，确认前不执行，确认后刷新排序方案。
- 排序预览必须说明会实际改变方案和导出顺序，并进入待重新审查。
- Explore 只读分析不能写 pending、不能发工作台卡片。
- 无 pending 时“确认”必须快速返回保护性提示。
- pending 之后如果用户明确“先不要改方案 / 只分析 / 不执行”，必须清掉旧方案 pending；后续“确认”不能误执行旧排序/移动。

本地最新复跑结果：

| 场景 | 耗时 | 效果结论 |
| --- | ---: | --- |
| 方案结构化现状 | 2.6s | 通过；包含数量、冲稳保、审查、缺口、前排示例和偏好承接。偏好摘要已在截断时显示“等 N 项”，避免示例命中未展开偏好时造成误解。 |
| 专业组移动 preview | 4.3s | 通过；明确专业组名称、组内专业数、目标专业组位置和确认边界。 |
| 专业组移动 confirm | 4.6s - 31.7s | 功能通过；`llmRequests=0`，确认后刷新 `ordered`。本地复跑存在波动，慢例中 Agent `mutationRequestDurationMs≈28.1s`，慢点仍在后端移动接口/本地状态处理，不是模型。 |
| 院校层次排序 preview | 2.2s | 通过；说明会改变方案/导出顺序并触发待重新审查。 |
| 体制内稳定就业承接分析 | 26.3s | 通过；只走 `analyze_current_career_direction`，未再先 `load_skill`，未写 pending，未发工作台卡片；回复保留学生适配、方案承接、候选机会和下一步。 |
| 只读分析后确认保护 | 约 2s | 通过；排序 preview 后用户说“先不要改方案”会清掉旧 pending，下一句“确认”返回没有待确认动作，不误执行旧排序。 |
| 法学 vs 财政学对比 | 16.3s | 通过；只走 `compare_majors`，未写 pending，回复有结构化对比。 |
| 无 pending 确认保护 | 2.1s | 通过；不进工具、不发工作台卡片。 |

结论：

- Plan 快路径已达到可接受体验，主要慢点不在方案查询/排序/专业组操作。
- Explore 只读分析在去掉不必要 `load_skill` 后已明显下降；后续重点转为减少工具内部生成和主模型最终组织的重复总结。
- 确认边界要和效果一起验收：只读分析不能保留会让下一句“确认”误执行的旧方案 pending。
- 性能 benchmark 必须保留人工抽样看全文；本次即发现“偏好摘要只展示前三项，但示例命中隐藏偏好”的效果问题，已通过截断提示修复。

## 7. 落地顺序

### Phase 0：补齐观测

目标：

- benchmark 输出记录 tool call、actionFamily、resultKind、LLM request/token。
- `conversation_turn_event` 增加 routeDecision 和 tool duration。
- 保持功能逻辑不变。

验收：

- 当前 11 个 case 仍全部通过。
- 能直接看出每个慢 case 的慢点在 LLM、工具还是后端接口。

实施记录：

- `conversation_turn_event` 已补充 `routeDecision`、`llmRequests`、`inputTokens`、`outputTokens`、`totalTokens`、`toolCallCount` 和结构化 `toolCalls` 摘要。
- direct pending plan / direct pending intent / no pending confirm guard 都明确记录 `llmRequests=0`，方便和 full-agent 路径区分。
- full-agent 路径的 `toolCalls` 会从工具调用和工具返回中提取 `actionFamily`、`stage`、`resultKind`、`applied`、`messageCode` 等字段。
- `dialog_regression_runner.py` 的 metrics 输出已增加 `turnObservability`，从本地 SQLite 历史中解析本轮 tool call、tool return、action family 和 result kind；不改变 WebSocket 协议，也不影响前端。
- 当前 runner 侧还不能直接拿到服务端 `RunUsage` token 数据；token/请求数以服务端 `conversation_turn_event` 为准，runner 负责补齐每步动作路径和工具结果。

### Phase 1：Plan 高置信快路径

目标：

- 接管 `query_state`、数字移动、专业组数字移动、排序、审查。
- 复用 `execute_plan_action`，保留 preview/pending/confirm。

验收：

- 专业模式、专业组模式均通过 preview -> confirm -> apply。
- 快路径命中时 `routingPath=plan_fast_route`。
- 无内部字段泄露。
- 工作台联动卡片行为不回退。

实施记录：

- 新增 `app.resolver.plan_fast_router`，只识别高置信 Plan 请求：
  - 方案状态查看：`query_state`
  - 数字志愿移动：`move_unit preview`
  - 数字专业组移动：`move_ordered_unit preview`
  - 数字志愿/专业组删除：`remove_units / remove_ordered_unit preview`
  - 指定维度排序：`sort_ordered_plan preview`
  - 显式方案审查：`review_plan`
- service 层在已有 planning summary 时启用快路径；如果规划状态取不到或快路径不命中，仍回完整 ChatAgent。
- 快路径不生成模板回复，命中后仍调用 `_plan_next_action_model -> execute_plan_action`，并把工具调用/返回写入 SQLite 历史，保证 pending 确认、审计和 benchmark 解析仍可用。
- 快路径日志 `routingPath=plan_fast_route`，并记录 `llmRequests=0`、tool 耗时、actionFamily、resultKind 和 applied 状态。
- 名称/简称类操作暂不接管，例如“把广西师大统计改到第3位”仍回完整 Agent + 执行层唯一性解析，避免误匹配。

真实 e2e 复测记录（2026-05-24，本地 Agent + 当前 SiliconFlow/Kimi-K2.6 配置）：

| 场景 | 结果 | 观测 |
| --- | --- | --- |
| 方案状态查看 | 内容通过 | `routingPath=plan_fast_route`，`llmRequests=0`，服务端 turn 约 0.6s；runner 端到端约 10.8s，包含 WebSocket/本地环境等待开销 |
| 单志愿移动 preview | 内容通过 | `routingPath=plan_fast_route`，`llmRequests=0`，runner 约 3.5s |
| 单志愿移动确认 | 内容通过 | `direct_pending_plan_confirm`，`llmRequests=0`，runner 约 12.2s；慢点在后端移动和复审 |
| 专业组移动 preview | 内容通过 | `routingPath=plan_fast_route`，`llmRequests=0`，runner 约 15.3s；服务端工具约 2.2s，剩余为本地端到端等待 |
| 专业组移动确认 | 内容通过但性能阈值失败 | `direct_pending_plan_confirm`，`llmRequests=0`，runner 约 32.7s；慢点是后端专业组移动接口，不是模型 |
| 体制内/稳定就业承接分析 | 内容通过但慢 | runner 约 149.8s；实际进入 Explore 主模型 + 职业方向 slot LLM + 方向分析 LLM + 最终组织 |
| 学校局部只读查询 | 内容通过但慢 | runner 约 58.8s；进入 `query_volunteer_plan` 后仍需主模型最终组织 |
| 专业对比只读分析 | 内容通过 | runner 约 56.6s；仍触发 `analyze_current_major_interest`，说明专业对比与专业适配边界还需收紧 |
| Intent preview / 影响分析 | 内容通过但慢 | 首轮约 17.7s；“先不确认，看看影响”约 60.9s |

结论：

- Phase 1 已解决明确 Plan 动作被主模型反复试工具的问题，确认/预览边界保持正确。
- 当前最大慢点已从 Plan 路由转移到 Explore 内部多次 LLM 和部分后端变更接口。
- 专业组移动确认超过 20s 的问题不应继续归咎于模型；需要后端专业组移动接口或异步复审/状态刷新策略继续优化。

Phase 2 首轮复测记录：

| 场景 | 结果 | 观测 |
| --- | --- | --- |
| 体制内/稳定就业承接分析 | 约 43.0s | `resolve_career_direction_slots` 本地命中 `system_public_service + stable_employment`；内部方向生成 10s 超时后 fallback；主路径为 2 次主 LLM + 1 个 `analyze_current_career_direction`，不再追加 `plan_next_action(query_state)` |
| 专业对比只读分析（无分数画像会话） | 约 24.5s | 命中 `compare_majors`，不再调用 `analyze_current_major_interest`；权重接口 404 时退回通用维度比较，不再输出“空指标等分” |

### Phase 2：Explore / Intent 减重

目标：

- 职业有限 taxonomy 本地规范化。
- 明确专业对比直达 compare。
- Intent 明确结构入参时跳过重复抽取。

验收：

- “只分析不要记偏好”不生成 pending intent。
- “我倾向 A，但 B 不要”仍生成确认预览。
- 职业和专业对比耗时明显下降，结构化内容不变薄。

实施记录（首轮）：

- `resolve_career_direction_slots` 增加有限 taxonomy 本地归一化：体制内/考公/考编/公务员/事业单位、稳定就业/求稳/抗风险、读研/考研/保研/深造等明确表达直接解析为 career slots，不再为这些常见表达额外调用 slot 识别 LLM。
- 职业方向分析内部生成 LLM 增加 10s 短超时；超时后使用已有结构化事实与 fallback 分析交给主模型组织，避免单个内部润色调用拖到 100s 以上。
- `tool_dispatch_rules` 和 `major_chat / explore_chat` skill 收紧专业对比边界：两个具体专业的只读对比优先 `compare_majors / compare_majors_adhoc`，不要先走 `analyze_current_major_interest` 或 Intent 确认链。
- `tool_dispatch_rules` 明确 Explore 工具已经承接当前方案/候选分析，同一轮调用后不再补调 `plan_next_action(query_state)` 或 `query_volunteer_plan` 做重复状态查询。
- `tool_dispatch_rules` 明确专用 Explore 工具可承接时不要先调用 `load_skill`；`load_skill` 只在没有明显专用工具或需要补充领域解释框架时使用。真实复跑中职业承接场景从 `load_skill + analyze_current_career_direction` 收敛为单个专用工具，端到端约 26.3s。
- `compare_majors / compare_majors_adhoc` 增加缺失量化权重兜底：当会话没有分数画像或权重接口返回空数据时，不再用 0 值生成“综合得分相同”这类误导性结论，而是退回通用维度比较提示。
- 仍保留开放式 Explore 主模型组织能力，没有新增面向用户的模板回复，也没有绕过只读/确认边界。

遗留：

- `compare_majors` 工具自身仍会调用一次 LLM 生成对比摘要，主 Agent 还会做最终组织；后续可评估把工具返回改为结构化 facts，减少一次重复总结。
- 学校/专业局部查询仍主要慢在主模型最终组织，后续可考虑只读查询的结构化 answer renderer。
- 专业组移动确认慢点不在大模型。当前确认链路是 `direct_pending_plan_confirm -> execute_plan_action(apply) -> _resolve_ordered_unit_ids -> POST /inner/planning/{tenantId}/session/ordered-plan/unit/move -> workspace refresh ordered/review`；后端 `moveOrderedUnit` 会重排整组、重建 `orderedPlanState.units`、重算 summary、标记 `staleFlags.review=true / planAdjustment=true`、记录行为事件并保存状态，但不会显式调用 `runReview`。因此 30s+ 的慢点应继续定位在后端状态重建/保存/响应体大小或本地服务等待，不应再按 LLM 优化处理。

### Phase 2.5：专业组确认慢点定位与轻量响应设计

目标：

- 先确认专业组移动确认的真实耗时分布：Agent 内部定位、后端 `unit/move`、后端状态重建/保存、WebSocket followup 哪一段最慢。
- 在不改变用户可见行为的前提下，减少确认 apply 返回前不必要的重状态构建和大响应传输。
- 保持“执行后方案进入待重新审查，前端引导审查”的语义，不在确认链路里同步跑完整审查。

当前调用链：

```text
用户确认
  -> ChatService direct_pending_plan_confirm
     -> execute_plan_action(apply)
        -> _move_ordered_unit
           -> _resolve_ordered_unit_ids
              -> GET planning state
           -> POST /ordered-plan/unit/move
              -> PlanningStateService.moveOrderedUnit
                 -> loadPlanningState
                 -> buildOrderedUnitIds / regroup ordered items
                 -> resolveEffectiveCandidates(refreshOverlayIfNeeded=false)
                 -> buildOrderedUnitsFromOrderedItems
                 -> recalculateOrderedSummary
                 -> staleFlags.review = true
                 -> staleFlags.planAdjustment = true
                 -> appendUnitBehaviorEvent
                 -> saveOrderedState
           -> return OrderedPlanActionRes
     -> emit ordered/review workspace refresh
```

判断：

- 该链路已经是 `llmRequests=0`，继续压 prompt 或换模型不能解决确认慢。
- 后端没有同步 `runReview`，但会同步返回 `OrderedPlanActionRes`，其中包含完整 `orderedPlanState`。而 Agent 回复只需要成功/失败、message、version/stale flags；真正的方案刷新会由 followup 触发前端重新拉取。
- Agent 当前在执行后还会再次 `_resolve_ordered_unit_ids` 用于 `executed_actions` 记录，可改为复用执行前已解析出的 unitIds，但这只是小优化，不能单独解释 30s+。

设计方案：

1. 先补耗时埋点，不直接改业务结果：
   - Agent `_move_ordered_unit / _remove_ordered_units` 记录 `resolveUnitDurationMs`、`mutationRequestDurationMs`、`postResolveDurationMs`。
   - 后端 `moveOrderedUnit / removeOrderedUnits` 记录 load、resolve candidates、build units、save、response build 各段耗时。
2. 再考虑轻量响应：
   - 新增或扩展内部 mutation endpoint 支持 `responseMode=summary`。
   - summary 模式只返回 `sessionId/version/phase/staleFlags/message/affectedUnitIds`，不返回完整 `orderedPlanState`。
   - Agent apply 成功后仍发送 `workspace_refresh_targets=["ordered","review"]`，由前端按既有流程刷新方案和审查状态。
3. 保留状态语义：
   - 移动/删除/排序后只标记 `review` stale，不同步跑审查。
   - 用户侧文案保持“方案已更新，建议审查/待重新审查”，不显示旧审查异常。

验收：

- 专业组移动确认仍完成 apply，返回成功文案并刷新方案。
- `conversation_turn_event` 显示 `routingPath=direct_pending_plan_confirm`、`llmRequests=0`。
- 后端耗时日志能定位瓶颈段。
- summary 响应模式下，专业组移动确认 p95 目标降到 8s 内；如果仍超过，继续看后端状态文件/数据库保存和候选池规模。

实施记录（首轮）：

- Agent `_move_ordered_unit / _remove_ordered_units` 增加 `plan_ordered_unit_mutation_timing` 结构化事件，记录 `resolveUnitDurationMs`、`mutationRequestDurationMs`、`totalDurationMs`、`unitIds`、`targetPosition` 和成功/失败原因；apply 后为 `executed_actions` 再解析 unitIds 的步骤单独记录 `plan_ordered_unit_post_apply_timing.postResolveDurationMs`。
- Server `PlanningStateService.moveOrderedUnit / removeOrderedUnits` 增加 `planning_ordered_unit_move_timing / planning_ordered_unit_remove_timing` 分段日志，覆盖 load、单位定位、顺序重建、候选合成、units 重建、summary 重算、行为事件记录、保存和 total。
- 真实确认回归发现：专业组移动执行后如果再次按“第 N 个专业组”解析，会因为方案顺序已变而拿到另一个专业组，导致 `executed_actions` 和日志记录错误。已改为复用执行前解析出的 unitIds，`plan_ordered_unit_post_apply_timing` 记录 `reusedPreMutationUnitIds=true` 和 `postResolveDurationMs=0`。
- 当前不改变接口返回结构、不改变 `staleFlags.review=true` 语义、不新增同步审查。
- 下一步根据生产或本地复跑日志决定是否做 `responseMode=summary` 轻量响应；没有分段数据前不直接改后端执行路径。

真实复测记录：

| 场景 | 结果 |
| --- | --- |
| 专业组移动 preview | 通过，端到端约 4.6s；回复明确专业组名称、组内专业数、目标专业组位置和确认边界，没有内部字段。 |
| 专业组移动 confirm | 通过，端到端约 4.7s；`llmRequests=0`，`mutationRequestDurationMs≈1.5s`，`postResolveDurationMs=0`，`unitIds` 与执行前一致，发送 `ordered refresh=true`。 |

验证口径：

- Agent 日志中同一轮应同时看到：
  - `conversation_turn_event routingPath=direct_pending_plan_confirm llmRequests=0`
  - `plan_action_event actionFamily=move_ordered_unit/remove_ordered_unit stage=apply`
  - `plan_ordered_unit_mutation_timing status=success`
  - `plan_ordered_unit_post_apply_timing postResolveDurationMs=...`
- Server 日志中应看到：
  - `planning_ordered_unit_move_timing ... totalMs=...`
  - 或 `planning_ordered_unit_remove_timing ... totalMs=...`
- 如果 Agent `mutationRequestDurationMs` 明显大，而 Server `totalMs` 也大，瓶颈在后端状态处理。
- 如果 Server `totalMs` 小但 Agent `mutationRequestDurationMs` 大，优先检查 HTTP 调用、网络、响应体序列化/传输。
- 如果 `resolveUnitDurationMs` 大，优先检查 Agent 为定位第 N 个专业组而读取 planning state 的耗时。
- 如果 `postResolveDurationMs` 大，优先检查执行后重复定位 unitIds 的状态读取，并评估是否复用 apply 前已解析结果。
- 如果 Server `behaviorEventMs/saveMs` 大，优先检查行为事件存储或 planning state 持久化。

### Phase 3：ActionResolver 影子对比与灰度接管

目标：

- ActionResolver 输出 shadow log。
- 与真实 action_family 做差异分析。
- 对低风险动作启用接管。

验收：

- shadow mismatch 有统计。
- 低风险接管场景通过所有 regression。
- 不增加字符串模板回复。

实施记录（首轮）：

- `ActionResolver` 补齐结构化映射缺口：`verb=move + target.unit_refs` 映射为 `move_ordered_unit`，`verb=remove + target.unit_refs` 映射为 `remove_ordered_unit`；新增结构化 `verb=sort` 映射为 `sort_ordered_plan`。
- 新增 `action_resolver_shadow_from_plan_fast_decision`，只在 `plan_fast_route` 命中的高置信 Plan 场景生成影子解析结果，并输出 `action_resolver_shadow_event`。
- 影子日志记录 `actualActionFamily`、`shadowActionFamily`、`shadowStage`、`actionFamilyMatch`、`missingInputs` 和 `normalizationApplied`；该日志不改变真实执行路径、不影响 preview/confirm/apply。
- 首轮影子对比只覆盖 fast route 已明确的结构化动作：方案状态、数字志愿移动/删除、数字专业组移动/删除、排序、审查。名称/简称类动作仍由完整 Agent 和执行层唯一性解析处理。

### Phase 4：清理技术债

目标：

- 梳理 `plan_orchestration_tool.py` 中 deprecated keyword helper。
- 明确哪些保留为安全兜底，哪些迁移到 typed resolver。
- handler registry 逐步覆盖 mutation/review/compensation。

验收：

- 新能力不再接入 deprecated router。
- 旧兼容路径有测试保护，不能误删。

## 8. 风险与约束

### 8.1 误路由风险

快路径如果过度激进，可能把咨询问题误当成执行问题。因此必须满足：

- 只处理高置信结构。
- 命中 mutation 只能 preview，不能直接 apply。
- 低置信全部 fallback。

### 8.2 用户语言多样性

用户不一定按数字索引表达，也可能说：

- 把 XX 大学 XX 专业移到第几位。
- 把广西师大统计加进来。
- 去掉某学校某专业。

这些是 3.0.3 需要继续优化的方向，但第一阶段快路径不应为了覆盖简称而牺牲安全性。建议：

- 数字引用先走快路径。
- 名称/简称引用继续走执行层唯一性解析。
- 简称歧义必须澄清。

### 8.3 大模型输出质量

直接减少 LLM 次数可能让回复变硬。解决方式不是回到模板拼接，而是：

- 工具返回结构化 facts 和面向用户 summary。
- Renderer 做统一、自然、克制的表达。
- 开放式咨询仍保留大模型组织能力。

### 8.4 Provider 性能差异

切换更快 provider 可以改善单次请求耗时，但如果一轮仍有 5 到 6 次 LLM 请求，整体体验仍不稳定。因此：

- provider benchmark 要继续跑。
- 主优化仍是减少无意义请求数和 token。

## 9. 待确认决策

需要确认后再进入代码实现：

1. 是否同意 `3.0.3` 优先做 Agent 效果和性能，不再继续扩 UI 范围。
2. 是否同意先落 Phase 0 观测，再落 Phase 1 Plan 快路径。
3. 是否同意快路径只做结构化动作装配，不直接模板化回复。
4. 是否同意职业方向有限 taxonomy 可以本地规范化，开放式方向问题继续走 LLM。
5. 是否同意名称/简称类方案操作先保守处理：唯一命中才执行预览，歧义必须澄清。

确认后建议从 Phase 0 开始落地，先让每个慢 case 的 LLM 次数、tool 耗时和 action 路径可见，再进入 Plan 快路径改造。
