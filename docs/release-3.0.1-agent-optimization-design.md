# Release 3.0.1 Agent Optimization Design

本文承接 `docs/release-3.0.1-current-state-and-optimization-roadmap.md`，用于确认下一批 Agent 和对话驱动优化的落地设计。确认前不改运行代码。

## 1. 目标和范围

### 1.1 本轮目标

本轮优化只做低风险收口，目标是让后续代码改动更可控：

1. 修正文档和 skill 中容易误导的旧入口描述。
2. 补齐 Agent 对话端到端 examples，覆盖职业探索、意向确认、方案排序、专业组操作和去草稿语言。
3. 设计最小结构化日志，为后续替换关键词兜底和评估模型效果提供数据。
4. 明确专业组 unit 级对话操作如何接入 Agent 主链。
5. 明确本期不删除 `planning_workflow_tool`，不重写 `plan_next_action`。

### 1.2 不在本轮做

- 不直接删除 service 层确认短语兜底。
- 不把 `plan_next_action` 改成全 LLM planner。
- 不一次性删除 `planning_router_tool` 或 `planning_workflow_tool`。
- 不改变生产模型 provider 和大模型配置策略。
- 不把行为反馈自动用于算法调参。

## 2. 文档和入口描述收口

### 2.1 Career Explore 入口

当前问题：

- `skills/career_path_chat/SKILL.md` 仍然存在，这是合理的语义说明层。
- 但部分文档把“Career 分析”直接写成 `skills/career_path_chat`，容易误解为旧 skill-only 运行链路。

目标描述：

```text
Career skill 负责语义边界说明；运行时主入口是 analyze_current_career_direction。
职业偏好写入必须走 preview_current_career_intent_confirmation -> update_volunteer_intent_state(confirm)。
```

需要更新的文档：

- `zhiyuan-agent/docs/next_session_handoff.md`
- `zhiyuan-agent/docs/semantic_layer_structure.md`
- `zhiyuan-agent/docs/planning_agentize_design.md`

验收：

- 文档中不再把 `skills/career_path_chat` 描述为运行时主入口。
- 文档明确 Explore 只读、Intent 确认后写入。

### 2.2 Plan Router 入口

当前问题：

- 历史文档仍有 `handle_planning_request` 作为主入口的描述。
- 当前主入口已经收口为 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。

目标描述：

```text
planning_router_tool.handle_planning_request 是 deprecated compatibility wrapper。
新增能力必须接入 Plan 主链，不再接入 router。
```

需要更新的文档：

- `zhiyuan-agent/docs/planning_agentize_design.md`
- `zhiyuan-agent/docs/plan_action_orchestration_design.md`
- `zhiyuan-agent/docs/CHANGELOG.md` 只追加新记录，不改历史记录。

验收：

- 当前设计章节不再要求新逻辑调用 `handle_planning_request`。
- 历史 changelog 保留历史事实，但新增 changelog 标明入口已切换。

### 2.3 Workflow Helper 定位

当前问题：

- `planning_workflow_tool` 名称像 tool，但实际已成为内部 helper 集合。
- 多个 handlers 直接复用它，不能裸删。

目标描述：

```text
planning_workflow_tool 暂时保留为内部 helper 集合。
后续拆分为 formatter / state reader / mutation / review / compensation helper。
测试 patch 点逐步迁移到 handler 实际调用位置。
```

验收：

- 文档明确“不直接删除”。
- 后续拆分顺序清晰，避免误删造成大面积回归。

## 3. Agent Examples 补齐

### 3.1 Career Explore / Intent

新增或补齐 examples：

| 场景 | 用户话术 | 期望链路 | 验收点 |
| --- | --- | --- | --- |
| 泛方向探索 | 我适合什么方向 | `analyze_current_career_direction` | 只读分析，不写 pending intent |
| 具体职业方向探索 | 体制内适不适合我 | `analyze_current_career_direction` | 不说“已记录” |
| 多方向对比 | 体制内和读研哪个更适合我 | career comparison | 先看本人，再看方案承接 |
| 职业正向 intent | 以后优先按体制内稳定就业看 | `preview_current_career_intent_confirmation` | 等用户确认 |
| 职业负向 intent | 不想走体制内 | `preview_current_career_intent_confirmation` with negative | 确认后写入负向 career intent |
| 确认后方案承接 | 确认 -> 当前方案匹配吗 | `update_volunteer_intent_state` 后进入 Plan 主链 | 不重复要求确认 |

落地文件：

- `zhiyuan-agent/examples/dialog_regression_mainline_cases.json`
- `zhiyuan-agent/examples/dialog_regression_plan_correctness_cases.json`
- 必要时补充 `tests/unit/test_intent_state_tool.py` 和 `tests/unit/test_dialog_scenario_stability.py`

### 3.2 Plan 操作和去草稿语言

新增或补齐 examples：

| 场景 | 用户话术 | 期望链路 | 验收点 |
| --- | --- | --- | --- |
| 方案排序 | 按院校层次排序 | `sort_ordered_plan` preview -> confirm -> apply | 审查变为待重新审查 |
| 录取率排序 | 按录取率排序 | `sort_ordered_plan(admissionRatio)` | 默认升序，不再问方向 |
| 固定/锁定拒绝 | 帮我锁定第 3 个 | no-op explanation | 不调用 `pin_unit/unpin_unit/lock_draft` |
| 去草稿文案 | 把这个加入方案 | `add_units` | 回复不出现“草稿” |
| 专业组移动 | 把这个专业组移到第 5 位 | 新增 unit action | 整组移动，组内专业不打散 |
| 专业组删除 | 删除这个专业组 | 新增 unit action | 删除 unit，不残留孤立专业 |
| 学校+专业移动 | 把 XX 大学的 XX 专业改到第 3 位 | `move_unit` | 通过学校名+专业名定位，不要求用户提供数字索引 |
| 学校+专业删除 | 去掉 XX 大学.XX 专业 | `remove_units` | 支持“的”、`.`、`-` 等自然分隔符；歧义时不误删 |

## 4. 最小结构化日志设计

### 4.1 设计原则

- 先做可观测，不改变用户可见行为。
- 日志只记录必要元数据，不记录敏感 API Key。
- 用户文本可以按现有日志策略记录；如后续进入生产分析平台，需要再做脱敏策略。
- 日志失败不能影响主对话。

### 4.2 Conversation Turn Event

建议新增结构化日志事件 `conversation_turn_event`：

```json
{
  "event": "conversation_turn_event",
  "sessionId": "123",
  "userId": "u1",
  "turnId": "optional",
  "scene": "plan|intent|explore|unknown",
  "routingPath": "direct_pending_plan_confirm|direct_pending_intent_confirm|basic_plan_status|full_agent",
  "pendingType": "plan|intent|null",
  "actionFamily": "sort_ordered_plan",
  "modelProvider": "siliconflow",
  "modelName": "xxx",
  "totalDurationMs": 1200,
  "llmDurationMs": 900,
  "toolDurationMs": 200,
  "toolCalls": [
    {
      "name": "execute_plan_action",
      "durationMs": 180,
      "success": true,
      "actionFamily": "sort_ordered_plan"
    }
  ],
  "postProcessingApplied": ["normalize_user_facing_terms"],
  "status": "success",
  "errorType": null
}
```

### 4.3 第一阶段落地点

第一阶段优先在 `zhiyuan-agent/app/service.py` 记录：

- 直接 pending plan confirm。
- 直接 pending intent confirm。
- basic plan status shortcut。
- full agent fallback。

同时在 tool 执行层记录：

- `execute_plan_action` 的 `action_family`、preview/apply、成功/失败、耗时。
- `update_volunteer_intent_state` 的 action、applied、messageCode。

验收：

- 本地运行一轮 plan sort、career explore、intent confirm 后，日志能看出实际 routing path。
- 日志不改变原回复内容。
- 失败异常仍按原逻辑返回，不因日志失败二次报错。

## 5. 专业组 Unit 级对话操作设计

### 5.1 当前能力差异

前端/后端：

- 已有组级移动接口：`/ordered-plan/unit/move`。
- 已有组级删除接口：`/ordered-plan/unit/remove`。
- 成功后会刷新 ordered/draft summary，并标记 review 和 planAdjustment 过期。

Agent：

- 当前主要通过 `move_unit / remove_units` 和 `volunteer_ids` 处理 item 级动作。
- 对专业组模式下“这个专业组”这类表达，缺少稳定的 unit action schema。

### 5.2 新增动作

建议新增两个 action family：

- `move_ordered_unit`
- `remove_ordered_unit`

`PlanAtomicAction` 增加字段：

```json
{
  "unit_ids": ["unit-xxx"],
  "volunteer_ids": [],
  "target_position": 5
}
```

兼容规则：

- `majorGroup` 模式优先用 `unit_ids` 执行组级操作。
- 用户明确说“专业组/这一组/整组/学校专业组”时，规划为 unit action。
- 用户明确点名组内某个专业时，仍可使用 item 级动作。
- 如果只有位置引用，例如“把第 3 个专业组移到第 5 个”，resolver 应按 ordered units 解析。

### 5.3 执行接口

`internal_client` 增加 wrappers：

- `_move_ordered_plan_unit_request(session_id, unit_id, target_position)`
- `_remove_ordered_plan_units_request(session_id, unit_ids)`

`execute_plan_action` 执行：

- preview 阶段展示受影响专业组名称、当前位置、目标位置（移动场景）、组内专业数，并明确“第 N 个专业组”按专业组顺序计算，不等同于“第 N 条志愿”。
- apply 阶段调用后端 unit 接口。
- 成功后刷新 `ordered` 和 `review`，并提示“方案已调整，建议重新审查”。

### 5.4 测试

必须覆盖：

- `majorGroup`：按 unitId 移动到目标位置。
- `majorGroup`：按位置引用移动专业组。
- `majorGroup`：删除专业组后组内专业不残留。
- `majorGroup`：移动/删除预览不得用“前 N 条志愿”解释专业组位置，避免把第 N 条志愿所在专业组误认为第 N 个专业组。
- `major`：不误走 unit action，仍使用 item 级移动/删除。
- preview -> confirm -> apply。
- 操作后 review stale。

## 6. 确认后实施顺序

确认本文后，建议按以下顺序落代码：

1. 文档残留修正，不改运行逻辑。已完成首轮收口。
2. examples 补齐和现有测试断言调整。已完成首轮收口。
3. 最小结构化日志，只记录不改变行为。已完成首轮接入。
4. 专业组 unit action schema、resolver、internal client 和执行层。已完成首轮接入。
5. 回归测试：career、intent、plan sort、unit move/remove、no draft wording。已完成首批目标测试。
6. 更新 `zhiyuan-agent/docs/CHANGELOG.md`。已完成首轮记录。

## 7. 当前实施记录

### 7.1 已落地内容

- 文档入口收口：
  - Career skill 明确为语义说明层，运行时入口为 `analyze_current_career_direction`。
  - Plan 主链统一为 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。
  - `planning_router_tool.handle_planning_request` 标记为 deprecated compatibility wrapper。
  - `planning_workflow_tool` 暂不删除，保留为内部 helper 集合。
- examples 补齐：
  - `dialog_regression_mainline_cases.json` 补充职业泛方向、职业对比、职业负向意向、专业组移动/删除和旧锁定禁用场景。
  - `dialog_regression_plan_correctness_cases.json` 补充 unit move/remove 正确性场景。
  - `model_provider_benchmark_e2e_cases.json` 补充 career generic 和 unit move 场景。
- 结构化日志：
  - 新增 `conversation_turn_event`，覆盖直接 plan confirm、直接 intent confirm、no-pending guard 和 full agent 路径。
  - 新增 `plan_action_event` 和 `intent_state_event`，记录 action family、阶段、耗时和结果状态。
  - 日志采用 best-effort，不影响原对话流程。
- 专业组 unit 级对话动作：
  - 新增 `move_ordered_unit` 和 `remove_ordered_unit`。
  - `PlanAtomicAction` 支持 `unit_ids`。
  - `plan_next_action` 支持显式 `unit_ids`，并在用户说“专业组/这一组/整组/院校专业组”时将 item 级移动/删除归一为 unit 级动作。
  - `execute_plan_action` 支持按 `unit_ids` 执行，也支持从 `orderedPlanState.units` 解析“第 N 个专业组”。
  - `internal_client` 接入后端组级移动/删除接口，成功后刷新 `ordered` 和 `review`。
- 3.0.1 用户侧约束：
  - Agent 文案继续去“草稿”，统一使用“方案/当前方案/已加入方案”。
  - `pin_unit/unpin_unit/lock_draft` 不作为用户可触发入口；用户要求固定/锁定时，回复当前新版工作台暂不提供该入口，并建议移动到指定位置或使用排序。
  - `ActionResolver` 侧也同步阻断 `pin/unpin` 结构化意图，避免后续 structured planner 或测试旁路重新产出前端不可见的固定/锁定动作。

### 7.2 已验证内容

- JSON examples 格式校验通过：
  - `dialog_regression_mainline_cases.json`
  - `dialog_regression_plan_correctness_cases.json`
  - `model_provider_benchmark_e2e_cases.json`
- Python 编译校验通过：
  - `typed_actions.py`
  - `plan_orchestration_tool.py`
  - `plan_execution_tool.py`
  - `state_sync.py`
  - `service.py`
  - `structured_log.py`
- Targeted 单测通过：
  - `tests/unit/models/test_typed_actions.py`
  - `tests/unit/test_action_resolver.py`
  - `tests/unit/test_plan_orchestration_tool.py`
  - `tests/unit/test_state_sync.py`
  - `tests/unit/test_chat_agent_init_profile.py`
  - `tests/unit/test_plan_execution_tool.py`
  - 结果：`315 passed`
- Router/workflow 兼容测试已完成同步清理：
  - `tests/unit/test_planning_router_tool.py`
  - `tests/unit/test_planning_router_tool_sync.py`
  - `tests/unit/test_planning_plan_scenarios_sync.py`
  - `tests/unit/test_planning_workflow_tool.py`
  - 修正重点：初始生成方案补齐候选池前置 mock；旧 `handle_planning_request` 用例保留为 compatibility wrapper 测试；旧“草稿/排序方案摘要/volunteerId”断言同步为 3.0.1 用户侧语言；执行链 patch 点迁移到当前 handler/internal-client alias。
  - 结果：`72 passed`
- Agent 主链路 + router/workflow 兼容集合通过：
  - 覆盖 resolver、typed action、orchestration、state sync、chat profile、plan execution、router/workflow。
  - 结果：`387 passed`
- `git diff --check` 通过。

### 7.2.1 真实 WebSocket 验证口径

新增 3.0.1 Agent smoke 用例文件：

- `zhiyuan-agent/examples/dialog_regression_301_agent_smoke_cases.json`

覆盖场景：

| 场景 | session | 期望链路 | 重点验收 |
| --- | --- | --- | --- |
| 查看当前方案 | `17` | `query_state` | 返回冲稳保和方案概况，不出现内部字段，不额外要求用户确认 |
| 审查方案 | `17` | `review_plan` | 返回审查/风险摘要，用户语言保持“方案” |
| 按院校层次排序 | `16` | `sort_ordered_plan -> confirm -> apply` | 先预览确认，确认后刷新 `ordered`，审查进入待重新审查 |
| 移动专业组 | `16` | `move_ordered_unit -> confirm -> apply` | 整组移动，不打散组内专业，确认后刷新 `ordered` |

执行命令：

```bash
cd zhiyuan-agent
PYTHONPATH=. ./.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_301_agent_smoke_cases.json \
  --response-timeout 180
```

记录口径：

- runner 输出每轮 `elapsedMs / primaryMessages / followupMessages`。
- 结构化日志补充核对 `conversation_turn_event / plan_action_event` 中的 `toolCalls`、`actionFamily`、模型耗时和 token 用量。
- 对副作用动作必须同时检查文本回复和 follow-up：排序、移动、删除、审查等动作需要看到 `targetView=ordered` 且 `refresh=true`。
- 用户可见文本不得出现 `草稿`、`payload`、`stage`、`action_family`、`volunteerId` 等内部词。

当前 examples 同步：

- 移除旧 `correctness-pin-and-verify-35` 用例，避免和 3.0.1 “固定/锁定入口关闭”策略冲突。
- 保留 `correctness-pin-disabled-in-301-35`，作为新版锁定入口关闭的唯一验证口径。
- `session=35` 当前存在历史 pending intent 干扰，不适合作为 3.0.1 排序/专业组 smoke fixture；专业组 smoke 改用 `session=16`。

本轮真实 smoke 发现：

- `session=17 / 看看现在的方案` 可返回，runner 耗时约 `18.0s`，结构化日志为 `3` 次 LLM 请求、`36082` input tokens、`2` 次 tool call，最终 action 为 `query_state`。
- `session=17 / 帮我审查一下` 可返回，runner 耗时约 `27.1s`，结构化日志为 `4` 次 LLM 请求、`57447` input tokens、`3` 次 tool call，仍有一次重复 `collect_plan_context_inputs`，后续可继续优化 prompt/schema。
- `session=35 / 把第3个专业组移到第5位` 触发了长链路循环：约 `144.4s`、`17` 次 LLM 请求、`19` 次 tool call，执行层多次返回 `invalid_plan_model`。该样本被移出 smoke fixture，另记为后续 agent unit action 稳定性问题。
- `session=16 / 按院校层次排序 -> 确认` 暴露执行状态不一致：后端实际执行成功并刷新，但文本返回“排序失败”。原因是执行层只识别 `{code: 0}`，未兼容 `{success: true}`，且失败摘要仍被包装为 `applied=true`。当前修复为统一成功判定，并且失败时 `applied=false`、不返回 workspace refresh。

执行层修复后首次复跑发现：

- `session=17 / 看看现在的方案` 通过，耗时约 `20.8s`，`3` 条主消息，无 follow-up。
- `session=17 / 帮我审查一下` 通过，耗时约 `18.7s`，`3` 条主消息，无 follow-up。
- `session=16 / 按院校层次排序` 曾暴露 pending 形成不稳定：模型有时只调用 `collect_plan_context_inputs -> plan_next_action`，未继续调用 `execute_plan_action(preview)`，确认时进入 `plan_confirmation_guard_no_pending`。当前通过 service 层直接从 `plan_next_action(preview)` 提取 pending 收口。
- `session=16 / 把第3个专业组移到第5位` 曾暴露 pending 被只读查询清掉：模型形成 `move_ordered_unit` preview 后又执行 `query_state`，旧逻辑把任意 `applied=true` 都视为清 pending。当前已改为只有变更动作 apply 成功才清 pending。

下一步修复方向：

- 对高副作用动作预览，不能只依赖模型自觉继续调用 `execute_plan_action`；需要在设计上明确“`plan_next_action` 产出 preview 后如何稳定形成 pending plan”。可选方案包括：提示词继续收紧、服务层从 `plan_next_action` 工具返回直接提取 pending、或引入结构化 planner 执行器统一串联 preview。
- 专业组位置移动要减少模型循环：`move_ordered_unit` 的 preview 一旦可解析 `unit_ids/target_position`，应直接形成可确认预览，不应继续查询多个学校/专业再改回 item 级判断。

本轮已落地的结构收口：

- `plan_next_action` 增加高副作用动作状态约束：当 `user_confirmed=false` 时，即使模型传入 `current_stage="apply"`，也强制回到 `preview` 或 `analyze`，避免出现“未确认但 apply”的结构矛盾。
- `move_ordered_unit / remove_ordered_unit` 支持“第 N 个专业组/志愿组”作为位置引用；preview 阶段不再要求模型必须提前提供真实 `unit_ids`，执行层继续负责按当前 ordered units 解析真实 unitId。
- `move_unit / remove_units / replace_units` 支持学校名+专业名引用（如“XX大学的XX专业”“XX大学.XX专业”）；执行层会按当前方案重新解析真实 volunteerId。如果同校同专业在多个专业组中同时出现，不能静默选择其中一个，必须返回需要进一步明确的提示。
- Agent 指令补充：未确认动作不得传 `current_stage="apply"` 或 `user_confirmed=true`；`execute_plan_action` 返回 `preview_only` 后本轮停止继续查工具，直接等待用户确认。
- service 层 pending 提取规则收口：同一轮中如果已经形成高副作用 preview，后续只读 `query_state` 成功不会再清掉 pending；只有真正的变更动作 apply 成功才清掉上一轮待确认计划。该修复解决了“专业组移动预览后模型又查状态，导致用户确认时无 pending”的问题。
- 本地排序接口失败定位为运行进程 class 版本不一致：8080 后端旧 class 抛 `PlanningStateService$OrderedSortKey` `NoSuchMethodError`。重新编译/重启后端后，`ordered-plan/sort` 能正常返回成功结果；源码层未发现 agent payload 问题。
- 测试口径同步：service 层历史测试不再 patch 已删除的 `get_planning_state`，改为当前真实依赖 `get_planning_workspace_state`；旧 `review` 工作台卡片断言已清理，因为当前兼容工作台只支持 `candidate / ordered` 两类目标。

已验证：

- `tests/unit/test_plan_orchestration_tool.py`
- `tests/unit/test_plan_execution_tool.py`
- `tests/unit/test_chat_service_history_persistence.py`
- 结果：`171 passed`
- 真实 WebSocket smoke：`examples/dialog_regression_301_agent_smoke_cases.json` 通过。
  - `session=17 / 看看现在的方案`：约 `16.7s`，无 follow-up。
  - `session=17 / 帮我审查一下`：约 `8.9s`，无 follow-up。
  - `session=16 / 按院校层次排序 -> 确认`：预览约 `19.4s`，确认约 `5.6s`，返回 `ordered` 刷新卡片。
  - `session=16 / 把第3个专业组移到第5位 -> 确认`：预览约 `22.1s`，确认约 `4.9s`，返回 `ordered` 刷新卡片。
- 专业组位置文案修正后复测：
  - `session=16 / 把第3个专业组移到第5位 -> 确认`：预览约 `36.4s`，确认约 `4.9s`。
  - 预览明确展示“当前第3个专业组”“组内共 2 个专业”“移动到第5个专业组的位置”，不再使用“前5位志愿概况”解释专业组位置。
  - 执行后读取当前方案确认：河南牧业经济学院卡洛理工国际学院第203组位于第 `5` 个专业组位置，组内 `2` 条志愿连续，`orderReason=user_unit_move`。

### 7.3 已知测试边界

- `tests/unit/test_plan_execution_tool.py` 的历史 fixture 债务已完成首轮清理：旧用例从 patch `plan_execution_tool` 里的旧 workflow wrapper，迁移到当前实际消费方 handler 或 internal-client alias，避免本地单测误连真实 backend。
- router/workflow 旧入口测试已按兼容定位收口，但仍不代表新增能力可以继续接入 router；新增能力仍必须走 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。
- 真实 websocket regression 已完成首轮 smoke：方案现状、审查、院校层次排序确认、专业组移动确认通过。后续仍需扩充删除专业组、专业模式移动/删除、补齐建议 apply 等用例。

### 7.4 WebSocket Smoke 发现的问题

历史本地真实 compat websocket 验证曾出现超时：

```bash
./.venv/bin/python examples/dialog_regression_runner.py \
  --session 17 \
  --prompts "看看现在的方案" \
  --response-timeout 180
```

历史现象：

- Agent 健康接口正常，backend `8080` 和 rank `5001` 均在监听。
- WebSocket 能建立连接，但 180 秒内没有收到结束消息。

初步定位：

- “看看现在的方案”这类低副作用快捷问法当前会进入完整 LLM agent 链路。
- 现象上看不到是 LLM provider 延迟、Agent 工具调用卡住，还是 WebSocket 结束消息没有正确发出。
- 当前已有 `_is_basic_plan_status_question()` 和 `_build_basic_plan_status_reply()` 这类确定性摘要辅助函数，但直接绕过大模型会降低回复润色和上下文适配能力，不作为未确认方案直接落地。

当前状态：

- 不短路大模型，仅通过提示词和工具链约束减少重复 `collect_plan_context_inputs`。
- `examples/dialog_regression_301_agent_smoke_cases.json` 已通过真实 WebSocket 验证，未复现 180 秒超时。

待解决问题：

- 增加链路分段耗时记录：score/profile/workspace state、LLM 首 token、工具调用、最终发送。
- 对快捷方案状态类问题保留大模型润色，但需要给模型更小、更结构化的上下文，避免拉取过重状态或进入多轮工具循环。
- 确认是否需要“模型超时后使用结构化摘要兜底”的降级策略；兜底只应在超时或异常时触发，不作为默认路径。
- 持续扩充真实 websocket regression case：当前已覆盖 `看看现在的方案`、`帮我审查一下`、`按院校层次排序 -> 确认`、`把第 N 个专业组移到第 M 位 -> 确认`；后续还需要补 `remove_ordered_unit`、专业模式 `move_unit/remove_units`、补齐建议 preview/apply。
- 如果后续要接入 `basic_plan_status` routing path，应设计为“轻量事实摘要 -> LLM 润色 -> 超时兜底”，而不是简单绕过大模型。

已确认的低风险优化方向：

- 保留大模型最终表达，不在 service 层直接返回确定性模板。
- 对“方案有了么 / 看看现在的方案 / 当前方案怎么样”这类现状查询，提示词层面允许模型直接调用 `plan_next_action(action_family="query_state") -> execute_plan_action`，不再要求先单独调用一次 `collect_plan_context_inputs`。`plan_next_action` 内部已经会读取上下文，单独调用 `collect_plan_context_inputs` 会造成重复工具和额外 LLM 往返。
- 暂不增加新的字符串匹配 guard。当前如果只是多一次模型/工具调用，先记录为性能待优化项；后续优先通过 prompt、工具 schema 和 examples 让模型稳定选择 `query_state`。
- 预期效果：`看看现在的方案` 尽量从“collect -> plan_next -> execute -> final”降为“plan_next -> execute -> final”，但不在本轮通过关键词规则强行改写 action。

当前验证结果：

- SiliconFlow `Pro/moonshotai/Kimi-K2.6` 下，提示词优化前真实 websocket smoke 为约 `38.3s`，`4` 次 LLM 请求，约 `40109` input tokens，工具执行约 `963ms`。
- 当前代码直接跑 `ChatService.handle_message(session=17, content="看看现在的方案")`，链路为 `plan_next_action -> execute_plan_action(query_state) -> final`，没有单独工具调用 `collect_plan_context_inputs`。
- 当前诊断耗时约 `14.6s`，`3` 次 LLM 请求，约 `28331` input tokens，`execute_plan_action(query_state)` 约 `305ms`。
- 结论：不绕过大模型的前提下，提示词收敛已经能减少一次模型往返和约 1.18 万 input tokens；后续若还需进一步降延迟，再考虑模型结构化分类、轻量事实摘要或超时兜底设计。

#### 显式方案改动类请求

真实 WebSocket 删除专业组验证中，`session=16 / 删除第3个专业组` 曾出现先 `query_state` 再 `remove_ordered_unit(preview)` 的绕路，导致一次无必要的状态播报和额外 LLM 往返。当前提示词进一步收敛：

- 显式排序、移动、删除当前方案的请求，不先做 `query_state` 状态播报。
- 直接规划对应 action 的 preview，并交给 `execute_plan_action` 形成可确认 pending。
- 仍不增加新的 service 层字符串匹配或确定性短路，最终回复继续由大模型基于工具事实组织。

验证结果：

- 首次验证中，`session=16 / 删除第3个专业组` 曾先执行一次 `query_state`，说明该性能问题需要通过提示词和可观测性一起收口。
- 补充显式改动类请求约束并重启 agent 后，复测 `session=16 / 删除第3个专业组` 不再先做 `query_state`，链路为 `plan_next_action -> execute_plan_action(remove_ordered_unit preview) -> final`；runner 耗时约 `24.1s`，LLM 请求 `2` 次，tool call `2` 次。
- 同轮最终结果是 `remove_ordered_unit(preview)`，但旧 `conversation_turn_event.actionFamily` 会记录成第一次工具结果 `query_state`。当前已修正日志归因：如果同一轮包含多个 plan action，优先记录最后一个非 query action，避免 benchmark 和线上分析把实际删除/移动预览统计成状态查询。

### 7.5 Release 3.0.0 Review 跟进

`docs/release-3.0.0-review-claude.md` 已纳入 3.0.1 后续优化参考。当前先处理低风险、可验证事项：

- 已清理 `ChatAgent` 中不再生效的旧 `_build_instructions` 死代码，当前唯一生效入口为 `app.agent.instructions.assembler.build_instructions`。
- 暂不直接移除 service 层确认检测、pending 历史扫描或文本后处理；这些路径仍承担线上兼容和确认态兜底，需要先完成结构化 classifier / shared pending store / tool response envelope 的设计与回归覆盖。
- `_RECENT_PLAN_EXECUTION_RESULTS` 仍是内存级短 TTL 缓存，多 worker 下需要 sticky session 或共享存储。该项记录为发布部署风险，不在本轮用临时规则修补。

## 8. 风险控制

- 所有高副作用动作继续 preview -> confirm -> apply。
- unit action 只在专业组语义明确或 mode 为 `majorGroup` 且引用的是 unit 时启用。
- 日志记录失败全部吞掉并 warning，不影响用户主流程。
- 旧 router/workflow 不在本轮删除，避免一次性扩大影响面。
