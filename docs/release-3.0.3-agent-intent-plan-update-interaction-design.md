# Release 3.0.3 Agent 意向与方案更新交互设计

## 1. 背景

3.0.3 的 Agent 优化过程中暴露了一个核心问题：意向更新、硬要求更新和方案调整虽然都已有“预览后再确认”的概念，但确认入口和状态来源没有统一。

当前系统同时存在：

- Intent 卡片采纳：`planEditSelectPopup / intentDetectSelectPopup / intentConfirmPopup`
- Intent 文本确认：`direct_pending_intent_confirm`
- Plan 文本确认：`direct_pending_plan_confirm`
- 工作区联动卡片：`planningWorkspaceAction`
- 后端旧缓存：`planEditCache`
- 运行时 pending：`conversation_phase.pending`
- 旧运行时字段：`pending_intent_change / pending_plan_action`
- 从历史消息和工具返回中恢复 pending 的逻辑

这些路径在功能上大多没有坏，但会造成用户预期不一致：用户看到的是一张待确认卡片，系统内部却可能因为后续自然语言、历史 pending 或旧缓存而决定是否执行更新。

本设计目标是把所有会改变长期意向、硬要求、候选收紧逻辑或方案内容/顺序的动作，统一收口到一套显式确认卡片协议。

## 2. 产品原则

1. 所有状态更新都必须先生成待确认卡片。
2. 用户点击卡片按钮是唯一确认入口。
3. 普通对话文本不能触发意向、要求或方案更新。
4. 卡片必须披露本次会更新什么、属于偏好还是要求、确认前是否生效、确认后影响哪些后续行为。
5. 用户不点击卡片而继续对话时，pending 保持未采纳；只读追问可以分析影响，但不能消费 pending。
6. 用户回头点击同一张卡片时，应按卡片披露内容执行，除非 pending 已过期、被覆盖、已取消或后端版本已失效。
7. Intent 更新和 Plan 更新使用同一套 `pending -> card -> confirm/cancel -> apply` 协议。

## 3. 软意向与硬要求

### 3.1 定义

| 类型 | 含义 | 示例 | 确认后行为 |
| --- | --- | --- | --- |
| 软意向 `preference` | 非排他偏好，作为后续推荐、解释、方案分析的参考 | 想去北京；更倾向财经；体制内方向可以优先看看 | 写入参考偏好，不直接收紧候选 |
| 硬要求 `constraint` | 排他或强限制条件，会影响候选范围和方案检查边界 | 就去北京；只看北京；不去上海；护理不要 | 写入要求，并用于 candidate filters / 方案检查 |

### 3.2 当前保留情况

当前后端保留 `intent_mode=preference|constraint`：

- Intent preview payload、卡片内容和 `planEditCache` 中都会带 `intentMode/intent_mode`。
- `preference` 确认后主要写入 profile / latent profile，作为后续分析参考。
- `constraint` 确认后会构建 candidate filters，返回候选收紧数量和 candidate 工作区刷新意图。
- 前端 Intent 卡片已有“采纳”按钮，但主要靠标题和文案区分偏好/要求。

### 3.3 当前缺口

当前 `_classify_intent_mode` 的默认逻辑是：

- 有显式 `intent_mode` 时使用显式值。
- 没有负向排除时默认 `preference`。
- 有负向排除时默认 `constraint`。

这会导致：

- “想去北京”默认偏好，合理。
- “不去上海 / 护理不要”默认要求，合理。
- “就去北京 / 只看北京 / 必须北京”这类纯正向硬要求，如果模型没有显式传 `intent_mode=constraint`，会退成偏好。

后续落地时，hard positive 必须稳定进入 `constraint` 卡片；如果系统不确定，应在卡片中披露“我理解为要求，请确认”，而不是默认当偏好。

### 3.4 意向确认后的专家优选推荐更新

意向或要求一旦被用户确认，就不只是写入对话画像，还需要更新“专家优选”的志愿推荐结果。否则右侧候选和推荐仍然沿用旧偏好，用户会看到“我已经采纳了新偏好，但推荐没有变化”的错位。

确认后的目标链路：

1. 写入新的偏好/要求。
2. 调用后端候选池/专家优选推荐更新链路，基于最新画像重新生成或刷新专家优选结果。
3. 返回工作区刷新目标，让前端刷新候选和专家优选推荐。
4. 如果当前排序方案里已有用户手动调整过的志愿，不因为意向变更自动覆盖当前排序方案。
5. 如果新要求和当前排序方案冲突，应标记方案需要重新检查，并提示用户“可以查看方案里哪些志愿不符合新要求”，而不是静默删除或重排。

接口层面可复用现有能力：

- `POST /inner/planning/{tenantId}/session/candidate-pool/generate`
- `POST /inner/planning/{tenantId}/session/initial-recommendation/generate`
- 必要时结合内部推荐接口或 rank 服务重新计算推荐排序。

这里的原则是：意向确认会更新专家优选推荐和候选展示，但不会自动改动用户已经在排序区里的方案。方案变更仍然必须再走方案调整确认卡片。

## 4. 当前链路 Review

### 4.1 Plan 方案更新

当前 Plan 变更动作包括：

- `add_units`
- `remove_units`
- `move_unit`
- `move_ordered_unit`
- `remove_ordered_unit`
- `replace_units`
- `sort_ordered_plan`
- `regenerate_order`
- `apply_compensation`

现状：

- 执行层已有 apply guard：未确认时 mutating apply 会降级为 preview。
- preview 结果通过 `_extract_pending_plan_action` 从历史工具返回中恢复成旧格式 `pending_plan_action`。
- 用户回复“确认 / 好的 / 可以 / 就这样”等短文本时，`service.py` 会走 `direct_pending_plan_confirm`，直接调用 `execute_plan_action(apply)`。
- 前端没有 Plan 变更确认卡片。
- `planningWorkspaceAction` 只是打开/刷新工作区，不是确认入口。

问题：

- Plan 当前是“预览 -> 文本确认 -> 执行”，不是“预览 -> 卡片确认 -> 执行”。
- pending 来源依赖历史扫描，容易被中间只读追问、历史裁剪或旧工具返回影响。
- 文本“确认”语义不可控，可能只是用户对上一轮分析的口语收尾。

### 4.2 Intent 意向/要求更新

现状：

- 用户表达偏好或要求时，Agent 调用 `preview_current_*_intent_confirmation`。
- 工具会把待确认内容写入 `planEditCache`，并返回 Intent 确认卡片。
- 前端点击“采纳”后通过 WebSocket `inputType=intentSelect` 发送 `selected + message_id`。
- 服务端调用 `apply_selected_intents`，再调用 `update_volunteer_intent_state(action="apply_selected")` 写入正式意向。
- 同时仍保留文本确认：如果当前 session 有 pending intent，用户输入“确认”等短文本可能走 `direct_pending_intent_confirm`。

问题：

- Intent 已有卡片，但没有统一 `pending_id`。
- `planEditCache` 是匿名缓存，不适合作为长期确认状态主源。
- 文本确认和卡片采纳并存，可能造成确认错位。
- 旧 `pending_intent_change`、`planEditCache`、`conversation_phase.pending` 并存。

### 4.3 前端卡片类型

| 卡片类型 | 当前用途 | 是否确认卡片 |
| --- | --- | --- |
| `planningWorkspaceAction` | 打开/刷新候选或方案工作区 | 否 |
| `planEditSelectPopup` | Intent 采纳 | 是，旧格式 |
| `intentDetectSelectPopup` | Intent 采纳 | 是，旧格式 |
| `intentConfirmPopup` | Intent 采纳 | 是，旧格式 |
| `interestAnalysisPopup` | 兴趣/影响分析后续动作 | 否 |

结论：

- 前端已有 Intent 确认卡片雏形。
- 前端没有 Plan 方案更新确认卡片。
- 工作区联动卡片不能承载确认语义。
- 新协议需要独立 `pendingConfirmationCard`。

## 5. 目标状态模型

```text
MutationCandidateCreated
  -> PendingConfirmation(active)
  -> pendingConfirmationCard
  -> user_click_confirm_card
      -> confirm(pending_id)
      -> apply_update(payload)
      -> PendingConfirmation(applied)
      -> workspace refresh if needed
  -> user_click_cancel_card
      -> PendingConfirmation(cancelled)
  -> new_pending_replaces_old
      -> old PendingConfirmation(replaced)
  -> pending_expired_or_version_invalid
      -> PendingConfirmation(expired)
```

`new_pending_replaces_old` 的用户侧行为：

- 同一会话同一时间只保留一个可点击的待确认卡片。
- 如果用户还没处理上一张待确认卡片，又提出了新的偏好、要求或方案调整，系统直接用新的待确认内容替代旧内容。
- 旧卡片立即变成不可点击状态，显示“已被新的确认内容替代”。
- 用户再点击旧卡片时，不执行旧动作，只提示“这条内容已经被后面的新确认内容替代，需要重新生成”。
- 新卡片必须完整披露最新要采纳或调整的内容，不能依赖旧卡片里的说明。
- 不判断新旧卡片是否同类、是否冲突。只要新的卡片会改变状态，就替代当前 active 卡片。
- 只读追问、普通咨询、工作区打开/刷新卡片不会替代当前 active 卡片。

只读追问：

```text
PendingConfirmation(active)
  -> user_followup_readonly
  -> analyze_with_related_pending(pending_id)
  -> PendingConfirmation(active)
```

## 6. PendingConfirmation 数据模型

```json
{
  "pendingId": "uuid",
  "sessionId": "16",
  "kind": "intent_change | plan_mutation",
  "actionFamily": "set_preference | set_constraint | add_units | remove_units | move_ordered_unit | sort_ordered_plan | ...",
  "status": "active | applied | cancelled | replaced | expired",
  "intentMode": "preference | constraint",
  "summary": "用户可见摘要",
  "disclosure": {
    "title": "待确认内容",
    "items": [],
    "impact": [],
    "confirmText": "采纳",
    "cancelText": "暂不采纳"
  },
  "payload": {},
  "sourceMessageId": 12345,
  "sourceTurn": 12,
  "sourceBackendVersion": 7,
  "createdAt": "2026-06-02T00:00:00+08:00",
  "expiresAt": "2026-06-02T00:30:00+08:00"
}
```

约束：

- 同一 session 原则上只允许一个 active pending。
- 新 pending 生成时，要么覆盖旧 pending 并把旧 pending 标记为 `replaced`，要么提示用户先处理旧 pending。
- `confirm` 只接受 `active + same pendingId + not expired + version valid`。
- 过期、覆盖、取消、已执行的 pending 不能再次确认。

## 7. 统一确认卡片

### 7.1 Intent 偏好卡片

```json
{
  "type": "pendingConfirmationCard",
  "pendingId": "uuid",
  "kind": "intent_change",
  "actionFamily": "set_preference",
  "intentMode": "preference",
  "title": "要把这个想法记下来吗？",
  "summary": "采纳后，我会在后面推荐和分析时优先参考“北京”。",
  "items": [
    {
      "label": "偏好地域",
      "content": "北京",
      "value": {"city_intents": {"province": ["北京"]}}
    }
  ],
  "impact": [
    "不采纳也没关系，当前方案不会变化。",
    "采纳后会重新看看专家优选推荐，但不会直接改动你的排序方案。"
  ],
  "confirmText": "采纳",
  "cancelText": "暂不采纳",
  "status": "active"
}
```

### 7.2 Intent 要求卡片

```json
{
  "type": "pendingConfirmationCard",
  "pendingId": "uuid",
  "kind": "intent_change",
  "actionFamily": "set_constraint",
  "intentMode": "constraint",
  "title": "要按这个要求来筛吗？",
  "summary": "采纳后，护理学会作为后续不考虑的方向。",
  "items": [
    {
      "label": "排除专业",
      "content": "护理学",
      "value": {"major_intents": {"negative_level3": ["护理学"]}}
    }
  ],
  "impact": [
    "不采纳前，当前方案和推荐不会变化。",
    "采纳后会重新看看可选志愿和专家优选推荐，并提醒当前方案里是否有冲突。"
  ],
  "confirmText": "采纳",
  "cancelText": "暂不采纳",
  "status": "active"
}
```

### 7.3 Plan 方案调整卡片

```json
{
  "type": "pendingConfirmationCard",
  "pendingId": "uuid",
  "kind": "plan_mutation",
  "actionFamily": "move_ordered_unit",
  "title": "确认这样调整方案吗？",
  "summary": "确认后，会把第 3 个专业组移到第 5 位。",
  "items": [
    {
      "label": "调整对象",
      "content": "天津财经大学珠江学院(01)专业组"
    },
    {
      "label": "位置变化",
      "content": "第 3 位 -> 第 5 位"
    }
  ],
  "impact": [
    "这会改变当前方案顺序。",
    "调整后建议重新审查一下方案风险。"
  ],
  "confirmText": "确认调整",
  "cancelText": "暂不调整",
  "status": "active"
}
```

### 7.4 失效卡片

旧卡片、过期 pending 或版本失效 pending 在前端应展示为不可点击状态：

```json
{
  "type": "pendingConfirmationCard",
  "pendingId": "uuid",
  "status": "expired",
  "title": "这条确认已失效",
  "summary": "方案或偏好已经有变化了，请重新说一下要采纳或调整的内容。",
  "confirmText": "已失效",
  "cancelText": "",
  "disabledReason": "pending expired or planning version changed"
}
```

前端展示规则：

- `active`：显示确认/取消按钮。
- `applied`：按钮置灰，显示“已采纳/已调整”。
- `cancelled`：按钮置灰，显示“已取消”。
- `replaced`：按钮置灰，显示“已被新的确认内容替代”。
- `expired`：按钮置灰，显示“已失效，请重新生成”。

## 8. 服务端接口

| API | 用途 | 调用方 |
| --- | --- | --- |
| `POST /inner/pending-confirmations` | 创建 pending，并返回卡片 disclosure | Agent preview 工具 |
| `GET /inner/pending-confirmations/active?sessionId=...` | 查询当前 active pending | Agent / 前端重连 |
| `POST /pending-confirmations/{pendingId}/confirm` | 确认并执行 pending payload | 前端卡片按钮 |
| `POST /pending-confirmations/{pendingId}/cancel` | 取消 pending | 前端卡片按钮 |
| `POST /inner/pending-confirmations/{pendingId}/expire` | 主动过期 pending | 后端/清理任务 |

执行规则：

- `confirm` 不接受自然语言内容作为确认依据。
- `confirm` 必须校验 session、用户权限、pending 状态、过期时间和后端版本。
- `plan_mutation` 确认成功后执行原 `execute_plan_action(apply)` handler，但入口是确认服务内部。
- `intent_change` 确认成功后执行原 `apply_selected_intents` / `update_volunteer_intent_state` 合并写入逻辑，但入口是确认服务内部。
- `intent_change` 确认成功后必须触发专家优选推荐更新。对于偏好，刷新推荐排序和匹配解释；对于要求，刷新可选志愿、专家优选推荐和冲突提示。
- 专家优选推荐更新采用异步完成。确认接口先返回“已采纳，正在重新看看推荐”，推荐刷新完成后再通知或触发前端刷新候选/专家优选区域。
- 执行成功后返回用户可见摘要和 `workspaceRefreshTargets`。
- 执行失败时，如果可重试，pending 保持 `active`；如果不可重试，pending 标记为 `expired` 或 `cancelled` 并返回原因。

## 9. Agent 改造

### 9.1 Intent preview

新链路：

1. Agent 判断用户是在表达偏好/要求。
2. 调用对应 Intent preview 工具，抽取结构化 payload。
3. 工具生成 disclosure，创建 `PendingConfirmation(kind=intent_change)`。
4. Agent 返回文本说明和 `pendingConfirmationCard`。
5. 确认前不写入 profile，不刷新候选，不改变方案。

要求：

- `preview_current_*_intent_confirmation` 不再把匿名 `planEditCache` 作为最终 pending。
- 如果本轮只是只读影响分析，不创建 pending。
- hard positive 必须进入 `constraint` 卡片，不能默认偏好。

确认后的刷新要求：

- `preference` 确认后：更新画像，重新计算专家优选推荐，刷新候选/专家优选展示；不直接改排序方案。
- `constraint` 确认后：更新画像和筛选边界，重新计算候选池和专家优选推荐；如当前方案存在不符合要求的志愿，提示用户查看方案风险或发起方案调整确认。
- 专家优选推荐刷新异步完成，不阻塞用户采纳偏好/要求。
- 如果 rank 或推荐更新失败，不能把意向写入回滚成不确定状态；应明确提示“偏好已采纳，但推荐刷新失败，可稍后重试刷新”，并保留可重试的刷新动作。
- 异步刷新结果必须带上画像版本/推荐版本，不能让旧刷新结果覆盖新偏好或新要求。

### 9.2 Plan preview

新链路：

1. Agent 判断用户要改变方案内容或顺序。
2. `plan_next_action` / `execute_plan_action(preview)` 生成预览 facts。
3. 创建 `PendingConfirmation(kind=plan_mutation)`。
4. 返回 `pendingConfirmationCard`。
5. 确认前不刷新工作区，不改变方案。

要求：

- `planningWorkspaceAction` 只在 apply 成功后发送。
- Plan preview 卡片必须展示调整对象、位置/数量变化、影响和重新审查提示。
- `execute_plan_action(apply)` 不再暴露给模型作为可直接执行入口。

### 9.3 文本确认

文本“确认 / 好的 / 可以 / 就这样”统一处理：

- 有 active pending：提示“请点击上方卡片确认”，必要时重发 active card。
- 无 active pending：返回 no-pending guard。
- 不执行任何更新。

### 9.4 只读追问

如果用户在 active pending 后追问：

- “这个偏好会影响当前方案吗”
- “如果采纳会少多少候选”
- “这个调整会不会太冒险”
- “采纳后专家优选会变吗”
- “现在方案里哪些会不符合这个要求”

系统应读取 `pending_id` 对应 disclosure/payload 做只读分析，并保持 pending active。

只读追问的行为边界：

- 可以读取当前方案、候选池、专家优选推荐、审查结果和 pending payload。
- 可以给出“如果采纳，大概会影响哪些推荐/哪些志愿可能冲突”的解释。
- 不能写入偏好或要求。
- 不能刷新 rank 结果。
- 不能改动排序方案。
- 不能把旧 pending 消费掉。
- 回复末尾应自然提醒：“如果你觉得这个方向合适，点上面的采纳按钮就行。”

只读追问不是新一轮待确认更新。它只是帮用户理解上一张卡片采纳后的影响。

### 9.5 专业模式与院校专业组模式的方案边界

方案调整必须区分两种数据结构，不能把专业和专业组混用：

| 模式 | 主要结构 | 用户侧对象 | 调整口径 |
| --- | --- | --- | --- |
| 专业+大学模式 | `orderedPlanState.items` | 一条“学校 + 专业”志愿 | 移动、删除、加入、替换按单条志愿处理 |
| 院校专业组模式 | `orderedPlanState.units` + `unit.majorItems` | 一个“学校 + 专业组”及组内专业 | 用户说“专业组/这一组/整组”时按专业组整体处理 |

要求：

- 专业+大学模式下，同一学校的多个专业也是多条独立志愿，不能合并成专业组结构。
- 院校专业组模式下，专业组整体移动/删除不能打散组内专业。
- 专业组内专业展示顺序继续沿用 3.0.2 的口径：组内专业按专业录取率从低到高展示，页面和导出一致。
- 如果用户点名“某专业组里的某个专业”，系统不能直接把它当成单条专业+大学志愿处理；必须确认当前后端是否支持组内专业级操作。若不支持，应说明“当前只能调整整个专业组，不能单独移动组内某个专业”。
- Plan 确认卡片必须把对象写清楚：
  - 专业+大学：展示学校名、专业名、当前位置、目标位置。
  - 院校专业组：展示学校/专业组名、组内专业数量、当前位置、目标位置。
- apply 成功后：
  - 专业+大学模式刷新 ordered。
  - 院校专业组整体移动/删除刷新 ordered 和 review。
  - 任何实际方案调整后，审查状态进入待重新审查。

## 10. 前端改造

1. 新增 `pendingConfirmationCard` 组件。
2. 旧 Intent 卡片迁移到统一组件。
3. Plan preview 使用同一组件。
4. 卡片点击确认/取消时，携带 `pendingId` 调接口。
5. 页面刷新或 WebSocket 重连时，查询 active pending 并恢复卡片。
6. `planningWorkspaceAction` 保持工作区入口语义，不展示“确认/采纳”类按钮。
7. 对 `expired/replaced/cancelled/applied` 状态展示置灰不可点击。

视觉建议：

- 偏好：用户文案用“把这个想法记下来”，说明“后面推荐和分析会参考它”。
- 要求：用户文案用“按这个要求来筛”，说明“会重新看可选志愿，并提醒方案里有没有冲突”。
- 方案调整：用户文案用“确认这样调整方案吗”，说明“会改变当前方案顺序/内容”。
- 失效：用户文案用“这条确认已失效”，说明“请重新说一下要采纳或调整的内容”。

文案原则：

- 避免直接给用户展示 `pending`、`payload`、`constraint`、`rank`、`candidate filters`、`workspace refresh` 这类系统词。
- 可以说“可选志愿”“专家优选推荐”“当前方案”“采纳”“暂不采纳”“重新看看推荐”。
- 卡片主标题要短，详情放在影响说明里。
- 不要让用户误以为“生成卡片”就已经生效；必须明确“采纳后才会更新”。

## 11. 老版本对话兼容策略

### 11.1 旧数据类型

旧会话可能存在：

- 历史消息里的旧 Intent 卡片。
- 历史消息里的 Plan preview 文本。
- `planEditCache` 中未确认的意向缓存。
- `pending_plan_action` 可从历史工具返回中恢复。
- `pending_intent_change` 运行时标记。

### 11.2 兼容原则

1. 旧数据不能自动生效。
2. 历史对话内容继续展示，但历史未确认卡片默认不保留可点击能力。
3. 旧会话恢复只在进入会话或加载 active pending 时做一次轻量检查；不能把历史扫描重新变成每轮对话主路径。
4. 只有后端能可靠恢复 payload、来源消息和版本，并成功创建新的 `PendingConfirmation`，旧内容才可以以“新确认卡片”的形式恢复。
5. 不能可靠恢复的旧卡片一律标记为 `expired`。
6. 旧卡片点击不能绕过新确认接口。
7. 旧会话首次进入时应进行一次轻量兼容检查，避免用户看到可点击但实际不可执行的旧卡片。
8. 不为了兼容旧对话保留文本确认直执行、匿名 cache confirm 或 history 扫描主路径。

### 11.3 旧 Intent 卡片

可兼容条件：

- 旧卡片包含 `message_id`。
- 旧卡片包含 `items[].value`。
- 后端 `planEditCache` 中仍能读到同一轮或同一内容的 payload。
- 该 pending 未被后续更新覆盖。

处理：

- 服务端转换为新的 `PendingConfirmation(kind=intent_change)`。
- `intentMode` 从旧卡片 `intentMode` 或 `planEditCache.intent_mode` 读取。
- 前端展示新的 `pendingConfirmationCard`，确认时走新 `pendingId`。
- 原历史卡片本身不再作为可点击入口。

不可兼容条件：

- 旧卡片缺少 `items[].value`。
- `planEditCache` 为空或与卡片内容不一致。
- 已经有更新版本的 profile/plan 状态。
- 无法确认是否已被用户处理。

处理：

- 卡片标记为 `expired`。
- 展示文案：“这条待确认内容来自旧版本，当前无法确认执行，请重新说明偏好或要求。”

### 11.4 旧 Plan preview

可兼容条件：

- 能从历史工具返回中恢复完整 `plan_payload`。
- payload 包含 action family、stage preview/apply 所需参数。
- 当前 `planningState.version` 与 preview 生成时版本一致，或旧 payload 带有可校验版本。

处理：

- 服务端转换为新的 `PendingConfirmation(kind=plan_mutation)`。
- 生成新 Plan 确认卡片。
- 原历史 preview 本身不再作为可点击入口。

不可兼容条件：

- 只有自然语言预览，没有结构化 payload。
- 无法恢复 action family 或具体对象。
- 当前方案版本已经变化。
- 旧 preview 来自迁移前不稳定的历史消息。

处理：

- 标记为 `expired`。
- 提示用户重新发起调整，例如“请重新说一下要移动、删除或排序的内容，我会基于当前方案重新生成确认卡片。”

### 11.5 `planEditCache`

`planEditCache` 不能直接作为最终方案或最终意向自动合并。

处理策略：

- 新会话不再写匿名 `planEditCache` 作为主 pending。
- 旧会话如果 `planEditCache` 非空，尝试转换为 `PendingConfirmation(kind=intent_change)`。
- 如果无法确认来源或 payload 完整性，记录操作日志并提示有旧版本待确认内容，但卡片标记为 `expired`。

### 11.6 是否必须兼容旧对话

兼容分两类：

| 类型 | 是否兼容 | 处理 |
| --- | --- | --- |
| 已生效的历史消息 | 兼容展示 | 只作为聊天历史展示，不再参与 pending 判断 |
| 已应用的旧意向/profile | 兼容读取 | 继续作为当前用户画像和方案分析参考 |
| 未确认但 payload 完整的旧 Intent 卡片 | 有条件兼容 | 后端重新创建新 pending card；原旧卡片不可直接点击 |
| 未确认但 payload 完整且版本有效的旧 Plan preview | 有条件兼容 | 后端重新创建新 pending card；原旧 preview 不可直接点击 |
| 只有自然语言、无 payload 或版本不可信的旧卡片 | 不兼容执行 | 标记为已失效 |
| 旧文本确认入口 | 不兼容执行 | 提示点击卡片或重新生成 |

原则上，旧对话内容本身继续展示；旧 pending 是否还能执行，必须看能否转换成带 `pending_id`、payload 和版本校验的新 pending。不能转换的，不做模糊兼容，直接标记失效。

更简单的产品口径：

- 老消息可以看。
- 老卡片默认不能直接点。
- 如果系统能安全恢复，会在当前对话里生成一张新的确认卡片。
- 如果不能安全恢复，就显示已失效，让用户重新说一次要采纳或调整的内容。

## 12. 旧逻辑清理计划

| 旧逻辑 | 新处理 |
| --- | --- |
| `direct_pending_plan_confirm` | 删除直接执行；改为提示点击卡片/重发 active card |
| `direct_pending_intent_confirm` | 删除直接执行；改为提示点击卡片/重发 active card |
| `_is_plan_action_confirmation` | 只保留 no-pending guard，不参与 apply |
| `_is_pending_intent_confirmation` | 只保留 no-pending guard，不参与 apply |
| `_extract_pending_plan_action` history 扫描 | 迁移期 adapter；新会话不依赖 |
| `pending_plan_action` | 转成 `PendingConfirmation(kind=plan_mutation)` 后删除 |
| `pending_intent_change` | 转成 `PendingConfirmation(kind=intent_change)` 后删除 |
| 匿名 `planEditCache` | 旧会话 adapter；新会话不作为主 pending |
| 模型可调用 `update_volunteer_intent_state(confirm)` | 从主 Agent 工具集移除或限制为确认接口内部调用 |
| 模型可调用 `execute_plan_action(apply)` | 主 Agent 只能 preview；apply 由确认接口内部调用 |

## 13. 实施顺序

1. 新增 `PendingConfirmation` 持久化模型和确认接口，不切主链路。
2. 新增 `pendingConfirmationCard` 前端组件和状态展示。
3. Intent preview 接入新 pending；旧 Intent 卡片 adapter 保留。
4. Plan preview 接入新 pending；生成 Plan 确认卡片。
5. Intent confirm 接入异步专家优选推荐刷新，确认先返回，刷新完成后更新候选/专家优选区域。
6. 文本确认改为提示/重发卡片，不再执行更新。
7. 接入旧会话兼容检查，能迁移的转新 pending，不能迁移的标记失效。
8. 删除旧短确认直执行、匿名 cache confirm 和 history 扫描主路径。
9. 补齐 pending 行为事件：创建、确认、取消、替代、过期、推荐刷新开始/完成/失败。
10. 跑完新会话、旧会话、刷新重连、移动端和真实对话回归后，再清理 adapter。

## 13.1 已确认设计决策

| 编号 | 决策 | 落地约束 |
| --- | --- | --- |
| 1 | 意向确认后需要更新专家优选推荐 | 偏好/要求采纳后触发候选和专家优选刷新 |
| 2 | 专家优选推荐刷新异步完成 | 确认接口不长时间等待 rank；刷新完成后更新工作区 |
| 3 | 新 pending 替代旧 pending 时旧卡片置灰即可 | 沿用老版本已有置灰样式，不增加复杂交互 |
| 4 | 旧会话兼容只做轻量恢复 | 进入会话或加载 active pending 时检查一次，不能回到每轮 history 扫描主路径 |
| 5 | 专业组内专业调整边界必须明确 | 不支持组内专业级操作时，统一说明只能调整整个专业组 |
| 6 | 必须做版本校验 | Plan 用 `planningState.version`；Intent/rank 刷新用画像/推荐版本防止旧结果覆盖 |
| 7 | pending 行为需要记录事件 | 创建、确认、取消、替代、过期、推荐刷新结果都要可追溯 |
| 8 | 前端历史卡片状态要同步 | 被替代、失效、已确认、已取消的卡片刷新后仍保持置灰不可点击 |

## 14. 测试矩阵

| 类型 | Case | 预期 |
| --- | --- | --- |
| 软意向 | 想去北京 | 生成偏好卡片，未点击不生效 |
| 硬要求 | 只看北京 | 生成要求卡片，确认后收紧候选 |
| 负向要求 | 护理不要 | 生成要求卡片，确认后作为排除条件 |
| 软硬混合 | 北京优先但上海不要 | 同一卡片披露偏好和要求 |
| 只读追问 | 这个偏好会影响方案吗 | 分析影响，不消费 pending |
| 只读追问 | 采纳后专家优选会变吗 | 说明会重新看推荐，但不实际刷新 |
| 文本确认 | 用户只说“确认” | 不执行，提示点击卡片 |
| Plan 排序 | 按录取率排序 | 生成方案调整卡片 |
| Plan 移动 | 把第 3 个专业组移到第 5 位 | 生成方案调整卡片 |
| Plan 删除 | 删除某学校某专业 | 生成方案调整卡片，无法唯一定位则澄清 |
| 专业模式调整 | 把某大学某专业移到第 3 位 | 按单条志愿处理，不按学校合并 |
| 专业组模式调整 | 把第 3 个专业组移到第 5 位 | 按专业组整体处理，不打散组内专业 |
| 专业组内专业点名 | 去掉某专业组里的某个专业 | 不误当单条志愿；不支持时明确说明边界 |
| 卡片确认 | 点击确认 | 按 pendingId 执行 |
| 卡片取消 | 点击暂不采纳 | pending 变 cancelled |
| 重复点击 | 已确认卡片再点 | 不重复执行 |
| 过期点击 | expired 卡片点击 | 不执行，提示重新生成 |
| 旧 Intent 卡片 | payload 完整 | 转新 pending card |
| 旧 Intent 卡片 | payload 缺失 | 标记 expired |
| 旧 Plan preview | payload + version 有效 | 转新 pending card |
| 旧 Plan preview | 只有文本 | 标记 expired |
| 前端刷新 | active pending 存在 | 恢复卡片 |
| 工作区联动 | apply 成功后 | 发送 `planningWorkspaceAction` 刷新 |
| 意向确认刷新 | 采纳地域/专业偏好 | 更新专家优选推荐，不自动覆盖当前排序方案 |
| 要求确认刷新 | 采纳排除护理/只看北京 | 更新可选志愿和专家优选推荐，并提示当前方案冲突 |
| 异步刷新失败 | 采纳偏好后 rank 失败 | 偏好保持已采纳，提示推荐刷新失败，可重试 |
| 新 pending 替代 | 旧卡片未处理又生成新卡片 | 旧卡片置灰，新卡片 active |
| 版本校验 | 旧 plan pending 确认时方案已变化 | 不执行旧调整，旧卡片失效 |
| 事件记录 | 创建/确认/取消/替代/过期 | 新表能查到对应 pending 行为事件 |
| 前端刷新 | 旧卡片已 replaced/expired | 刷新后仍置灰，不恢复可点击 |

## 15. 验收标准

- 任意更新动作在用户点击确认卡片前不会改变意向、要求、候选筛选、方案顺序、方案内容或审查状态。
- 任意文本“确认/好的/可以/就这样”不会触发更新。
- 卡片披露内容、后端 payload 和实际执行结果一致。
- 每个 active pending 都有唯一 `pending_id`，可追踪创建、确认、取消、过期和执行日志。
- 旧会话中不可可靠执行的旧卡片会明确置灰并标记失效。
- 新会话不再依赖 `planEditCache`、`pending_plan_action`、`pending_intent_change` 或 history 扫描作为状态主源。
- `planningWorkspaceAction` 不再承载确认语义，只用于确认执行成功后的工作区打开/刷新。
- 意向/要求采纳后，专家优选推荐会异步刷新；刷新失败不会回滚已采纳内容。
- 所有 pending 状态变化和推荐刷新结果都有行为事件记录。

## 16. 2026-06-02 第一阶段落地记录

本阶段先关闭最高风险的“文本确认直执行”旁路，保持现有旧 Intent 卡片点击采纳链路可用。

已完成：

- `service.py` 中有 active plan pending 时，用户只发“确认/执行/就按这个来”等文本，不再调用 `execute_plan_action(apply)`，只提示点击卡片确认。
- `service.py` 中有 active intent pending 时，用户只发“确认”等文本，不再调用 `update_volunteer_intent_state(confirm)`，只提示点击卡片采纳。
- 删除服务层已无引用的 direct pending 执行辅助函数，避免后续误用。
- `pending_context.py` 不再指导模型在用户文本确认时直接调用 apply payload，改为提示点击确认卡片。
- Intent 预览和边界文案从“回复确认”改为“点击卡片采纳”。
- 单测覆盖文本确认不执行工具、不调用模型、只返回卡片确认提示。

仍未完成：

- 新 `pending_id` 持久化模型和确认接口。
- 新 `pendingConfirmationCard` 前端统一组件。
- Plan 方案调整确认卡片。
- 新 pending 替代旧 pending 后旧卡片自动置灰的持久状态。
- Intent 采纳后的异步专家优选/rank 刷新。
- pending 行为事件表和刷新事件记录。
- 旧会话 pending 轻量恢复和不可恢复卡片失效标记。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/agent/instructions/pending_context.py app/tools/intent_response_tool.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -k "card_click or pending_regenerate_order or intent_text_confirmation or plan_next_action_pending_text_confirmation or normalize_pending_intent_reply or pending_intent_boundary" -q
```

## 17. 2026-06-02 第二阶段落地记录

本阶段补齐 Plan 方案调整的显式确认卡片闭环，避免第一阶段关闭文本确认后方案预览无法执行。

已完成：

- 新增 WebSocket 入站类型 `pendingConfirmation`。
- 新增服务端 `handle_pending_confirmation`：
  - 当前支持 `kind=plan_mutation` 的卡片确认。
  - 点击确认后，从近期方案预览历史恢复 apply payload，调用 `execute_plan_action(apply)`。
  - 执行成功后继续返回 `planningWorkspaceAction` 刷新排序方案。
  - 点击取消时不执行，只返回取消提示。
- Plan preview 本轮生成可执行 pending 时，额外返回并持久化 `pendingConfirmationCard`。
- 前端 `MessageList` 支持渲染 `pendingConfirmationCard`：
  - 确认执行按钮发送 `inputType=pendingConfirmation`。
  - 暂不执行按钮发送取消动作。
  - 点击后本地置灰，避免重复点击。
- `message_store`、WS schema、compat/v3 websocket followup 持久化均支持 `pendingConfirmationCard`。
- 单测覆盖：
  - Plan preview 会生成确认卡片。
  - 用户只发文本“确认”仍不会执行。
  - 点击确认卡片会执行 apply payload 并刷新工作区。

当前限制：

- 这一步是迁移桥接方案，执行 payload 仍从近期历史 preview 中恢复，不是最终 `pending_id` 持久化模型；第三阶段已替换为 extra-data 持久 pending。
- 卡片点击后的置灰状态前端先本地处理，刷新后的 replaced/expired/applied 持久状态仍待新 pending 表支撑。
- Intent 仍使用旧卡片采纳链路，尚未迁移到统一 `pendingConfirmationCard`。
- Intent 采纳后的异步专家优选/rank 刷新仍未接入。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/server.py app/schemas.py app/schemas/ws.py app/data/message_store.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
cd ../zhiyuan-web
./node_modules/.bin/tsc --noEmit --pretty false
```

说明：前端 `tsc --noEmit` 当前仍有历史类型错误，主要位于 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts`；本次新增的 `MessageList/index.tsx` 类型错误已清除。

## 18. 2026-06-02 第三阶段落地记录

本阶段把 Plan 方案调整确认从“历史消息反查 payload”升级为最小持久 pending 状态，确保旧卡片、重复点击和被新卡片替代的卡片不会误执行。

已完成：

- Agent 复用后端 `assistant_chat_session_extra_data` 读写能力，新增 extra-data key：`pendingConfirmation`。
- Plan preview 生成确认卡片时同步写入 active pending：
  - `pendingId`：本次确认唯一 ID。
  - `kind=plan_mutation`。
  - `status=active`。
  - `actionFamily`：方案调整动作类型。
  - `summary` / `userGoal`：用于卡片和追踪。
  - `executionPayload.toolName=execute_plan_action`。
  - `executionPayload.planPayload`：确认点击后执行的 apply payload。
  - `sourceBackendVersion`：从 preview payload 提取，用于后续版本校验扩展。
- `pendingConfirmationCard` 现在携带 `pendingId`。
- 点击确认/取消时，服务端先读取 `pendingConfirmation`：
  - 没有 `pendingId`：不执行，提示重新生成预览。
  - 当前 active pending 不存在：不执行，提示卡片已失效。
  - `pendingId` 不一致：不执行，提示按最新卡片操作。
  - `kind` 不一致：不执行，提示卡片与当前操作不一致。
  - 取消：状态写为 `cancelled`，不执行。
  - 确认：只执行当前 active pending 的 `executionPayload.planPayload`，执行后状态写为 `applied`。
- new pending replaces old 的当前实现：
  - 每个会话只保留一个 active `pendingConfirmation`。
  - 新 preview 生成新 pending 时覆盖旧 active pending，并在新状态记录 `replacesPendingId`。
  - 旧卡片本身仍可能在历史消息里可见，但点击时 `pendingId` 与 active 不一致，因此不会执行。
- 单测覆盖：
  - Plan preview 卡片携带 `pendingId`，且 pending 状态持久化为 `active`。
  - 文本“确认”仍不会执行方案调整。
  - 点击当前 active 卡片才执行方案 apply，并把 pending 状态写为 `applied`。
  - 点击被替代的旧卡片不会执行。

当前限制：

- 仍未新增独立 pending/event 表；当前使用 extra-data 单 key 覆盖 active pending，足够支撑单 active 卡片协议，但不能完整追踪所有历史 pending 事件。
- 前端刷新后对历史旧卡片的“置灰展示”还依赖消息内容和点击返回提示；后续可以通过 messageId/pendingId 批量查状态后渲染为 expired/replaced。
- Intent 变更仍在旧 `planEditCache` + `intentSelect` 链路，尚未迁移到统一 `pendingConfirmation`。
- 意向/要求确认后的专家优选 rank 异步刷新仍未接入。
- 方案版本冲突当前只记录 `sourceBackendVersion`，确认时尚未强制比较最新 workspace version。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/util/internal_client.py app/server.py app/schemas.py app/schemas/ws.py app/data/message_store.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
```

验证结果：

- `py_compile` 通过。
- `test_chat_service_history_persistence.py`：`130 passed`。

## 19. 2026-06-02 第四阶段落地记录

本阶段把 Intent 旧卡片的“点击即采纳”改为统一确认协议，避免意向/要求和方案调整在交互上出现两套生效规则。

已完成：

- 旧 `intentSelect` 卡片点击后不再直接调用 `_apply_selected_intents` 写入偏好/要求。
- `handle_intent_select` 现在只负责把用户勾选内容转换成 active `pendingConfirmation`：
  - `kind=intent_change`。
  - `actionFamily=apply_selected_intents`。
  - `executionPayload.selectedData`：原旧卡片提交内容。
  - `executionPayload.merged`：勾选项合并后的意向结构。
  - `executionPayload.intentMode`：从旧卡片 `intentMode` 读取，保留软意向 `preference` / 硬要求 `constraint` 区分。
  - `executionPayload.batch`：从成绩信息读取，读不到时按 `01` 兜底。
- 旧 Intent 卡片点击后返回新的 `pendingConfirmationCard`：
  - 偏好卡片标题为“确认采纳这次偏好”。
  - 要求卡片标题为“确认采纳这次要求”。
  - 主按钮为“采纳”，取消按钮为“暂不采纳”。
  - 文案明确：点击采纳前不会写入后续报考参考。
- `handle_pending_confirmation` 现在支持 `kind=intent_change`：
  - 先按 `pendingId/status/kind` 校验。
  - 确认后再调用原 `_apply_selected_intents`。
  - 应用成功后把 pending 状态写为 `applied`。
  - 硬要求采纳后继续返回工作区引导：
    - 如果产生候选筛选，返回候选区刷新卡片。
    - 同时返回“请查看方案”卡片，引导用户回到方案区查看审查/调整状态。
    - 这一步只提示和刷新工作区，不自动重排当前方案，也不自动执行审查。
  - 取消时写为 `cancelled`，不写入偏好/要求。
- 前端统一确认卡片支持 intent 文案：
  - `kind=intent_change` 确认后显示“已采纳”。
  - 取消后显示“未采纳”。

当前限制：

- 旧 Intent 卡片本身还会先变成本地已点击状态；刷新后以后端消息状态为准。后续如果要更强一致，需要在前端按 pending 状态恢复旧卡片 disabled/expired。
- 意向/要求采纳后的专家优选/rank 刷新已在第五阶段接入 best-effort overlay refresh；显式后端刷新 API 仍待补。
- 旧 `planEditCache` 仍作为 intent preview 缓存存在；它不再是用户点击后直接生效的入口，但 preview 生成链路尚未完全迁移到 `pendingConfirmation`。
- 约束类 intent 采纳后已提示用户查看方案；是否自动触发审查或自动修复仍保持后续独立设计，不在本阶段隐式执行。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/util/internal_client.py app/server.py app/schemas.py app/schemas/ws.py app/data/message_store.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
```

验证结果：

- `py_compile` 通过。
- `test_chat_service_history_persistence.py`：`130 passed`。

## 20. 2026-06-02 第五阶段落地记录

本阶段补上 Intent 采纳后的推荐刷新第一阶段能力，并修复两个意向识别/文案回归点。

已完成：

- Intent 采纳成功后，`intent_state_tool` 会 best-effort 触发一次候选查询：
  - 后端 `candidate-pool/query` 在 `recommendationOverlay` stale 或为空时会刷新推荐叠加层。
  - Agent 只触发刷新，不重排当前排序方案，不自动覆盖当前方案。
  - 刷新失败不回滚已采纳的偏好/要求，只记录日志并在结构化结果中标记失败。
  - `IntentStateUpdateResult` 新增 `recommendationRefresh` 元信息，记录 `triggered/success/mode`。
- 软偏好采纳：
  - 写入用户偏好后触发推荐叠加层刷新。
  - 不刷新候选筛选条件，不改变当前方案。
- 硬要求采纳：
  - 继续返回候选筛选 `candidateFilters`，用于前端打开候选区。
  - 同时触发推荐叠加层刷新，后续候选推荐分和优选解释可按新要求更新。
- 专业简称/宽泛表达补充：
  - 常用专业简称表新增 `土木建筑 -> 土木类/建筑类 + 土木工程/建筑学`。
  - 修复“土木建筑那种别碰”被过度收缩成只排除 `土木工程` 的问题。
- Interest 阶段文案修复：
  - 保留“先按这个方向看影响和边界”这一用户侧提示。
  - 同时展示具体方向，例如避开/关注哪些专业。

当前限制：

- 后端已在第六阶段补充显式 stale 标记接口；推荐刷新仍借用候选查询触发 overlay refresh，后续如需更强语义可再补独立 `refreshRecommendationOverlay` 接口。
- 如果后端 stale 标记成功但 rank/候选查询失败，已采纳偏好仍保留，推荐刷新会标记失败并等待后续重试。
- 当前方案仍只标记 stale/待复审，不会在采纳偏好后自动重排。后续若要让用户一键按新偏好重排，应继续走方案调整确认卡片。
- 约束采纳后“当前方案中不符合新要求的志愿”还没有自动给出审查/冲突提示。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/tools/intent_state_tool.py app/tools/intent_response_tool.py app/data/major_aliases.py app/service.py app/util/internal_client.py app/server.py app/schemas.py app/schemas/ws.py app/data/message_store.py
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py -q
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
```

验证结果：

- `py_compile` 通过。
- `test_intent_state_tool.py`：`124 passed`。
- `test_chat_service_history_persistence.py`：`130 passed`。

## 21. 2026-06-02 第六阶段落地记录

本阶段补齐后端显式 stale 标记接口，避免 Agent 只依赖候选查询隐式触发推荐刷新。

已完成：

- Backend 新增请求 DTO：`MarkPlanningIntentStaleReq`。
- Backend 新增内部接口：
  - `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/intent-change/stale?chatSessionId=...`
  - 请求体：`{"intentMode": "preference|constraint"}`
  - 返回：`PlanningStateVersionDTO`
- Backend `PlanningStateService.markIntentChangeStale(...)` 复用已有 stale 语义：
  - `preference` 走 `touchAndSavePreference`：
    - `recommendationOverlay=true`
    - `initialRecommendation=true`
    - `orderedPlan=true`
    - `planAdjustment=true`
    - `review=true`
    - 不标记 `candidatePool`
  - `constraint` 走 `touchAndSaveConstraint`：
    - `candidatePool=true`
    - `recommendationOverlay=true`
    - `initialRecommendation=true`
    - `orderedPlan=true`
    - `planAdjustment=true`
    - `review=true`
- Agent 新增 `mark_planning_intent_change_stale(...)` internal client。
- Intent 采纳成功后流程调整为：
  1. 写入用户偏好/要求。
  2. 清理旧 `planEditCache`。
  3. 显式调用后端 stale 标记接口。
  4. best-effort 查询候选池，触发推荐 overlay refresh。
  5. 返回用户侧确认结果；不自动重排当前方案。
- `recommendationRefresh` 结构增加 `staleMarked` 字段，便于排查 stale 标记和 overlay 刷新哪个环节失败。

验证命令：

```bash
cd zhiyuan-server
mvn -q -DskipTests compile

cd ../zhiyuan-agent
.venv/bin/python -m py_compile app/tools/intent_state_tool.py app/tools/intent_response_tool.py app/data/major_aliases.py app/service.py app/util/internal_client.py app/server.py app/schemas.py app/schemas/ws.py app/data/message_store.py
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py -q
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
```

验证结果：

- Backend compile 通过。
- Agent `py_compile` 通过。
- `test_intent_state_tool.py`：`124 passed`。
- `test_chat_service_history_persistence.py`：`130 passed`。

## 22. 2026-06-02 第七阶段落地记录

本阶段补齐“硬要求采纳后当前方案可能过期”的用户侧引导，并明确后端 stale 维护方式。

### 22.1 stale 维护方式

后端不单独维护一张 stale 状态表，stale 直接挂在 `PlanningStateDTO.staleFlags` 上，并通过 `version` 推进表达“规划状态已经发生变化”。

当前入口：

- Agent 在用户点击确认卡片采纳意向后，调用：
  - `mark_planning_intent_change_stale(thread_id, intent_mode)`
- 后端内部接口：
  - `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/intent-change/stale?chatSessionId=...`
  - body：`{"intentMode":"preference|constraint"}`
- 后端服务：
  - `PlanningStateService.markIntentChangeStale(...)`

软偏好 `preference`：

- `version + 1`
- `phase = profile_ready`
- `recommendationOverlay = true`
- `initialRecommendation = true`
- `orderedPlan = true`
- `planAdjustment = true`
- `review = true`
- 不标记 `candidatePool`

硬要求 `constraint`：

- `version + 1`
- `phase = profile_ready`
- `candidatePool = true`
- `recommendationOverlay = true`
- `initialRecommendation = true`
- `orderedPlan = true`
- `planAdjustment = true`
- `review = true`

含义：

- 偏好变化会影响推荐解释、推荐叠加层、方案与审查有效性，但不必重建全量候选池。
- 硬要求变化可能改变候选可选范围，因此同时标记候选池过期。
- 两者都不自动覆盖当前方案；当前方案只是进入需要复看/复审的状态。

### 22.2 硬要求采纳后的工作区引导

已完成：

- `handle_pending_confirmation(kind=intent_change)` 在硬要求采纳成功后返回工作区引导：
  - 如果有 `candidateFilters`，返回候选区刷新卡片。
  - 同时返回“请查看方案”卡片，打开方案区。
- “请查看方案”卡片文案：
  - 标题：`请查看方案`
  - 内容：`这次要求已采纳，当前方案可能需要重新审查或调整。`
  - 按钮：`查看方案`
- 该卡片只负责打开/刷新工作区，不自动执行审查，不自动重排，不自动补偿。

边界：

- 软偏好采纳不强制追加“查看方案”卡片，避免偏好类调整过度打扰用户。
- 硬要求采纳后的审查与调整仍应走方案审查、方案调整、补偿预览等既有链路；如涉及真正改动方案，仍必须生成确认卡片并由用户点击。

### 22.3 旧确认卡置灰

已完成：

- 后端 active pending 仍采用单会话唯一状态：
  - 新 pending 生成时覆盖当前 active pending。
  - 老卡片点击时，因为 `pendingId` 与当前 active pending 不一致，会返回“这张确认卡片已经失效”。
- 前端消息渲染补充派生状态：
  - 同一会话历史消息中，只保留最后一张 active `pendingConfirmationCard` 可操作。
  - 更早的 active pending 卡片在 UI 上展示为“已被新的确认卡替代”，按钮置灰。
  - 已确认、已取消、已失效的卡片状态继续按消息自身 `status/clicked` 展示。

设计边界：

- 旧卡置灰是前端展示层派生，不改写历史消息内容。
- 后端 `pendingId` 校验仍是最终安全边界；即使前端状态异常，旧卡也不能执行。
- 不引入多 pending 队列，符合本阶段“新 pending 替代旧 pending”的简单协议。

### 22.4 高层 Intent Preview 统一接入 PendingConfirmation

复测发现：

- `preview_current_major_intent_confirmation`
- `preview_current_school_intent_confirmation`
- `preview_current_region_intent_confirmation`
- `preview_current_career_intent_confirmation`

这些高层 Intent 工具会返回结构化 `IntentAnalysisPayload`，但 direct tool reply 展示给用户的是其中的 `message` 文本。此前服务层只对旧 Intent 卡片点击迁移和方案预览生成 `pendingConfirmationCard`，导致高层 preview 仍只写旧 `planEditCache`，没有落 `pendingConfirmation`。

本次修复：

- 服务层不从用户可见文案里反解析意向内容。
- 服务层从当前轮 `ToolReturnPart.content` 读取结构化 `IntentAnalysisPayload`。
- 当 `analysisStage=confirmed` 且 `items.value` 存在时：
  - 合并 `items.value` 为待采纳偏好/要求。
  - 从当前会话分数信息读取 `batch`，避免跨批次确认时固定成本科批。
  - 写入统一 `pendingConfirmation`。
  - 向前端追加 `pendingConfirmationCard`。
- `analyze_volunteer_intent_change()` 默认不再写匿名 `planEditCache`。
- 新 `pendingConfirmation` 保存后会 best-effort 清空旧 `planEditCache`，避免历史残留污染后续追问。
- 文本“确认/可以/好的”仍只提示用户点击卡片，不执行更新。
- 点击卡片后才调用 `apply_selected_intents`，执行成功后把 pending 状态更新为 `applied`。

验证结果：

- session `990405` 输入“把北京的学校优先考虑”：
  - 返回 `pendingConfirmationCard`。
  - 后端 `pendingConfirmation.status=active`。
  - 文本“确认”只返回“请点击上方卡片里的采纳按钮”，未执行更新。
  - 模拟前端点击卡片后，返回“已确认，这个偏好会作为后续报考参考”。
  - 后端 `pendingConfirmation.status=applied`，`resultCode=preference_applied`。
- session `990407` 输入“把北京的学校优先考虑”：
  - 返回 `pendingConfirmationCard`。
  - 后端 `pendingConfirmation.status=active`。
  - 后端 `planEditCache={}`，确认新 preview 不再写旧匿名 cache。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q -k 'structured_intent_preview or pending_confirmation or pending_from_confirmation_card or rejects_replaced'
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py -q

.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --session 990405 \
  --prompts "把北京的学校优先考虑" "确认" \
  --response-timeout 120 \
  --keep-response-text \
  --metrics-output /private/tmp/zhiyuan_303_pending_card_after_payload_fix.json

.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --session 990407 \
  --prompts "把北京的学校优先考虑" \
  --response-timeout 120 \
  --keep-response-text \
  --metrics-output /private/tmp/zhiyuan_303_plan_edit_cache_cleared.json

cd ../zhiyuan-web
npx tsc --noEmit
```

验证结果：

- `py_compile` 通过。
- `test_chat_service_history_persistence.py`：`132 passed`。
- `test_intent_state_tool.py`：`124 passed`。
- 新增 focused pending 测试：`5 passed, 127 deselected`。
- 真实 websocket 回归：
  - `pendingConfirmationCard` 已返回。
  - `pendingConfirmation` 已落库。
  - 新 preview 后 `planEditCache={}`。
  - 文本确认不会执行。
  - 卡片确认会执行并置为 `applied`。
- `npx tsc --noEmit` 未通过，失败点为项目既有类型错误，未指向本次修改的 `MessageList/index.tsx`。
