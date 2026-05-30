# Release 3.0.3 Agent Effect / Performance Deep Dive

本文记录 `3.0.3` 针对 Agent 效果和性能的专项分析、优化设计、实施记录和回归结果。

关联文档：

- `docs/release-3.0.2-routing-preview-action-review.md`
- `docs/release-3.0.2-implementation-design.md`
- `docs/release-3.0.1-agent-optimization-design.md`
- `docs/release-3.0.3-agent-response-quality-review.md`

## 0. 基线重置记录

2026-05-29 决策：近期围绕 fast route、semantic route、字符串补丁式分流的运行时代码不再继续迭代；运行时代码先回到 `prod-3.0.2` 发布状态，重新 deep dive 当前 full agent 本身的效率、性能和回复质量问题。

本次保留范围：

- `3.0.3` 相关设计、评估和测试用例文档。
- 对话回归、case 评估、质量门禁、多模型 benchmark、semantic frame probe/evaluator 等测试工具和脚本。
- 已沉淀的真实对话衍生 case 文件，用于后续重新跑 full agent 基线。

不保留范围：

- 运行时 fast route / fixed scenario route / semantic intent route 相关实现。
- 逐 case 字符串匹配补丁及其运行时接入。
- 依赖上述运行时代码的路由单测，除非它们只是评估工具自身的测试。

当前校验：

- `zhiyuan-agent/app`、`zhiyuan-server/src` 等运行时代码与 `prod-3.0.2` 对齐。
- 评估工具可在 `prod-3.0.2` 运行时基线上导入和运行。
- `semantic_frame_probe.py` 作为评估工具保留；在没有 3.0.3 semantic router 运行时代码时不会阻断导入，实际执行 probe 会明确提示依赖不可用。
- 工具脚本相关单测：`106 passed`。

注意：`/private/tmp/zhiyuan_agent_303_dialogue_derived_live.json` 等既有输出包含 3.0.3 fast route 历史结果，不能直接作为“纯 3.0.2 full agent 基线”结论。它们只能用于历史对照；重新评估必须基于 `prod-3.0.2` 运行时重新跑 WebSocket e2e。

### 0.1 历史 deep dive 资料的使用口径

本文件后续章节保留了此前 `3.0.3` deep dive 的大量记录，包括 Plan/Explore/Intent 快路径、semantic route shadow、selective arbitration、专业对比 renderer、职业方向快路由、局部查询快路由等设计和验证结果。这些内容现在不再表示“当前运行时代码已经保留”，而应按下面口径使用：

- **可作为问题证据**：此前 case 里已经观察到的 full agent 慢点、误试工具、重复 LLM 调用、回复过薄或边界不清等问题，仍然对当前分析有效。
- **可作为候选优化方案**：此前落过的快路径、renderer、semantic frame、progress hint 等方案可以作为后续设计输入，但需要重新基于 `prod-3.0.2` 基线评估后再决定是否恢复或重做。
- **不可作为当前实现状态**：运行时代码已经回到 `prod-3.0.2`，所以文档中出现的 `plan_fast_route`、`major_compare_fast_route`、`SemanticIntentRouter`、`fixedScenario`、`fast_route_arbitrator` 等都应理解为历史试验或候选设计。
- **不可替代新基线数据**：此前 `/private/tmp` 下的 3.0.3 输出多数混入了 fast route 或 semantic shadow 结果，不能直接证明 full agent 当前表现。当前必须以新跑出的 `zhiyuan_agent_303_full_agent_baseline_live.json` 为准。

因此，当前整理方式是：先把历史 case 结论纳入“问题画像”和“候选方案库”，再用新的 full-agent 基线回归确认哪些问题仍然存在、影响多大、优先级如何。

### 0.2 历史 deep dive 已沉淀的问题画像

此前围绕 3.0.3 的 case 和真实 WebSocket 验证，已经反复出现以下问题类型：

| 问题类型 | 历史样例 | 用户侧影响 | 当前是否需重新验证 |
| --- | --- | --- | --- |
| Plan 明确动作也进入完整 Agent | `把第2个志愿移到第4位`、`按院校层次排序` | 预览慢，且可能先走错工具再重试 | 是 |
| Plan 状态查看上下文过重 | `看看现在的方案` | 回复可用但首包慢，输入 token 大 | 是 |
| Explore 只读分析误进多工具链 | `法学和财政学哪个更适合...`、`体制内稳定就业承接` | 2-4 次 LLM，耗时可到 1-2 分钟 | 是 |
| 专业意向表达触发重复抽取 | `我倾向法学和财政学，但护理不要` | 正负向各自抽取，可能超时；确认边界也更难解释 | 是 |
| 开放口语 Explore 缺少轻量承接 | `一模二模差挺多...`、`孩子数学忽高忽低...` | full agent 大上下文 + 多次模型调用，长时间无反馈 | 是 |
| 政策/资格类问题路由不稳定 | 口试、专项、体检、视力、色弱等 | 可能无进度提示，或误接到意向/方案链路 | 是 |
| 进度提示覆盖不足 | 首轮模型选工具前、工具内部 LLM、最终回复生成阶段 | 用户看到系统“没动静”，即使后台在工作 | 是 |
| 回复质量和性能相互拉扯 | 方案概览、审查、专业对比、职业方向 | 为了快可能变薄；为了丰满可能继续慢 | 是 |

这些问题不能靠继续补个别关键词解决。后续设计要优先基于“任务层级 + 副作用边界 + 可验证事实”的结构化分层：确认/执行类由状态机保护，高置信固定类可以考虑结构化入口，开放咨询继续保留完整 Agent 或经过充分评估后再接管。

## 1. 本期目标

`3.0.3` 重置后的核心目标不是继续堆 UI 功能，也不是继续给 fast route 打补丁，而是先把 `prod-3.0.2` full agent 的主链路问题重新看清楚：

1. 用 80+ 真实对话衍生 case 复测 full agent，定位慢点、误路由、重复工具调用和回复质量问题。
2. 区分三类请求：确定性工具/skill 请求、领域内需要多级编排的请求、与工具无关的普通闲聊。
3. 保留大模型的解释和组织能力，不能为了快把回复压薄、做僵硬模板或丢掉用户想要的信息。
4. 建立可持续的效果与性能 benchmark，后续每次换模型、改提示词、改工具或恢复某类结构化入口，都能量化比较。
5. 在不破坏 `preview -> confirm -> apply` 安全边界的前提下，再决定是否恢复高置信结构化入口、semantic shadow 或特定只读 renderer。

不在本期做：

- 不把所有对话改成规则模板回复。
- 不把历史 fast route 实现直接视为当前方案。
- 不绕过确认机制直接执行高副作用动作。
- 不把 provider 切换当成唯一优化手段。
- 不重写后端方案算法。
- 不删除历史兼容路径，除非已有测试证明无消费方。

## 2. 早期小样本实测表现

本节保留早期 `dialog_regression_302_effect_perf_cases.json` 的 11 step 小样本结果，用于说明 3.0.3 deep dive 最初为什么聚焦 Agent 性能和工具链问题。它不是重置后的最终基线；当前 `prod-3.0.2` full agent 88 case 基线见 4.9。

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

### 4.6 回到 3.0.2 后的 full agent 调用链确认

`prod-3.0.2` 基线下，非确认类消息主链路如下：

```text
ChatService.handle_message
  -> load persisted history
  -> extract pending plan / pending intent
  -> build_runtime_history
  -> fetch score_detail / init_profile / planning_summary
  -> build ConversationPhase
  -> direct pending confirm guard
  -> ChatAgent.run_with_message_deltas
       -> Pydantic Agent initial LLM request
       -> CallToolsNode
            -> tool progress hint
            -> selected tool execution
            -> tool may call backend and/or nested LLM
       -> optional more tool rounds
       -> final LLM answer
  -> normalize plan / intent reply wording
  -> save history
  -> emit workspace followup
```

进度提示的关键限制：

- 只有进入 `CallToolsNode` 后，才会根据工具名发送 thinking/progress 文案。
- 初始 LLM 还没决定工具之前，用户看不到进度。
- 工具内部如果再调 LLM，例如职业方向 slot 识别、方向分析生成、专业对比总结，外层只知道“某个工具在执行”，不知道内部卡在哪。
- 工具返回后到最终回复生成之间，也没有阶段性提示。

这意味着“用户感觉系统没动静”的场景，不一定是后端工具慢；也可能是首轮模型路由慢、工具内部模型慢，或 final answer 慢。

### 4.7 需要重新验证的 full agent 问题

从代码链路看，`prod-3.0.2` full agent 仍有以下高风险点，需要通过重新跑基线确认影响程度：

1. 工具自由选择面过大：`ChatAgent` 暴露专业介绍、专业对比、学校对比、推荐、方案查询、方案编排、意向预览、意向确认、分数线查询等多类工具；低歧义请求也可能先选错工具再自我修正。
2. Explore 工具内嵌多次模型调用：职业方向可能经历方向识别、泛方向判定、方向分析生成；专业对比可能经历专业名消歧、权重查询、对比总结。
3. Plan 链路上下文读取较重：`plan_next_action` 每次都会调用 `_collect_plan_context_inputs_model`，如果同轮重复调用会重复读状态并膨胀历史。
4. 观测只到 turn 级：当前 `conversation_turn_event` 有总耗时、LLM 总耗时、工具名序列和 usage 汇总，但缺少每次 LLM request、每个工具、工具内部子任务的耗时。
5. 回复质量与延迟耦合：为了降延迟直接压薄回复会丢信息；本阶段先评估 full agent 的真实质量和耗时，再决定是否需要结构化入口、小模型路由或工具内降级。

### 4.8 重新跑基线的命令

在本地启动 `prod-3.0.2` 运行时代码后，先跑完整真实对话衍生 case，不启用任何 fast route / semantic route 运行时逻辑：

```bash
cd zhiyuan-agent
RUN_AGENT_DIALOG_E2E=1 \
AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_full_agent_baseline_live.json \
.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_303_dialogue_derived_cases.json \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --response-timeout 180 \
  --keep-response-text
```

生成质量和性能报告：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_case_evaluation_report.py \
  --current /private/tmp/zhiyuan_agent_303_full_agent_baseline_live.json \
  --case-definitions examples/dialog_regression_303_dialogue_derived_cases.json \
  --output /private/tmp/zhiyuan_agent_303_full_agent_baseline_eval.json

.venv/bin/python examples/dialog_case_evaluation_report.py \
  --current /private/tmp/zhiyuan_agent_303_full_agent_baseline_live.json \
  --case-definitions examples/dialog_regression_303_dialogue_derived_cases.json \
  --markdown-detail \
  --output /private/tmp/zhiyuan_agent_303_full_agent_baseline_eval.md
```

基线报告重点看：

- `elapsedMedianMs / elapsedP95Ms / elapsedMaxMs`。
- `firstMessageMs` 是否长时间为空白或超过 10s。
- `usage.requests`、`tool_calls` 与慢 case 的关系。
- 是否存在重复工具调用、错误工具后重试、工具链过长。
- 质量维度是否因为慢链路仍然没有给出足够信息。

### 4.9 full agent 88 case 基线复盘

2026-05-29 已按上述口径重新跑 `dialog_regression_303_dialogue_derived_cases.json`，这次运行时代码按 `prod-3.0.2` 基线，不启用 3.0.3 fast route / semantic route 运行时代码。

执行命令：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_dialogue_derived_cases.json \
  --response-timeout 220 \
  --clear-history-per-case \
  --keep-response-text \
  --metrics-output /private/tmp/zhiyuan_agent_303_full_agent_baseline_live.json
```

输出：

- `/private/tmp/zhiyuan_agent_303_full_agent_baseline_live.json`
- `/private/tmp/zhiyuan_agent_303_full_agent_baseline_eval.json`
- `/private/tmp/zhiyuan_agent_303_full_agent_baseline_eval.md`

runner 退出码为 `1`，原因是 case 质量/性能门禁失败；不是 WebSocket runner 或服务崩溃。88 个 step 都拿到了用户可见回复，但有明显长尾、质量警告和部分断言/评估口径问题。

总体指标：

| 指标 | 结果 |
| --- | ---: |
| steps | 88 |
| verdict | `fail=17 / needs_review=71 / strong=0` |
| latency | min `2450ms` / median `30661ms` / p95 `99659ms` / max `185860ms` |
| first message | median `8252ms` |
| final message | median `28658ms` |
| 平均分 | correctness `4.51` / completeness `4.66` / naturalness `3.98` / actionability `3.38` / latency `1.31` / structure `3.44` / route `4.25` |

按场景看：

| flow | count | verdict | median / p95 / max |
| --- | ---: | --- | ---: |
| explore | 52 | `fail=6 / needs_review=46` | `30661ms / 98234ms / 119701ms` |
| plan | 41 | `fail=6 / needs_review=35` | `28950ms / 69888ms / 185860ms` |
| intent | 10 | `fail=6 / needs_review=4` | `40358ms / 152678ms / 185860ms` |
| review | 9 | `needs_review=9` | `28950ms / 42648ms / 45240ms` |
| confirm_guard | 2 | `fail=1 / needs_review=1` | `8869ms / 14646ms / 15288ms` |
| readonly | 2 | `fail=2` | `12982ms / 15469ms / 15745ms` |

最慢样例：

| prompt | 耗时 | 工具链 | 复盘 |
| --- | ---: | --- | --- |
| `孩子不想当老师，师范是不是都别要` | `185860ms` | 无可见 tool call | 最终走超时兜底，说明首轮模型/最终生成阶段可能卡住；缺少更细粒度 LLM request 观测。 |
| `等成绩出来再定，今天先看大方向` | `119701ms` | `load_skill -> analyze_current_career_direction` | 开放 Explore 同轮加载 skill 又跑职业方向分析，长时间无足够进度解释。 |
| `会计审计还行，土木别要` | `112123ms` | `preview_current_major_intent_confirmation` | 回复内容基本可理解，但 pending 文案里“后续不再推荐/正式记成”容易被评估为已生效语气，且耗时超 100s。 |
| `历史政治地理这个组合，就业别太窄咋选` | `109339ms` | `analyze_current_career_direction` | 选科组合 + 就业面问题被职业方向工具承接，质量可复核但链路过慢。 |
| `大城市就业和考编哪个更现实` | `102153ms` | `analyze_current_career_direction` | 职业取舍类问题仍是 Explore 长尾。 |
| `法律听着稳但怕太卷，财政会不会更实际` | `95027ms` | `analyze_current_career_direction -> compare_majors` | 专业对比被同时拆成职业方向和专业比较，属于工具自由试探。 |
| `孩子内向，不太想天天跟人打交道` | `87382ms` | `analyze_current_career_direction` | 用户话术很口语，最终进入职业方向分析，但耗时和等待感过重。 |
| `汉语言和历史哪个更稳一点` | `85301ms` | `compare_majors -> analyze_current_major_interest` | 明确专业对比后又追加专业兴趣分析，说明工具边界仍不够硬。 |

工具调用分布：

| tool | count |
| --- | ---: |
| `load_skill` | 37 |
| `plan_next_action` | 30 |
| `execute_plan_action` | 22 |
| `analyze_current_career_direction` | 15 |
| `collect_plan_context_inputs` | 10 |
| `analyze_current_major_interest` | 6 |
| `get_major_introduction` | 6 |
| `compare_majors` | 5 |
| `query_volunteer_plan` | 5 |
| `analyze_current_region_interest` | 4 |

高频工具序列：

| 工具序列 | 次数 | 说明 |
| --- | ---: | --- |
| `load_skill` | 13 | 许多开放问法只加载 skill 后由主模型组织，首轮和最终生成仍可能很慢。 |
| `plan_next_action -> execute_plan_action` | 12 | 方案查询/预览主路径可工作，但在 full agent 下仍需要模型先规划。 |
| 无工具 | 10 | 包含无 pending guard 和部分超时兜底；无工具并不等于快。 |
| `analyze_current_career_direction` | 6 | 职业方向单工具链仍有 80s+ 长尾。 |
| `load_skill -> analyze_current_career_direction` | 5 | 明显的重复领域承接，后续应减少。 |
| `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` | 3 | 方案链路存在重复上下文读取。 |

这次能确认的问题：

1. **长尾是当前最大问题**：median 已经到 30s，p95 接近 100s，用户很容易感觉系统卡住。回复质量优先于延迟，但 50-100s 的无效等待不可接受。
2. **Explore/Intent 是主要慢点**：职业方向、专业对比、专业意向、口语化家庭约束等场景经常触发工具内部 LLM 或多个工具串联。
3. **full agent 仍会自由试工具**：专业比较可能同时走职业方向和专业比较，开放职业问题可能先 `load_skill` 再 `analyze_current_career_direction`，方案问题可能先 `collect_plan_context_inputs` 再规划执行。
4. **Plan 查询/审查质量比早期好，但链路仍重**：`看看方案`、审查、排序预览能给出结构化信息，但经常 `plan_next_action -> execute_plan_action`，输入历史和方案上下文仍容易膨胀。
5. **进度提示不足**：报告有 `missing_progress_for_long_task=20`，慢 case 往往只有泛化 thinking，无法告诉用户“正在读取方案/比较专业/生成承接分析”。
6. **观测缺口仍明显**：报告中 `Full Agent Tool Trial Issues` 为 0，不代表没有工具试探；原因是 `prod-3.0.2` 基线的 runner 输出大多缺 `routingPath` 和更细 action trace。stdout、tool 序列和 agent 日志已经能看到工具试探，但评估器还不能自动聚合。
7. **部分失败是评估口径过窄**：例如无 pending 时回复“我这边没有上一轮待确认的方案动作”是合理保护，但断言未覆盖该表达；“现在信息不全，先给我列缺啥”实际列出了 7 项信息，断言仍可能漏判。这些应修评估器或 case 断言，不应贸然改业务逻辑。
8. **共享 session 污染影响判断**：`sessionId=17` 被多类 Plan/Intent case 共用。runner 清理的是 agent 本地 SQLite 历史，但后端方案、偏好和 ordered state 仍会被前序 case 影响。后续 Plan/Intent 深评应拆干净会话，避免把历史状态污染误判为路由问题。

### 4.10 当前优先级和下一步

在重新设计前，先按下面顺序推进，不恢复字符串/关键词 fast route：

1. **补观测**：记录每次 LLM request 耗时、首 token/首消息耗时、每个工具耗时、工具内部 LLM 耗时、最终回复生成耗时、输入 token 来源。没有这些数据，无法判断 `185s` 无工具超时是初始模型、最终模型还是上下文过大。
2. **校准评估器**：修正 `confirm-without-pending`、`missing-info-list` 等合理回复被误判的问题；同时让 `fullAgentToolTrialIssues` 能基于工具序列识别重复工具、错工具后重试和缺进度。
3. **拆干净会话重跑 Plan/Intent**：为专业+大学和院校专业组各准备独立会话，分别覆盖查询、审查、排序、移动、加入、删除、意向预览/确认/取消，避免共用 `session=17`。
4. **分层复跑 88 case**：先分 Explore、Intent、Plan、Review 跑，避免开放 Explore 长尾阻塞整批报告；保留全量跑作为最终验收。
5. **先优化 full agent 提示和工具边界**：明确只读问题不要写 pending，明确专业对比不要再追加专业兴趣分析，明确职业方向工具命中后不要再 `load_skill`，明确方案查询/审查不重复读取上下文。
6. **再评估结构化入口**：只有当某类场景高置信、低歧义、回复质量稳定且能显著降低等待时，才考虑恢复 typed resolver、renderer 或小模型 semantic shadow；仍必须保留 `preview -> confirm -> apply`。

### 4.11 可直接恢复的观测工具

此前 3.0.3 已做过一批观测和评估工具，其中一部分不改变业务行为，可以直接恢复到当前 `prod-3.0.2` full agent 基线上，用于下一轮优化前定位问题。

可恢复范围：

| 能力 | 是否恢复 | 原因 |
| --- | --- | --- |
| `conversation_turn_event` 的 `routingPath=full_agent`、`routeDecision.toolTrial`、`llmRequests`、token、model、`toolCallCount` | 是 | 只写结构化日志，帮助判断慢点和工具试探，不改变回复。 |
| full agent 工具调用摘要：`actionFamily / stage / resultKind / applied / messageCode` | 是 | 从已有 tool call/return 中压缩提取，避免报告只能看到工具名。 |
| `route-observability` 内部历史消息 | 是 | 让 `dialog_regression_runner.py` 能从本地 SQLite history 直接读到 turn event；同时 runtime history 必须过滤，避免进入大模型上下文。 |
| `dialog_case_evaluation_report.py` 的 `Full Agent Tool Trial Issues` 聚合 | 是 | 用于自动归类重复工具、预期路由落回 full agent、慢任务缺进度等问题。 |
| progress hint 用户侧文案优化 | 可以恢复 | 只影响用户等待期间看到的提示，不改变工具选择。需要保留“确认前不生效”的表达边界。 |
| `semantic_frame_evaluator.py`、`semantic_frame_probe.py` | 保留为离线/影子评估 | 不接主链路，只用于评估未来是否可用小模型做语义帧。 |

暂不恢复范围：

| 能力 | 暂不恢复原因 |
| --- | --- |
| `plan_fast_route / plan_query_fast_route / major_intent_fast_route / major_compare_fast_route / career_direction_fast_route` 等执行接管 | 当前要先评估 full agent 本身问题，不能直接恢复历史快路径掩盖根因。 |
| `fixed_scenario_route_resolver / fast_route_arbitrator` 主路径接入 | 仍属于路由接管，需要设计确认和质量评估后再恢复。 |
| `SemanticIntentRouter` 阻塞或接管主路径 | 小样本显示可作为候选，但延迟和混淆边界仍不足以全量前置。 |
| 专业对比/地域 renderer 直接返回 | 属于回复生成策略，后续要基于质量评估决定是否恢复。 |
| 字符串/关键词补丁式路由 | 已明确不继续走逐 case 补丁。 |

本轮代码恢复目标：

1. 恢复 full-agent turn 级观测，不改变用户可见业务逻辑。
2. 恢复 runner/report 对观测消息和工具试探的解析，下一轮 88 case 报告应能看到 `Full Agent Tool Trial Issues` 不再为空。
3. 观测消息必须从 `build_runtime_history` 过滤，确保不会增加后续 LLM 输入 token 或污染回复。
4. 不恢复任何 fast route、semantic route、renderer、typed resolver 的主路径接管。

落地记录：

- `ChatService` full-agent 路径恢复 `turn_event` 结构化对象，包含 `routingPath=full_agent`、`routeDecision.toolTrial`、模型 provider/model、`llmRequests`、input/output/total tokens、`toolCallCount`、`llmDurationMs` 和压缩后的 `toolCalls`。
- `toolCalls` 摘要会从 tool call args 和 tool return 中提取 `actionFamily / stage / resultKind / applied / messageCode`，不展开用户 payload。
- `route-observability` 内部消息写入本地 SQLite history，插在最终用户可见回复前，避免破坏“最后一条消息是本轮回复”的既有语义。
- `build_runtime_history` 会过滤 `route-observability`，因此内部观测不会进入后续 LLM prompt，也不会增加 token。
- `dialog_case_evaluation_report.py` 已具备基于 `routeDecision.toolTrial` 和 `turnObservability.toolCalls` 聚合 `Full Agent Tool Trial Issues` 的能力；下一轮 full-agent 88 case 复跑应重点看该 section。
- 本次没有恢复任何 fast route/semantic route 执行接管。

验证记录：

- `PYTHONPYCACHEPREFIX=/private/tmp/zhiyuan-pycache python3 -m py_compile zhiyuan-agent/app/service.py`
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py tests/unit/test_dialog_case_evaluation_report.py -q`：`171 passed`
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_agent_progress_hints.py tests/unit/test_ws_compat.py tests/unit/test_base_agent.py -q`：`216 passed`

### 4.12 恢复观测后的 88 case 复跑

2026-05-29 在不恢复 fast route / semantic route 执行接管的前提下，复跑 88 个真实对话衍生 case，验证 restored observability 是否能把 full agent 工具链问题暴露出来。

执行命令：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_dialogue_derived_cases.json \
  --response-timeout 220 \
  --clear-history-per-case \
  --keep-response-text \
  --metrics-output /private/tmp/zhiyuan_agent_303_full_agent_observability_live.json
```

输出：

- `/private/tmp/zhiyuan_agent_303_full_agent_observability_live.json`
- `/private/tmp/zhiyuan_agent_303_full_agent_observability_eval.json`
- `/private/tmp/zhiyuan_agent_303_full_agent_observability_eval.md`

runner 退出码仍为 `1`，但 88 个 step 都拿到了用户可见回复，`request failed=0`。失败来自质量/性能门禁：9 个 case 超过 `100s`，1 个 case 是“无 pending 确认”的断言文案口径未覆盖实际合理表达。评估报告的总体判定为 `fail=19 / needs_review=69 / strong=0`，说明当前质量仍需人工复核和持续优化。

总体延迟：

| 指标 | 结果 |
| --- | ---: |
| steps | 88 |
| median | `27999ms` |
| p95 | `108244ms` |
| max | `155647ms` |
| first message median | `7180ms` |
| final message median | `25997ms` |

观测恢复后的工具链聚合结果：

| 指标 | 结果 |
| --- | ---: |
| `Full Agent Tool Trial Issues.count` | 78 |
| `slowOrTimeoutCount` | 78 |
| `missingProgressCount` | 28 |
| `very_slow_tool_chain` | 39 |
| `repeated_tool_calls` | 8 |
| `many_tool_calls` | 16 |
| `tool_result_error` | 1 |

高频工具：

| tool | count |
| --- | ---: |
| `load_skill` | 39 |
| `plan_next_action` | 30 |
| `execute_plan_action` | 22 |
| `analyze_current_career_direction` | 15 |
| `collect_plan_context_inputs` | 9 |
| `analyze_current_major_interest` | 7 |
| `get_major_introduction` | 6 |
| `analyze_current_region_interest` | 6 |
| `compare_majors` | 5 |
| `query_volunteer_plan` | 4 |

重复工具分布：

| repeated tool | count |
| --- | ---: |
| `plan_next_action` | 4 |
| `execute_plan_action` | 2 |
| `load_skill` | 2 |
| `query_volunteer_plan` | 1 |
| `compare_majors` | 1 |
| `get_major_introduction` | 1 |

最慢和最有代表性的问题：

| case | 耗时 | 工具链 | 问题 |
| --- | ---: | --- | --- |
| `计算机太累的话，信息管理这种算不算折中` | `155647ms` | `analyze_current_major_interest -> get_major_introduction -> compare_majors` | 专业适配、专业介绍、专业对比串行叠加；回复可读，但工具成本过高。 |
| `物理不太好但选了物化地，计算机还现实吗` | `134020ms` | `analyze_current_major_interest` | 单工具也能超过 2 分钟，说明工具内部或最终生成耗时仍需细分观测。 |
| `新闻新媒体能不能当备选，不想太虚` | `123953ms` | `analyze_current_major_interest -> get_major_introduction` | 适配分析后追加专业介绍，信息增益存在但等待过长。 |
| `等成绩出来再定，今天先看大方向` | `110327ms` | `load_skill -> analyze_current_career_direction` | 开放 Explore 被职业方向工具承接，等待长且用户只想先聊大方向。 |
| `离家近和好专业冲突怎么取舍` | `109732ms` | `load_skill -> load_skill -> analyze_current_career_direction -> analyze_current_region_interest` | 重复 skill 加载、职业和地域分析同时触发。 |
| `把太贵的那几个先去掉看看` | `103921ms` | `load_skill -> collect_plan_context_inputs -> plan_next_action -> execute_plan_action(error) -> query_volunteer_plan -> query_volunteer_plan -> plan_next_action -> execute_plan_action(error)` | 典型错误预览后重试；最后回复澄清范围是合理的，但工具链过长。 |

这轮新确认的结论：

1. **观测工具已经能发现真实问题**：`Full Agent Tool Trial Issues` 不再为空，能聚合重复工具、工具错误结果、慢工具链和长任务缺进度。
2. **回复质量和延迟的矛盾仍然存在**：很多慢 case 的最终回复内容并不差，不能简单短路成薄模板；优化应优先减少重复/串行工具成本。
3. **Explore 是首批优化主战场**：专业适配、专业对比、职业方向、地域取舍最容易产生 60-150 秒长尾。
4. **Plan 预览/查询存在过度升级**：例如“公办占比怎么样”从查询升级到审查，“高收费风险”进入 remove preview；需要收紧 tool boundary，不是用关键词绕过。
5. **确认边界整体安全**：排序、移动等高副作用操作仍停在 preview；无 pending 时不会误执行。断言失败属于测试文案覆盖不足。
6. **下一步不应恢复字符串快路由**：本轮问题主要是工具编排、工具内部耗时、进度提示和报告归因；字符串补丁只能解决个别表达，不能系统性降低风险。

评估器修复记录：

- `dialog_case_evaluation_report.py` 补充从 `turnObservability.toolCalls` 直接识别工具链问题，即使本地 history 没带出 `routingPath/routeDecision`，也能统计慢工具链、重复工具、错误结果和多工具调用。
- 新增单测覆盖“没有 routingPath 但有 toolCalls 的错误预览 + 重复查询”场景，避免后续报告再次把工具链问题统计为 0。
- `PYTHONPYCACHEPREFIX=/private/tmp/zhiyuan-pycache python3 -m py_compile examples/dialog_case_evaluation_report.py` 通过。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_dialog_regression_runner.py -q`：`77 passed`。

下一步优化顺序：

1. **先做工具边界/编排优化设计**：减少 Explore 同轮 `load_skill + analyze_*`、专业对比里 `analyze_current_major_interest + compare_majors`、Plan 查询里 `query_state + review_plan` 的重复组合。
2. **补进度提示**：首轮模型选择工具前、工具内部长任务、错误预览重试时要给用户可理解的状态，而不是长时间无反馈。
3. **拆分场景回归**：按 Explore / Intent / Plan / Review 分批跑，避免开放 Explore 长尾阻塞整批；Plan/Intent 使用干净后端会话验证 preview -> confirm -> apply。
4. **再评估是否恢复高置信结构化入口**：只有当某类场景的工具边界、质量标准和副作用边界都稳定后，再考虑 typed resolver 或小模型 semantic shadow；仍不走逐 case 字符串补丁。

### 4.13 full agent 工具边界与技能工具收口设计

88 case 复跑后，首个低风险优化点不是恢复 fast route，而是先处理 full agent 自身可见工具和指令边界不一致的问题。

确认到的根因：

- `pydantic_ai_skills.SkillsToolset` 默认提示会要求模型在命中技能域时先调用 `load_skill`。
- 当前主对话已经注册了 `analyze_current_career_direction`、`compare_majors`、`plan_next_action`、`execute_plan_action` 等业务工具，`load_skill` 在主链路里只会增加一轮模型/工具往返。
- 88 case 中 `load_skill` 出现 39 次，且代表性慢 case 包含 `load_skill -> analyze_current_career_direction`、`load_skill -> load_skill -> analyze_current_career_direction -> analyze_current_region_interest`。
- `tool_dispatch_rules.py` 已经要求不要先 `collect_plan_context_inputs` 查询方案状态，但 `plan_chat` skill 仍保留“方案现状先 collect”的旧口径；如果 skill 被加载，会给模型相反的编排提示。

本轮设计原则：

1. **不做字符串快路由**：不通过关键词直接接管用户请求，不绕开大模型对开放问题的组织能力。
2. **不缩短为薄模板**：Explore/Plan 最终回复仍由模型基于工具事实自然组织，允许结构化标题和要点。
3. **先减少无效工具轮次**：主对话默认只注入技能边界摘要，不把 `list_skills/load_skill/read_skill_resource/run_skill_script` 暴露给模型；需要完整技能工具的专门 Agent 可以显式开启。
4. **收紧语义工具边界**：
   - 明确多个专业/专业类的比较优先 `compare_majors / compare_majors_adhoc`，不要先泛化成 `analyze_current_major_interest`；除非用户追问“学什么/课程/就业详情”，不要同轮追加 `get_major_introduction`。
   - 单个专业“适不适合我”优先 `analyze_current_major_interest`，不是 Intent 写入，也不要默认再追加专业介绍。
   - 职业方向问题优先 `analyze_current_career_direction`；地域取舍优先 `analyze_current_region_interest`。只有用户明确同时问职业和地域时，才组合两个 Explore 工具。
   - Explore 专用工具已经包含“当前方案承接/候选机会”的事实时，同一轮不要再补 `plan_next_action(query_state)` 或 `query_volunteer_plan`。
   - 方案状态/数量/分布/占比类问题优先 `query_state -> execute_plan_action`；审查/风险类问题用 `review_plan`；“有没有高收费/公办占比怎么样”不能升级成删除、替换或补偿预览，除非用户明确要求改方案。
   - `execute_plan_action(result_kind="error")` 后不重复同一 `action_family` 试探，应直接说明失败原因和可补充的信息。

预期收益：

- `load_skill` 从主对话工具序列中消失，减少一轮无业务收益的工具调用。
- 专业对比、职业方向、地域取舍等只读 Explore 场景更容易收敛到单个专用工具。
- Plan 查询和风险分析不再被提示词诱导成“查询 + 审查 + 删除预览”的过度升级。
- 对仍由 full agent 直接生成、短时间内没有工具进度的开放问题，超过短阈值会先推送“正在理解你的问题，并结合当前信息整理回答...”，降低用户感知上的无响应等待。

验证计划：

- 单测保护：ChatAgent 默认不注册技能管理工具；完整技能工具仍可通过 `BaseAgent(expose_skill_tools=True)` 显式开启；指令文本包含新的 Explore/Plan 边界。
- 聚焦验证：先跑指令、BaseAgent、ChatAgent 工具注册、评估报告相关单测。
- 真实 WebSocket 验证：下一轮优先复跑 88 case 中 `load_skill` 高频和专业对比/职业方向/Plan 过度升级样例，对比 `toolCalls`、首包延迟、最终回复质量。

首轮抽样验证：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8010/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --session 990303 \
  --prompts '等成绩出来再定，今天先看大方向' '汉语言和历史哪个更稳一点' '公办占比怎么样' \
  --response-timeout 220 \
  --clear-history \
  --keep-response-text \
  --metrics-output /private/tmp/zhiyuan_agent_303_tool_boundary_probe.json
```

结果：

| prompt | 耗时 | 工具链 | 结论 |
| --- | ---: | --- | --- |
| `等成绩出来再定，今天先看大方向` | `9229ms` | 无工具 | 不再 `load_skill`；回复质量可用，但首条消息约 `7.2s`，需补首轮静默等待提示。 |
| `汉语言和历史哪个更稳一点` | `29627ms` | `compare_majors` | 只走专业对比工具，不再追加 `analyze_current_major_interest` 或 `get_major_introduction`；回复包含就业面、壁垒、深造和结论。 |
| `公办占比怎么样` | `10572ms` | `plan_next_action(query_state) -> execute_plan_action(query_state)` | 只读统计未升级成审查或变更预览；无正式方案时诚实说明。 |

本轮实施结果：

- `BaseAgent` 默认使用技能边界摘要模板，不暴露技能管理工具，也不再把“先调用 load_skill”的默认技能提示注入主对话；`expose_skill_tools=True` 仍保留完整技能工具。
- `ChatAgent` 显式 `expose_skill_tools=False`。
- `tool_dispatch_rules`、`explore_chat`、`major_chat`、`plan_chat` 同步收紧工具边界。
- `ChatService` 增加首轮静默等待提示：full agent 路径超过短阈值且尚未发送工具进度时，推送一条用户可理解的 thinking；如果工具进度已经出现，不重复发送。
- 首轮静默提示复验：相同 3 条抽样在 `8011` 最新代码上通过，第一条约 `3.4s` 先出现“正在理解你的问题，并结合当前信息整理回答...”；三条工具链仍未出现 `load_skill`，但 provider 长尾明显，最大耗时 `86893ms`，后续仍需继续做模型/工具内部耗时拆分。
- 聚焦验证：`144 passed`；语法检查和 `git diff --check` 通过。

## 5. 历史候选方案库

本节开始记录此前 3.0.3 deep dive 中已经设计和试验过的候选方案。它们不是当前运行时代码状态；当前是否恢复，需要等新的 `prod-3.0.2` full-agent 基线报告完成后再评估。

### 5.1 候选总体架构

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

## 7. 历史试验落地记录

本节保留此前围绕候选方案做过的实现和验证记录，用于后续判断“哪些方向曾经有效、哪些方向风险较大”。当前运行时代码已回到 `prod-3.0.2`，因此这里的 `已新增 / 已接入 / 已验证` 都表示历史试验结果，不表示当前代码仍保留。

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
- 职业方向只读回复进一步去掉“当前判断 -> 初步判断 / 需要补充留意 / 可以继续展开”的嵌套结构，改为“方案承接 / 需要留意 / 候选机会 / 下一步”的用户可读结构；该调整只影响展示层，不改变方向识别、候选/方案事实计算和只读边界。
- 真实 WebSocket 输出 `/private/tmp/dialog-regression-303-after-review-and-career-polish.json`，`14/14` steps 通过；中位耗时约 `2240ms`，最大耗时约 `4140ms`。
- 最新合并单测覆盖 ChatService、Explore、mainline、方案执行/查询和快路由，结果为 `336 passed`。
- 职业方向结构收口后，最新真实 WebSocket 输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_career_format_restart.json`，`14/14` steps 通过；中位耗时约 `2317ms`，最大耗时约 `4704ms`。开放式质量集合输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_career_format_restart.json`，`4/4` steps 通过；中位耗时约 `3140ms`，最大耗时约 `3794ms`。

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
| `pending_intent_impact_fast_route` | 已有待确认意向后，用户继续追问“这个偏好会影响当前方案吗” | 依赖后端 `planEditCache` 可读；cache 未写入或后端不可用时会回落完整 Agent，可能变慢 | 只在已有 pending intent 且问题是影响/匹配/冲突类只读追问时命中；不确认、不刷新工作台、不改方案 |
| `major_compare_fast_route` | 两个三级专业的只读对比 | 简称、专业类、三专业比较暂时不接管，可能回落慢链路 | 只接精确两个三级专业；专业类和简称保守回落 |
| `career_direction_fast_route` | 体制内、稳定就业、读研等有限方向只读分析 | 泛方向问题和候选查询不接管；开放表达仍可能走主 Agent | 只接有限 taxonomy + 只读语义；意向写入、方案修改、确认语义全部回落 |
| `conversation_phase.pending` | Plan / Intent 统一待确认协议 | 新旧 pending 不同步可能确认错位 | 新字段优先；旧字段仅兼容；版本/轮次守护拦截过期 pending |
| 后端 planning 接口 | 方案状态、排序方案、候选池、审查、移动/删除/排序 | 后端数据缺失或历史脏数据会影响回复准确性 | 快路径只读/预览不改数据；执行层做唯一性解析和失败返回 |
| 专业目录 / career taxonomy | 专业意向、专业对比、职业方向识别 | 目录缺项会导致快路径漏判；taxonomy 覆盖有限 | 漏判回落主 Agent，不直接猜测；后续通过 case 扩展 |
| `dialog_regression_runner` metrics | 效果、延迟、thinking、followup、tool trace | 测试过度偏结构化快路径，无法代表开放式生成质量 | 结果文档明确限制；后续继续补开放式 Explore / Intent follow-up case |

当前 `ChatService` 的快路径优先级为：

1. 已有方案 pending 的确认 / 放弃 / 过期保护。
2. 已有待确认意向下的影响追问：`pending_intent_impact_fast_route`。该检查放在用户画像、分数和 planning summary 通用拉取前，避免一个只读追问被通用上下文加载和完整 Agent 放慢。
3. 无 pending 的孤立确认保护。
4. `plan_fast_route`。
5. `plan_query_fast_route`。
6. `major_intent_fast_route`。
7. `major_compare_fast_route`。
8. `career_direction_fast_route`。
9. 完整 `ChatAgent`。

这个顺序的设计意图是：先保护确认安全，再处理已有 pending 的低成本只读追问，再承接明确方案动作和只读方案查询，再处理意向、专业对比和职业方向。潜在影响是，如果前面的 router 规则过宽，会抢走后面更合适的链路。因此 3.0.3 增加了 release 级路由矩阵单测，覆盖典型输入的预期接管层：

- 方案概览 -> `plan`
- 当前方案里有没有某专业 -> `plan_query`
- 学校相关专业只读查询 -> `plan_query`
- 明确专业偏好/排除 -> `major_intent`
- 待确认意向后追问当前方案影响 -> `pending_intent_impact`
- 两个专业只读比较 -> `major_compare`
- 体制内/稳定就业承接分析 -> `career_direction`
- 复合删改补动作 -> `full_agent`

验证记录：

- 路由矩阵与五类 fast router 单测：`35 passed`。
- 3.0.3 相关合并单测扩展覆盖 ChatService、Explore、mainline、方案执行/查询、Plan / Intent / Major / Career fast router：`346 passed`。
- `git diff --check` 通过。

开放式 Intent 追问补充验证：

- 新增 `dialog_regression_303_open_quality_cases.json`，覆盖待确认意向后追问影响、职业方向多方向只读、专业对比上下文使用。
- 真实 WebSocket 首轮验证曾失败，原因不是路由判断错误，而是 Backend 8080 未启动导致 `planEditCache` 保存失败；第二轮读不到 pending 时只能回完整 Agent。
- 启动 Backend 后复跑通过：`4/4` steps 通过，中位耗时约 `3107ms`，最大耗时约 `4987ms`；pending intent 影响追问约 `2899ms`，`routingPath=pending_intent_impact_fast_route`，`llmRequests=0`，无 followup 工作台卡片。
- 该路径会把待确认内容、当前方案贴近/冲突和候选机会组织成用户语言；确认前不正式生效，也不改动当前方案。

### 8.6 潜在功能退化清单

当前未发现核心 Plan 执行链路退化，真实 WebSocket 3.0.3 quality 回归 `14/14` 通过，相关单测 `336 passed`。仍需持续关注：

- 复杂自然语言：多动作、多目标、口语缩写可能不命中快路径，表现为回落主 Agent 或要求澄清。
- 简称/别名：名称类方案动作只做语法抽取，真正唯一性仍由执行层解析；如果候选/方案中没有稳定别名数据，会更保守。
- 开放式回复：关闭主链路中的 Explore 内部二次 LLM 后，职业方向回复更快更稳，但可能少一些自由发挥和个性化表达。
- Intent pending 依赖：待确认意向的影响追问依赖后端 `planEditCache`。如果预览阶段没有成功写入 cache，影响追问会回完整 Agent 或提示没有待确认内容；后续可评估是否从本地历史中恢复 pending，但本轮不新增不可靠兜底。
- 前端联动：mutation apply 后可能同时刷新 `ordered + review`，前端需要支持多 followup；旧测试中只期望 `ordered` 的地方已经调整。
- 历史上下文裁剪：降低 token 和污染风险，但长对话里用户依赖很早之前的细节时，仍可能需要重新说明。
- 多模型结论边界：当前多模型对照主要证明结构化快路径稳定，不能代表开放式生成质量优劣。
- 历史/脏数据：真实 session 里的方案、候选、专业组数据如果已被多轮测试改动，可能影响样例文本；关键验证应优先用干净会话或清理 Agent 历史后复跑。

## 9. 本轮进展更新

本轮继续聚焦 Explore / Intent / Plan 之间的路由边界、用户可理解回复和端到端延迟，已落地以下修复：

1. `plan_query_fast_route` 排除“适合什么方向 / 适合什么专业 / 看适合什么”等探索问法，避免把“我是山东450分，物理历史地理，想先看看适合什么方向”误路由为当前方案局部查询。
2. `execute_plan_action` 在缺少 `existing_plan` 时不再暴露 `缺少必要输入：existing_plan`，改为“当前还没有可审查或可调整的方案，先生成基础方案后再审查/调整”的用户语言。
3. Intent preview 标题去掉“卡片里选择”的前端实现词，影响说明会清理无事实支撑的“我先帮你看看 / 顺手看看”等占位句；如果已经有真实方案或候选命中，则保留父级标题和事实内容。
4. 专业对比和专业意向快路由补充本地唯一别名：`跨境电商` 可归一为 `跨境电子商务`，同时继续保持专业类、三专业比较、方案修改等低置信场景回落主链路。
5. 专业对比缺少系统量化权重时，会从最近用户上下文承接省份、分数和选科；例如第二轮“网络与新媒体和跨境电商哪个更适合我”会承接上一轮“山东450分，物理历史地理”。
6. 专业类画像补强 `新闻传播学类` 与 `电子商务类`，避免 `网络与新媒体 vs 跨境电子商务` 只输出“当前没有沉淀专门画像”的空泛比较。
7. `BaseAgent` 的技能体系调整为默认只注入技能边界摘要，不再把 `list_skills / load_skill / read_skill_resource / run_skill_script` 暴露给主对话运行时；需要完整技能工具的专门 Agent 仍可显式开启 `expose_skill_tools=True`。这次修复的目标是去掉开放式 Explore 中“先加载技能说明”的额外工具轮次，不新增用户侧模板短路，也不改变 Explore / Intent / Plan 的业务工具。

`load_skill` 根因复盘：

- `load_skill` 来自 `pydantic_ai_skills.SkillsToolset` 的默认工具集，不是志愿规划业务工具。
- 默认 skills system prompt 会要求“任务落在技能域内时先调用 `load_skill`”，这与本系统已经注册的 `analyze_current_career_direction / compare_majors / plan_next_action` 等专用业务工具存在冲突。
- 仅在 `tool_dispatch_rules` 里写“不要先调用 `load_skill`”不足以稳定约束模型，因为工具本身仍可见，且技能工具的系统提示会给出相反倾向。
- 当前改为保留技能摘要作为任务边界提示，但不注册技能管理工具，主对话模型只能选择真实业务工具；这样可以减少无意义工具轮次，同时保留领域分工语义。

最新验证：

- 相关宽单测：`PYTHONPATH=. pytest --noconftest tests/unit/test_plan_query_fast_router.py tests/unit/test_major_intent_fast_router.py tests/unit/test_major_compare_fast_router.py tests/unit/test_major_compare_reply_renderer.py tests/unit/test_plan_execution_tool.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py -q`，结果 `340 passed`。
- 技能注入聚焦单测：`tests/unit/test_base_agent.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_chat_agent_tools.py -q`，结果 `40 passed`；确认主对话默认不再注册技能管理工具，业务工具注册不受影响。
- 最新真实 WebSocket effect/perf：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_effect_perf_after_profile_restart.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`，`14/14` steps 通过，中位耗时约 `2203ms`，最大耗时约 `4432ms`。
- 技能工具收紧后真实 WebSocket effect/perf：`RUN_AGENT_DIALOG_E2E=1 AGENT_DIALOG_E2E_METRICS_OUTPUT=/private/tmp/zhiyuan_agent_303_effect_perf_after_skill_toolset_scope.json .venv/bin/python -m pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s`，`14/14` steps 通过，中位耗时约 `2284ms`，最大耗时约 `4930ms`；职业方向承接场景约 `2204ms`，tool trace 仅有 `analyze_current_career_direction`，没有 `load_skill`，`llmRequests=0`。
- 技能工具收紧后 open quality：`AGENT_DIALOG_E2E_CASES=examples/dialog_regression_303_open_quality_cases.json` 真实 WebSocket `4/4` steps 通过，中位耗时约 `3046ms`，最大耗时约 `3506ms`；覆盖待确认意向影响追问、多方向职业承接和专业对比上下文承接。
- 补充新会话链路：session `880403`，覆盖“山东450分物理历史地理 -> 网络与新媒体和跨境电商对比 -> 记成偏好”。三步均通过；专业对比约 `2166ms`，能展示新闻传播学类和电子商务类的就业路径、门槛、稳定性和试错成本；Intent preview 约 `2319ms`，能把 `跨境电商` 归一成 `跨境电子商务`。
- 同一补充链路的第一步开放式 Explore 曾慢到约 `46925ms`，当时观测到 `load_skill` 和 `analyze_current_career_direction` 同轮出现；技能工具收紧后的 effect/perf 与 open quality 已确认主回归路径不再出现 `load_skill`。如果后续仍有开放表达回落完整 Agent 且变慢，重点应继续看完整 Agent 两次远端模型调用和开放式方向分析组织，而不是回退到字符串模板。

### 4.14 Explore 内部方向判定合并设计

技能工具收口后，职业方向 Explore 的外层工具链已经从 `load_skill -> analyze_current_career_direction` 收敛为单个 `analyze_current_career_direction`。但真实日志仍显示，工具内部可能继续串行触发：

1. full agent 首轮模型判断并调用 `analyze_current_career_direction`；
2. 工具内 LLM 识别 `system_public_service / stable_employment / further_study` 等发展方向 slot；
3. 如果 slot 为空，再用另一个工具内 LLM 判断是否属于“泛方向适配”；
4. 读取方案 / 候选事实；
5. 工具内生成分析草稿；
6. full agent 最终组织回复。

其中第 2、3 步本质都是“理解用户这句职业方向问题应该怎么承接”，串行调用会把“等成绩出来再定，今天先看大方向”这类开放 Explore 变成长尾链路。这个问题不能继续通过扩大关键词命中来解决，因为真实表达非常口语化，关键词补丁会带来漏判和误判。

本轮设计只优化工具内部，不改变 full agent 主路径：

- 保留 `analyze_current_career_direction` 作为模型可调用的业务工具，不新增 service 层字符串快路由。
- 将“方向 slot 识别”和“泛方向适配判定”合并为一次内部语义判定，输出 `positive / negative / shouldAnalyze / reason`。
- 判定结果按当前 `RequestContext + latest_user_text` 缓存在上下文对象上；同轮先调用 `resolve_career_direction_slots` 后再调用 `should_use_generic_direction_analysis` 时，不再重复请求模型。
- 旧函数名继续保留，避免影响 `intent_preview_tool`、单测和未来工具调用入口；只是它们底层共用同一个 decision。
- 不改变只读边界：职业方向 Explore 仍只返回分析，不写 pending、不触发方案修改、不发送工作台联动卡片。

预期收益：

- 泛方向 Explore 至少减少 1 次工具内部 LLM 调用。
- 多方向 / 单方向问题仍能返回原来的 slot 列表，不影响 `preview_direction_comparison_from_request` 和 `preview_direction_analysis_from_request`。
- 如果模型服务长尾仍主要发生在“分析草稿生成”或 full agent 最终组织阶段，后续再单独评估是否关闭真实聊天主链路的 Explore 内层生成；本轮不直接削薄用户侧回复。

实施结果：

- `explore_direction_tool` 新增 `CareerDirectionRouteDecision`，将职业方向 slot 和泛方向适配标记合并到一次工具内语义判定。
- `resolve_career_direction_slots` 与 `should_use_generic_direction_analysis` 继续保留旧入口，但底层共享同一个 decision，并按 `latest_user_text` 缓存在 `RequestContext` 上。
- 新增单测覆盖“先取 slot、再判断泛方向”只调用一次内部 route agent，避免泛方向 fallback 重复跑模型。
- 聚焦回归：`tests/unit/test_explore_direction_scenarios_sync.py`，`11 passed`。
- Agent 宽回归：`tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_base_agent.py tests/unit/test_chat_agent_tools.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_instructions.py -q`，`301 passed`。
- 编译校验：`py_compile explore_direction_tool.py intent_preview_tool.py` 通过；`git diff --check` 通过。

### 4.15 Explore 内层生成收口设计

在 4.14 后，泛方向判断已从两次内部判定收敛为一次，但职业方向 Explore 仍有一段重复生成：

```text
analyze_current_career_direction
  -> preview_direction_analysis / preview_direction_comparison / preview_generic_direction_analysis
      -> 读取 planning state / candidate sample
      -> 构造 student_fit_fact / direction_facts
      -> 工具内部 LLM 生成 DirectionAnalysisDraft
  -> ChatAgent 主模型基于工具结果再生成最终回复
```

这会让用户同一句只读探索经历“工具内生成 + 主模型最终生成”两层远端模型调用。考虑到工具已经有结构化事实和 fallback 文本，正式聊天主链路可以跳过工具内部草稿生成，把最终表达交给 ChatAgent；直接单测、脚本或未来独立调用工具时仍保留原内部生成能力。

设计边界：

- `RequestContext.allow_explore_inner_llm` 默认 `True`，保持直接调用工具的既有行为。
- `ChatService` 构造正式对话 `RequestContext` 时设置为 `False`，仅关闭主对话链路里的 Explore 内层生成。
- `preview_direction_analysis_from_request`、`preview_generic_direction_analysis_from_request`、`preview_direction_comparison_from_request` 判断该开关；关闭时只使用结构化事实 fallback，不调用 `_generate_*_analysis_content`。
- 不改变 `analyze_current_career_direction` 是否被调用，不改变只读 / pending / 工作台联动边界，也不把最终回复改成确定性模板。用户最终仍由 full agent 基于工具返回内容组织。
- 质量风险：少一次工具内自由生成，某些开放 Explore 的措辞可能更依赖 fallback 事实质量。通过保留“学生本人判断 / 方案承接 / 候选机会 / 下一步”的结构，避免回复被压成薄摘要。

实施结果：

- `RequestContext` 新增 `allow_explore_inner_llm`，默认 `True`；`ChatService` 正式聊天主链路创建上下文时设置为 `False`。
- `preview_direction_analysis_from_request`、`preview_generic_direction_analysis_from_request`、`preview_direction_comparison_from_request` 在该开关关闭时跳过工具内 `_generate_*_analysis_content`，直接返回结构化事实 fallback。
- 新增单测覆盖单方向、多方向和泛方向三条 Explore 链路在主链路开关关闭时不会调用内部生成；同时验证 `ChatService` 注入 `allow_explore_inner_llm=False`。
- 聚焦回归：`tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_chat_service_history_persistence.py -q`，`111 passed`。
- Agent 宽回归：`tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_base_agent.py tests/unit/test_chat_agent_tools.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_instructions.py -q`，`304 passed`。
- 编译校验：`py_compile context.py service.py explore_direction_tool.py intent_preview_tool.py` 通过；`git diff --check` 通过。

### 4.16 专业对比工具内层生成收口设计

`compare_majors` 当前不是路由问题，而是工具内部也有一层总结模型：

```text
full agent 首轮模型
  -> compare_majors
      -> 专业名规范化 / 权重查询
      -> _summarize_comparison 内部 LLM 生成专业对比总结
  -> full agent 最终模型基于工具结果再组织回复
```

这和职业方向 Explore 的重复生成类似。区别是：专业对比的事实主要来自两个来源：

- 三级专业目录及其所属专业类；
- `query_volunteer_analysis_weight / rank query_weight` 返回的性别指数、满意度、薪酬、热度、综合评分和个性化备注。

本轮不恢复 `major_compare_fast_route`，也不做“法学/财政学”这类 pair 专属模板。优化点只放在工具内部：

- `RequestContext.allow_explore_inner_llm=False` 时，`compare_majors / compare_majors_adhoc` 不再调用 `_summarize_comparison` 的内部 LLM。
- 工具直接返回结构化、用户可读的对比事实：专业所属类、当前是否有个性化量化数据、四个指标的相对强弱、综合评分差异、个性化备注和下一步建议。
- 如果权重数据为空或缺失，不输出“两个专业得分相同”这种误导性结论，而是明确说明“当前缺少个性化量化评分”，再给通用比较维度，等待 full agent 根据用户上下文组织最终判断。
- 直接调用工具、独立脚本和既有默认用法仍保留内部 LLM 生成能力，避免一次性改变所有消费方。

质量边界：

- 专业对比回复允许结构化，不能变成薄的“哪个更好”结论。
- 至少覆盖就业路径、稳定性 / 热度、学习或试错成本、是否适合当前学生这几类判断维度中的若干项。
- 如果缺少画像，不假装已经知道性别、家庭、分数；但用户本轮已经提供的信息可由 full agent 在最终组织阶段补进去。

实施结果：

- `major_compare_tool` 复用 `allow_explore_inner_llm`：默认仍走内部 `_summarize_comparison`，正式聊天主链路关闭时返回结构化对比事实。
- 结构化事实包含专业所属类、是否有个性化量化指标、性别分布适配、满意度、薪酬、热度、综合评分、个性化备注和数据来源。
- 缺权重时明确提示“当前缺少完整个性化量化评分”，不再把空指标解释成“得分相同”。
- 聚焦单测：`tests/unit/test_compare_resolution.py -q`，`5 passed`。
- Agent 宽回归：`tests/unit/test_compare_resolution.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_base_agent.py tests/unit/test_chat_agent_tools.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_instructions.py -q`，`309 passed`。
- 编译校验：`py_compile context.py service.py explore_direction_tool.py intent_preview_tool.py major_compare_tool.py` 通过；`git diff --check` 通过。

### 4.17 学校对比工具内层生成收口设计

`compare_schools / compare_schools_adhoc` 和专业对比存在同类重复生成：

```text
full agent 首轮模型
  -> compare_schools
      -> 学校名规范化 / 权重查询
      -> _summarize_comparison 内部 LLM 生成院校对比总结
  -> full agent 最终模型基于工具结果再组织回复
```

这类问题的事实来自 `query_school_analysis_weight / rank query_weight`，包括省份 GDP、城市等级、考研率、保研率、院校等级、综合评分和个性化备注。正式聊天主链路可以直接返回这些结构化事实，由 full agent 最终组织成用户可读建议。

设计边界：

- 不新增学校对比 fast route，不靠字符串判断用户是否要比较院校；仍由 full agent 自己选择 `compare_schools`。
- `allow_explore_inner_llm=False` 时，学校对比工具跳过内部总结 LLM，返回院校对比事实和数据来源。
- 直接调用工具默认仍保留内部 LLM 总结。
- 缺少权重时明确说明缺少完整个性化量化评分，不把空指标解释成“两个学校一样”。
- 只读边界不变：不写 pending、不改方案、不触发工作台卡片。

实施结果：

- `school_compare_tool` 复用 `allow_explore_inner_llm`：默认仍走内部 `_summarize_comparison`，正式聊天主链路关闭时返回结构化院校对比事实。
- 结构化事实包含省份经济资源、城市等级、考研率、保研率、院校等级、综合评分、个性化备注和数据来源。
- 缺权重时明确提示“当前缺少完整个性化量化评分”，不把空指标解释成“得分相同”。
- 聚焦单测：`tests/unit/test_compare_resolution.py -q`，`8 passed`。
- Agent 宽回归：`tests/unit/test_compare_resolution.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_base_agent.py tests/unit/test_chat_agent_tools.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_instructions.py -q`，`312 passed`。
- 编译校验：`py_compile context.py service.py explore_direction_tool.py intent_preview_tool.py major_compare_tool.py school_compare_tool.py` 通过；`git diff --check` 通过。

### 4.18 专业推荐工具内层生成收口设计

`get_major_recommendations / get_major_recommendations_adhoc` 也会在工具内部把推荐专业列表交给 LLM 总结，然后 full agent 再最终组织回复。院校推荐 `get_school_recommendations` 当前已经是确定性文本，不需要同类处理。

设计边界：

- 不新增专业推荐路由；仍由 full agent 判断是否需要调用 `get_major_recommendations`。
- `allow_explore_inner_llm=False` 时，专业推荐工具跳过内部 `_summarize_recommendations`，返回推荐专业列表、关键指标和数据来源。
- 直接调用工具默认仍保留内部 LLM 总结。
- 结构化事实必须保留推荐对象、性别指数、满意度、薪酬、热度等关键信息，避免回复只剩“推荐几个专业”的薄列表。
- 只读边界不变：不写 pending、不改方案、不触发工作台卡片。

实施结果：

- `major_recommend_tool` 复用 `allow_explore_inner_llm`：默认仍走内部 `_summarize_recommendations`，正式聊天主链路关闭时返回结构化推荐事实。
- 结构化事实包含推荐专业、性别分布适配、满意度、薪酬、热度、判断建议和数据来源。
- 聚焦单测：`tests/unit/test_major_recommend_tool.py -q`，`2 passed`。
- Agent 宽回归：`tests/unit/test_major_recommend_tool.py tests/unit/test_compare_resolution.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_base_agent.py tests/unit/test_chat_agent_tools.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_instructions.py -q`，`314 passed`。
- 编译校验：`py_compile context.py service.py explore_direction_tool.py intent_preview_tool.py major_compare_tool.py school_compare_tool.py major_recommend_tool.py` 通过；`git diff --check` 通过。

## 10. Semantic Router 模型候选评估

2026-05-28 对 `SemanticIntentRouter` 做了阻塞 shadow 小样本评估，重点验证“轻量模型是否可做全局前置语义路由”。本轮没有把 shadow 接入主路由，只在 `turnObservability.semanticRouterShadow` 和报告里记录结果。

### 10.1 配置能力

本轮新增专用路由模型配置：

```env
SEMANTIC_ROUTER_LLM_PROVIDER=openai_compatible
SEMANTIC_ROUTER_LLM_BASE_URL=
SEMANTIC_ROUTER_LLM_API_KEY=
SEMANTIC_ROUTER_LLM_MODEL_NAME=deepseek-ai/DeepSeek-V4-Flash
SEMANTIC_ROUTER_LLM_TEMPERATURE=0
SEMANTIC_ROUTER_LLM_MAX_TOKENS=512
SEMANTIC_ROUTER_LLM_ENABLE_THINKING=false
```

如果不配置 `SEMANTIC_ROUTER_LLM_MODEL_NAME`，router 继续复用主 Agent 的 `LLMClient`。`SEMANTIC_ROUTER_LLM_ENABLE_THINKING=false` 会进入 OpenAI-compatible `extra_body.enable_thinking=false`，用于测试 DeepSeek V4 Flash Non-think 模式。

### 10.2 实测结果

测试集：`examples/dialog_regression_303_effect_perf_cases.json`，14 个 step。为了看真实阻塞成本，测试时设置 `SEMANTIC_ROUTER_BLOCKING=true` 和 `SEMANTIC_ROUTER_TIMEOUT_SECONDS=8`。

| 路由模型 | semantic success | semantic timeout/error | median | p95 | max | 备注 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `Pro/moonshotai/Kimi-K2.6` | 4 | timeout 10 | `22.261s` | `22.782s` | `23.076s` | 主模型做阻塞路由不可用 |
| `deepseek-ai/DeepSeek-V4-Flash` | 4 | timeout 10 | `10.428s` | `14.554s` | `17.725s` | 更快，但仍频繁超时 |
| `deepseek-ai/DeepSeek-V4-Flash` Non-think，修复前 | 6 | timeout 6 / error 2 | `10.164s` | `12.196s` | `13.063s` | 实体类型输出不稳定，`positions` 可为数字/对象 |
| `deepseek-ai/DeepSeek-V4-Flash` Non-think，实体规范化后 | 7 | timeout 7 | `10.168s` | `11.269s` | `12.267s` | 解析错误清零，但阻塞成本仍高 |

业务结果方面，四轮均保持 `14/14` step 执行成功，原因是 shadow 不改变主路由。质量报告中仍有 `2` 个 fail，都是阻塞 shadow 拉长了“确认”类 guard 的耗时，超过 case 的 `5s` maxElapsed 门槛，不是回复内容或动作边界失败。

### 10.3 结论

当前不能把轻量 LLM 语义路由放到全量阻塞主路径：

- 即使使用 DeepSeek V4 Flash Non-think，8 秒 timeout 仍占一半。
- 对 `确认` / `apply` 的授权不能交给 LLM 判定，必须继续由 `conversation_phase.pending`、版本和轮次守护决定。
- 现有 full-context router prompt 太重，路由模型需要读历史、pending、方案摘要、分数画像，单次调用成本还没有低到可全量前置。
- semantic frame 对专业比较、局部查询、政策/要求类场景的映射还不够精细，直接替换会丢失当前 fast route 的业务边界。

建议的下一步不是继续换一个模型硬接管，而是：

1. 保持 `SEMANTIC_ROUTER_BLOCKING=false` 作为默认，继续 shadow 记录 route confusion matrix。
2. 缩短 router prompt，只给用户输入、最近可见上下文、pending 摘要和必要方案 summary。
3. 用 deterministic guard 与当前稳定 fast route 先行；只在候选冲突或低置信场景启用短超时 semantic arbitration。
4. 对 `apply`、工作台联动和偏好写入保持确定性安全门禁，LLM 只能提供语义解释和候选建议。
5. 后续用 80+ dialogue-derived 与历史 e2e 全量门禁评估 selective 接管，不以 14 step 小样本作为替换依据。

### 10.4 输入压缩复核

为了确认 timeout 是否主要由上下文过大导致，本轮将 router prompt 改成预算内完整 JSON 压缩：

- 保留 `userPrompt / pending / planningSummary / scoreDetail` 核心字段。
- 最近对话只保留近 2 条短文本，超预算时直接移除。
- 风险、地域、专业等列表只保留少量短摘要。
- 超预算时分级降级 planning summary，而不是截断序列化 JSON。
- shadow 结果记录 `promptChars`，方便和耗时对照。

小规模 Non-think probe：

| 输入 | promptChars | semantic status | router 耗时 | 业务路由 |
| --- | ---: | --- | ---: | --- |
| 看看现在的方案，给我一个结构化一点的结论 | 368 | timeout | `8002ms` | `plan_fast_route` |
| 按院校层次排序 | 453 | timeout | `8002ms` | `plan_fast_route` |
| 法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好 | 618 | success | `4865ms` | `major_compare_fast_route` |
| 确认 | 1124 | timeout | `8001ms` | `plan_confirmation_guard_no_pending` |

结论：prompt 压缩后输入已经足够小，但 DeepSeek V4 Flash Non-think 仍存在明显 timeout。后续性能优化不能寄希望于“把全局 LLM 路由放到每一轮最前面”，而应走 selective arbitration：

- 高置信 plan/query/intent/compare/career 仍由本地 fast route 和确定性 resolver 先处理。
- semantic router 默认非阻塞，仅用于记录和评估。
- 只有多个候选冲突、当前规则信心不足且回复质量可能受影响时，才用短超时 semantic router 辅助仲裁。
- 仲裁失败或超时时直接回当前稳定路径，不阻塞用户回复。

### 10.5 Selective Arbitration 实施口径

第一阶段只做观测，不改变用户侧行为：

```text
fast routers 产出候选
  -> fast_route_arbitrator 选择当前真实路径
  -> 同时判断 semanticArbitrationNeeded
  -> routeDecision.arbitration 记录触发原因和候选路径
  -> 当前真实路径继续执行，不等待 LLM
```

触发原则：

| 类型 | 是否触发 | 原因 |
| --- | --- | --- |
| 单一高置信候选 | 否 | 现有 fast route 已稳定，额外 LLM 只会增加延迟 |
| 多候选但分差很大 | 否 | 本地仲裁已有明确赢家 |
| 多候选且分数接近 | 是 | 存在真实语义冲突，适合作为 semantic arbitration 候选 |
| 所有候选被 quality gate 拦住 | 是 | 本地规则知道“不能走薄路径”，但还需要更好分类或澄清 |
| intent 与 plan/explore 混合 | 是 | 容易出现“看影响 / 别碰 / 能接受”这类软硬意向和只读分析混合 |
| confirmation / apply | 否 | 必须由 pending 状态机决定，不让 LLM 仲裁执行权限 |

当前版本只记录：

- `semanticArbitrationNeeded`
- `semanticArbitrationReason`
- `semanticArbitrationCandidatePaths`

后续若要真正接入 LLM 仲裁，需要额外增加短超时策略、失败 fallback、semantic route 到当前 resolver 的映射，以及 case 级 route confusion matrix 门禁。

实施复核：

- `dialog_regression_303_effect_perf_cases.json` 在 semantic router 关闭、只保留本地 fast-route 仲裁时复跑 `14/14` 通过，median 约 `2281ms`，p95 约 `5771ms`，没有引入阻塞 LLM 等待。
- 当前新增字段已经进入服务端 `conversation_turn_event.routeDecision.arbitration` 结构化日志。
- 已新增内部历史消息 `model_name=route-observability`，用于把 fast-route 成功路径的 `conversation_turn_event.routingPath` 与 `routeDecision.arbitration` 落入本地 SQLite 历史，`dialog_regression_runner.py` 可直接提取 `turnObservability.routeDecision / fastRouteArbitration`。
- `build_runtime_history` 会过滤 `semantic-router-shadow` 与 `route-observability` 两类内部观测消息，确保它们不会进入后续主模型上下文，也不会影响用户可见回复。
- 当前内部历史观测优先覆盖 `plan_fast_route / plan_query_fast_route / major_intent_fast_route / major_compare_fast_route / career_direction_fast_route / region_safety_tradeoff_route`。full-agent 路径的 token、toolCalls 和 routeDecision 仍以服务端结构化日志为准，后续如果需要统一离线报告，可继续把 full-agent turn event 也落为内部观测消息。
- `dialog_regression_runner.py` 已在 metrics summary 中新增 `fastRouteArbitration` 汇总，包括 observed、semanticArbitrationNeeded、selectedPaths、neededReasons、candidatePaths 和前 10 个需仲裁样例。
- 复跑 `dialog_regression_303_effect_perf_cases.json`，输出 `/private/tmp/zhiyuan_303_effect_perf_arbitration_distribution.json`：`14/14` steps 通过，median `2237ms`，p95 `3623ms`，max `4142ms`；其中 10 个 fast-route 观测全部 `semanticArbitrationNeeded=0`，路径分布为 `plan_fast_route=6 / plan_query_fast_route=1 / career_direction_fast_route=1 / major_compare_fast_route=1 / major_intent_fast_route=1`。结论是当前稳定高置信路径不应接入阻塞 LLM 仲裁，下一步要在 dialogue-derived 和开放口语 case 中寻找真实混淆样本。
- 本轮日志中观察到意向确认后候选 total 查询返回 `None` 的 warning，但业务回复和状态写入成功，暂列为独立观察点；它不属于 selective arbitration 主问题。
- 复跑 `dialog_regression_303_open_quality_cases.json`，输出 `/private/tmp/zhiyuan_303_open_quality_arbitration_distribution.json`：`23/23` steps 通过，median `2203ms`，p95 `3773ms`，max `4229ms`；19 个 fast-route 观测全部 `semanticArbitrationNeeded=0`，路径分布为 `major_intent_fast_route=2 / career_direction_fast_route=5 / major_compare_fast_route=6 / plan_query_fast_route=2 / plan_fast_route=4`。结论同上：开放口语基线中的高置信路径不需要额外 LLM 仲裁。
- 直接跑 80+ `dialog_regression_303_dialogue_derived_cases.json` 时，首批开放探索 case 进入 `full_agent`，服务端分别出现约 `163s` 与 `152s` 的完整 Agent 两次远端模型调用，runner 在 `120s` response timeout 后断开。示例：`一模二模差挺多，这个成绩波动填志愿咋看` 走 `full_agent`，`llmRequests=2`、`inputTokens≈16063`、`totalDurationMs≈163390`；`孩子数学忽高忽低，理工还能不能碰` 走 `full_agent`，`llmRequests=2`、`inputTokens≈16350`、`totalDurationMs≈152079`。
- 这类问题不是 fast-route 多候选冲突，也不是 selective arbitration 能直接解决的问题；它暴露的是开放 Explore / score-profile 类问题缺少轻量结构化回复路径，导致完整 Agent 大上下文和两次远端模型调用。后续 80+ 评估应先按场景分层抽样运行，并把 `score_profile / eligibility_constraints / generic_explore` 这类 full-agent 慢路径列为专项优化，不应为了绕开慢请求而把所有请求前置给 LLM 路由。

### 10.6 Score/Profile 开放探索慢路径专项设计

问题边界：

- 真实对话派生样本里，`一模二模差挺多，这个成绩波动填志愿咋看`、`孩子数学忽高忽低，理工还能不能碰` 这类问题本质是只读策略解释，不需要改偏好、不需要移动方案、不需要候选联动。
- 现有完整 Agent 会带入较大的方案上下文并发生两次远端模型调用，实测可到 `150s+`，用户侧表现为长时间无结果。
- 这类问题不是“多 fast route 混淆”，也不是“需要 LLM 路由仲裁”的典型场景；它缺的是一个可靠的只读承接层。

当前结论：

- 不应把这类问题继续做成关键词 fast route。`成绩波动 / 压线 / 单科忽高忽低` 的真实表达非常发散，逐 case 补词会造成不可持续的规则债；用户换成“擦线、悬着、发挥飘、数学掉链子、分不稳”等说法时仍可能漏路由。
- 在语义接管质量没有通过 80+ dialogue-derived、历史 regression 和 e2e 门禁前，开放 score/profile 问题继续回完整 Agent，宁可慢一些，也不要用脆弱规则误判或漏判。
- 性能优化的正确方向是先建设 `SemanticIntentFrame` 的可评估分类能力，再做有置信度门槛的选择性接管。

后续设计范围：

- 稳定确定性路径继续保留：Plan 查询/调整、Intent preview/confirm、专业对比、职业方向有限 taxonomy 和 pending guard 不交给 LLM 执行权限判断。
- 对未命中稳定 fast route 的开放探索输入，先由 semantic router 输出结构化语义帧：`taskLayer / topic / verb / sideEffect / confidence / requiredFacts`。
- 只有语义帧满足 `taskLayer=explore`、`topic=score`、`verb=analyze|explain|recommend`、`sideEffect=readonly`、`confidence >= 0.85`，且没有 pending/apply/plan mutation 语义时，才允许进入结构化 score/profile 分析。
- 低置信、语义冲突、包含方案动作、包含意向写入、具体院校录取查询或政策资格查询时，不接管，回完整 Agent 或先澄清。
- 回复形态必须保持信息量，至少覆盖“结论 / 判断方法 / 填报影响 / 下一步”，避免为了性能把回复压成薄模板。

路由边界：

| 输入类型 | 处理 |
| --- | --- |
| `一模二模差挺多，这个成绩波动填志愿咋看` | 先由 semantic frame 判断为 score/readonly/analyze；通过质量门禁后再接管 |
| `孩子数学忽高忽低，理工还能不能碰` | 先由 semantic frame 判断为 score/readonly/analyze；通过质量门禁后再接管 |
| `分数刚压本科线，别给我画大饼` | 先由 semantic frame 判断为 score/readonly/analyze；通过质量门禁后再接管 |
| `550 分能上北京大学吗` | 不接管，属于具体院校录取查询 |
| `按这个成绩波动帮我调整方案` | 不接管，属于方案调整预览/执行 |
| `数学不好，以后不要数学相关专业` | 不接管，属于意向/要求写入 |

验证要求：

- 先做 shadow/评估，不直接主路径接管：验证 semantic frame 对 score/profile、policy/requirement、career、major compare、plan query 和 intent 的混淆率。
- case 必须覆盖真实口语、简称、省略、家长表达、负向要求和动作混合表达；不能只覆盖已经见过的 2-3 个句子。
- 通过标准应同时看路由正确率、回复质量、确认边界、无误联动和延迟；如果 semantic 分类不稳，继续回完整 Agent。
- 后续 80+ dialogue-derived 评估按场景分层运行，避免开放 Explore 慢 case 阻断全量报告，同时保留这些慢 case 作为 semantic 接管候选的重点评估样本。

### 10.7 分级路由落地状态

本期先把“分级路由”落为可评估框架，不直接改变主链路执行结果：

```text
L0 确认/安全守卫
  - conversation_phase.pending、版本漂移、确认/取消等状态机判断
  - 负责 apply 权限，不交给 LLM

L1 稳定确定性 fast route
  - plan_fast_route / plan_query_fast_route
  - major_intent_fast_route / major_compare_fast_route
  - career_direction_fast_route / region_safety_tradeoff_route
  - 命中高置信路径时继续按现有链路执行

L2 SemanticIntentFrame shadow/evaluation
  - 对 taskLayer / topic / verb / sideEffect / confidence 做结构化观测
  - 评估工具按 case coverage 推导 expectedSemanticFrame
  - 只产出 mismatch / unverified 指标，不接管执行

L3 full_agent fallback
  - 未命中稳定路径、开放 Explore、复杂混合语义继续回完整 Agent
```

这次没有新增 score/profile 的关键词 fast route。原因是该类真实表达高度发散，靠“成绩波动/压线/数学忽高忽低”等词补丁只能解决个别句子，并会继续制造漏判和误判。当前 3.0.3 的范围收缩为：

- 只把“高置信、固定类型、回复质量稳定且能明显节省延迟”的场景作为快捷入口，例如明确方案查询、明确方案排序/移动/删除/加入、明确专业对比、明确意向确认、明确职业方向只读分析。
- 其他非高置信场景，包括开放 Explore、弱承接、闲聊、信息不足、跨领域混合表达，继续交给原 Agent 自行判断、调用工具和组织回复。
- 三类场景边界作为后续设计理解保留：明确直连 tool/skill、领域内需要 skill 多级编排、与当前工具无关的闲聊承接。但本版本不把它实现成新的运行时 schema 或接管路由，避免扩大覆盖范围后引入误路由。
- `fast_route_arbitrator` 增加 `fixedScenario` 白名单，只有以下细分场景可以作为快捷入口；matched 但不在白名单的候选会被挡回 full Agent：
  - `plan.status_overview_readonly`、`plan.safety_status_readonly`、`plan.risk_status_readonly`、`plan.explicit_review_readonly`。
  - `plan.explicit_sort_preview`、`plan.numeric_*_move/remove_preview`、`plan.named_*_move/remove/add_preview`。
  - `plan.review_issue_adjustment_preview`、`plan.review_issue_compensation_preview`、`plan.colloquial_adjustment_preview`。
  - `plan_query.plan/candidate/plan_then_candidate_local_lookup_readonly`。
  - `major_compare.exact_two_level3_readonly`、`major_compare.exact_three_level3_readonly`。
  - `intent.catalog_major_preference/constraint/mixed_preview`。
  - `career_direction.local_taxonomy_readonly_analysis`、`region_safety.structured_tradeoff_readonly`。
- 明确不作为固定入口的例子：`物理不太好但选了物化地，计算机还现实吗` 这类专业适配/分数画像混合问法不走专业对比；`英语还行但总分不稳，专业上能不能利用一下` 这类开放策略问法不按 topic=major 直接接管。
- `dialog_case_evaluation_report.py` 支持 `expectedSemanticFrame`，并允许字段有多个合理取值，例如 `verb=analyze|explain|recommend`。
- 若 semantic shadow 成功返回但 frame 与期望不符，报告计入 `semantic_frame_mismatch`，用于判断语义路由是否可靠。
- 若 semantic shadow 未启用、排队、超时或报错，只记 `semantic_frame_unverified:*` warning，不把用户可见回复误判为失败。
- `dialog_regression_303_dialogue_derived_cases.json` 通过 coverage 自动获得语义期望，覆盖 score/profile、policy/requirement、major、region、career、budget、plan review、plan operation 和 followup guard 等 80+ 场景。

当前边界：

- L2 不是线上执行路由，不能据此直接更新偏好、移动方案、排序或触发工作台联动。
- 后续若要让 L2 接管某类只读回复，必须先在 dialogue-derived、历史 regression、effect/perf 和多模型评估中证明：语义帧准确、低置信 fallback 正确、回复质量不变薄、延迟可接受。
- 确认执行、pending apply、方案变更写入仍由 L0/L1 的确定性状态机和后端执行层决定。

下一步工具化：

- 新增一个离线 semantic frame evaluator，不启动 WebSocket、不请求 LLM，只读取 case definitions 和可选 runner/report 输出。
- 未传入运行输出时，只检查 case 是否都能推导出 `expectedSemanticFrame`，并汇总期望层级分布，用于防止新增 case 漏掉 L2 评估基准。
- 传入 runner 输出时，对齐每个 `case#step` 的 `semanticRouterShadow.frame` 与 `expectedSemanticFrame`，输出 match / mismatch / unverified、按 coverage/flow 的分布和代表样例。
- 该工具只作为 L2 接管前的准入评估，不改变主链路。只有在真实 shadow 结果持续稳定后，才考虑把某些 `readonly explore` 场景接入结构化只读回复路径。

落地结果：

- 新增 `examples/semantic_frame_evaluator.py`，复用报告工具的 case expansion、coverage 推导和语义帧匹配逻辑。
- `dialog_quality_gate.py` 会为每个 live case 文件追加 `semantic-frame-*` 报告命令，依赖对应 live 输出。
- `dialog_quality_gate.py` 的 local gate 会过滤当前 checkout 中已经不存在的历史测试目标，避免 3.0.3 撤回 fast-route/semantic-router 运行时代码后，评估入口仍被旧测试文件名卡住。
- 对 `dialog_regression_303_dialogue_derived_cases.json` 执行 expected-only 检查：`total=88 / expectedTotal=88 / comparableTotal=0`，说明 88 个真实对话派生样例都具备 L2 语义期望。
- 当前期望分布：`taskLayer` 包含 `explore=49 / plan=36 / intent=15 / general=9`，`sideEffect` 包含 `readonly=70 / preview=18 / none=9`。部分 case 允许多个合理层级或动作，因此分布计数会大于 case 总数。

2026-05-28 继续增加 `examples/semantic_frame_probe.py`，用于直接调用 `SemanticIntentRouter.route_shadow` 生成 runner 兼容 records。该 probe 只验证 L2 语义帧，不跑完整 Agent，也不触发 planning 工具。

小样本结果：

- 初版 score/profile 5 条 probe：4 条成功但全部 mismatch，1 条 timeout。主要错在 `score_profile` 被模型判成 `policy / major / intent`，以及评估期望把 `score_profile + risk_summary` 误推成 plan review。
- 修正 semantic prompt 后，同一 score/profile 5 条复跑：4 条成功全部 match，1 条 timeout；成功耗时约 `3.3s-6.0s`。
- 混合 20 条 dialogue-derived probe：初评 `comparableTotal=14 / match=10 / mismatch=4 / timeout=6`。其中 4 个 mismatch 复盘后主要是评估口径过窄：专项/体检/视力类允许 `policy/query`，文史政地就业面允许 `career`。
- 修正 coverage 期望优先级后，用同一份 20 条 probe 输出重评估：`comparableTotal=14 / match=14 / mismatch=0 / timeout=6`，`matchRate=1.0`。
- 按“先不设置超时，只记录效果和返回延迟”的口径，将 `timeout_seconds=0` 作为无超时 probe 模式：同一 20 条混合样例完整返回后为 `comparableTotal=20 / match=20 / mismatch=0 / unverified=0`，`matchRate=1.0`；延迟 `median=9123ms / p95=32206ms / max=62839ms`。
- 百家平台 `deepseek-v4-pro` 非思考模式无超时 20 条混合样例结果：`comparableTotal=19 / match=16 / mismatch=3 / unverified:error=1`，`matchRate=0.8421`；延迟 `median=9970ms / p95=13708ms / max=13912ms`。3 个 mismatch 主要暴露“单句可被多种领域承接”的评估边界，例如英语优势+总分不稳可被判为 `major` 或 `score`，涨分是否留冲空间可被判为 `plan` 或 `score`；因此 3.0.3 不扩大接管范围，只让高置信固定类型走快捷入口，其他继续回原 Agent。

当前结论：

- score/profile 的语义边界已明显改善，但样本仍小，不能据此接管主链路。
- 不设超时后，DeepSeek V4 Flash Non-think 在 20 条混合样例上的分类效果可用，但真实延迟长尾严重，最长超过 `60s`；后续要继续比较更轻/更稳的路由模型，或做 selective、失败 fallback，不能全量阻塞接管。
- 当前 L2 继续保持 shadow/evaluation；真正可接管前，至少需要覆盖 88 条 dialogue-derived、effect/perf、open-quality 和多模型场景，并同时满足分类准确率与超时率门槛。

## 11. 重置后的待确认决策

需要确认后再进入代码实现：

1. 是否同意 `3.0.3` 优先做 Agent 效果和性能，不再继续扩 UI 范围。
2. 是否同意以 `prod-3.0.2` full agent 88 case 基线作为当前事实基准，不再用混入历史 fast route 的输出判断当前效果。
3. 是否同意先落观测和评估器校准：拆出每次 LLM、每个工具、工具内部 LLM、首响、最终回复和输入 token 来源。
4. 是否同意先修 full agent 工具边界和提示词，例如专业对比不追加专业兴趣分析、职业方向命中后不重复 `load_skill`、方案链路不重复读取上下文。
5. 是否同意后续任何结构化入口、小模型 semantic route 或 renderer 都必须先通过 80+ dialogue-derived、历史 regression、effect/perf、open-quality 和多模型质量评估，再决定是否接回主路径。

确认后建议先进入“观测 + 评估器校准 + 分层复跑”阶段。Plan/Explore/Intent 的结构化入口可以作为候选方案保留，但不直接恢复历史运行时代码，也不继续补逐 case 字符串规则。

## 12. Full Agent 内部工具调用收口

### 12.1 Intent 恢复阶段正负抽取合并

问题：

- 在 full agent 主链路里，意向预览工具本身已经是明确业务路径，例如专业意向预览、地域意向预览。
- 当模型调用 preview 工具但没有传结构化 `major_intents/city_intents` 时，`analyze_volunteer_intent_change` 会按 `recovery_scope` 从最新用户输入恢复意向。
- 之前专业 scope 会连续调用 `extract_major_intent` 和 `extract_negative_major_intent`，地域 scope 会连续调用 `extract_city_intent` 和 `extract_negative_city_intent`。这属于同一条已确定链路中的重复语义抽取，会增加一次模型请求延迟。
- 这不是路由问题，也不应该用字符串 fast route 解决。用户可能说“法学可以，护理别放”“北京周边能看，上海算了”等混合表达，正负意向需要一起判断。

设计：

- 新增工具内部组合抽取入口：
  - `extract_major_intents_with_polarity`：一次模型请求返回 `positive` 和 `negative` 两个专业意向结构。
  - `extract_city_intents_with_polarity`：一次模型请求返回 `positive` 和 `negative` 两个地域意向结构。
- 仅在 `_recover_intents_from_context` 的 recovery 分支使用组合抽取：
  - `recovery_scope=major` 或 `generic` 的专业恢复优先用组合抽取。
  - `recovery_scope=region/city` 或 `generic` 的地域恢复优先用组合抽取。
- 保留旧的 `extract_major_intent / extract_negative_major_intent / extract_city_intent / extract_negative_city_intent`：
  - 其他直接调用不受影响。
  - 组合抽取输出格式异常、模型异常时，自动回退到旧的正负单抽取，保证质量和稳定性优先。
- 不改变 full agent 主路由，不新增关键词路由，不恢复 semantic router 接管。

用户侧影响：

- 对“我倾向法学和财政学，但护理不要”这类正负混合意向，仍会进入确认卡片流程，用户确认后再写入偏好/要求。
- 对“更想去北京，上海不要”这类地域混合意向，仍保持正负意向分开呈现和候选过滤语义。
- 正常情况下少一次工具内部 LLM 请求；组合抽取失败时宁可慢一点，也回退到旧链路。

验证：

- 新增组合抽取单测覆盖专业和地域的正负同轮解析。
- 新增 recovery scope 单测验证：
  - `major` scope 优先调用一次 `extract_major_intents_with_polarity`，不调用旧正负抽取。
  - `region` scope 优先调用一次 `extract_city_intents_with_polarity`，不调用旧正负抽取。
  - `career_preference` 和 `school` scope 不触发专业/地域组合抽取。
  - 组合抽取异常时回退旧正负抽取。
- 聚焦测试：`tests/unit/test_major_intent_tool.py tests/unit/test_city_intent_tool.py tests/unit/test_intent_state_tool.py`，`167 passed`。
- 扩展 Agent 回归集合：`test_major_recommend_tool / test_compare_resolution / test_explore_direction_scenarios_sync / test_dialog_scenario_stability / test_intent_state_tool / test_chat_service_history_persistence / test_base_agent / test_chat_agent_tools / test_chat_agent_init_profile / test_instructions`，`316 passed`。

### 12.2 职业方向只读分析不再硬编码体制内

问题：

- `preview_interest_analysis_from_request(recovery_scope="career_preference")` 是只读 Explore 入口，用于“体制内适不适合我 / 稳定就业值不值得 / 读研和稳定哪个更适合”等方向分析。
- 旧实现只要 scope 是 `career_preference`，就直接调用 `preview_direction_analysis_from_request(..., system_public_service)`。
- 这会导致用户问“稳定就业适不适合我”或“读研和稳定就业哪个更适合”时，也被兜成体制内方向分析，属于回复正确性问题。

设计与实现：

- 进入 career scope 后先调用 `_resolve_career_direction_slots(request_context)`：
  - 解析出 1 个方向时，按真实 slot 调用单方向分析。
  - 解析出多个方向时，调用方向对比分析。
  - 解析不到时，保留原体制内兜底，兼容旧的 scope-only 调用。
- 这不是意向写入，也不会创建 pending；仍是只读 Explore 分析。
- 不新增字符串路由，不扩大职业意向确认的本地规则，避免把“适不适合 / 先看看”误写成偏好。

验证：

- 新增单测覆盖：
  - `稳定就业适不适合我` 使用 `stable_employment` 单方向分析。
  - `稳定就业和读研哪个更适合` 使用多方向对比。
  - 原体制内路径保持兼容。
- 职业/意向/Explore 聚焦回归：`tests/unit/test_intent_state_tool.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_explore_direction_scenarios_sync.py`，`146 passed`。
- 扩展 Agent 回归集合：新增合并抽取、职业方向修复、Compare/Recommend/Service/Instructions 相关测试共 `392 passed`。

### 12.3 评估 gate 清单同步

问题：

- 3.0.3 过程中撤掉了旧 fast-route / semantic-router 运行时代码和对应测试文件，但 `dialog_quality_gate.py` 的 `LOCAL_PYTEST_TARGETS` 里仍残留部分旧文件。
- 这会导致后续执行 `dialog_quality_gate.py --execute --mode local` 时，因为 pytest 收到不存在的测试路径而失败，影响本地评估流程可信度。

实现：

- 新增 `_existing_local_pytest_targets()`，构建 local gate 计划时只纳入当前 checkout 实际存在的 `tests/...` 目标。
- dry-run 和 execute 使用同一套过滤后的命令，避免计划看起来可用但执行失败。
- 新增单测验证 local gate 不包含已删除的 `test_semantic_router.py / test_major_intent_fast_router.py / test_plan_query_fast_router.py / test_fast_route_arbitrator.py`，且所有 `tests/` 目标都存在。

验证：

- `tests/unit/test_dialog_quality_gate.py`，`7 passed`。
- 生成 local gate dry-run：`/private/tmp/zhiyuan_303_quality_gate_local_plan.json`，包含 `19` 个存在的测试目标，`missing=[]`。
- 相关回归集合：`476 passed`。
- `py_compile` 和 `git diff --check` 通过。

### 12.4 待确认意向与方案预览回复边界复测

本轮补充真实 WebSocket 小样本，重点不只看耗时，也看最终回复是否对用户有用、是否误触发工作台联动。

初始 smoke：

- case 文件：`/private/tmp/zhiyuan_303_quality_smoke_cases.json`，覆盖 `plan / intent / explore / career / sort preview`，共 `8` 个 case、`9` 轮。
- 输出：`/private/tmp/zhiyuan_303_quality_smoke_live.json`。
- 结果：`successfulSteps=9 / failedSteps=0`，但延迟 `median=37637ms / p95=115282ms / max=115282ms`。
- 回复质量：方案概览、专业对比、职业承接、压线保底等正文已经明显优于旧的“方案情况如下”拼接式回复，能够给出结论、依据、风险和下一步。
- 问题：
  - `preview_current_major_intent_confirmation` 后仍发送 `planningWorkspaceAction(candidate)`，确认前让前端看起来像候选库已经跟随未确认偏好联动。
  - 待确认偏好的二轮追问缺少稳定的“尚未确认 / 确认前不会写入后续参考”边界。
  - 排序预览有时只说“会改变顺序和导出顺序”，缺少排序方向、前几项变化、冲稳保结构等用户需要判断的信息。
  - Explore 类场景仍有 70s-115s 长尾，例如专业对比和职业方向承接。

修复：

- 意向预览阶段不再自动追加候选库刷新卡片；只有用户确认/勾选后真正采纳约束，才继续通过 `candidateFilters` 联动候选栏。
- 对存在待确认意向的只读追问，后处理兜底追加用户可见边界：“待确认内容 / 尚未确认 / 确认前不会写入后续参考”。
- 该边界限定为意向场景：如果本轮已经走 `plan_next_action -> execute_plan_action` 的方案链路，不把意向 pending 尾巴追加到排序、审查、移动、删除等方案回复里。
- `sort_ordered_plan` 预览阶段补充结构化事实：排序字段、自然排序方向、当前数量、冲稳保分布和排序后前几项示例；确认前不执行后端排序。

复测：

- 意向 + 排序复测输出：`/private/tmp/zhiyuan_303_quality_fix_verify_live_after_restart.json`。
  - `successfulSteps=3 / failedSteps=0`。
  - 意向首轮 `followupMessages=0`，确认前不再联动候选。
  - 二轮影响分析包含“尚未确认 / 确认前不会写入后续参考”。
  - 延迟 `min=21551ms / median=22160ms / max=49023ms`，仍偏高。
- 排序边界单独复测：`/private/tmp/zhiyuan_303_sort_preview_after_boundary_fix.json`。
  - `elapsedMs=27887`，`followupMessages=0`。
  - 回复包含推荐系数降序、当前 `94/96`、排序后前几位示例、导出顺序影响、审查待重新审查、以及“冲66 / 稳28 / 保0 仅靠排序不能解决”的风险提醒。
  - 不再追加“待确认偏好”尾巴，说明方案链路和意向 pending 边界已隔离。

验证：

- 聚焦单测：意向预览不刷新候选、待确认追问补边界、约束采纳后仍可联动候选、排序预览有分布与示例，`6 passed`。
- 相关回归：`tests/unit/test_chat_service_history_persistence.py`、排序预览相关 `test_plan_execution_tool`、`test_dialog_scenario_stability.py`，`137 passed`。

遗留：

- 真实回复质量已改善，但 full agent 长尾仍明显。日志里排序预览仍有 `3` 次 LLM 请求、约 `28k` tokens；专业/职业 Explore 场景最高超过 `100s`。后续继续优先优化 full agent 工具链和上下文裁剪，不用字符串快路由替代质量判断。
- runner 中部分 `assertThinkingContains` 仍绑定旧固定进度文案，实际回复正文已经满足用户边界；后续应把 thinking 断言改成语义类断言，避免进度提示文案优化造成误报。

#### 12.4.1 当前代码 live 复测与边界修正

本轮继续回到当前 full agent 主路径验证，未恢复字符串 fast route，也未启用小模型路由接管。

复测结果：

- 专业简称对比：`法和财哪个更适合女孩子，家里一般`
  - 输出：`/private/tmp/zhiyuan_303_major_compare_current_live.json`
  - 路由：`routingPath=full_agent`，工具只调用 `compare_majors`，未再出现旧输出里的 `load_skill`、`analyze_current_career_direction` 或重复 `get_major_introduction`。
  - 回复质量：正文能围绕家庭经济容错、职业门槛、考公路径、转行兜底给出结构化判断，结论是“普通家庭想更稳可优先看财务/会计类，法学更适合能接受考研+法考长期投入的人”。
  - 性能：`elapsedMs=36374`，`firstMessageMs=3039`。质量可用，但 full agent + 工具 + 最终组织仍慢。
- 专业简称对比长耗时提示复测：同一输入复跑到 `/private/tmp/zhiyuan_303_major_compare_long_progress_live.json`
  - 性能：`elapsedMs=30483`，`firstMessageMs=3038`。
  - thinking：包含“正在理解你的问题”“正在对比这几个专业的差异”“这轮分析耗时较长...”三段提示，说明长耗时期间用户能持续感知系统仍在处理。
  - 回复质量：正文仍保持结构化，围绕法学、金融/财会、普通家庭容错、考公和直接就业分别给出判断，没有因为补进度提示而退化成薄回复。
- 考公/稳定方向：`想稳点以后考公 这版支撑吗`
  - 输出：`/private/tmp/zhiyuan_303_career_plan_support_boundary_fix_live.json`
  - 路由：`routingPath=full_agent`，工具调用 `collect_plan_context_inputs -> preview_current_career_intent_confirmation`。
  - 性能：`elapsedMs=26720`，`firstMessageMs=3037`。
  - 当前限制：本地 `INTERNAL_SERVICE_URL=http://localhost:8080` 未启动，Agent 读取方案状态失败，因此回复降级为“目前还没有正式方案”。这不能作为方案承接质量结论，只能用于验证边界和工具选择。

新发现问题：

- 当本轮进入 Plan 只读查询（如 `query_state`），但回复里提到“确认考公偏好”时，原有 `_append_plan_preview_confirmation_boundary` 会把“回复确认”误判成方案调整确认，追加“还没有拿到可执行的调整预览”的尾巴。
- 这会把“意向待确认”和“方案调整待确认”混在一起，用户会误以为系统正在准备改方案。

修复：

- 新增 `_tool_returns_plan_mutation_context()`，只在本轮工具返回属于方案变更上下文时，才允许追加“没有可执行调整预览”的保护文案。
- 只读 Plan 查询（`query_state/query_draft/query_ordered/query_candidates`）不会再因为回复中存在“确认偏好”而触发方案调整边界。
- 保留原保护能力：对 `replace_units/remove_units/sort_ordered_plan/preview_compensation/analyze_adjustment` 等确实属于方案变更或调整分析的场景，如果模型说“回复确认即可执行”但没有可复用 preview payload，仍会清理未支撑的确认执行文案并追加安全边界。
- 补充 full agent 长耗时进度提示：在初始提示和工具提示之外，超过约 `12s / 25s` 且近期没有新提示时，继续发送“还在处理 / 这轮分析耗时较长”的用户可理解提示。该改动不改变路由和回复内容，只改善长等待期间的可感知状态。

验证：

- 单测：`test_plan_preview_confirmation_boundary_corrects_confirm_copy_without_pending_payload`、`test_plan_preview_confirmation_boundary_ignores_intent_confirm_copy_on_query_state`、`test_plan_preview_confirmation_boundary_removes_unbacked_replace_confirm_section`、`test_plan_preview_confirmation_boundary_removes_immediate_execute_copy_without_payload`，`4 passed`。
- 进度提示单测：`test_chat_service_emits_initial_progress_when_full_agent_is_silent`、`test_chat_service_does_not_duplicate_initial_progress_after_tool_progress`、`test_chat_service_emits_long_running_progress_for_slow_full_agent`，`3 passed`。
- live 复测：`/private/tmp/zhiyuan_303_career_plan_support_boundary_fix_live.json` 中已不再出现“还没有拿到可执行的调整预览”，只保留“待确认内容 / 尚未确认 / 确认前不会写入后续参考”的意向边界。

后续判断：

- 当前最主要的性能瓶颈仍是 full agent 每轮需要带完整工具 schema 与指令，简单问题输入 token 约 `16k`，再叠加工具后最终组织，容易落到 `25s-40s`。
- 这轮不通过关键词抢路由来压延迟；下一步优先做两件事：
  1. 在本地 Server/Rank 可用时复跑方案类 case，避免“后端未启动导致空方案”的假结论。
  2. 继续从 full agent 工具面和上下文面优化，例如减少重复上下文读取、裁剪不必要工具暴露、把长耗时 case 的 progress hint 做到更连续。

#### 12.4.2 正负专业意向混合表达长尾

新增真实口语 case：

- 输入：`医学护理这些别碰，财会还能接受，先看看影响`
- 首次输出：`/private/tmp/zhiyuan_303_mixed_major_intent_live.json`
- 问题：
  - full agent 连续多次重复进入专业意向预览链路，每次又触发 `extract_major_intents_with_polarity`，最终到 `180s` 超时。
  - 抽取候选层级只包含“医学/护理”相关内容，没有包含“财会”相关专业，因此正向“财会还能接受”被漏掉。
  - 超时兜底文案过泛，还举了“计算机方向”的无关例子，用户侧会感觉系统没有理解当前问题。

修复与设计边界：

- 专业层级候选过滤补充受控领域别名扩展：`财会/财管/会计/财务` 扩展到 `工商管理类 / 会计学 / 财务管理 / 审计学`，`新传` 扩展到新闻传播相关，`跨电` 扩展到电子商务相关。该逻辑只用于实体候选召回，不做路由决策。
- 专业简称归一化新增集中维护的常用表：确定性简称（如 `计科 -> 计算机科学与技术`、`软工 -> 软件工程`、`AI -> 人工智能`、`国贸 -> 国际经济与贸易`、`口腔 -> 口腔医学`）可在分数线查询、选科校验等 `resolve_major_names_async` 链路本地前置命中；多目标简称（如 `财会`、`大数据`）只用于候选召回，不在 level3 normalize 中强行落到某一个专业，避免误查分数线或误做选科校验。
- `extract_major_intents_with_polarity` 提示补充“财会/财务/会计/财管”的匹配规则，避免模型在候选已召回时仍漏掉正向意向。
- `preview_current_major_intent_confirmation` 工具描述补充混合输入示例，要求用户已经说清目标时直接传 `major_intents`，不要无参数重复调用。
- Tool dispatch rules 补充硬边界：`preview_current_*_intent_confirmation` 返回后，本轮直接基于工具结果回复用户并等待确认，不要重复调用同一个 preview 工具。
- WebSocket 超时兜底改为引用用户原问题，并明确“这轮还没有拿到完整分析结果，也不会自动写入偏好或改动方案”，不再输出无关示例。

验证：

- `tests/unit/test_major_utils.py` 覆盖“财会还能接受”可召回工商管理类、会计学、财务管理及负向护理学类。
- `tests/unit/test_score_and_validation_normalization.py` 覆盖 `计科/国贸/AI/口腔` 在分数线/选科校验 normalize 前置命中，且 `财会/大数据` 这类多目标简称不会被硬归一到单一 level3 专业。
- `tests/unit/test_instructions.py::TestToolDispatchRules::test_intent_preview_tool_boundaries_stop_after_preview` 验证调度规则包含 preview 后停下的约束。
- `tests/unit/test_ws_compat.py` 超时兜底回归验证保留原用户问题和无副作用边界。
- 聚焦测试：`12 passed`。

复测说明：

- 复测输出：`/private/tmp/zhiyuan_303_mixed_major_intent_after_alias_live.json`。
- 本次复测仍在 `180s` 超时，但日志显示首轮模型请求本身没有完成，没有进入工具调用阶段，因此这次不能证明重复 preview 已解决或未解决；它说明当前供应商/模型还有首轮请求挂起的长尾。
- 针对这类“未进入工具阶段”的长尾，Agent 迭代层补充节点耗时观测：每个节点会记录 `nodeTimings`，如果被 `wait_for` 取消，会记录 `failedNode / failedNodeElapsedMs / errorType` 并写入 `conversation_turn_event.routeDecision.agentRun`。后续复跑时可以直接区分首轮模型请求挂起、工具节点慢、还是最终回复生成慢。
- 长耗时用户提示拆成两类：尚未进入工具阶段时提示“正在等待模型返回 / 不会自动写入偏好或改动方案”；已经进入工具阶段后才提示“结合工具结果整理结论”，避免用户看到与实际阶段不一致的处理中说明。
- `dialog_case_evaluation_report.py` 同步识别 `routeDecision.agentRun.failedNode`，报告中会标记 `agent_run_interrupted` 与 `first_model_request_or_final_generation_interrupted`，避免复测后只看到“超时”而看不出是否根本没有进入工具阶段。
- 评估报告进一步识别慢但成功的 Agent 节点：会输出 `slowestAgentNode`，并标记 `slow_agent_node / very_slow_agent_node / slow_before_first_tool_or_final_generation / late_first_tool_call`，用于区分“首轮模型慢”“工具调用前等待久”“工具链慢”这几类不同优化对象。
- `dialog_regression_runner.py` 在单轮请求异常时也会尝试从本地 history DB 读取该 prompt 对应的 route observability；如果服务端已写入失败观测，即使 runner 自己先超时，也能在 metrics 里保留 `failedNode` 等诊断信息。
- LLM client 新增默认关闭的 `LLM_TIMEOUT_SECONDS` 配置，`0` 表示不设置模型请求层超时，仍使用外层服务超时兜底。后续做供应商稳定性实验时可以显式设置模型请求层 timeout，让首轮模型挂起更早返回可观测错误；默认不改变当前线上行为。
- 后续需要在模型服务稳定后再复跑该 case，重点看：
  1. 是否只调用一次 `preview_current_major_intent_confirmation`；
  2. 是否识别出负向医学/护理和正向财会；
  3. 是否停在待确认回复而不是重复抽取。

复跑结论：

- 复测输出：`/private/tmp/zhiyuan_303_mixed_major_intent_observability_live.json`
- 评估报告：`/private/tmp/zhiyuan_303_mixed_major_intent_observability_eval.md`
- 输入：`医学护理这些别碰，财会还能接受，先看看影响`
- 结果：`successfulSteps=1 / failedSteps=0`，最终回复质量评分 `strong`。
- 工具链：只调用 `1` 次 `preview_current_major_intent_confirmation`，`repeatedToolNames=[]`，说明重复 preview 问题在本轮已消失。
- 识别结果：回复正确识别负向 `医学类 / 护理学类` 与正向 `财会相关（工商管理类下会计/财务管理等）`，并停在待确认状态，没有写入偏好或改方案。
- 性能：总耗时 `118792ms`，首个 thinking 约 `3042ms`，最终回复约 `116788ms`。
- 节点归因：`ModelRequestNode` 首轮约 `12991ms`，`CallToolsNode(preview_current_major_intent_confirmation)` 约 `94014ms`，最终 `ModelRequestNode` 约 `9711ms`。
- 结论：这次不是首轮模型请求挂死，也不是重复 preview；当前主要瓶颈是专业意向预览工具内部的 `extract_major_intents_with_polarity` LLM 抽取，日志显示该内部请求从 `17:07:51` 到 `17:09:25`，约 `94s`。

下一步优化对象：

1. 优先分析 `preview_current_major_intent_confirmation -> analyze_volunteer_intent_change -> extract_major_intents_with_polarity` 的内部抽取提示词、候选层级长度和模型调用配置。
2. 对已经通过候选召回明确到少量专业类/专业的输入，考虑让工具返回结构化候选事实，减少内部抽取 LLM 的上下文长度或请求次数；但仍保持待确认边界，不直接写状态。
3. 用同一 case 作为回归样例，目标是保持当前回复质量和确认边界，同时把工具节点耗时从分钟级降下来。

本轮继续修复：

- 专业意向预览工具内部新增保守本地恢复：当已经进入 `preview_current_major_intent_confirmation`，且最新用户输入在同一句里清楚表达正向/负向专业意向时，优先基于专业目录和受控别名表恢复结构化 payload。
- 支持混合正负例：`医学护理这些别碰，财会还能接受，先看看影响` 会恢复为 `negative_level1=["医学"]`、`negative_level3=["护理学"]`、`level2=["工商管理类"]`；`土木别要，计科可以` 会恢复为 `negative_level3=["土木工程"]`、`level3=["计算机科学与技术"]`。
- 该逻辑只在已进入专业 Intent 工具后生效，不作为顶层对话路由，不改变 Explore / Plan 主链路；无法在目录或别名表中稳定落位时继续回落到原来的 LLM 抽取。
- 当模型主动传入过度展开的专业 payload 时，工具会用本轮用户原话可支撑的本地结构做校正，避免把“医学别碰”展开成几十个医学下级专业，同时补回“财会还能接受”这类被漏掉的正向意向。
- Tool dispatch rules 补充语义边界：用户同时表达“排除哪些专业 / 哪些还能接受 / 看看影响”时属于 Intent 影响预览；专业意向最终回复只能复述工具 JSON 已出现的专业门类、专业类或专业，不能自行扩展相邻专业范围。

复测：

- 聚焦单测：`tests/unit/test_intent_state_tool.py` 新增本地混合恢复、简称混合恢复、过度展开 payload 校正；`tests/unit/test_instructions.py` 覆盖 Intent 影响预览和不自行扩展专业范围的指令。
- 相关回归：`206 passed`。
- 真实 WebSocket 输出：`/private/tmp/zhiyuan_303_mixed_major_intent_instruction_refine_live.json`。
- 评估报告：`/private/tmp/zhiyuan_303_mixed_major_intent_instruction_refine_eval.md`。
- 结果：`strong C5/F5/A5/L1/R4`，只调用一次 `preview_current_major_intent_confirmation`，`repeatedToolNames=[]`。
- 节点归因：首轮 `ModelRequestNode=19288ms`，`CallToolsNode(preview_current_major_intent_confirmation)=12ms`，最终 `ModelRequestNode=27397ms`，总耗时约 `48.8s`。
- 结论：原先 `94s` 的工具内部专业抽取 LLM 已从该高置信混合表达里移除；当前剩余慢点主要是外层 full agent 的两次模型请求，后续需要继续评估是否通过模型配置、回复生成约束或更轻的最终组织链路降低延迟。

临时影响说明清理复核：

- 问题：同一 case 在 direct tool return 后，仍可能把 `build_plan_relation_analysis` 生成的“我先帮你看看 / 继续看看方案匹配 / 直接让我给你调整建议”等占位句当成有效影响说明，导致用户看到没有事实支撑的“影响说明”。
- 临时修复范围：仅在 Intent 预览最终成文前清理这些已观测占位句；不参与路由、不识别用户意图、不改 pending 状态，也不影响真实方案/候选事实行。
- 单测：`test_render_intent_analysis_text_replaces_generic_impact_placeholder_for_confirmed_preview` 覆盖新旧占位句，确认会回落到“待确认、确认前不生效、不改方案”的边界说明。
- 相关回归：`166 passed`，覆盖 base agent、ChatAgent tool direct return、长耗时 progress、intent state、评估报告和 regression runner 观测链路。
- 真实 WebSocket 输出：`/private/tmp/zhiyuan_303_mixed_major_intent_direct_preview_tempfix_live.json`。
- 评估报告：`/private/tmp/zhiyuan_303_mixed_major_intent_direct_preview_tempfix_eval.md`。
- 结果：`strong C5/F5/A4/L1/R4`，无质量违规；只调用一次 `preview_current_major_intent_confirmation`，`directToolReturn=true`，`CallToolsNode=8ms`。
- 延迟归因：总耗时约 `42.8s`，首个 thinking 约 `3.0s`，最终回复约 `40.8s`；慢点集中在首轮 `ModelRequestNode=40.7s`，不是工具内部抽取，也不是重复 preview。
- 判断：临时方案已经解决“泛化影响说明泄漏”的输出质量问题；但它仍是文本占位清理。后续如果类似占位句继续扩散，应把 `impactAnalysis` 改成结构化事实/占位标记，用是否存在 `fact` 决定展示影响说明，而不是继续堆字符串。

#### 12.4.3 真实对话派生 88 case 全量复跑

本轮继续按“回复质量优先、延迟次之”的口径复跑真实对话派生集，没有恢复字符串 fast route，也没有为了性能把回复做薄。

运行方式：

- Agent：本地 `127.0.0.1:8001`，复跑完成后已停止。
- Case：`examples/dialog_regression_303_dialogue_derived_cases.json`，共 `88` 条。
- 分批输出：
  - `/private/tmp/zhiyuan_303_dialogue_derived_canary12_live.json`
  - `/private/tmp/zhiyuan_303_dialogue_derived_batch2_20_live.json`
  - `/private/tmp/zhiyuan_303_dialogue_derived_batch3_24_live.json`
  - `/private/tmp/zhiyuan_303_dialogue_derived_batch4_16_live_current.json`
  - `/private/tmp/zhiyuan_303_dialogue_derived_batch5_16_live_corrected.json`
- 汇总输出：`/private/tmp/zhiyuan_303_dialogue_derived_all88_live_current.json`
- 汇总报告：`/private/tmp/zhiyuan_303_dialogue_derived_all88_eval_current.md`

汇总结果：

- `totalCases=88`
- `current verdicts={'needs_review': 87, 'fail': 1}`
- `elapsedMedianMs=23670`
- `elapsedP95Ms=75689`
- `elapsedMaxMs=172968`
- `firstMessageMedianMs=3015`
- `finalMessageMedianMs=21668`
- `missingProgressCount=0`
- `Full Agent Tool Trial Issues.count=81`
- `slow_full_agent=81`
- `very_slow_full_agent=36`
- `very_slow_agent_node=58`
- `repeated_tool_calls=2`
- `many_tool_calls=4`
- `tool_result_error=1`

质量观察：

- 多数开放 Explore / 取舍类问题的回复质量可用，能给出结构化判断和下一步，例如地域取舍、民办 vs 公办、稳定就业、考公、体检风险、预算/高收费风险等。
- 没有发现为了降低延迟导致的“薄回复”成为主问题；相反，慢 case 往往是回复内容较丰满、最终组织阶段较长。
- `thinking` 首响稳定在约 `3s`，长耗时 case 也能持续提示。已修正“等待模型返回”等内部表达，改为“正在整理可用信息 / 正在补全结论”等用户侧语言。
- 方案类 case 因本地 clean session 多数没有正式方案，回复主要验证“无方案边界”是否正确：没有误执行、没有误发工作台刷新，能引导先生成方案或补充信息。

真实问题：

1. `专业组里只保留最稳的专业行不行`
   - 结果质量：回复内容较好，能解释“只留一个专业 + 不服从调剂 / 服从调剂”的风险，并给出“组内尽量填满、最稳兜底、谨慎调剂”的建议。
   - 性能：`elapsedMs=172968`，超过 `maxElapsedMs=100000`。
   - 节点归因：`plan_next_action` 后最终 `ModelRequestNode=159242ms`，不是重复工具，也不是工具内部耗时。
   - 判断：这是高质量长回复的最终生成长尾。短期不应通过关键词 fast route 或薄模板解决；更合理方向是降低该类只读策略问题暴露的 Plan 工具负担，或优化最终回复生成上下文规模。
2. `候选里有稳一点的会计加进来吗，先别加`
   - 回复：`查询暂时没拉出来，可能是系统有点延迟...`
   - 问题：在 clean session / 无候选环境下，这种表达容易把正常空结果说成系统延迟。
   - 已修正：`query_volunteer_plan` 的候选空结果现在明确说明“当前候选池按这个条件没有命中，不是系统延迟或查询失败”；Plan 调度规则也要求最终回复不得把“暂时没有筛到/没有命中”改写成“系统延迟、稍后再试、查询没拉出来”，除非工具明确返回查询失败。
3. 部分开放取舍 case 多工具叠加：
   - 例如 `大城市民办和小城市公办怎么选` 会调用地域 + 职业两个工具；`中外合作贵不贵，值不值得放` 会调用职业、方案、院校多个工具。
   - 当前回复质量可用，但延迟高。下一步应从工具暴露和调度边界收敛，减少同轮非必要工具，不通过字符串匹配抢路由。

评估工具修正：

- 旧 fast route 预期不再作为质量硬失败，仅保留严格确认守护类路由校验；否则当前 full agent 基线会被旧优化路线误判为质量失败。
- 空方案结果纳入 `_EMPTY_RESULT_TOKENS`，空方案时不再强制套用“预览/示例必须覆盖分布”的质量门禁。
- 条件性 pending 建议（如“如果你想，我可以把它先记成待确认偏好”）不再被误判为“已经生效”的 pending 文案；仍会继续拦截未加确认条件的“已经记成 / 后续都会按这个要求”。
- 修正多个 case 元数据：预算/中外合作、偏好可变更、弱确认收口、专业组策略等从错误的 preview / intent 预期调整为只读或空方案边界场景。

验证：

- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py -q`：`54 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_plan_query_tool.py tests/unit/test_instructions.py tests/unit/test_dialog_case_evaluation_report.py -q`：`105 passed`。
- 离线报告重算：`/private/tmp/zhiyuan_303_dialogue_derived_all88_eval_current.md`，剩余硬失败仅为专业组策略长尾延迟。

结论：

- 当前瓶颈主要不是“缺少快路由”，而是 full agent 在开放式问题上上下文和工具选择偏重、最终回复生成长尾明显。
- 继续优化时应优先做可维护的系统性收敛：工具暴露边界、只读策略场景的上下文裁剪、空结果语义稳定、慢节点观测与模型供应商稳定性评估。
- 不建议回到字符串关键词补丁；真实输入的说法变化太大，容易造成覆盖漏洞和误路由。

#### 12.4.4 工具边界收敛：多专业取舍与多专业介绍

本轮继续按“回复质量优先、延迟次之”的口径处理工具链冗余，不恢复字符串 fast route，也不在 service 层做固定模板回复。

问题一：三专业取舍被拆成多次二元对比。

- 代表输入：`财管会计审计这几个怎么排优先级`
- 旧表现：full agent 会连续调用 `compare_majors(财务管理, 会计学)` 和 `compare_majors(会计学, 审计学)`，最终能答，但工具链和最终组织都偏重。
- 修复：新增 `compare_major_options`，用于三个及以上具体专业/专业类的优先级、排序、取舍判断；一次查询多专业横向事实，再由主模型组织用户侧回复。
- 指令边界：两个专业仍用 `compare_majors / compare_majors_adhoc`；三个及以上取舍用 `compare_major_options`，不要拆成多次二元对比，也不要先绕到 `analyze_current_major_interest` 或 Intent 预览。

复测：

- 输出：`/private/tmp/zhiyuan_303_accounting_priority_major_options_backend_live.json`
- 路径：`routingPath=full_agent`
- 工具：`compare_major_options` 1 次，`repeatedToolNames=[]`
- 性能：后端权重查询约 `61ms`，端到端约 `15.6s`；后续再次复测 `/private/tmp/zhiyuan_303_accounting_priority_after_major_intro_live.json` 仍保持单次 `compare_major_options`。
- 回复质量：保留“默认排序 / 为什么这样排 / 按考公、企业就业、事务所、读研目标调整 / 下一步细化”的结构，没有退化成薄回复。

问题二：多个专业的学习内容/基础要求对照被并行打多个专业介绍工具。

- 代表输入：`建筑城乡规划要不要美术基础`
- 旧表现：同轮并行调用 `get_major_introduction` 3 次。回复质量较好，但 `toolTrial.hasRepeatedToolCalls=true`，属于可维护性和延迟风险。
- 修复：新增 `get_major_introductions`，用于多个专业的学习内容、基础要求、课程训练、就业方向横向对照；一次读取当前方案状态，每个专业读取 profile 与候选承接事实，最终仍由主模型组织回复。
- 指令边界：多个专业介绍/基础要求对照优先 `get_major_introductions`，不要并行或连续多次调用 `get_major_introduction`；单专业介绍仍保留原工具。

复测：

- 修复前输出：`/private/tmp/zhiyuan_303_architecture_foundation_backend_live.json`
  - 工具：`get_major_introduction` 3 次。
  - 性能：约 `19.6s`。
  - 回复质量：可用，能解释建筑学和城乡规划对美术基础的差异。
- 修复后输出：`/private/tmp/zhiyuan_303_architecture_foundation_major_introductions_live.json`
  - 工具：`get_major_introductions` 1 次，`repeatedToolNames=[]`。
  - 性能：约 `17.5s`。
  - 回复质量：保留“录取门槛 / 入学后要求 / 没有美术基础怎么办 / 方案承接”的结构，且更明确地区分“录取时通常不额外考美术”和“入学后建筑学训练更重”。

相邻回归：

- 候选空结果：`/private/tmp/zhiyuan_303_candidate_empty_semantics_backend_live.json`
  - 输入：`候选里有稳一点的会计加进来吗，先别加`
  - 工具：`query_volunteer_plan` 1 次。
  - 结果：明确表达“候选里目前没有会计学相关的候选机会”，没有再说成系统延迟，也没有误加入方案。
- 专业组策略：`/private/tmp/zhiyuan_303_major_group_strategy_backend_live.json`
  - 输入：`专业组里只保留最稳的专业行不行`
  - 工具：0 次。
  - 结果：作为只读策略建议回答，不误进方案修改；质量可用，但仍有约 `19s` 的首轮模型生成耗时。

验证：

- 聚焦单测：`tests/unit/test_major_info_tool.py tests/unit/test_compare_resolution.py tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_register_low_level_intent_extractors tests/unit/test_instructions.py::TestToolDispatchRules::test_explore_tool_boundaries_reduce_redundant_tool_chains tests/unit/test_chat_agent_init_profile.py::test_build_instructions_includes_explore_first_direction_fit_guidance tests/unit/test_chat_agent_progress_hints.py -q`，`24 passed`。
- 前一轮 pending 边界、候选空结果和 progress 去重聚焦单测保持通过：`14 passed`、`105 passed`。

结论：

- 当前优化方向是“把模型已经想调用的同类工具合并成更合适的结构化工具”，不是靠输入字符串抢路由。
- 这能减少重复工具调用、降低工具试探风险，并保留 full agent 对最终回复的自然组织能力。
- 剩余主要慢点仍是外层两次模型请求，尤其是首轮工具选择和最终回复生成。后续继续看模型供应商稳定性、工具 schema/指令规模和只读策略问题的上下文裁剪。

#### 12.4.5 长等待感优化：更早的用户侧进度提示

问题：

- 上述真实 case 的工具链已经收敛，但端到端仍常见 `20s+`，慢点集中在外层 `ModelRequestNode`。
- 用户真正困惑的是“系统是不是没动”，不是所有场景都必须把最终回复压到几秒内。
- 原 `firstMessageMs` 约 `3s`，如果上下文读取或模型首轮选择慢，前几秒会没有任何反馈。

设计：

- 不改变路由、不改变工具选择、不改变最终回复。
- 增加上下文读取阶段的早期提示：如果非确认类请求进入成绩、画像、planning 摘要读取阶段超过短阈值，发送 `正在读取当前会话信息...`。
- 将 full-agent 初始理解提示从 `3.0s` 调整为 `1.5s`，文案仍是用户侧语言：`正在理解你的问题，并结合当前信息整理回答...`。
- 确认类请求（如上一轮 preview 后的“确认”）仍走 direct pending guard/confirm，不额外发送上下文提示，避免快速执行动作时出现多余 thinking。

验证：

- 单测覆盖：
  - 上下文读取慢时先发 `正在读取当前会话信息...`，随后进入模型理解提示。
  - 工具进度已经发送时，不重复发送初始理解提示。
  - 长耗时提示仍不包含 `模型 / 工具结果 / action / payload / stage / volunteerId` 等内部表达。
- 真实 WebSocket 小回归：
  - `/private/tmp/zhiyuan_303_tool_boundary_early_progress_live.json`
  - `/private/tmp/zhiyuan_303_tool_boundary_initial_1p5s_live.json`
  - `建筑城乡规划要不要美术基础` 与 `财管会计审计这几个怎么排优先级` 工具链仍分别为单次 `get_major_introductions` / `compare_major_options`。
  - 本地上下文接口较快时早期上下文提示不会出现；初始理解提示前移后，两个 case 的 `firstMessageMs` 从约 `3.3s` 降到约 `1.8s`。
  - 端到端耗时仍取决于模型长尾，本轮分别约 `18.8s` 和 `15.1s`；这是感知改善，不是模型请求数优化。

影响：

- 这是感知层优化，不减少 LLM 请求数，也不降低回复质量。
- 如果后端上下文读取本身变慢，用户能更早看到系统正在读取当前会话信息；如果上下文读取很快，则仍直接进入 full agent 的理解提示和工具提示。

#### 12.4.6 评估口径校准：区分回复质量、工具边界和模型长尾

本轮在两条真实 dialogue-derived case 上复查后发现：运行链路已经通过 `compare_major_options` / `get_major_introductions` 收敛了重复工具调用，回复内容也达到用户侧可读标准，但自动评估仍把它们标为 `needs_review`。原因主要是评估器口径滞后，而不是回复质量退化。

问题：

- `major_compare` 场景只把 `compare_majors` 视为有效动作观测，未把新聚合工具 `compare_major_options` 计入，因此 `财管会计审计这几个怎么排优先级` 被误报 `missing_action_observability:compare_majors`。
- 关键点匹配过窄：`就业路径` 未识别“就业面、企业财务、金融机构、事务所、风控、考公”等自然表达；`学习要求` 未识别“入学后课程、课程训练、核心能力、美术训练”；`下一步` 未识别“可以直接问我、愿意补充”等用户侧引导。
- `readonly_boundary` 对纯 Explore 信息咨询要求过重。像 `建筑城乡规划要不要美术基础` 这种只读专业知识问题，本身不会被用户理解为方案变更，不应强制占用回复篇幅说“不会改方案”。方案、候选、意向、确认、移动、删除、排序等有副作用歧义的场景仍保留该要求。
- 自动推断出来的 semantic frame 在当前 full-agent 基线中没有开启 shadow 验证时，不应作为普通报告的质量告警；显式指定的语义帧测试仍保留未验证告警。

修正：

- `compare_majors` 的动作观测别名扩展为 `compare_majors / compare_majors_adhoc / compare_major_options`。
- 增加关键点同义表达：学习要求、就业路径、排序建议、下一步等。
- 增加决策依据识别维度：`career_path / learning_requirement / admission_requirement / decision_recommendation`，避免结构化表格和自然表达被低估。
- `readonly_boundary` 改为条件要求：计划/候选/意向/确认/变更相关 coverage 或用户明确说“先别动、只分析、别直接加”等才强制要求；纯专业知识咨询不再误报。
- case 定义中显式 `expectedSemanticFrame` 标记为 `explicit`；覆盖标签推断出来的语义帧标记为 `inferred`，未启用 shadow 时不再产生报告噪音。

复跑结果：

- 输出报告：`/private/tmp/zhiyuan_303_tool_boundary_initial_1p5s_eval_refined.md`
- 两条真实 case：`current verdicts={'strong': 2}`。
- 质量违规：`quality violations={}`。
- 评估告警：`evaluation warnings={}`。
- 延迟仍清晰保留：median `16936ms`，max `18755ms`；`Full Agent Tool Trial Issues` 仍记录 `slow_tool_chain / slow_full_agent / slow_agent_node`。
- 结论更准确：这两条 case 的当前主要问题不是回复薄、工具错或边界错，而是 full agent 外层两轮模型请求仍偏慢。

验证：

- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py -q`：`58 passed`。
- 离线报告重算命令：
  - `.venv/bin/python examples/dialog_case_evaluation_report.py --current /private/tmp/zhiyuan_303_tool_boundary_initial_1p5s_live.json --case-definitions /private/tmp/zhiyuan_303_tool_boundary_cases.json --markdown-detail --output /private/tmp/zhiyuan_303_tool_boundary_initial_1p5s_eval_refined.md`

影响：

- 只调整离线评估和报告，不改变 agent 运行时路由、工具选择或最终回复。
- 后续评估能更稳定地区分三类问题：用户侧回复质量、工具调用边界、模型请求长尾。
- 这为继续做 full-agent 深挖提供更干净的基线，避免重新引入字符串快路由来“修复”其实是评估误判的问题。

#### 12.4.7 职业方向工具参数化：减少工具内部方向识别长尾

继续复跑旧 88 case 中的职业方向慢样例后，当前代码表现为：

- 输入：`大城市就业和考编哪个更现实`
- 输出：`/private/tmp/zhiyuan_303_career_big_city_vs_exam_current_live.json`
- 工具链：`analyze_current_career_direction` 1 次，没有 `load_skill`，没有 pending，也没有工作台联动。
- 回复质量：可用，能对比考编/体制内与大城市市场化就业，覆盖优势、现实门槛、适合人群和下一步信息补充。
- 耗时：约 `44.6s`；其中首轮模型约 `4.9s`，工具约 `27.7s`，最终模型约 `9.8s`。

定位：

- `ChatService` 已经在正式聊天主链路里设置 `allow_explore_inner_llm=false`，所以职业方向工具不再做内部草稿生成。
- 当前工具内部慢点主要来自 `resolve_career_direction_slots`：外层 full agent 已经理解用户在问职业路径，却仍让工具再发起一次职业方向 slot 识别 LLM。
- 这不是字符串快路由问题，而是工具接口缺少结构化参数，导致模型已经判断出的语义不能传给工具复用。

修复设计：

- `analyze_current_career_direction` 增加可选参数 `career_directions`。
- 参数枚举固定为：
  - `system_public_service`：考公、考编、体制内、公务员、事业单位。
  - `stable_employment`：稳定就业、求稳、抗风险。
  - `further_study`：读研、深造、升学。
- 外层模型如果当前用户句子已经明确提到这些方向，直接把一个或多个枚举传入工具。
- 工具收到有效参数后直接进入单方向或多方向分析，不再调用 `_resolve_career_direction_slots`。
- 参数为空或无效时继续走原有 resolver 兜底，保证开放口语和未覆盖表达不退化。
- 仍由 full agent 组织最终回复；不引入 service 层字符串路由，也不把回复改成模板。

预期影响：

- 对“考编 vs 大城市就业”“读研还是求稳”“体制内和稳定就业承接”等显式职业方向问题，减少一次工具内部 LLM 调用。
- 对没有明确方向的泛问法，例如“我适合什么方向 / 先看大方向”，仍保持原有语义判定和泛方向分析链路。
- 只影响只读 Explore 分析，不写 pending、不修改方案、不发送工作台卡片。

验证：

- 单测新增覆盖：
  - 工具 schema 暴露 `career_directions` 枚举。
  - 显式传入多个方向时，不再调用 resolver，直接进入方向对比。
  - 传入无效方向时回落 resolver。
  - 指令要求模型在明确方向场景直接传 `career_directions`。
- 聚焦测试：
  - `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_chat_agent_tools.py tests/unit/test_instructions.py -q`：`64 passed`。

待验证：

- 需要重启本地 agent 进程后复跑真实 WebSocket，确认远端模型会按照新 schema 传入 `career_directions`。
- 如果模型仍不传参数，下一步不是加关键词快路由，而是继续优化工具描述和 few-shot 指令，使模型把已理解出的方向以结构化参数传给工具。

#### 12.4.8 职业方向 taxonomy 与泛方向参数化

本轮继续围绕职业方向 Explore 做深挖，重点处理两个问题：一是“大城市就业 / 市场化就业”没有结构化 slot，二是“先看大方向”这类泛方向问法会在工具内部再触发一次 LLM 判定。

问题：

- `大城市就业和考编哪个更现实` 之前只能稳定识别 `system_public_service`，市场化就业这一侧没有结构化 slot，工具事实层只能靠最终模型自行补全，后续意向承接和方案关系分析也缺少统一标签。
- `等成绩出来再定，今天先看大方向` 在加强回复质量后会进入 `analyze_current_career_direction`，但工具内部仍调用 `resolve_career_direction_route` 判断“是否泛方向”，导致工具节点约 `15.9s`。
- 一次真实回复里出现了 `学历门槛 increasingly 要硕士` 这类中英混排，说明用户侧语言质量需要纳入评估约束。

修复：

- 新增职业方向 slot：
  - `market_employment`：企业就业 / 市场化就业 / 大城市就业 / 互联网或产业岗位。
  - 标签为“市场化就业导向”。
  - 接入 `analyze_current_career_direction(career_directions=...)` schema、职业意向抽取、职业方向 Explore 事实匹配和 Intent/方案关系分析。
- `intent_relation_tool` 的职业方向匹配从“所有 career intent 都按体制内匹配”改为按 slot 匹配：
  - `system_public_service`：政法、师范、法学、汉语言、行政管理等。
  - `stable_employment`：公办、师范、医药、政法、农林及稳定岗位口径。
  - `further_study`：保研、双一流、985/211、硕博点、升学率等。
  - `market_employment`：理工/财经/综合、计算机、电子信息、金融、会计、互联网、实习、产业等。
- `analyze_current_career_direction` 增加 `generic_direction: bool` 参数：
  - full agent 对“适合什么方向 / 先看大方向 / 出分前先定方向”等泛方向问题调用 `analyze_current_career_direction(generic_direction=true)`。
  - 工具收到该参数后直接进入泛方向分析，跳过内部 `resolve_career_direction_route` LLM。
- Explore 指令补充质量底线：
  - 出分前或信息不完整的泛方向回复不能只列“可以聊什么”。
  - 至少给出体制内/稳定就业、市场化就业/大城市就业、读研/深造等 2-3 条方向框架，分别说明关键筹码、适合人群、主要风险和下一步。
- 回复风格与评估补充：
  - 用户正文不得夹杂不必要英文词或中英混排，专业英文缩写和正式英文名除外。
  - `dialog_case_evaluation_report` 把 `increasingly / vs / TODO / N/A` 等纳入 `user_language` 风险提示。
  - 新增职业方向专项回归文件 `examples/dialog_regression_303_career_direction_cases.json`。

验证：

- 聚焦单测：
  - `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_career_slots.py tests/unit/test_chat_agent_tools.py tests/unit/test_instructions.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_intent_state_tool.py tests/unit/test_dialog_case_evaluation_report.py -q`：`227 passed`。
  - 增加 `generic_direction` 后补跑：`tests/unit/test_chat_agent_tools.py tests/unit/test_instructions.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_dialog_case_evaluation_report.py -q`：`126 passed`。
- 真实 WebSocket：
  - `/private/tmp/zhiyuan_303_career_direction_cases_live.json`
  - 4 条职业方向 case 全部成功，耗时区间约 `10.2s - 19.6s`，没有重复工具调用；报告 `/private/tmp/zhiyuan_303_career_direction_cases_eval.md` 显示主要问题为 `slow_full_agent` 和部分回复信息量/下一步口径不足。
  - 针对薄弱 case `等成绩出来再定，今天先看大方向`，加强指令后输出 `/private/tmp/zhiyuan_303_general_direction_after_instruction_live.json`：回复覆盖体制内/稳定就业、市场化就业、大城市发展、读研深造的适配人群、关键筹码和风险，但工具节点因内部泛方向判定约 `15.9s`。
  - 增加 `generic_direction` 参数后复跑 `/private/tmp/zhiyuan_303_general_direction_generic_param_live.json`：日志确认 `using_generic_direction_analysis=explicit`；工具节点从约 `15.9s` 降到约 `293ms`，端到端从约 `34.3s` 降到约 `19.0s`，回复仍保留三条方向框架和下一步。
  - 全量职业方向 case 复跑 `/private/tmp/zhiyuan_303_career_direction_cases_after_generic_param_live.json`，评估报告 `/private/tmp/zhiyuan_303_career_direction_cases_after_generic_param_eval.md`：4 条全部成功，无质量违规，2 条 strong、2 条 needs_review；needs_review 主要来自 full-agent 慢节点和只读边界/用户语言口径继续收紧。
  - 只读边界复跑 `/private/tmp/zhiyuan_303_career_readonly_boundary_live.json`：`体制内稳定就业承接怎么样，先不要改方案` 首句明确“这轮只做分析，不会改动你的方案”；工具节点约 `126ms`，端到端约 `16.2s`。
- 最终聚焦单测：
  - `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_career_slots.py tests/unit/test_chat_agent_tools.py tests/unit/test_instructions.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_intent_state_tool.py tests/unit/test_dialog_case_evaluation_report.py -q`：`228 passed`。

结论：

- 这次优化仍保持 full agent 主路由，没有恢复 service 层字符串快路由。
- 性能收益来自“工具结构化参数复用外层模型已理解的语义”，不是把回复模板化。
- 当前剩余慢点主要是 full agent 外层两次主模型请求，尤其最终组织回复节点仍常见 `10s+`；后续可继续从模型选择、上下文裁剪和工具返回事实压缩入手，但不能牺牲回复信息量。

#### 12.4.9 专业/院校实体理解公共层

本轮继续处理真实对话里反复出现的实体理解问题。用户明确指出，继续补 `_phrase_mentions_tcm_boundary`、`_major_boundary_notes` 或单独追加“审计”等别名，无法解决自然语言里大量简称、父子层级和只读/写入边界问题。因此本轮不再做 case 级补丁，而是把专业、院校识别收敛成可复用公共层。

现状确认：

- `extract_major_intent / extract_major_intents_with_polarity` 已存在，但只在 Intent 预览缺少结构化参数时作为 fallback 调用。
- `extract_school_intent` 同样只服务院校意向 fallback。
- 方案加入/删除/移动里的“广西师大统计”“湖北工程学院的计算机科学与技术”不走上述 extractor，而是由 `plan_execution_tool` 基于当前方案/候选池解析真实 `volunteerId`。
- 因此当前不是没有 extractor，而是缺少跨 Intent / Explore / Plan 的统一实体解析契约。

本轮落地：

- 新增 `zhiyuan-agent/app/domain/entity_resolution.py`，定义统一候选结构：
  - `entity_type`：`major / school / school_major_ref`
  - `canonical_name`
  - `level`
  - `source`：`exact / alias / auto_alias / catalog / extractor / item_match`
  - `confidence`
  - `ambiguous`
- 新增 `zhiyuan-agent/app/domain/major_entity_resolver.py`：
  - 直接复用官方专业目录 `major_data.py`。
  - 复用 `major_aliases.py` 作为受控常用简称表。
  - 从目录自动生成唯一简称，仅当别名只指向一个官方专业/专业类时接受。
  - `resolve_major_mentions_from_text` 用于短句里的专业实体召回。
  - `build_major_relation_notes` 基于 `level3_to_level2 / level2_to_level1` 生成通用父子层级说明，不再写死“中医/师范”等话术。
- 新增 `zhiyuan-agent/app/domain/school_entity_resolver.py`：
  - 复用官方院校目录。
  - 抽出院校简称规则，如“广西师大”“湖工”。
  - 多候选时返回 `ambiguous=true`，不猜。
- 新增 `zhiyuan-agent/app/domain/school_major_ref_resolver.py`：
  - 面向方案操作里的“学校+专业”引用，例如“广西师大统计”“湖北工程学院的计算机科学与技术”。
  - 先按显式分隔符拆分；没有分隔符时用院校目录和专业目录做边界扫描。
  - 只输出标准化查询线索，如 `school_keywords=["广西师范大学"]`、`major_keywords=["统计学"]`。
  - 如果学校或专业侧存在多候选歧义，例如“湖工计科”，返回歧义状态，不生成查询线索。
- `intent_state_tool` 的本地专业恢复改为调用 `resolve_major_mentions_from_text + append_major_mentions_to_payload`。
- `intent_response_tool` 的专业边界提示改为调用 `build_major_relation_notes`。
- 移除“师范/老师”直接补成 `教育学类` 的运行时特殊逻辑，避免把“师范是不是都别要”这类咨询/澄清句误写成待确认排除。
- `plan_execution_tool` 小范围接入学校+专业引用解析：
  - 候选加入先用当前 `candidatePoolState.items` 做真实 item 唯一匹配，能匹配则不额外查询。
  - 当前页未加载目标时，再用 `school_major_ref_resolver` 生成候选池查询关键词。
  - 查询返回后仍走现有 `_ordered_item_labels` 唯一命中逻辑，只有唯一真实 `volunteerId` 才会执行加入。
  - 不把公共 resolver 的结果直接当作执行目标，避免把简称/口语表达误执行成错误志愿。
- `plan_execution_tool` 的 item label 生成复用公共专业/院校别名层：
  - 删除 Plan 内部重复维护的院校简称规则，统一调用 `school_alias_variants`。
  - 专业简称统一从 `major_aliases.py + major_alias_variants_for_name` 反查，覆盖“审计、软工、国贸、新媒体、计科、统计”等常用表达。
  - 已选方案里的移动/删除仍不靠公共 resolver 直接选目标，而是把公共别名加入 item label 后继续做唯一真实 `volunteerId` 匹配。

当前边界：

- 本轮没有把 Plan 执行层整体改写为公共 resolver。`plan_execution_tool` 基于当前方案/候选池的唯一命中与歧义保护仍是最终落点。
- `school_major_ref_resolver` 当前只增强候选池查询召回，尤其是目标不在当前候选页时的“简称+专业”表达。
- 已选方案里的删除/移动仍依赖当前方案 item 的 label/alias 唯一匹配；公共层只提供 label 变体，不直接选择执行目标。
- `extract_major/school` 不废弃；它们继续作为 LLM 语义抽取 fallback。公共 resolver 负责 deterministic/catalog/alias 层，extractor 负责更开放的语义补位。

验证重点：

- `会计审计还行，土木别要`：公共解析能召回会计学、审计学、土木工程。
- `医学 + 中医学类/中医学`：层级说明来自目录关系。
- `孩子不想当老师，师范是不是都别要`：不再被本地特殊逻辑直接写成排除教育学类。
- `广西师大`：可解析为广西师范大学。
- `湖工`：如果命中湖北工程学院、湖北工业大学等多个候选，必须标记歧义，不猜。
- `广西师大统计`：
  - 如果当前候选状态页已经有唯一 item，直接解析到该 `volunteerId`，不触发额外候选查询。
  - 如果当前候选状态页为空或没加载到目标，用 `广西师范大学 + 统计学` 查询候选池；查询结果仍必须唯一命中真实 `volunteerId` 才允许加入方案。
- `湖工计科`：学校简称歧义时不生成候选查询线索；如果当前候选/方案 item 也不能唯一命中，则返回需要用户点选或补充信息。
- `青岛城市学院新媒体`：专业简称来自公共 `major_aliases.py`，可在当前方案 item 中唯一匹配到“网络与新媒体”后再移动；如果当前方案里多个 item 都匹配，仍返回需要点选，不猜。

聚焦验证：

- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_entity_resolution.py tests/unit/test_intent_state_tool.py::test_local_major_recovery_does_not_force_teacher_track_into_intent_preview tests/unit/test_intent_state_tool.py::test_refine_major_intents_supplements_model_omitted_major_alias tests/unit/test_intent_state_tool.py::test_render_intent_analysis_text_explains_tcm_boundary_under_medical_constraint -q`：`9 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_intent_state_tool.py::test_recover_major_intent_from_context_recovers_mixed_polarity_locally_without_llm tests/unit/test_intent_state_tool.py::test_recover_major_intent_from_context_recovers_common_major_abbreviations_locally tests/unit/test_intent_state_tool.py::test_recover_intents_from_context_major_scope_only_uses_major_extractors tests/unit/test_intent_state_tool.py::test_recover_intents_from_context_major_scope_falls_back_when_combined_extractor_fails tests/unit/test_intent_state_tool.py::test_recover_intents_from_context_school_scope_only_uses_school_extractor -q`：`5 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_entity_resolution.py tests/unit/test_major_utils.py tests/unit/test_code_enrichment.py tests/unit/test_major_intent_tool.py -q`：`62 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_entity_resolution.py tests/unit/test_plan_execution_tool.py::test_execute_plan_action_add_units_queries_candidate_pool_for_unloaded_short_ref tests/unit/test_plan_execution_tool.py::test_execute_plan_action_add_units_resolves_candidate_school_major_alias_ref tests/unit/test_plan_execution_tool.py::test_execute_plan_action_add_units_does_not_guess_ambiguous_candidate_alias_ref tests/unit/test_plan_execution_tool.py::test_execute_plan_action_runs_move_unit_after_resolving_school_major_alias_ref tests/unit/test_plan_execution_tool.py::test_execute_plan_action_does_not_guess_ambiguous_school_major_alias_ref -q`：`13 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_entity_resolution.py tests/unit/test_plan_execution_tool.py -q`：`98 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_entity_resolution.py tests/unit/test_major_utils.py tests/unit/test_code_enrichment.py tests/unit/test_major_intent_tool.py tests/unit/test_intent_state_tool.py tests/unit/test_plan_execution_tool.py -q`：`258 passed`。

真实链路 smoke：

- `会计审计还行，土木别要 -> 确认`：
  - 输出文件：`/private/tmp/zhiyuan_303_entity_intent_smoke.json`。
  - 首轮耗时约 `9.4s`，工具链为 `preview_current_major_intent_confirmation` 一次。
  - 回复正确识别“会计学、审计学”为偏好，“土木类”为排除；确认轮走 `direct_pending_intent_confirm`，耗时约 `2.3s`。
- `青岛城市学院新媒体挪到第3位看看`：
  - 输出文件：`/private/tmp/zhiyuan_303_entity_plan_ref_smoke.json`。
  - 当前会话里没有唯一的“青岛城市学院-网络与新媒体”组合，系统没有执行移动，而是提示澄清“青岛电影学院-网络与新媒体”或“青岛城市学院其他专业”。
  - 暴露问题：full agent 出现 `query_volunteer_plan` 重复调用 2 次，总耗时约 `31.6s`，后续应继续优化工具试探和重复查询。
- `广西师大统计挪到第3位看看`：
  - 输出文件：`/private/tmp/zhiyuan_303_entity_plan_alias_smoke.json`。
  - 当前方案没有广西师范大学/统计学时没有执行移动，回复解释无法直接挪，并给出“加入方案/先查可上概率/补充信息”的下一步。
  - 暴露问题：模型把明确移动请求先组织成 `move_unit analyze`，随后重复 `query_volunteer_plan` 3 次；实体安全边界正确，但路由与性能仍需后续优化。

#### 12.4.10 Plan 选择阻断结果直出

在 12.4.9 的真实链路 smoke 里，实体解析和执行安全边界已经正确，但出现了新的性能问题：`execute_plan_action` 已经返回“无法唯一定位，需要用户点选或补充信息”后，full agent 仍继续调用 `query_volunteer_plan` 试图自行补查，导致同一轮重复查询 2-3 次。

问题复盘：

- `tool_dispatch_rules` 已经要求 `execute_plan_action result_kind="error"` 时不要重复重试，但实际模型仍可能把这个错误理解为“还需要再查一遍当前方案”。
- 这类错误不是系统故障，而是受控的业务阻断：没有唯一定位到当前方案/候选里的真实志愿，继续查不会让执行更安全。
- 如果任由模型继续补查，用户侧会看到更长等待；且模型可能把“目标不存在”改写成多个猜测选项，反而弱化“需要点选/补充”的核心安全边界。

修复：

- 在 `ChatAgent.should_return_directly_from_tool` 中新增严格限定的 direct return：
  - 只处理单个 `execute_plan_action` 工具返回。
  - 只在 `result_kind="error"` 且 `reply_focus` 包含 `needs_volunteer_selection` 或 `needs_candidate_selection` 时触发。
  - 直接使用工具返回的 `summary/state_summary` 作为用户回复，结束本轮。
- 不影响：
  - 正常 `preview_only`，仍由模型组织确认话术。
  - 正常 `mutation_result`，仍由模型说明执行结果和复审。
  - `review_plan/query_state/analyze_adjustment` 等只读结果。
  - 一般系统错误和 stale pending 错误。

验证：

- 单测：
  - `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_only_direct_returns_intent_preview_tools tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_plan_selection_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_direct_return_normal_plan_preview tests/unit/test_base_agent.py::test_run_can_return_directly_after_user_facing_tool_result -q`：`4 passed`。
  - `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_agent_tools.py tests/unit/test_base_agent.py tests/unit/test_plan_execution_tool.py tests/unit/test_entity_resolution.py -q`：`140 passed`。
- 真实链路复测：
  - `青岛城市学院新媒体挪到第3位看看`
    - 修复前：`plan_next_action -> execute_plan_action -> query_volunteer_plan -> query_volunteer_plan`，耗时约 `31.6s`。
    - 修复后：`plan_next_action -> execute_plan_action`，无重复查询，耗时约 `18.7s`。
    - 输出文件：`/private/tmp/zhiyuan_303_plan_selection_blocking_direct_return_after.json`。
  - `广西师大统计挪到第3位看看`
    - 修复前：`plan_next_action(analyze) -> query_volunteer_plan * 3`，耗时约 `15.9s`。
    - 修复后：`plan_next_action -> execute_plan_action`，无重复查询，耗时约 `14.4s`。
    - 输出文件：`/private/tmp/zhiyuan_303_plan_alias_blocking_direct_return_after.json`。

剩余问题：

- 这次只解决“执行层已经给出选择阻断后，模型继续补查”的重复工具问题。
- 明确移动请求仍需要两次主模型请求（先生成 plan，再执行 tool），因此延迟仍在 14-19s 区间。
- 后续如果要继续降延迟，应优化 Plan 预览生成链路或高置信 Plan 动作结构化入口，但仍不能绕过 `preview -> confirm -> apply` 和唯一命中校验。

补充修复：

- 真实复测中又出现一种相邻问题：模型先调用 `plan_next_action(stage=analyze)`，该结果已经提示缺少可唯一定位的 `volunteer_id`；随后模型自行构造了一个简化版 `execute_plan_action` payload，只带 `action_family / volunteer_ids / target_position / user_confirmed=false`，没有完整 `stage / atomic_actions`。
- 旧执行层会把这类简化 payload 判成 `missing_plan_payload`，返回“方案操作信息不完整”。该文案对用户不友好，并且没有被 direct return 规则识别，模型又继续调用 `plan_next_action` 和 `query_volunteer_plan` 补救，导致单轮变成 `6` 次模型请求、`5` 次工具调用，耗时约 `38.6s`。
- 修复分两层：
  - `normalize_plan_action_payload` 兼容这类简化动作 payload：当模型显式传入 `user_confirmed=false` 且是高副作用动作时，补成 `stage=preview` 并生成 `atomic_actions`，让执行层走既有的真实志愿唯一匹配、歧义阻断和确认预览逻辑。
  - 为避免影响确认后的真实执行，该兼容只在 payload 显式包含 `user_confirmed` 时生效；历史 pending 确认注入的标准 `apply` payload 不会被降级。
  - `ChatAgent` 的 direct return 阻断范围增加 `missing_plan_payload`，并把用户可见文案改成“还没有形成可确认的方案调整内容”，不暴露 payload、stage、volunteerId 等内部概念。
- 安全边界不变：
  - 简化 payload 只会进入 preview 或选择阻断，不会绕过确认直接执行。
  - 唯一命中后只返回 `resolved_apply_payload` 给确认轮使用；真实执行仍要求 pending 确认。
  - 多个志愿都能匹配同一句简称时，仍返回“没有唯一匹配”，不猜。

新增验证：

- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_plan_selection_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_incomplete_plan_payload_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_direct_return_normal_plan_preview tests/unit/test_plan_execution_tool.py::test_execute_plan_action_returns_structured_error_when_payload_schema_is_incomplete tests/unit/test_plan_execution_tool.py::test_execute_plan_action_normalizes_simplified_unconfirmed_move_payload_to_preview tests/unit/test_plan_execution_tool.py::test_execute_plan_action_simplified_move_payload_still_blocks_ambiguous_ref_before_confirmation -q`：`6 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_agent_tools.py tests/unit/test_base_agent.py tests/unit/test_plan_execution_tool.py tests/unit/test_entity_resolution.py -q`：`143 passed`。

#### 12.4.11 通用 Tool Reply Policy

用户指出 12.4.10 里按 `tool_name == execute_plan_action` 做直返判断仍然偏局部：如果其他工具也返回“已经足够给用户看的受控阻断”，仍可能出现同样的重复工具调用；反过来，如果模型误把非方案问题打到 `execute_plan_action`，也可能被片面直返掩盖上游路由问题。因此本轮把直返判断从 `ChatAgent` 的 tool name 特判抽成统一策略层。

问题抽象：

- 工具返回后，系统需要统一判断当前结果应如何处理：
  - `continue_model`：继续交给大模型组织回复。
  - `direct_reply`：工具结果已经是稳定用户回复，直接结束本轮。
  - `direct_blocking`：工具已经给出业务阻断，继续试工具只会增加延迟或误导用户。
  - `preview_wait_confirm`：工具已经形成待确认预览，直接回复并等待用户确认。
- 默认必须保守：没有明确策略或高确定性结构时继续交给模型，不因为追求速度牺牲回复质量。

落地：

- 新增 `app/agent/tool_reply_policy.py`：
  - `ToolReplyDecision` 统一描述直返策略、回复文本和原因。
  - `decide_tool_reply(tool_names, tool_returns, deps)` 作为唯一入口。
  - 多工具同轮默认不直返，避免吞掉后续工具上下文。
  - 工具显式返回 `reply_strategy` 时优先执行。
  - 兼容高确定性结构化兜底：
    - Intent preview 工具：`preview_wait_confirm`。
    - `result_kind=error` 且 `reply_focus` 命中 `needs_volunteer_selection / needs_candidate_selection / missing_plan_payload`：`direct_blocking`。
    - `result_kind=no_change`：`direct_reply`。
- `ChatAgent.should_return_directly_from_tool` 和 `render_direct_tool_output` 改为只调用 `decide_tool_reply`，不再直接解析 `execute_plan_action` 的细节。
- `PlanExecutionResult` 增加可选 `reply_strategy` 字段。
- Plan 执行层对以下高确定性结果显式设置策略：
  - 当前方案/候选无法唯一定位：`direct_blocking`。
  - 工具 payload 不完整，无法形成可确认预览：`direct_blocking`。
  - add 已在方案中或候选条件下没有可加入项：`direct_reply`。
- 保持不接管的场景：
  - 正常 `preview_only`，仍交给模型组织更自然的确认说明。
  - 正常 `mutation_result`，仍交给模型说明执行结果、刷新和复审影响。
  - `query_state / review_plan / analyze_adjustment / Explore / 专业对比`，仍交给模型保证回复信息量。
  - 一般系统错误、后端异常，不做直返，避免吞掉可解释的降级建议。

同时修正 12.4.10 真实 smoke 暴露出的确认文案问题：

- 同一轮里 `plan_next_action(stage=preview)` 可能先留下 pending，但后续 `execute_plan_action(result_kind=error)` 已经明确阻断。
- 旧 `_extract_pending_plan_action` 没有被后续 error 清空，导致服务层又追加“如果你确认要这样做，我再执行”。
- 修复后，`execute_plan_action result_kind=error` 会清理同一轮同类 pending，避免“没有可执行预览却让用户确认”。

继续补充 12.4.10 中真实 smoke 暴露的另一类边界：

- 模型有时会把明确的移动/删除/替换请求组织成 `stage=analyze`，但这类动作本质上已经是高副作用调整。如果直接按 analyze 返回“当前阶段仅分析或预览”，模型可能继续自行组织成“已生成预览，确认后执行”，造成没有真实定位和没有可复用 apply payload 的假预览。
- 修复后，`execute_plan_action` 对 `move_unit / remove_units / replace_units / sort_ordered_plan / add_units` 等 mutating action 的 `stage=analyze` 统一改走 `preview` 安全路径：必须先解析当前方案/候选里的真实目标，无法唯一命中就返回受控阻断；只有成功解析后才会形成可确认预览。
- 该修复不绕过 `preview -> confirm -> apply`，也不把 analyze 直接执行成 apply。

同时补齐用户可见文案边界：

- 直返策略会尊重工具显式 `reply_strategy`，因此工具返回内容必须已经是用户语言。
- `replace_units` 缺少目标或替换范围时，不再输出 `volunteer_ids / replacement_scope` 这类内部字段，改为提示“还没定位到要替换的志愿”或“还缺少新志愿筛选方向”。

新增验证：

- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_tool_reply_policy.py tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_uses_tool_reply_policy_for_direct_returns tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_plan_selection_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_incomplete_plan_payload_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_direct_return_normal_plan_preview -q`：`11 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_chat_agent_tools.py tests/unit/test_base_agent.py tests/unit/test_plan_execution_tool.py tests/unit/test_entity_resolution.py tests/unit/test_chat_service_history_persistence.py::test_extract_pending_plan_action_clears_plan_next_preview_after_execute_error tests/unit/test_chat_service_history_persistence.py::test_plan_preview_confirmation_boundary_does_not_append_after_execute_error_clears_pending tests/unit/test_tool_reply_policy.py -q`：`152 passed`。
- `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_tool_reply_policy.py tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_uses_tool_reply_policy_for_direct_returns tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_plan_selection_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_direct_returns_incomplete_plan_payload_blocking_error tests/unit/test_chat_agent_tools.py::TestChatAgentToolRegistration::test_chat_agent_does_not_direct_return_normal_plan_preview tests/unit/test_plan_execution_tool.py::test_execute_plan_action_analyze_move_payload_runs_preview_resolution_before_confirmation tests/unit/test_plan_execution_tool.py::test_execute_plan_action_replace_missing_scope_uses_user_facing_blocking_message tests/unit/test_chat_service_history_persistence.py::test_extract_pending_plan_action_clears_plan_next_preview_after_execute_error tests/unit/test_chat_service_history_persistence.py::test_plan_preview_confirmation_boundary_does_not_append_after_execute_error_clears_pending -q`：`15 passed`。
- 真实 WebSocket smoke：`session=17 / 青岛城市学院新媒体挪到第3位看看`，修复后链路为 `plan_next_action -> execute_plan_action`，`execute_plan_action` 返回 `result_kind=error / reply_strategy=direct_blocking`，最终回复为“我理解你想移动的是：青岛城市学院新媒体。但我在当前方案里还没有唯一匹配到这条志愿...”，没有重复 `query_volunteer_plan`，没有拼出“确认后执行”的假预览，端到端约 `18.3s`。
- 非阻断 smoke：`会计审计还行，土木别要` 仍走 `preview_current_major_intent_confirmation` 待确认直返；`看看现在的方案` 仍走 `query_state` 后交给模型组织结构化概览，未被 Tool Reply Policy 截断。

#### 12.4.12 只读查询后的确认错位与工具循环护栏

本轮 open-quality 复测前先处理 3 个真实链路问题，仍沿用“通用护栏优先，不做单句关键词补丁”的原则。

问题 1：只读方案查询后，短句“确认”误确认旧意向。

- 复现场景：用户先问 `当前方案里青岛城市学院相关机会是不是很多，先查一下不要改`，下一轮回复 `确认`。
- 根因：backend `planEditCache` 里仍有旧的 pending intent，服务层只看“当前是否有 pending intent + 用户是否短确认”，没有判断最近一轮是否仍然处在意向待确认语境。
- 修复：`direct_pending_intent_confirm` 前增加最近历史语境判断。只有最近一轮包含 `preview_current_*_intent_confirmation`，或最近回复明确是待确认意向影响说明时，短确认才会直接应用；如果最近一轮是方案/候选/Explore 只读查询，则进入确认护栏，不执行旧 intent。
- 影响边界：空历史仍兼容旧确认；最近一轮确实是意向预览时仍可 `确认` 生效。

问题 2：`query_volunteer_plan` 在 full agent 内重复调用，直到使用上限或超时。

- 复现场景：`候选里还有没有更稳一点的会计审计，别直接加` 曾出现同一轮几十次 `query_volunteer_plan`，最终 `UsageLimitExceeded` 且空回复。
- 根因：模型在拿到局部查询结果后没有收敛，继续重复调用同一只读工具；这不是某个词的问题，而是工具循环缺少运行时断路。
- 修复：`BaseAgent` 增加通用工具重复计数，当前先对 `query_volunteer_plan` 设置同轮上限 `2`；超过后直接返回用户可理解的“查询未稳定收敛”提示，并在 `agent_observability` 中记录 `toolLoopGuarded / guardedToolName / guardedToolCount`。断路时会丢弃最后一个未执行的 tool-call response，避免历史里留下未配对 tool call。
- 影响边界：只限制重复只读查询工具；正常单次查询、方案 preview/apply、审查和 Explore 不受影响。

问题 3：候选只读查询误发工作区卡片或误留下可确认修改预览。

- 复现场景：用户说 `候选里还有没有更稳一点的会计审计，别直接加`，系统虽然文本是只读分析，但附带 `planningWorkspaceAction(candidate)`。
- 根因：`execute_plan_action(query_candidates)` 的 read-only result 里带了 `workspace_refresh_targets=["candidate"]`，服务层把它转换成 view followup；另一种错误路径是模型先把“别直接加”的只读诉求误规划成 `add_units preview`，服务层会把它当作可确认 pending。
- 修复：`query_candidates` 不再通过 `_extract_execute_plan_action_view_targets` 产生工作区联动卡片；同时增加显式只读副作用护栏：当用户明确表达“只查/只看/别直接加/不要改方案”时，如果当前轮工具误产生 add/remove/move/sort 等修改预览，服务层会把该结果改写为只读结果、清空 workspace targets，并移除确认文案，避免下一轮“确认”误执行。
- 影响边界：这是副作用安全边界，不是业务快路由；真实修改请求仍必须走 `preview -> confirm -> apply`，确认/勾选后的约束采纳仍走 `candidateFilters`，方案修改仍走 ordered/review 刷新。

验证：

- 单测：`cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_base_agent.py tests/unit/test_tool_reply_policy.py tests/unit/test_chat_service_history_persistence.py -q`：`138 passed`。
- 真实 WebSocket smoke：
  - `session=17 / 当前方案里青岛城市学院相关机会是不是很多，先查一下不要改 -> 确认`：首轮只调用 `query_volunteer_plan` 1 次，无 followup；确认轮返回“没有上一轮待确认的方案动作”，没有误走 `direct_pending_intent_confirm`。输出：`/private/tmp/zhiyuan_303_pending_guard_fix_smoke.json`。
  - `session=17 / 候选里还有没有更稳一点的会计审计，别直接加`：只调用 `query_volunteer_plan` 1 次，无重复工具、无候选工作区卡片，端到端约 `12.5s`。输出：`/private/tmp/zhiyuan_303_query_loop_guard_smoke.json`。
- 百家 Kimi 验证：
  - 本地服务用 `LLM_BASE_URL=https://llm.baijia.com/v1 / LLM_MODEL_NAME=kimi-k2.6` 启动在 `127.0.0.1:8013`；`curl` 最小请求已确认端点恢复连通。
  - `session=17 / 当前方案里青岛城市学院相关机会是不是很多，先查一下不要改 -> 确认`：首轮 `12.7s`，工具链 `query_volunteer_plan` 1 次，无 followup；回复命中 7 条青岛城市学院相关志愿，并说明全为冲档、录取率约 1%；确认轮 `2.1s`，进入 no-pending guard，没有误执行。
  - `session=17 / 候选里还有没有更稳一点的会计审计，别直接加`：`49.2s`，工具链 `plan_next_action(query_candidates) -> execute_plan_action(query_candidates) -> query_volunteer_plan`，无重复工具、无候选工作区卡片、无“确认后执行”修改预览；输出文件：`/private/tmp/zhiyuan_303_baijia_kimi_candidate_readonly_guard_smoke_after_network.json`。

剩余问题：

- 百家 Kimi 候选只读链路耗时仍高，主要耗在 4 次模型请求；虽然已经没有副作用问题，但性能仍需进入后续评估。
- 百家 Kimi 候选只读链路没有拿到真实候选列表，最终回复转为概括性建议，包含“省内公办二本/财经类院校/稳的标准”等方向；这比空回复好，但候选查询质量和工具结果承接仍需后续定位。
- 第一条只读方案查询回复质量可接受，但仍用了两次主模型请求；后续应继续在 full-agent 质量评估框架内看是否优化 Plan 查询类最终组织耗时。

补充修复：候选查询共享筛选抽取层与失败语义。

- 百家 Kimi 复测中定位到两层问题：
  - 模型已经进入 `query_candidates`，但可能只把“会计审计”中的一部分传成 `major_keyword=会计`，导致候选查询条件偏窄。
  - 本地 `session=17` 的候选池查询接口对该类条件返回系统错误；旧实现会把“查询候选池失败”继续包装成 `candidate_snapshot / applied=true`，模型容易误以为已经拿到候选事实，再输出概括性建议。
- 修复方式：
  - 新增 `candidate_filter_extraction_tool` 作为共享候选筛选抽取层。它只解析本轮候选池查询文本，输出 `tiers / province_names / city_names / school_keywords / major_keywords / school_tags / major_tags`，不更新长期意向，不生成用户回复，也不作为 fast route。
  - `handle_query_candidates` 和 `query_volunteer_plan(scope=candidate / plan_then_candidate)` 统一接入该抽取层；模型只要判断到“需要查候选”，具体筛选条件可由共享层补齐并做 catalog 归一化，避免两个入口语义不一致。
  - `query_volunteer_plan` 会把模型传入的 `query` 与当前轮用户原句合并后送入抽取层，避免主模型把“候选里有没有更稳一点的师范类机会，先查一下别加”压缩成“师范类”后丢失“更稳 / 只查不加”等关键限定。
  - 显式传入的筛选条件优先保留，抽取层只做补充合并；例如模型只传了部分专业或没有传档位时，共享层可补齐专业、地域、冲稳保和院校/专业标签。
  - 候选池接口失败时返回 `result_kind=error / reply_strategy=direct_blocking / reply_focus=candidate_query_failed`，并给用户明确说明“这次候选池没有查成功”，不再输出候选列表或留下确认动作。
- 影响边界：
  - 这不是关键词路由；用户没有被模型或既有工具链判成候选查询时不会被该逻辑接管。
  - 抽取层是输入解析，不改变 `preview -> confirm -> apply`，也不向前端发送候选联动卡片。
  - `majorKeywords` 继续承接候选池历史口径里的专业大类/具体专业，`majorTags` 承接专业门类、招生类型和限报要求，`schoolTags` 承接院校类型/性质/层次等标签。
  - 正常候选查询成功时仍交给模型组织回复；失败直返只用于避免编造候选事实。
- 验证：
  - 单测新增覆盖：
    - `query_candidates` 空 filters 但共享抽取层返回“更稳一点的会计审计”结构时，候选查询带 `tiers=["稳"]`、`major_keywords=["会计学", "审计学"]`。
    - 模型显式传部分筛选条件时，共享抽取层可补齐另一部分条件，合并后再查候选池。
    - `query_volunteer_plan(scope=candidate)` 对“更稳一点的师范类机会”会通过共享抽取层转成 `tiers=["稳"] / school_tags=["师范"]`，避免退化成单个宽泛关键词查询。
    - 候选池失败时返回 `error/direct_blocking`，不带 workspace 刷新。
  - 聚焦回归：`cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_candidate_filter_extraction_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_tool_reply_policy.py tests/unit/test_base_agent.py tests/unit/test_chat_service_history_persistence.py -q`：`264 passed`。
  - 百家 Kimi smoke：`session=120 / 候选里有没有更稳一点的师范类机会，先查一下别加`，工具链为单次 `query_volunteer_plan`，无 follow-up 卡片、无确认预览，端到端约 `13.7s`。抽取日志显示 `tiers=["稳"] / school_tags=["师范"]`，最终回复命中 `南宁师范大学(01)-地理科学（师范）`，录取率约 `60%`。输出文件：`/private/tmp/zhiyuan_303_candidate_filter_shared_extractor_smoke_with_logs.json`。
  - `session=17` 本地候选接口异常不再作为召回质量判断依据。

补充修复：候选筛选标签值归一化。

- 继续复测 `session=120 / 帮我查一下候选池里稳档师范类机会，不要加入方案` 时发现，模型会把用户口语里的“师范类”抽成 `schoolTags=["师范类"]`，候选池标准标签实际是 `师范`。旧链路会把 `师范类` 作为强过滤条件传下去，导致明明存在稳档师范机会却返回空结果。
- 修复方式：
  - 在共享候选筛选抽取层增加 catalog-backed 标签值归一化，不改变路由，不生成模板回复。
  - 对 `schoolTags` 去掉常见类别后缀后匹配 catalog 标签，例如 `师范类 / 师范类院校 / 师范学校` 归一为 `师范`；无法归一的院校动态标签仍保留，避免破坏既有筛选能力。
  - 对 `majorTags` 只保留专业门类、招生类型、限报要求等 catalog 可确认的枚举标签；像 `师范类` 这类实际更接近院校标签或二级专业类的值不会继续作为专业标签 AND 过滤，避免误伤候选召回。
  - catalog 不可用时保留旧行为，不因为本地服务短暂不可达把原有筛选值清空。
- 验证：
  - 聚焦回归：`cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_candidate_filter_extraction_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_tool_reply_policy.py tests/unit/test_base_agent.py tests/unit/test_chat_service_history_persistence.py -q`：`266 passed`。
  - 百家 Kimi smoke：`session=120 / 帮我查一下候选池里稳档师范类机会，不要加入方案`，抽取日志显示 raw `school_tags=["师范类"]`，normalized `school_tags=["师范"] / major_tags=[]`；最终仍只调用一次 `query_volunteer_plan`，无 follow-up 卡片、无确认预览，回复命中 `南宁师范大学(01)-地理科学（师范）`，录取率约 `60%`。端到端约 `33.3s`，其中两次模型请求各约 `9-10s`，工具节点约 `11s`，说明质量链路恢复，但候选只读仍存在“主模型 + 抽取模型 + 后端查询 + 最终模型”叠加耗时。

补充修复：院校标签与专业关键词冲突消解。

- 上述 smoke 继续检查时发现，主模型有时会在调用 `query_volunteer_plan(scope=candidate)` 时把“师范类”压缩为 `major_keywords=["师范"]`，共享抽取层同时又正确识别出 `school_tags=["师范"]`。如果两者都保留，会变成“院校是师范类 AND 专业名/专业类也含师范”的窄筛选，漏掉师范类院校里的非师范专业机会。
- 修复方式：
  - 在 `query_volunteer_plan` 的结构化筛选合并层增加冲突消解：只有当共享抽取层明确给出同值 `school_tags` 时，才移除同值 `major_keywords`。
  - 这仍然不是路由规则，也不是字符串快路径；它只是在模型参数和抽取层结果冲突时，优先信任专门抽取器对字段归属的判断。
  - 不影响真实专业查询，例如 `生物工程 / 网络与新媒体 / 教育学类 / 师范专业` 等仍可作为专业关键词或专业标签传递。
- 验证：
  - 聚焦回归：`cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_candidate_filter_extraction_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_tool_reply_policy.py tests/unit/test_base_agent.py tests/unit/test_chat_service_history_persistence.py -q`：`267 passed`。
  - 百家 Kimi smoke：同一 `session=120 / 帮我查一下候选池里稳档师范类机会，不要加入方案`，最终候选查询 filters 为 `tiers=["稳"] / major_keywords=[] / school_tags=["师范"] / major_tags=[]`；回复从只命中 1 条扩展为 2 条，包含 `南宁师范大学(01)-地理科学（师范）` 和 `广西师范大学(01)-朝鲜语`，并在最终回复中区分“师范类院校”和“专业本身是否师范”，无 follow-up 卡片、无确认预览。端到端约 `21.8s`。

补充修复：候选查询示例去内部 ID 化。

- 复测“候选里还有没有更稳一点的会计审计，别直接加”时，候选查询质量已经恢复，但工具摘要仍可能以 `id=...` 形式把内部 `volunteerId` 暴露给最终模型。即使最终回复不一定原样输出，这类字段也会增加用户侧出现难懂格式的风险。
- 修复方式：
  - `query_volunteer_plan(scope=candidate)` 的候选示例改为用户可读字段：学校、专业、冲稳保、录取率、地域、院校性质、学费。
  - 兼容 `query_planning_candidate_pool` 摘要同步去掉 `id=...`，但只改用户可见文本，不删除结构化数据里的 `volunteerId`，因此不影响后续加入方案、移动、删除等执行链路。
  - 这不是路由快路径，也不改变候选筛选、pending 或确认行为。
- 验证：
  - 聚焦回归：`cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_plan_query_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_planning_router_tool.py -q`：`75 passed`。
  - 百家 Kimi smoke：`session=120 / 候选里还有没有更稳一点的会计审计，别直接加`，最终回复以表格列出 3 条稳档会计学候选，包含学校、专业、层级、录取率、学费和地域；`rg` 检查输出文件未命中 `id=`、`volunteerId`、`planningWorkspaceAction` 或“确认后”。本轮无 follow-up 卡片、无确认预览，端到端约 `38.3s`。
- 后续性能观察：
  - 该 smoke 仍走 `plan_next_action(query_state) -> execute_plan_action(query_state) -> query_volunteer_plan`，共 4 次模型请求。质量和安全边界可接受，但只读候选查询仍存在不必要状态查询和多次模型往返，后续应优先在 full-agent 工具选择层减少无效状态探查，而不是用字符串快路由替代。
