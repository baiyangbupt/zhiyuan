# Release 3.0.3 Agent Effect / Performance Deep Dive

本文记录 `3.0.3` 针对 Agent 效果和性能的专项分析、优化设计、实施记录和回归结果。

关联文档：

- `docs/release-3.0.2-routing-preview-action-review.md`
- `docs/release-3.0.2-implementation-design.md`
- `docs/release-3.0.1-agent-optimization-design.md`
- `docs/release-3.0.3-agent-response-quality-review.md`

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

### 6.0 Case 级评估框架与阶段性结果

3.0.3 已补充 case 级评估框架，不再只看“快不快”，而是同时记录：

- 完整回复文本
- thinking / progress 提示
- followup 工作台动作
- tool/action observability
- 首响与最终耗时
- 内容断言和延迟门禁

相关文件：

- `docs/release-3.0.3-agent-case-evaluation-framework.md`
- `docs/release-3.0.3-agent-case-evaluation-report-template.md`
- `docs/release-3.0.3-agent-case-evaluation-first-pass.md`
- `zhiyuan-agent/examples/dialog_case_evaluation_report.py`
- `zhiyuan-agent/examples/model_provider_303_quality_readonly_cases.json`

2026-05-25 当前实现质量补跑结果：

| case 集 | steps | failed | median | max |
| --- | ---: | ---: | ---: | ---: |
| `dialog_regression_303_effect_perf_cases.json` | 13 | 0 | 2.319s | 4.922s |

同一批只读/预览 case 的四模型对照：

| provider | steps | assertion failures | median final | max final |
| --- | ---: | ---: | ---: | ---: |
| siliconflow-kimi-k26 | 10 | 0 | 0.214s | 2.164s |
| siliconflow-minimax-m25 | 10 | 0 | 0.160s | 2.503s |
| siliconflow-deepseek-v4-flash | 10 | 0 | 0.176s | 2.368s |
| siliconflow-glm-51 | 10 | 0 | 0.155s | 2.339s |

结论和限制：

- Plan 快路径、只读查询、预览边界和 Intent preview 在四个模型配置下稳定。
- 这批 case 大多不依赖模型自由生成，因此不能用来判断开放式回复质量谁最好。
- 后续要补更开放的 Explore / Intent follow-up / 方案影响分析 case，才能真正比较模型表达质量。

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
| 表达自然 | 允许 Markdown 标题、分点和编号列表；需要避免的是强迫选择、固定菜单、系统播报、空洞模板和内部字段外露，而不是避免结构化本身。 |
| 边界明确 | 高副作用动作必须先 preview，说明“确认后才会执行”；确认前不得刷新方案，确认后才刷新 `ordered/review`。 |
| 只读不误联动 | “先只分析 / 不要改方案 / 不要记偏好”不得生成无意义工作台卡片或 pending intent。 |
| 歧义不误操作 | 学校/专业简称无法唯一定位时要澄清，不为了快而猜测并执行。 |
| 事实一致 | 执行类回复、`executed_actions`、工作台刷新对象和日志中的目标对象必须一致，尤其是专业组移动后不能按变化后的顺序重新解析目标。 |

当前 runner 用 `assertContains / assertContainsAny / assertNotContains / assertNoFollowups / assertFollowupTarget` 做自动质量门禁；`assertPlanStyle` 只拦截严重体验问题，例如强迫用户选 A/B、泄漏内部词、出现残句或无意义系统词，不拦截正常标题、分点和编号。真实效果仍需要抽样人工看完整文本，重点检查是否丰富、是否自然、是否能直接指导用户下一步。

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

补充定位记录（2026-05-24）：

- 慢例不是模型耗时：Agent 记录 `routingPath=direct_pending_plan_confirm`、`llmRequests=0`，耗时集中在 `mutationRequestDurationMs`。
- 同一慢例在 Server controller 日志中对应 `POST /inner/planning/1/session/ordered-plan/unit/move?chatSessionId=16`，接口从 `08:50:21.438` 到 `08:50:49.550`，总耗时 `28112ms`，与 Agent `mutationRequestDurationMs≈28127ms` 基本一致。
- 当时运行中的 8080 后端没有输出 `planning_ordered_unit_move_timing` service 分段日志，说明本机运行实例不是最新已编译代码，或者分段日志所在 class 未生效；因此该慢例只能定位到 controller 总耗时，无法拆出旧实例内部子步骤。
- 重新以当前源码启动后复现同一会话：
  - no-op 移动：controller `1294ms`，service `totalMs=1053`，主要是 `loadMs=1053`。
  - 真实移动 2 -> 3：controller `2626ms`，service `totalMs=2344`，其中 `loadMs=644`、`resolveCandidatesMs=25`、`buildUnitsMs=16`、`behaviorEventMs=111`、`saveMs=1541`。
  - 回移 3 -> 2：controller `2101ms`，service `totalMs=1827`，其中 `loadMs=501`、`resolveCandidatesMs=10`、`buildUnitsMs=3`、`behaviorEventMs=182`、`saveMs=1130`。
- `sessionId=16` 的完整 planning state 响应体约 `19.1MB`，包含 `candidateItems=6421`、`overlayItems=6421`、`orderedItems=176`、`orderedUnits=45`；当前 mutation 会保存完整 `PlanningStateDTO` JSON，常态下 `saveMs` 已是最大头。
- 历史日志里 `unit/move` 大多在 `1.3s - 2.3s`，但 `2026-05-24 01:36` 和 `08:50` 各出现一次约 `28s` outlier；因此当前判断是“大状态保存/DB 写入/旧运行实例状态”导致的偶发慢请求，不是稳定的算法计算慢，也不是 LLM 慢。

后续优化设计结论：

- `responseMode=summary` 只能减少返回体和 Agent 反序列化成本，无法解决 `savePlanningState` 保存完整 19MB 状态的根因；仍可作为轻量响应优化，但优先级低于状态持久化拆分。
- 真正的性能优化方向是把高频 mutation 的写入粒度从完整 `PlanningStateDTO` 缩小到方案相关状态，例如独立持久化 `orderedPlanState`、`staleFlags`、`version/phase` 和行为事件，候选池与 overlay 不随每次移动/删除/排序反复重写。
- 在拆分持久化前，必须保留当前分段日志，并把 `saveMs/loadMs/controllerMs` 纳入 e2e 性能回归；如果再出现 20s+ 慢例，优先看 service `saveMs` 是否同步放大。

### Phase 2.6：方案高频操作轻量持久化设计

问题：

- 当前 `PlanningStateDTO` 是聚合状态，`candidatePoolState.items` 和 `recommendationOverlayState.items` 都在同一个 `planningState` JSON 内。
- `moveOrderedItem / moveOrderedUnit / removeOrderedUnits / sortOrderedPlan` 这类高频方案操作只改变排序方案、少量 draft 兼容字段、`staleFlags` 和 `version/phase`，但仍通过 `saveOrderedState -> savePlanningState` 重写完整状态。
- 在 `sessionId=16` 这类候选池较大的专业组会话中，完整状态约 19MB；常态 `saveMs` 已是最大头，偶发情况下会放大到 20s+。

设计选择：

1. 不在首轮直接拆历史 `planningState` 主数据，也不迁移老会话。
2. 新增一个小的 `ChatSessionExtraData` dataKey，例如 `planningMutableState`，保存高频可变部分：
   - `version`
   - `phase`
   - `staleFlags`
   - `draftPlanState`（仅保留当前仍需要同步的兼容字段）
   - `orderedPlanState`
   - `updatedAt`
3. `loadPlanningState` 仍先读取原 `planningState`，完成历史兼容和字段补齐后，再读取 `planningMutableState` 并按版本覆盖：
   - `mutable.version >= base.version` 时应用 mutable。
   - `mutable.version < base.version` 时忽略，避免老 overlay 覆盖后续完整保存的新状态。
4. 高频方案操作使用新的 `saveOrderedMutableState`：
   - 只更新 `planningMutableState`，不再重写 19MB 的完整 `planningState`。
   - 仍递增 `version`，仍设置 `phase=ordered`，仍设置 `staleFlags.review=true / planAdjustment=true`。
   - 行为事件继续写 `planning_behavior_event`，不退回到 DTO 内嵌事件。
5. 方案生成、候选池生成、审查、补偿、历史迁移导入和其他会改变大状态的流程，首轮继续使用完整 `savePlanningState`，避免扩大影响面。

首轮覆盖范围：

| 操作 | 是否纳入轻量持久化 | 原因 |
| --- | --- | --- |
| 单志愿移动 `moveOrderedItem` | 是 | 高频、只改方案顺序和行为事件 |
| 专业组移动 `moveOrderedUnit` | 是 | 本次慢例对应路径 |
| 专业组删除 `removeOrderedUnits` | 是 | 高频、会同步 draft 兼容字段，需要一并写入 mutable |
| 方案排序 `sortOrderedPlan` | 是 | 高频、可由前端和对话触发 |
| pin/unpin 接口 | 暂不动 | 新版用户侧已关闭，降低改动面 |
| `generateOrderedPlan / generateInitialPlan / reorderDraftPlan` | 暂不动 | 涉及生成元数据、候选池和自动补全语义，继续完整保存 |
| `runReview / compensation` | 暂不动 | 审查和补偿会写 review/adjustment 等状态，后续单独拆 |

实现要点：

- 新增 DTO：`PlanningMutableStateDTO`，不要复用完整 `PlanningStateDTO`，避免误把候选池继续带进去。
- 新增常量：`ChatSessionExtraDataConstants.PLANNING_MUTABLE_STATE_KEY`。
- 新增方法：
  - `applyPlanningMutableState(chatSessionId, state)`
  - `savePlanningMutableState(chatSessionId, state)`
  - `saveOrderedMutableState(chatSessionId, state)`
- `saveOrderedMutableState` 需要和现有 `saveOrderedState` 保持同样的状态语义，只替换持久化目标。
- `buildOrderedPlanActionRes` 不变，调用方拿到的是已叠加 mutable 后的 `state`。

风险与边界：

- 如果某个完整状态保存流程没有先 `loadPlanningState`，可能会覆盖 mutable；当前主要流程都从 `loadPlanningState` 进入，首轮测试要覆盖。
- 如果 mutable 版本比较规则处理不好，可能出现旧 overlay 覆盖新完整状态；必须用版本守护。
- 该方案先减少写入体积，但仍会读取并解析完整 `planningState`，因此只能解决 `saveMs` 和大 JSON 写入 outlier，不能完全解决 `loadMs`。后续如果 load 仍慢，再拆 `candidatePoolState / recommendationOverlayState`。

测试计划：

- Unit：
  - `moveOrderedUnit` 后只更新 `planningMutableState`，不更新 `planningState`。
  - 再次 `getPlanningState` 能看到移动后的 `orderedPlanState`。
  - `removeOrderedUnits` 后 ordered 和 draft 都能从 mutable 恢复。
  - `sortOrderedPlan` 后排序结果、`staleFlags.review`、行为事件不变。
  - `mutable.version < base.version` 时不覆盖 base。
  - 老会话没有 `planningMutableState` 时行为不变。
- Backend focused test：
  - `PlanningStateServiceTest` 覆盖专业+大学和院校专业组两种模式。
  - 行为事件 `plan_item_move / plan_unit_move / plan_unit_remove / plan_sort_apply` 仍写入新表。
- E2E：
  - 对话触发专业组移动 preview -> confirm。
  - 前端手动排序/移动后方案刷新和审查待重新审查状态不回退。
  - 导出仍读取最新排序方案。
- 性能：
  - 保留 `planning_ordered_unit_move_timing`，新增或复用 `saveMs` 观察。
  - 目标：专业组移动常态 `saveMs < 300ms`，controller p95 先压到 `5s` 内；如果仍超时，再看 load 和 DB 连接。

实现记录（2026-05-24）：

- 已新增 `planningMutableState` 轻量 overlay，字段包含 `version / phase / staleFlags / draftPlanState / orderedPlanState / updatedAt`。
- `loadPlanningState` 在读取并补齐完整 `planningState` 后叠加 mutable；当 `mutable.version < base.version` 时忽略旧 overlay，避免旧可变状态覆盖新的完整保存结果。
- 首轮已将 `moveOrderedItem / moveOrderedUnit / removeOrderedUnits / sortOrderedPlan` 切到 `saveOrderedMutableState`，这些高频方案调整不再重写候选池和推荐 overlay。
- `generateOrderedPlan / pinOrderedItem / unpinOrderedItem / review / compensation` 仍保持完整保存，避免一次性扩大审查、补偿和生成链路影响面。
- Unit 覆盖了专业+大学模式单志愿移动、院校专业组模式组删除、旧 mutable 版本忽略，以及既有移动/pin/导出/行为事件回归。
- 已验证：
  - `mvn -Dtest=PlanningStateServiceTest test`：99 tests，0 failure / 0 error，2 skipped。
  - `mvn -Dtest=PlanningStateServiceTest,PlanningBehaviorEventSharedServiceTest test`：100 tests，0 failure / 0 error，2 skipped。

真实 e2e 复测记录（2026-05-24）：

- 命令：
  - `RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_mutable_overlay_e2e.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`
- 结果：8 steps 全部通过，pytest 总耗时 `82.50s`，效果断言与确认边界断言均通过。
- 专业组移动确认链路：
  - preview：端到端 `4816ms`，`routingPath=plan_fast_route`，`llmRequests=0`。
  - confirm：端到端 `3789ms`，`routingPath=direct_pending_plan_confirm`，`llmRequests=0`，返回 `planningWorkspaceAction target=ordered refresh=true`。
  - Agent 分段：`mutationRequestDurationMs=538ms`，`totalDurationMs=1215ms`，`postResolveDurationMs=0`。
  - 对比前次失败样本：confirm 从约 `32703ms` 回落到 `3789ms`，慢点不再集中在后端 mutation request。
- 本地 DB 验证：
  - `sessionId=16 planningMutableState` 长度约 `119681` 字符。
  - `sessionId=16 planningState` 长度约 `16015932` 字符。
  - 说明本次移动已写入小状态，未重写完整候选池/推荐 overlay。
- 仍需继续优化的性能点：
  - `体制内稳定就业承接分析` 端到端 `32346ms`，走 full agent，`llmRequests=2`，其中方向分析内容生成有 10s timeout 后回退，但整体回复质量可接受。
  - `法学和财政学对比` 端到端 `30430ms`，走 full agent，`llmRequests=2`，内容结构完整；本地 session `880101` 无成绩画像，权重接口 404 后已走通用兜底。
  - 后续性能重点从 mutation 后端写入转向只读 Explore/专业对比的 LLM 调用次数、上下文长度和工具结果复用。

### Phase 2.7：Explore 内层生成减重

问题：

- 职业方向 Explore 现在有两层生成：工具内部先用 `_generate_direction_analysis_content / _generate_generic_direction_analysis_content` 生成一版分析草稿，随后 ChatAgent 主模型还会基于工具结果再组织最终回复。
- 真实 e2e 中 `体制内稳定就业承接分析` 已经收敛到单个专用工具，但工具内部生成仍会触发 10s timeout，再进入主模型最终组织，导致只读问题仍接近 30s。
- 这类工具内部生成不是唯一事实来源，事实已经来自 `student_fit_fact / direction_facts / planningState / candidatePool`；保留主模型最终组织即可继续保证回复自然度。

实现决策：

- `RequestContext` 新增 `allow_explore_inner_llm`，默认 `True`，保证直接调用工具和既有单测仍按原行为运行。
- `ChatService` 创建正式对话上下文时设置 `allow_explore_inner_llm=False`，只关闭真实聊天主链路中的 Explore 内层草稿生成。
- `preview_direction_analysis_from_request / preview_generic_direction_analysis_from_request / preview_direction_comparison_from_request` 在该开关关闭时跳过内部 LLM，直接返回结构化事实 fallback，由 ChatAgent 主模型继续生成用户可读回复。

影响边界：

- 不新增字符串模板匹配，不绕过 ChatAgent 主模型，也不改变只读/确认/pending 边界。
- 不影响 `resolve_career_direction_slots` 的本地 taxonomy 命中逻辑，也不影响专业对比 `compare_majors`。
- 后续如果要进一步压低 `法学和财政学对比` 这类只读专业对比耗时，应单独设计只读 answer renderer 或专业对比快路径，不能把专业简称识别强行做成低置信短路。

验证记录：

- 语法检查：`zhiyuan-agent/.venv/bin/python -m py_compile zhiyuan-agent/app/tools/explore_direction_tool.py zhiyuan-agent/app/agent/context.py zhiyuan-agent/app/service.py` 通过。
- 单测：
  - `tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_intent_state_tool.py`：139 passed。
  - `tests/unit/test_major_compare_tool.py`：1 passed。
- 真实 e2e：
  - 命令：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_explore_inner_llm_off_e2e.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`
  - 结果：8 steps 全部通过，pytest 总耗时 `84.72s`。
  - `体制内稳定就业承接分析`：端到端 `28578ms`，`llmRequests=2`，工具调用仍为 `analyze_current_career_direction`；日志确认 `Skip direction comparison inner LLM generation`，没有再触发 Explore 工具内部 10s 生成超时，回复仍包含基础条件、方案承接、候选机会和下一步。
  - `法学和财政学对比`：端到端 `36715ms`，`llmRequests=2`，慢点主要来自主 Agent 两次模型调用；当前工具因 session 缺少分数画像走通用兜底，后续要优化应设计专业对比只读 renderer 或快路径，不应混入本次职业方向开关。

### Phase 2.8：专业对比只读快路由设计

问题：

- `法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好` 已经能正确命中 `compare_majors`，但仍走完整 ChatAgent：第一次主模型选择工具，第二次主模型读取工具结果并组织回复。
- 真实 e2e 中该轮 `inputTokens≈19533`、`llmRequests=2`、端到端约 `36.7s`。慢点不是专业权重接口，主要是完整工具清单/系统指令下的两次主模型请求。
- 当前 session `880101` 没有分数画像，`compare_majors` 走缺失权重兜底；如果直接返回工具兜底文本，会变成“请做通用维度比较”的内部提示，不适合作为最终用户回复。

路由边界：

- 只处理明确的两个标准三级专业名同时出现，且句子包含比较/选择语义的只读问题，例如 `法学和财政学哪个更适合...`。
- 不处理专业类、简称和歧义表达，例如 `计算机和电子信息怎么选`、`计科和软工`、三个及以上专业对比；这些继续走 ChatAgent，由模型和专业规范化工具处理。若某个名称同时是一级门类和三级专业（如“法学”），只有在它也是三级专业目录精确项、且仅用于只读对比时才可命中，不能写入意向或改方案。
- 如果用户表达包含“记偏好/加入偏好/按这个改方案/加进方案/删除/移动/排序”等意向写入或方案变更语义，不能进入只读快路由。

实现方案：

- 新增 `major_compare_fast_router`，基于本地本科/专科三级专业目录做精确识别；命中时返回 `major_name1 / major_name2` 和 routeDecision。
- ChatService 在 Plan fast route 之前、完整 ChatAgent 之前检查该路由；命中后直接调用 `compare_majors(SimpleNamespace(deps=request_context), major1, major2)`。
- 如果工具返回的是可直接面向用户的个性化对比，直接做轻量清理后返回。
- 如果工具返回缺失权重兜底，不再调用无工具小 Agent；改用受控的用户态领域 renderer，把“缺少个性化量化评分”的事实、当前学生基础信息和两个专业所属专业类画像组织成可读回复。原因是首轮实现虽命中快路由，但该小 Agent 真实 e2e 耗时约 `96.7s`，仍然会放大远端模型延迟。
- renderer 不能按具体 pair 写死，例如不能只单独实现 `法学 vs 财政学`。实现上应先由三级专业映射到专业类，再复用专业类画像；未覆盖专业类走统一通用比较框架，避免把 e2e 样例变成不可维护的特殊规则。
- 当前不是手写覆盖全部 90+ 专业类画像，而是“精选专业类画像 + 全量通用 fallback”：本科 `93` 个专业类、专科 `97` 个专业类均应能生成非空用户回复；只有已沉淀画像的专业类会输出更具体的路径/门槛/稳定性/试错成本。
- 历史记录仍写入 `ModelRequest -> ToolCallPart(compare_majors) -> ToolReturnPart -> ModelResponse`，保持可追溯；不会产生 pending，也不会发送工作台卡片。

验收：

- 单测覆盖：标准专业名命中、专业类/简称不命中、意向写入或方案变更不命中、ChatService 命中快路由时不调用主 ChatAgent，缺权重兜底时也不调用额外 LLM。
- 单测覆盖所有本科/专科专业类代表专业，验证差异化画像未覆盖时仍走通用 fallback，且不泄漏“请只做”等工具内部提示。
- e2e 复跑：`303-quality-major-compare-readonly-no-intent` 仍无 followup、无 pending 文案，内容包含两个专业、适合/就业/方向等结构化判断；目标从 `36s+` 降到一次工具调用加本地 renderer。

首轮实现复盘：

- `major_compare_fast_route` 已命中，`compare_majors` 工具耗时约 `40ms`，但缺权重分支的无工具小 Agent 生成耗时约 `96683ms`，导致该轮总耗时约 `99530ms`。
- 结论：对“工具已经明确返回缺个性化量化权重”的已知业务态，不适合再依赖模型生成最终文案；该分支应使用稳定 renderer。它不是入口字符串模板兜底，不负责识别用户意图，也不会绕过专业名目录校验和 `compare_majors` 工具，只负责把工具结果中的缺权重状态转换成用户能理解的对比建议。renderer 已从单个专业组合修正为专业类画像驱动，避免只覆盖 `法学/财政学` 一个样例。

验证记录：

- 单测：
  - `tests/unit/test_major_compare_fast_router.py tests/unit/test_major_compare_tool.py tests/unit/test_compare_resolution.py`：8 passed。
  - `tests/unit/test_major_compare_reply_renderer.py tests/unit/test_dialog_regression_runner.py` 及 ChatService 专业对比/Plan fast route 聚焦用例：31 passed；其中 renderer 覆盖本科 `93` 个、专科 `97` 个专业类代表专业的通用 fallback。
- 真实 e2e：
  - 命令：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_major_compare_category_renderer_e2e.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`
  - 结果：8 steps 全部通过，pytest 总耗时 `38.26s`。
  - `法学和财政学对比`：端到端 `2316ms`，`followupMessages=0`，`toolCallCount=1`，`toolReturnCount=1`，历史工具为 `compare_majors`；Agent 日志确认 `routingPath=major_compare_fast_route`、`llmRequests=0`、`toolDurationMs=10ms`、`postProcessingApplied=["missing_weight_major_compare_renderer"]`。回复已按专业类画像输出 `法学（法学类）` 和 `财政学（财政学类）`，不是具体 pair 专属分支。
  - 当前最慢项仍是 `体制内稳定就业承接分析`：端到端 `18367ms`，走 full Agent + `analyze_current_career_direction`，属于后续 Explore 只读回复继续压缩范围，不混入本次专业对比快路由。

### Phase 2.9：职业方向只读分析快路由设计

现状链路：

```text
用户问“当前方案对体制内稳定就业方向承接得怎么样，先不要改方案”
  -> ChatService 构造完整 RequestContext
  -> 完整 ChatAgent 第一次 LLM 判断应该调用 analyze_current_career_direction
  -> analyze_current_career_direction 读取最后一句用户话术
  -> resolve_career_direction_slots 本地命中 system_public_service + stable_employment
  -> preview_direction_comparison_from_request 读取 planning state，统计当前方案和候选承接数量
  -> 工具返回“分析结论 / 当前判断 / 下一步”的分段文本
  -> 完整 ChatAgent 第二次 LLM 读取工具结果并组织最终回复
```

问题：

- Phase 2.7 已关闭真实聊天主链路里的 Explore 内层草稿生成，职业方向 slot 也能本地命中，工具内部不再额外调用方向分析 LLM。
- 真实 e2e 中该场景仍约 `18s`，日志显示 `routingPath=full_agent`、`llmRequests=2`、工具为 `analyze_current_career_direction`。当前慢点主要是完整 Agent 两次远端模型调用和大上下文，而不是职业方向事实计算。
- `preview_direction_analysis_from_request / preview_direction_comparison_from_request` 已经返回用户可读分段文本，不是内部 JSON 或“请生成”的中间提示；对明确只读问题，可以复用这份工具结果，减少一次“选工具”和一次“复述工具结果”的模型调用。

路由边界：

- 只处理显式只读的职业方向承接/适配分析问题，且职业方向必须能被本地 taxonomy 解析，例如：体制内、考公考编、公务员/事业单位、稳定就业、求稳、读研/考研/深造等。
- 必须排除意向写入或方案变更语义，例如：`记下来`、`作为偏好`、`以后优先`、`按这个改方案`、`加入方案`、`删除`、`移动`、`排序`、`确认`。这些继续走完整 Agent 和现有 pending/确认链路。
- 不处理开放式职业探索问题，例如“我适合什么方向”“以后走哪条路”。这类问题仍可能需要完整模型结合上下文做探索式组织。
- 不新增入口级字符串模板回复。快路由只做高置信路由判断，最终事实仍来自现有 `analyze_current_career_direction` / `preview_direction_*` 工具链。

实现方案：

- 新增职业方向只读 fast router，职责仅判断“是否为高置信只读职业方向分析”，并返回本地解析出的 direction slots 与 routeDecision。
- ChatService 在 plan fast route、major compare fast route 之后、完整 ChatAgent 之前检查该路由；命中后直接调用 `analyze_current_career_direction(SimpleNamespace(deps=request_context))`。
- 返回文本继续走现有用户态清理：`_normalize_user_facing_terms` 和 `_sanitize_reply_for_user`，避免暴露内部词，但不再调用 LLM 复述。
- 历史记录写入 `ModelRequest -> ToolCallPart(analyze_current_career_direction) -> ToolReturnPart -> ModelResponse`，保持工具调用可追溯；不创建 pending，不发送 workspace card，不修改偏好或方案。
- 日志记录 `routingPath=career_direction_fast_route`、`scene=explore`、`llmRequests=0`、`toolCallCount=1`、`toolDurationMs`、`directionSlots`，便于和 full Agent 路径对比。

验证计划：

- 单测：
  - 命中：`当前方案对体制内稳定就业方向承接得怎么样，先不要改方案`。
  - 不命中：`以后优先按体制内看`、`帮我记成偏好`、`按体制内方向调整方案`、`我适合什么方向`。
  - ChatService 命中后不调用主 ChatAgent，不产生 pending/followup workspace card，并保存工具 trace。
- 真实 e2e：
  - 复跑 `303-quality-career-fit-readonly-no-workspace`，预期仍保留学生情况、当前方案承接、候选机会、下一步等内容。
  - 观测 `routingPath=career_direction_fast_route`、`llmRequests=0`、无 pending、无 workspace card。
  - 与 Phase 2.8 专业对比快路由一起回归，确认 plan mutation、intent confirm、major compare 不受影响。

首轮实现：

- `app.domain.career_slots` 抽出公共本地 taxonomy：体制内/考公考编、公务员/事业单位、稳定就业/求稳、读研/考研/深造等关键词统一由 `resolve_career_slots_locally` 解析。Explore 原工具继续复用同一套解析逻辑，避免 fast router 和工具各维护一份词表。
- 新增 `career_direction_fast_router`，仅做高置信只读路由判断。它不生成回复、不写偏好、不改方案；如果命中意向写入、方案变更、确认或泛方向问题，直接不匹配。
- `ChatService` 在专业对比 fast route 之后、完整 ChatAgent 之前接入 `career_direction_fast_route`。命中后直接调用 `analyze_current_career_direction`，保留 `ToolCallPart / ToolReturnPart / ModelResponse` 历史 trace，并记录 `conversation_turn_event routingPath=career_direction_fast_route llmRequests=0`。

验证记录：

- 编译检查：`app/domain/career_slots.py app/tools/explore_direction_tool.py app/resolver/career_direction_fast_router.py app/service.py` 通过 `py_compile`。
- 聚焦单测：`test_career_direction_fast_router.py`、`test_major_compare_fast_router.py`、`test_plan_fast_router.py`、`test_career_slots.py`、`test_explore_direction_scenarios_sync.py` 及 ChatService 三条 fast route 用例：`31 passed`。
- ChatService 主链路回归：`tests/unit/test_chat_service_history_persistence.py`：`103 passed`，覆盖 pending、确认保护、runtime history 和 fast route 历史 trace。
- `git diff --check` 通过。
- 真实 WebSocket e2e：
  - 全量 3.0.3 effect/perf：`tests/e2e/test_agent_dialog_effect_perf.py` 8 steps 通过，总耗时 `25.79s`；职业方向轮 `elapsedMs=2275`，无 followup card，确认轮进入 no-pending guard。
  - 职业方向去重后单场景复跑：2 steps 通过；职业方向轮 `elapsedMs=5572`，Agent 结构化日志为 `routingPath=career_direction_fast_route`、`llmRequests=0`、`toolDurationMs=55ms`、`directionSlots=["system_public_service","stable_employment"]`；回复不再重复输出相同选科/分数段判断。

### Phase 2.10：Intent / Plan 多步提示与对话稳定感设计

问题：

- 3.0.3 已经把部分 Plan / Explore 场景压到 fast route，但 fast route 绕过完整 ChatAgent 后，也绕过了工具调用前的统一 progress hint。用户在“读取状态 -> 生成预览 -> 等确认”这类链路里，容易只看到短暂空白，不清楚系统正在平稳处理。
- Intent 确认和 Plan 确认虽然已经是直达执行链路，但确认后如果后端耗时略长，用户没有明确提示“正在按你的确认更新”，容易误以为卡住。
- 现有工具级 progress hint 里有一些抽象表述，例如“判断该先查看、分析还是调整方案”，用户能理解但不够贴近当前动作；需要改成更产品化的语言。

边界：

- 这次只优化用户可见进度提示和回复过程稳定感，不改变 Intent / Plan 路由判定，不新增入口级关键词短路。
- progress hint 只能描述“正在读取、整理、生成预览、按确认更新”，不能提前承诺“已记录偏好 / 已移动方案 / 已排序”。
- 对只读 Explore、Intent preview、Plan preview、Plan apply 继续保持副作用边界：只读不产生 pending，preview 等确认，apply 只能由明确确认触发。

实现方案：

- ChatService fast route 补充阶段性 progress：
  - Plan fast route：先提示正在读取当前方案并整理要求；拿到 `PlanActionPlan` 后，按 action family/stage 提示“整理方案概览 / 生成调整预览 / 准备审查”等。
  - Direct Plan confirm：提示正在按确认更新方案，完成后会刷新工作台。
  - Direct Intent confirm：提示正在按确认更新后续参考偏好。
  - Major compare / Career direction fast route 保留已有只读提示。
- ChatAgent 工具 progress 文案调整：
  - Intent preview：从“整理成待确认偏好”改成“先整理影响，等你确认后才会记入偏好”。
  - Plan 编排：从“判断该先查看、分析还是调整方案”改成“正在读取当前方案并整理这次请求”。
  - Plan 执行：从“正在处理你的方案”改成“正在生成预览或整理方案结果”。
- 单测覆盖 progress hints 不暴露内部词；ChatService fast route 和直接确认链路应能捕获对应 progress 文案。

实施记录：

- `ChatAgent` 工具级 progress 文案已调整为用户语言，Intent preview 明确“等确认后才记入偏好”，Plan 工具提示改为读取、整理、生成预览或整理结果。
- `ChatService` 对绕过完整 ChatAgent 的路径补充 `on_progress`：
  - Plan fast route：进入 `_plan_next_action_model` 前提示正在读取方案并整理请求；进入 `execute_plan_action` 前按 `action_family/stage` 提示方案概览、调整预览、审查或生成结果。
  - Direct Plan confirm：执行前提示正在按确认更新方案，完成后刷新工作台。
  - Direct Intent confirm：执行前提示正在按确认更新后续参考偏好。
- `dialog_regression_runner.py` 补充 thinking 断言能力：case step 可配置 `assertThinkingContains`、`assertThinkingContainsAny`、`assertThinkingNotContains`，metrics 增加 `thinkingMessages`，用于把“用户是否看到系统正在平稳处理”纳入场景回归。
- `dialog_regression_303_effect_perf_cases.json` 补充 thinking 断言，覆盖方案状态、专业组移动预览、方案确认执行、排序预览、Intent preview/confirm、职业方向只读承接和专业对比只读快路径。
- 这些提示不参与路由判断，不新增字符串模板回复，也不改变 preview -> confirm -> apply 的副作用边界。

验证记录：

- `cd zhiyuan-agent && .venv/bin/python -m py_compile app/service.py app/agent/chat_agent.py` 通过。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_agent_progress_hints.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_ws_compat.py -q` 通过：`131 passed`。
- 覆盖点包括：progress hint 不暴露内部词、方案 fast route 捕获“读取当前方案”和“生成调整预览”两段提示、Intent preview 捕获“确认后才会记入偏好”、方案确认直达执行捕获“按确认更新方案”、意向确认直达执行捕获“按确认更新后续参考偏好”、WebSocket 兼容入口允许先发送 `thinking` 再发送最终正文且不误发工作台联动卡片。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_dialog_regression_runner.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_agent_progress_hints.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_ws_compat.py -q` 通过：`164 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m json.tool examples/dialog_regression_303_effect_perf_cases.json` 通过。
- `cd zhiyuan-agent && .venv/bin/python -m py_compile app/service.py app/agent/chat_agent.py examples/dialog_regression_runner.py` 通过。
- 真实 WebSocket e2e 首轮补充验证中，`303-quality-intent-preview-confirm-progress` 暴露一个链路问题：首轮“我倾向法学和财政学，但护理不要”在 180s 超时，前端看到通用超时文案；下一轮“确认这个偏好”却能成功应用。说明 Intent preview 工具已经把 `planEditCache` 写入待确认缓存，但完整 ChatAgent 在工具后最终组织回复阶段超时，服务端原先只支持方案 recent result 超时兜底，缺少 Intent pending 兜底。
- 针对该问题新增 Intent pending 超时兜底设计：正常链路仍由模型组织回复；只有 `handle_message` 超时且方案 recent result 兜底没有命中时，服务端才读取 `planEditCache`，基于结构化 intent cache 渲染“待确认内容 + 下一步确认语”的用户文案。该兜底不应用偏好、不发送工作台联动卡片，也不新增入口级字符串路由。
- 兜底文案约束：必须说明“确认前不会正式生效，也不会直接改动当前方案”；必须包含本轮已识别的正向/负向专业、院校、地域或职业方向；不得暴露 `payload/stage/action_family/volunteerId` 等内部字段；不得说“已直接记录”。
- 复跑后又暴露一个既有行为：Intent preview 首轮会因为 `intent_preview_used_current_turn` 自动追加 `candidate` 工作台刷新卡片。该行为容易让用户理解成“偏好已经生效并筛过候选”，与 preview -> confirm 边界不一致。3.0.3 收口为：未确认的 Intent preview 不发送候选联动卡片；用户确认或勾选采纳后，仍由 direct intent confirm / `handle_intent_select` 的结构化结果触发候选刷新或筛选联动。

### Phase 2.11：专业意向预览快路由设计

问题：

- Phase 2.10 的 Intent pending 超时兜底只能处理“预览工具已执行并写入 `planEditCache`，但最终回复超时”的情况。
- 真实 e2e 复跑中又出现另一种慢点：首轮“我倾向法学和财政学，但护理不要”在 180s 内没有触发 `preview_current_major_intent_confirmation`，也没有写入 pending cache。下一轮确认自然只能命中 no-pending guard。
- 这说明部分明确专业偏好表达仍可能卡在完整 ChatAgent 的“选择工具”之前。仅靠超时兜底不够，因为兜底没有结构化 pending 可读。

设计原则：

- 不新增面向用户的字符串模板回复。
- 不直接写入偏好，不直接刷新候选，不直接改方案。
- 快路由只负责把高置信专业实体装配成 `MajorIntentPreviewInput`，最终仍调用现有 `preview_current_major_intent_confirmation`，由既有 Intent 预览链路生成影响分析、写入 pending cache，并等待用户确认。
- 只有专业名称能被本地专业目录或既有专业名规范化能力确认时才命中；模糊表达和泛方向表达继续走完整 ChatAgent。

路由边界：

| 类型 | 示例 | 处理 |
| --- | --- | --- |
| 明确正向 + 负向专业 | 我倾向法学和财政学，但护理不要 | 命中快路由，传 `level3=["法学","财政学"]`、`negative_level3=["护理学"]` |
| 明确专业类 | 以后优先看计算机类，不看护理类 | 命中快路由，传 `level2/negative_level2` |
| 只读对比 | 法学和财政学哪个更适合，先只分析不要记偏好 | 不命中，继续专业对比只读快路由 |
| 方案操作 | 把法学加入方案 / 按财政学调整方案 | 不命中，交给 Plan 链路 |
| 泛方向 | 我喜欢偏文一点 / 我想找稳定工作 | 不命中，交给完整 ChatAgent / Explore |

实现方案：

1. 新增 `major_intent_fast_router`：
   - 使用本科/专科 `level2/level3` 专业目录做精确匹配。
   - 对“护理”这类常见省略，通过既有 `resolve_major_names_async` 规范化为 `护理学`，但仍要求规范化结果必须存在于本地目录。
   - 同一句可以同时识别正向和负向意向；负向标记来自 `不要/不想/排除/避开/别选/不考虑` 等局部语义。
   - 遇到“哪个更适合/比较/对比/怎么选/只分析/不要记偏好”等只读分析语义，或者“加入方案/删除/移动/排序/改方案”等方案操作语义时不命中。
2. ChatService 接入：
   - 位置在 Plan fast route 之后、专业对比 / 职业方向 / full Agent 之前。
   - 命中后先发送“正在整理这个专业想法的影响，等你确认后才会记入偏好...”进度提示。
   - 调用 `preview_current_major_intent_confirmation(SimpleNamespace(deps=request_context), major_intents=MajorIntentPreviewInput(...), intent_mode=...)`。
   - 保存 `ModelRequest -> ToolCallPart(preview_current_major_intent_confirmation) -> ToolReturnPart -> ModelResponse` 历史 trace。
   - 记录 `conversation_turn_event routingPath=major_intent_fast_route llmRequests=0 toolCallCount=1`。
   - 返回用户态清理后的工具回复，不发送候选工作台联动卡片。
3. 用户确认仍走既有 `direct_pending_intent_confirm -> update_volunteer_intent_state(action="confirm")`，不新增确认分支。

验收：

- 单测覆盖正向/负向混合、专业类、简称规范化、只读对比不命中、方案操作不命中、泛表达不命中。
- ChatService 单测覆盖命中后不调用主 ChatAgent、会保存工具 trace、会发送进度提示、不会返回 workspace followup。
- 真实 e2e 复跑 `303-quality-intent-preview-confirm-progress`，预期首轮不再 180s 卡死，首轮生成待确认预览，第二轮确认可正常写入偏好。

实施记录：

- 新增 `app.resolver.major_intent_fast_router`，基于本科/专科 `level2/level3` 专业目录识别明确专业偏好和排除要求。
- 路由只输出结构化 `major_intents` 和 `intent_mode`，不生成最终回复、不写偏好、不刷新候选、不改方案。
- `ChatService` 在 Plan fast route 后、只读 Explore fast route 前接入 `major_intent_fast_route`；命中后直接调用现有 `preview_current_major_intent_confirmation`，保存工具调用历史，并记录 `conversation_turn_event routingPath=major_intent_fast_route llmRequests=0 toolCallCount=1`。
- `dialog_regression_303_effect_perf_cases.json` 的 Intent preview case 换用干净 session，并补充负向断言，禁止首轮 preview 出现“已经记下 / 已记录 / 当前已记录”等确认后语义。
- `_normalize_pending_intent_reply` 补充 existing-only 分支的用户态收口：即使后端当前 profile 已有相同偏好，未确认 preview 也不能说成“已经记下”，而应表达为“待确认/后续确认后生效”。

验证记录：

- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_major_intent_fast_router.py tests/unit/test_chat_service_history_persistence.py -q`：`112 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_major_intent_fast_router.py tests/unit/test_major_compare_fast_router.py tests/unit/test_career_direction_fast_router.py tests/unit/test_plan_fast_router.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py tests/unit/test_mainline_dialog_scenarios.py -q`：`159 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m json.tool examples/dialog_regression_303_effect_perf_cases.json` 通过。
- `cd zhiyuan-agent && .venv/bin/python -m py_compile app/service.py app/resolver/major_intent_fast_router.py` 通过。
- 真实 WebSocket e2e：
  - 命令：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_after_major_intent_preview_wording_fix.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`
  - 结果：10 steps 全部通过，pytest 总耗时 `26.53s`。
  - `303-quality-intent-preview-confirm-progress` 首轮 `elapsedMs=2296`，`toolCallCount=1`，工具为 `preview_current_major_intent_confirmation`，`followupMessages=0`；第二轮确认 `elapsedMs=2162`，工具为 `update_volunteer_intent_state`，确认后才应用。
  - 全量 3.0.3 effect/perf 中位数约 `2280ms`，p95 / max 约 `4354ms`；最慢仍为专业组移动 preview，属于后端状态读取/预览链路，不是模型选择工具慢。

### Phase 2.12：学校 / 专业局部只读查询快路由设计

问题：

- 真实 e2e 中“青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案”这类局部查询能得到正确结果，但仍会进入完整 ChatAgent，由模型先选择 `query_volunteer_plan`，工具返回后再让主模型组织最终回复。
- `query_volunteer_plan` 当前已经直接返回用户可读文本，并且只读取当前排序方案、已加入方案和候选机会，不写 pending、不刷新工作台、不改方案。对明确只读的局部查询，继续走完整 Agent 的主要收益不大，反而会增加模型延迟和工具选择误差。
- 工具候选示例里仍带 `id=...`，虽然不是 `volunteerId`，但对用户没有解释价值，也容易回到早期“内部格式过多”的体验问题。

边界：

- 只接管高置信局部查询：`当前方案里有没有 X`、`候选里看看 X`、`XX大学相关专业是不是有多个`、`候选里有没有 XX大学的 XX专业`。
- 不接管方案动作：加入、删除、移动、排序、补齐、替换、审查、生成、确认等继续走 Plan 主链路和 preview -> confirm -> apply。
- 不接管 Explore 问题：职业方向、地域机会趋势、专业对比、分数线 / 近三年录取分等仍由对应 Explore / Score 工具或完整 Agent 承接。
- 快路由不生成面向用户的模板回复，只把高置信只读查询装配成 `query_volunteer_plan` 参数；最终回答仍来自现有工具结果，并继续做用户态清理。

实现方案：

1. 新增 `plan_query_fast_router`：
   - 根据只读查询语义、范围词和学校 / 专业引用判断是否命中。
   - 明确候选范围传 `scope=candidate`，明确当前方案范围传 `scope=plan`，未明确但有学校 / 专业局部查询时传 `scope=plan_then_candidate`。
   - 对 `XX大学的XX专业 / XX大学.XX专业` 这类表达，提取 `school_keywords / major_keywords`，复用 `query_volunteer_plan` 内部的 catalog 归一化。
   - 遇到动作语义、职业方向、专业对比、分数线类查询时不命中，回落完整 Agent。
2. ChatService 接入：
   - 位置在 Plan fast route 之后、专业意向 / 专业对比 / 职业方向 fast route 之前。
   - 命中后发送“正在查当前方案和候选里的相关结果...”进度提示。
   - 调用 `query_volunteer_plan(SimpleNamespace(deps=request_context), ...)`，保存 `ModelRequest -> ToolCallPart(query_volunteer_plan) -> ToolReturnPart -> ModelResponse` 历史 trace。
   - 记录 `conversation_turn_event routingPath=plan_query_fast_route llmRequests=0 toolCallCount=1`。
   - 不生成 pending，不发送工作台卡片。
3. 文案清理：
   - `query_volunteer_plan` 候选示例去掉 `id=...`，仅保留学校、专业、冲稳保和录取率等用户能理解的信息。

验收：

- 单测覆盖：当前方案查询、候选查询、学校 + 专业结构化查询、只读“不要改方案”不误判为 mutation、加入 / 删除 / 排序 / 补齐不命中、职业方向 / 专业对比 / 分数线不命中。
- ChatService 单测覆盖：命中后不调用主 ChatAgent，保存工具 trace，返回用户态文本，无工作台 followup。
- 真实 e2e 补充局部查询场景，要求无内部字段、无工作台卡片，并观测 `routingPath=plan_query_fast_route`、`llmRequests=0`。

首轮实现：

- 新增 `app.resolver.plan_query_fast_router`，只负责高置信只读局部查询识别和 `query_volunteer_plan` 参数装配，不生成最终文案、不写 pending、不发送工作台卡片。
- `ChatService` 在 Plan fast route 后接入 `plan_query_fast_route`；命中后直连 `query_volunteer_plan`，保存工具调用历史，记录 `conversation_turn_event routingPath=plan_query_fast_route llmRequests=0 toolCallCount=1`。
- 路由会屏蔽已识别学校名后再识别专业，避免“北京农学院”里的“农学”被误当作专业筛选项。
- `query_volunteer_plan` 候选示例去掉 `id=...`，保留学校、专业、冲稳保和录取率。
- `dialog_regression_303_effect_perf_cases.json` 增加“青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案”场景，校验 thinking、无内部字段、无工作台联动。

验证记录：

- 聚焦单测：`tests/unit/test_plan_query_fast_router.py`、`tests/unit/test_plan_query_tool.py` 局部查询相关用例、ChatService 快路由用例通过。
- 3.0.3 相关回归：`tests/unit/test_plan_query_fast_router.py tests/unit/test_plan_query_tool.py tests/unit/test_major_intent_fast_router.py tests/unit/test_major_compare_fast_router.py tests/unit/test_career_direction_fast_router.py tests/unit/test_plan_fast_router.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_dialog_regression_runner.py -q`：`210 passed`。
- `py_compile` 与 `json.tool` 通过，`git diff --check` 通过。
- 真实 WebSocket e2e：
  - 命令：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_plan_query_fast_route_output.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`
  - 结果：11 steps 全部通过，pytest 总耗时 `29.47s`；中位数约 `2443ms`，p95 / max 约 `4557ms`。
  - 新增局部查询场景端到端 `2273ms`，thinking 为“正在查当前方案和候选里的相关结果...”，无 followup；历史 trace 为单个 `query_volunteer_plan`，服务端日志 `routingPath=plan_query_fast_route`、`llmRequests=0`、`toolDurationMs=103ms`。
  - 该场景回复为“当前排序方案里共命中了 7 条符合‘院校:青岛城市学院’的志愿...”，没有 `id=`、`volunteerId`、`payload/stage/action_family` 等内部字段。

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

### Phase 2.13：名称 / 简称方案操作快路由设计

问题：

- 用户不一定按数字位置表达方案调整，常见说法是“把湖北工程学院的计算机科学与技术改到第3位”“去掉湖北工程学院.计算机科学与技术”“把广西师大统计加进来”。
- 执行层已经支持将这类原始引用解析成真实志愿 ID，并在不唯一时返回澄清；但当前入口多数要先走完整 Agent 判断动作，增加一次 LLM 延迟。
- 这类请求有真实改动副作用，不能为了提速绕过预览、确认和唯一性校验。

设计：

1. 扩展 `plan_fast_route`，只接管高置信名称 / 简称 mutation：
   - 移动：`把{引用}移到/改到/调整到/放到第N位`，输出 `action_family=move_unit`、`volunteer_ids=[原始引用]`、`target_position=N`。
   - 删除：`去掉/删除/删掉/移除{引用}`，输出 `action_family=remove_units`、`volunteer_ids=[原始引用]`。
   - 加入：`把{引用}加进来/加入方案/加到方案`，输出 `action_family=add_units`、`volunteer_ids=[原始引用]`。
2. Router 只做语法抽取，不解析真实 ID、不生成最终回复：
   - 原始引用继续交给 `execute_plan_action` 的 `_resolve_ordered_volunteer_refs` / `_resolve_candidate_volunteer_refs`。
   - 唯一命中才进入预览；歧义或找不到时由执行层返回澄清。
   - 仍走 `_plan_next_action_model -> execute_plan_action(preview)`，确认后走既有 pending apply。
3. 安全边界：
   - 排除只读查询、专业对比、职业探索、意向写入、审查/排序/补齐等场景。
   - 引用过短、包含“第N个志愿/专业组”的数字引用仍交给原数字规则或回落。
   - 不支持批量复合句，例如“删掉 A 再补 B”；这类继续走完整 Agent。
4. 观测：
   - 继续记录 `conversation_turn_event routingPath=plan_fast_route llmRequests=0 toolCallCount=2`。
   - ActionResolver shadow 也覆盖名称引用，对比 `move/remove/add` 的 action family 和 stage。

验收：

- 单测覆盖名称移动、名称删除、名称加入、简称加入、只读查询不误判、专业意向不误判、复合动作不误判、过短引用不误判。
- 执行层既有唯一解析和歧义澄清测试继续通过。
- e2e 增加名称/简称操作场景，要求首轮是预览、无内部字段，确认后执行并刷新方案。

实施记录：

- `plan_fast_router` 已扩展名称 / 简称类高置信 mutation：
  - `named_volunteer_move`：保留原始引用并传入 `move_unit`。
  - `named_volunteer_remove`：保留原始引用并传入 `remove_units`。
  - `named_candidate_add`：保留原始引用并传入 `add_units`。
- `ActionResolver shadow` 补齐 `add_units` 映射，名称引用类动作也会产出影子解析结果，用于后续 typed resolver 接管前对比。
- `execute_plan_action` 对 `add_units` 的 preview 阶段增加候选唯一定位：
  - 唯一命中时只生成 `resolved_apply_payload`，不直接加入方案。
  - 已在方案中时返回 `no_change`，不会留下可确认 pending。
  - 无法唯一定位时返回澄清，并清理 pending，避免用户后续“确认”误执行。
- `execute_plan_action` 对 `move_unit` 的 preview 阶段补齐可读摘要：唯一定位到当前方案志愿后，会返回学校、专业、当前位置和目标位置，例如“已定位到 青岛城市学院-国际经济与贸易，当前在第36位，会移动到第3位”，同时保留 `resolved_apply_payload` 供确认轮稳定执行。
- 命名加入 / 删除的 preview 文案继续补齐：
  - `add_units` 唯一定位到候选后，应说明“已在候选里定位到哪个学校 / 专业，会加入当前方案”，而不是泛化成“会补入指定志愿或按条件补入候选”。
  - `remove_units` 唯一定位到当前方案后，应说明“已定位到当前方案里的哪个学校 / 专业，会从方案中移出”，而不是完全依赖模型传入的 `preview_summary`。
  - 两者都只改变用户可读摘要，不改变唯一性解析、`resolved_apply_payload`、确认后执行和失败澄清逻辑。
- `ChatService` pending 提取修正：当 preview 调用返回 `error/no_change` 等非 `preview_only` 结果时，会清理上一条 preview payload，不再保留无效待确认动作。
- `dialog_regression_303_effect_perf_cases.json` 增加名称移动和简称加入两个场景，校验 thinking、预览确认边界和内部字段屏蔽。

验证记录：

- 聚焦单测：`test_plan_fast_router.py`、`test_action_resolver_shadow.py`、新增候选加入 preview、名称引用 ChatService 快路由、preview error 清 pending 用例：`20 passed`。
- 命名移动预览聚焦回归：`test_execute_plan_action_move_preview_resolves_named_ref_with_readable_summary` 通过，确认 preview 阶段不会调用真实移动，且摘要包含学校、专业和目标位置。
- 命名加入 / 删除预览聚焦回归：`test_execute_plan_action_add_units_preview_resolves_candidate_alias_without_applying` 和 `test_execute_plan_action_remove_preview_returns_resolved_apply_payload_for_alias_ref` 通过，确认 preview 阶段不会执行真实加入 / 删除，且摘要包含学校、专业、动作方向和确认提示。
- 3.0.3 agent 相关宽回归：`tests/unit/test_plan_fast_router.py tests/unit/test_action_resolver_shadow.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_plan_query_fast_router.py tests/unit/test_plan_query_tool.py tests/unit/test_major_intent_fast_router.py tests/unit/test_major_compare_fast_router.py tests/unit/test_career_direction_fast_router.py tests/unit/test_ws_compat.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_dialog_regression_runner.py -q`：`312 passed`。
- `py_compile` 与 `json.tool` 通过。
- 真实 WebSocket e2e：
  - 命令：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_URL=ws://127.0.0.1:8001/gaotu-assistant-agent/plus/chat/1/bot/test/do AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_named_route_output.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`
  - 结果：13 steps 全部通过，pytest 总耗时 `32.54s`；中位数 `2182ms`，p95 `3534ms`，max `4419ms`。
  - 命名移动场景端到端 `2329ms`，历史 trace 为 `plan_next_action(move_unit, preview)` + `execute_plan_action(move_unit, preview_only)`，`applied=false`，回复包含“青岛城市学院-国际经济与贸易”“当前在第36位”“会移动到第3位”“需要你确认后才会执行”。
  - 命名加入场景端到端 `2415ms`，历史 trace 为 `plan_next_action(add_units, preview)` + `execute_plan_action(add_units, preview_only)`，`applied=false`，回复包含“河南农业大学-建筑类”“会加入当前方案”“需要你确认后才会执行”。

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

这些是 3.0.3 继续优化的方向。当前已覆盖高置信单动作，仍需保留安全边界：

- 数字引用先走快路径。
- 名称/简称引用只做语法抽取，继续走执行层唯一性解析。
- 简称歧义必须澄清。
- 复合动作和低置信引用继续回完整 Agent。

### 8.3 大模型输出质量

直接减少 LLM 次数可能让回复变硬。解决方式不是回到模板拼接，而是：

- 工具返回结构化 facts 和面向用户 summary。
- Renderer 做统一、自然、克制的表达。
- 开放式咨询仍保留大模型组织能力。

本轮回复质量评审后的 P1 修复范围：

- Intent preview 不再向用户暴露 `level1/level2/level3` 等专业目录层级字段。
- Intent confirm 不再笼统说“候选结果收紧”，改为“已记录为后续筛选和方案调整参考”。
- 职业方向承接分析需要先回答当前方案承接强弱，再展开候选机会和下一步。
- 专业对比缺少量化权重时，仍应使用本轮用户输入里的“普通家庭 / 女生”等事实，不能误报用户没有提供性别。
- 3.0.3 quality 主 case 补充方案审查，避免审查只靠 full journey / correctness 旧集合间接覆盖。

P1 修复后复跑结果：

- 真实 WebSocket：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` 共 `14/14` steps 通过，输出 `/private/tmp/dialog-regression-303-after-p1-quality-rerun.json`；中位耗时约 `2212ms`，最大耗时约 `4350ms`。
- 新增方案审查 case 命中 `review_plan`，返回 `review` 工作台刷新；用户可见审查回复不再带 `@1/@2` 这类内部位置标记。
- Intent preview 不再出现 `level1/level2/level3`；Intent confirm 不再使用“候选结果收紧”；专业对比能使用用户本轮给出的“普通家庭 / 女生”；职业方向承接先给当前方案承接强弱、数量和示例。
- 相关单测合并回归覆盖 ChatService、场景稳定性、方案执行/查询和快路由，结果为 `310 passed`。

补充文本质量收口后：

- 方案审查回复改为结构化要点，不再把风险、提醒、典型涉及压成一整段。
- 职业方向多方向承接回复去掉重复的承接结论和重复下一步提示。
- 真实 WebSocket 输出 `/private/tmp/dialog-regression-303-after-review-and-career-polish.json`，`14/14` steps 通过；中位耗时约 `2240ms`，最大耗时约 `4140ms`。
- 最新合并单测覆盖 ChatService、Explore、mainline、方案执行/查询和快路由，结果为 `336 passed`。

澄清：

- “结构化”不是问题，复杂问题可以用标题、分段、编号列表和要点输出。
- 需要避免的是僵硬模板、固定菜单式选择、系统内部播报、信息过薄和无上下文的泛化句。
- 当前自动化门禁能发现内部字段、确认边界、工作台误联动、强迫选择和关键事实缺失；对“自然度 / 丰富度 / 单调度”的评判仍主要依赖 e2e 样例内容断言加人工抽样 review，后续可补充更细的 rubric 或抽样评分。

### 8.4 Provider 性能差异

切换更快 provider 可以改善单次请求耗时，但如果一轮仍有 5 到 6 次 LLM 请求，整体体验仍不稳定。因此：

- provider benchmark 要继续跑。
- 主优化仍是减少无意义请求数和 token。

### 8.5 依赖与影响复盘

3.0.3 没有新增必须部署的第三方运行时依赖，主要新增的是内部链路依赖：

| 依赖点 | 影响范围 | 退化风险 | 当前控制方式 |
| --- | --- | --- | --- |
| `plan_fast_route` | 方案状态、数字/名称移动、删除、加入、排序、审查 | 规则过宽会把咨询误判成方案动作；规则过窄会回落主 Agent 变慢 | 只接高置信结构；mutation 永远先 preview；复合动作和低置信引用回落主 Agent |
| `plan_query_fast_route` | 当前方案/候选的局部只读查询 | 可能抢走 Explore、近三年分数、方案修改类请求 | 显式排除 mutation、Explore、分数线语义；要求实体或明确 scope |
| `major_intent_fast_route` | 明确专业偏好/排除的 preview | 可能把只读比较误当偏好写入，或把方案修改误当意向 | 显式排除“哪个更适合/只分析/不要记偏好”和“加入方案/调整方案”等语义 |
| `major_compare_fast_route` | 两个三级专业的只读对比 | 简称、专业类、三专业比较暂时不接管，可能回落慢链路 | 只接精确两个三级专业；专业类和简称保守回落 |
| `career_direction_fast_route` | 体制内、稳定就业、读研等有限方向只读分析 | 泛方向问题和候选查询不接管；开放表达仍可能走主 Agent | 只接有限 taxonomy + 只读语义；意向写入、方案修改、确认语义全部回落 |
| `conversation_phase.pending` | Plan / Intent 统一待确认协议 | 新旧 pending 不同步可能确认错位 | 新字段优先；旧字段仅兼容；版本/轮次守护拦截过期 pending |
| 后端 planning 接口 | 方案状态、排序方案、候选池、审查、移动/删除/排序 | 后端数据缺失或历史脏数据会影响回复准确性 | 快路径只读/预览不改数据；执行层做唯一性解析和失败返回 |
| 专业目录 / career taxonomy | 专业意向、专业对比、职业方向识别 | 目录缺项会导致快路径漏判；taxonomy 覆盖有限 | 漏判回落主 Agent，不直接猜测；后续通过 case 扩展 |
| `dialog_regression_runner` metrics | 效果、延迟、thinking、followup、tool trace | 测试过度偏结构化快路径，无法代表开放式生成质量 | 结果文档明确限制；后续继续补开放式 Explore / Intent follow-up case |

当前 `ChatService` 的快路径优先级为：

1. 无 pending 的孤立确认保护。
2. `plan_fast_route`。
3. `plan_query_fast_route`。
4. `major_intent_fast_route`。
5. `major_compare_fast_route`。
6. `career_direction_fast_route`。
7. 完整 `ChatAgent`。

这个顺序的设计意图是：先保护确认安全，再承接明确方案动作和只读方案查询，再处理意向、专业对比和职业方向。潜在影响是，如果前面的 router 规则过宽，会抢走后面更合适的链路。因此 3.0.3 增加了 release 级路由矩阵单测，覆盖典型输入的预期接管层：

- 方案概览 -> `plan`
- 当前方案里有没有某专业 -> `plan_query`
- 学校相关专业只读查询 -> `plan_query`
- 明确专业偏好/排除 -> `major_intent`
- 两个专业只读比较 -> `major_compare`
- 体制内/稳定就业承接分析 -> `career_direction`
- 复合删改补动作 -> `full_agent`

验证记录：

- 路由矩阵与五类 fast router 单测：`35 passed`。
- 3.0.3 相关合并单测扩展覆盖 ChatService、Explore、mainline、方案执行/查询、Plan / Intent / Major / Career fast router：`346 passed`。
- `git diff --check` 通过。

### 8.6 潜在功能退化清单

当前未发现核心 Plan 执行链路退化，真实 WebSocket 3.0.3 quality 回归 `14/14` 通过，相关单测 `336 passed`。仍需持续关注：

- 复杂自然语言：多动作、多目标、口语缩写可能不命中快路径，表现为回落主 Agent 或要求澄清。
- 简称/别名：名称类方案动作只做语法抽取，真正唯一性仍由执行层解析；如果候选/方案中没有稳定别名数据，会更保守。
- 开放式回复：关闭主链路中的 Explore 内部二次 LLM 后，职业方向回复更快更稳，但可能少一些自由发挥和个性化表达。
- 前端联动：mutation apply 后可能同时刷新 `ordered + review`，前端需要支持多 followup；旧测试中只期望 `ordered` 的地方已经调整。
- 历史上下文裁剪：降低 token 和污染风险，但长对话里用户依赖很早之前的细节时，仍可能需要重新说明。
- 多模型结论边界：当前多模型对照主要证明结构化快路径稳定，不能代表开放式生成质量优劣。
- 历史/脏数据：真实 session 里的方案、候选、专业组数据如果已被多轮测试改动，可能影响样例文本；关键验证应优先用干净会话或清理 Agent 历史后复跑。

## 9. 待确认决策

需要确认后再进入代码实现：

1. 是否同意 `3.0.3` 优先做 Agent 效果和性能，不再继续扩 UI 范围。
2. 是否同意先落 Phase 0 观测，再落 Phase 1 Plan 快路径。
3. 是否同意快路径只做结构化动作装配，不直接模板化回复。
4. 是否同意职业方向有限 taxonomy 可以本地规范化，开放式方向问题继续走 LLM。
5. 是否同意名称/简称类方案操作先保守处理：唯一命中才执行预览，歧义必须澄清。

确认后建议从 Phase 0 开始落地，先让每个慢 case 的 LLM 次数、tool 耗时和 action 路径可见，再进入 Plan 快路径改造。
