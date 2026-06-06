# Release 3.0.3 Agent 意图、意向与方案更新链路交互和实现机制设计

## 1. 文档定位

本文是 3.0.3 阶段关于 Agent 意图识别、意向/要求更新、方案调整和确认执行协议的汇总设计文档。

发布收口说明：本文是 3.0.3 当前确认协议的权威设计；发布范围、最终回归和 3.0.2 -> 3.0.3 升级准备见 `docs/release-3.0.3-summary-and-upgrade-plan.md`。

它整合以下几部分内容：

- 3.0.2 已有的 `preview -> pending -> confirm -> apply` 基础链路。
- 3.0.3 前期“所有更新必须通过确认卡片”的设计。
- 人工走查中发现的文本确认、旧卡片、模型自由回复、软硬意向混淆和方案调整状态错位问题。
- 最新确认的产品口径：卡片是主确认入口；短文本确认只作为已有 active pending 的兜底入口，不能凭模型自然语言或历史文本直接执行。

旧的阶段记录仍保留在 `release-3.0.3-agent-intent-plan-update-interaction-design.md`，但后续实现和验收以本文为准。

## 2. 要解决的问题

### 2.1 多套确认入口并存

当前和历史版本中存在多条状态更新路径：

- Intent 旧卡片：`intentSelect`、`planEditSelect`。
- 统一确认卡片：`pendingConfirmationCard`。
- 旧缓存：`planEditCache`。
- 旧运行时字段：`pending_plan_action`、`pending_intent_change`。
- 新运行时状态：`conversation_phase.pending`。
- 后端 extra-data：`pendingConfirmation`。
- 自然语言短确认：用户回复“确认 / 可以 / 好的 / 就这样”。
- 模型自由回复：模型可能说“确认后执行”“回复确认即可调整”。

如果这些路径不统一，会出现：

- 用户以为点卡片才生效，但系统可能因为一句“确认”直接执行。
- 用户说“确认”时，系统不知道是在确认哪一轮预览。
- 模型口头说可以确认，但实际没有可执行 pending。
- 旧卡片刷新后仍可点击，点击后执行了和当前状态不一致的动作。
- 偏好、硬要求和方案调整的生效边界不一致。

### 2.2 文本过死或过松都会有问题

完全禁止文本确认的问题：

- 用户已经看到确认卡片后，只回复“确认/可以”，系统却不执行，交互显得过死。
- 模型偶发用自然语言承接确认时，用户回复确认无法继续，体验割裂。

放开自然语言确认的问题：

- 自然语言容易指代不清。
- 用户可能是在确认一段分析，不是在确认方案变更。
- 模型回复里的“确认后执行”可能和后端 pending 内容不一致。
- 只靠字符串匹配用户输入或模型输出，维护成本高且容易误判。

因此新口径不是“靠文本识别执行”，而是“短文本只能消费当前 active 的结构化 pending”。

## 3. 产品原则

1. 所有会改变长期偏好、硬性要求、推荐排序参考、方案内容、方案顺序或审查状态的动作，都必须先形成结构化 preview/pending。
2. `pendingConfirmationCard` 是主确认入口，用户点击卡片是最清晰、最推荐的确认方式。
3. 短文本确认只作为兜底入口：只有当前会话存在 active pending，且用户本轮只表达确认，没有新增范围、条件或对象时，才允许消费该 pending。
4. 没有 active pending 时，任何“确认/可以/执行吧”都不能执行更新。
5. 模型自然语言里的“确认后执行/回复确认即可”不能作为执行依据；执行只认服务端保存的 pending payload。
6. 如果模型自然语言承诺和 pending 卡片内容可能不一致，应阻断文本确认，要求用户点击最新卡片或重新生成卡片。
7. 新 pending 出现时，直接替代旧 active pending；旧卡片置灰，点击不执行。
8. 旧会话内容可以展示；旧卡片只有能恢复成新 pending 时才能继续确认，不能恢复的标记失效。
9. 软意向和硬要求必须分开处理：偏好影响推荐和解释，要求影响后续候选查看的可见筛选参考、排除边界和方案检查；采纳要求本身不直接改小基础候选池。
10. 方案调整必须区分“专业+大学”和“院校专业组”两种结构，不能在移动、删除、导出或确认文案里混用。

## 4. 总体状态模型

```text
用户表达意图
  -> Agent / Tool 判断是否有副作用
  -> 只读问题
       -> 查询、分析、解释
       -> 不创建 pending
  -> 状态更新候选
       -> 生成 preview facts
       -> 创建 PendingConfirmation(active)
       -> 返回 pendingConfirmationCard
       -> 用户点击卡片确认
            -> apply_pending_confirmation(pendingId, entry=card)
       -> 用户短文本确认
            -> try_apply_active_pending_from_short_text(entry=short_text)
       -> 用户取消
            -> PendingConfirmation(cancelled)
       -> 新 pending 产生
            -> old PendingConfirmation(replaced)
       -> 版本漂移 / 过期
            -> PendingConfirmation(expired)
```

主路径：

```text
preview/tool result
  -> PendingConfirmation(active)
  -> pendingConfirmationCard
  -> card confirm OR short-text confirm fallback
  -> shared apply_pending_confirmation
  -> applied/cancelled/expired/replaced
```

核心约束：

- `apply` 只能读取后端 pending 中的 `executionPayload`。
- 模型不能直接构造 apply payload 并绕过 pending。
- 卡片确认和短文本确认必须进入同一个服务端 apply 方法。

## 5. PendingConfirmation 数据模型

建议模型：

```json
{
  "pendingId": "uuid",
  "sessionId": "129",
  "kind": "intent_change | plan_mutation",
  "actionFamily": "set_preference | set_constraint | remove_units | move_ordered_unit | sort_ordered_plan | ...",
  "status": "active | applied | cancelled | replaced | expired",
  "intentMode": "preference | constraint",
  "summary": "用户可见摘要",
  "disclosure": {
    "title": "确认采纳这次偏好",
    "content": "不优先专业：秘书学",
    "items": [],
    "impact": [],
    "confirmText": "采纳",
    "cancelText": "暂不采纳"
  },
  "executionPayload": {
    "toolName": "execute_plan_action | apply_selected_intents",
    "payload": {}
  },
  "sourceMessageId": "message-id",
  "sourceBackendVersion": 12,
  "createdAt": "2026-06-05T12:00:00+08:00",
  "updatedAt": "2026-06-05T12:00:00+08:00",
  "expiresAt": "2026-06-05T12:30:00+08:00",
  "replacesPendingId": "old-uuid"
}
```

字段说明：

- `kind`：区分意向/要求更新和方案变更。
- `actionFamily`：表达实际动作族，便于审计和前端文案。
- `intentMode`：只有 `intent_change` 需要；`preference` 表示偏好，`constraint` 表示硬要求。
- `executionPayload`：唯一可执行来源。
- `sourceBackendVersion`：方案变更需要校验版本，避免旧预览应用到新方案。
- `sourceMessageId`：用于确认后回写原卡片状态，避免刷新后旧卡片仍可点。

同一会话原则上只保留一个 active pending。新 pending 产生时，旧 pending 进入 `replaced`。

## 6. 确认入口规则

### 6.1 卡片确认

前端点击 `pendingConfirmationCard` 后发送：

```json
{
  "inputType": "pendingConfirmation",
  "pendingId": "uuid",
  "action": "confirm"
}
```

后端校验：

- `pendingId` 存在。
- `sessionId` 和当前会话一致。
- `status=active`。
- `kind/actionFamily` 与执行 payload 一致。
- 未过期。
- 方案类 pending 的 `sourceBackendVersion` 未漂移。

通过后进入统一执行：

```text
apply_pending_confirmation(pendingId, confirmedVia=card)
```

### 6.2 短文本确认兜底

短文本确认不是新的业务入口，只是 active pending 的备用确认方式。

允许条件：

- 当前会话存在且只存在一个 active pending。
- 用户本轮内容是短确认，不包含新的学校、专业、地域、职业、排序方式、位置、删除范围、筛选条件等新增信息。
- pending 未过期、未被替代、未取消、未应用。
- 方案类 pending 的版本仍有效。
- 当前最近的用户可见确认内容与 active pending 不存在已知冲突。

执行方式：

```text
try_apply_active_pending_from_short_text(userText)
  -> load active pending
  -> validate short confirmation only
  -> validate pending state and version
  -> apply_pending_confirmation(pendingId, confirmedVia=short_text)
```

禁止条件：

- 没有 active pending。
- 用户说“确认，但只排除江苏”这类带新范围的文本。
- 用户说“可以，不过别动第一个”这类带附加条件的文本。
- 最近模型回复中出现了和 pending 不一致的自然语言确认承诺。
- pending 已经被新卡片替代。

用户侧反馈：

- 允许执行：按卡片确认同样的结果回复。
- 无 active pending：提示“当前没有可确认的调整，请先让我整理成确认卡片。”
- 信息变更：提示“这次说法里带了新的条件，我会重新整理确认卡片。”
- 可能不一致：提示“为避免确认错内容，请点击最新卡片或重新生成确认卡片。”

### 6.3 自然语言模型回复不能直接执行

模型可能生成：

- “回复确认即可执行替换。”
- “确认后我会帮你删除。”
- “如果可以，我就按这个方案调整。”

这些文本本身不代表后端已有 pending，也不能成为执行依据。

处理规则：

- 如果已有 active pending，用户短文本确认可以尝试消费 pending，但执行内容以 pending payload 为准，不以模型文本为准。
- 如果没有 active pending，必须阻断，并要求重新生成确认卡片。
- 如果模型文本和 pending 摘要可能冲突，应阻断短文本确认，要求用户点击卡片。

## 7. 意向与要求更新链路

### 7.1 软意向 preference

定义：非排他偏好，用于后续推荐、排序解释、专家优选和方案分析参考。

示例：

- “想去北京。”
- “不太想去江苏。”
- “法学和财政学可以优先看看。”
- “孩子更倾向体制内稳定一点。”

确认后行为：

- 写入后续报考参考。
- 影响推荐系数、专家优选推荐和解释。
- 不直接删除当前方案中的志愿。
- 不自动覆盖用户已调整过的排序方案。
- 当前方案如果有不一致项，可以提示用户查看，但不自动移除。

卡片文案应使用用户语言：

- “不优先地域：江苏”
- “偏好专业：法学、财政学”
- “采纳后会影响后续推荐和分析，不会直接删除当前方案。”

### 7.2 硬要求 constraint

定义：排他性或强限制条件，会影响后续候选查看的筛选参考、方案检查和后续调整边界。

示例：

- “只看北京。”
- “不去天津。”
- “护理不要。”
- “只学金融。”

确认后行为：

- 写入硬性要求，并同步到旧用户画像和 planning 显式画像。
- 用于后续候选查看、推荐排序、方案检查和调整边界；基础候选池不在这一步直接改小。
- 触发推荐/候选复看相关 stale 标记，但采纳响应不返回过滤后候选数量。
- 如果当前方案存在冲突项，提示用户查看方案或生成方案调整预览。
- 不在意向确认这一步直接删除方案；真正删除或替换仍需要方案调整确认卡片。

卡片文案：

- “排除省份：天津”
- “只看专业：金融学类/金融学”
- “采纳后会写入硬性要求，用于后续推荐、方案检查和调整边界；不会改小候选池，也不会直接删除当前方案。”

### 7.3 软硬判断原则

不能只靠某个虚词或关键词判断。判断应结合语义强度、上下文和用户表达目标：

- “想去 / 倾向 / 可以优先 / 不太想 / 有点排斥”通常是偏好。
- “只看 / 必须 / 不去 / 不要 / 排除 / 就要”通常是要求。
- 表达含混时应在卡片里披露理解方式，例如“我先理解为偏好，不会直接排除；如果你是硬性不要，可以继续说明。”

如果模型或工具不能稳定判断，优先生成待确认卡片并明确影响范围，而不是静默写入。

### 7.4 意向确认后的推荐更新

用户采纳意向/要求后：

1. 写入画像或要求状态。
2. 清理或替换旧的待确认缓存。
3. 标记后端规划状态 stale。
4. 触发专家优选推荐或 recommendation overlay 刷新。
5. 返回方案查看引导；候选面板不自动套用隐藏筛选条件。

偏好：

- 标记 `recommendationOverlay`、`initialRecommendation`、`orderedPlan`、`planAdjustment`、`review` stale。
- 不强制重建基础候选池。

要求：

- 标记 `candidatePool`、`recommendationOverlay`、`initialRecommendation`、`orderedPlan`、`planAdjustment`、`review` stale。
- 这里的 `candidatePool` stale 表示“这条硬要求可能影响后续候选推荐/检查，需要复看或后续显式重建”，不表示本次采纳立即过滤基础候选池。
- 候选推荐叠加层和当前方案都需要重新检查；当前候选列表不自动变成过滤后的列表。

刷新失败时：

- 已采纳的意向不回滚。
- 反馈“已采纳，但推荐刷新暂时失败，可稍后重试。”
- 记录事件，便于追踪。

## 8. 方案更新链路

### 8.1 必须走确认卡片的动作

以下动作都属于高副作用：

- 生成或重新生成方案。
- 从候选加入方案。
- 删除方案中的志愿。
- 替换方案中的志愿。
- 移动方案中的志愿。
- 专业组整体移动或删除。
- 按录取率、院校层次、推荐系数排序。
- 补稳、补保、补偿方案。
- 应用审查后的自动修复建议。

统一链路：

```text
用户提出方案调整
  -> plan_next_action / execute_plan_action(preview)
  -> 生成预览事实
  -> 创建 PendingConfirmation(kind=plan_mutation)
  -> 返回 pendingConfirmationCard
  -> 用户确认
  -> apply_pending_confirmation
  -> execute_plan_action(apply)
  -> 标记方案待重新审查
  -> 工作区刷新
```

### 8.2 专业+大学模式

结构特点：

- 每条志愿是“学校 + 专业”的独立单元。
- 同一学校的多个专业不能合并成专业组结构。
- 移动、删除、加入、导出都应按单条志愿处理。

确认卡片必须披露：

- 学校名。
- 专业名。
- 当前位置和目标位置。
- 删除或替换的数量。

### 8.3 院校专业组模式

结构特点：

- 主单元是“学校 + 专业组”。
- 组内包含多个专业。
- 用户说“这个组/专业组/整组”时按专业组整体处理。

确认卡片必须披露：

- 学校名和专业组名。
- 组内专业数量。
- 当前专业组位置和目标位置。
- 是否会连同组内专业一起移动或删除。

边界：

- 如果用户点名组内某个专业，而当前后端不支持组内专业级调整，应明确说明“当前只能调整整个专业组，不能单独移动组内某个专业。”
- 不能把专业组内专业误当成专业+大学模式的独立志愿。

### 8.4 方案版本校验

方案 pending 创建时保存 `sourceBackendVersion`。

确认时如果发现当前方案版本已变化：

- 不执行旧 pending。
- 标记为 `expired`。
- 原卡片置灰。
- 提示用户基于当前方案重新生成调整预览。

这能避免用户在多次移动、删除、排序后点击旧卡片造成错位。

## 9. 只读链路

只读链路不创建 pending，也不消费 pending。

典型场景：

- “这个专业怎么样？”
- “法学和财政学怎么选？”
- “这个方案有什么风险？”
- “广西贵州内蒙这些地方要不要放？”
- “如果我不太想去江苏，会影响当前方案吗？”
- “强基计划怎么报名？”

只读链路可以：

- 查询候选或方案。
- 分析当前方案命中项。
- 解释政策、专业、职业、学校或地域。
- 说明如果采纳某类偏好/要求，可能产生什么影响。

只读链路不能：

- 写入偏好或要求。
- 删除、移动、排序或替换方案。
- 把“可以整理成确认卡片”说成“已经记下来”。
- 生成没有 payload 的伪确认。

如果只读分析后用户明确要沉淀为偏好/要求或调整方案，应进入 preview/pending/card。

## 10. 前端交互

### 10.1 统一确认卡片

统一使用 `pendingConfirmationCard`。

状态：

- `active`：显示按钮，可确认/取消。
- `applied`：置灰，显示已采纳/已调整。
- `cancelled`：置灰，显示已取消。
- `replaced`：置灰，显示已被新的确认内容替代。
- `expired`：置灰，显示已失效，请重新生成。

### 10.2 卡片直出

当本轮已经生成确认卡片时，主文本可以为空，由卡片直接承接。

适用：

- 意向/要求待确认。
- 方案调整待确认。
- 旧卡片转换成新确认卡片。

不适用：

- 只读分析。
- 方案审查结果。
- 候选查询结果。
- 执行成功/失败反馈。
- 澄清问题。

要求：

- 去掉重复主文本，但不能减少卡片信息量。
- 卡片必须包含本次确认后会生效的内容和影响。
- 方案调整卡片必须说明调整对象、范围和位置。

### 10.3 用户话术

避免系统词：

- 不直接说 `pending`、`payload`、`constraint`、`rank`、`stale`。
- 可以说“待确认内容”“采纳后”“当前方案”“可选志愿”“专家优选推荐”“请查看方案”。

偏好：

- “采纳后，我会在后续推荐和分析里优先参考。”

要求：

- “采纳后，会作为后续筛选和方案检查依据。”

方案：

- “确认后会调整当前方案，调整后建议重新审查。”

## 11. 新旧链路兼容与清理

### 11.1 保留兼容但不作为主路径

| 旧逻辑 | 新口径 |
| --- | --- |
| `intentSelect` / `planEditSelect` | 旧卡片点击后只转换为新的 `pendingConfirmationCard` |
| `planEditCache` | 只作为旧会话 fallback，不作为新 pending 主源 |
| `pending_plan_action` | 迁移期 adapter，后续转为 `pendingConfirmation` |
| `pending_intent_change` | 迁移期 adapter，后续转为 `pendingConfirmation` |
| 历史工具返回恢复 pending | 只用于旧会话轻量恢复，不回到每轮主路径 |
| `planningWorkspaceAction` | 只用于打开/刷新工作区，不承载确认语义 |

### 11.2 必须清理或限制的旁路

| 旁路 | 处理 |
| --- | --- |
| 模型直接调用 `execute_plan_action(apply)` | 只允许在 `confirmed_via_pending=true` 的服务端确认上下文中执行 |
| 模型直接调用 `update_volunteer_intent_state(confirm)` | 返回需要确认卡片，不写入 |
| 无 pending 的自然语言确认 | 不执行，提示重新生成确认卡片 |
| 旧卡片直接写入偏好/要求 | 改为生成新 pending card |
| 旧卡片刷新后仍可点 | 后端校验 pendingId，前端置灰 |

### 11.3 旧会话兼容

旧会话内容继续展示。

未确认旧卡片处理：

- 能恢复完整 payload、来源消息和版本：转换成新的 `pendingConfirmationCard`。
- 不能恢复：标记失效，不执行。

旧 Plan preview 处理：

- 有结构化 payload 且版本有效：转换成新 pending。
- 只有自然语言：不能执行，要求用户重新说明。

旧文本确认入口：

- 不再作为独立执行入口。
- 只有存在 active pending 且满足短文本兜底条件，才进入新统一确认方法。

## 12. 一致性与观测

### 12.1 为什么需要观测

短文本兜底会带来一个新风险：用户可能是根据模型刚刚说的一段自然语言来确认，而这段自然语言与当前 active pending 卡片不完全一致。

因此必须记录确认入口和一致性状态。

### 12.2 事件字段

建议记录：

```json
{
  "eventType": "pending_confirmation_apply",
  "sessionId": "129",
  "pendingId": "uuid",
  "kind": "intent_change",
  "actionFamily": "set_preference",
  "confirmationEntry": "card | short_text",
  "pendingSummary": "不优先专业：秘书学",
  "assistantConfirmationSummary": "最近一条助手确认语义摘要",
  "consistencyStatus": "matched | unknown | conflict | not_checked",
  "blockedReason": "",
  "sourceBackendVersion": 12,
  "currentBackendVersion": 12,
  "result": "applied | blocked | expired | failed"
}
```

### 12.3 阻断策略

短文本确认初期应偏保守：

- 卡片是最近一次用户可见确认内容：允许。
- 最近助手文本只是泛化说明，没有新的确认范围：允许。
- 最近助手文本出现和卡片不同的学校/专业/地域/位置：阻断。
- 无法确认一致性且动作副作用高：阻断，要求点击卡片。

卡片点击不受模型自然语言影响，因为用户点击的是明确卡片。

## 13. 实现机制

### 13.1 服务端统一入口

新增或整理共享方法：

```text
apply_pending_confirmation(
  session_id,
  pending_id,
  confirmed_via="card | short_text"
)
```

职责：

- 读取 active pending。
- 校验状态、版本、权限和类型。
- 调用 intent 或 plan 的内部 apply。
- 更新 pending 状态。
- 回写原卡片消息状态。
- 记录行为事件。
- 返回用户反馈和工作区刷新指令。

### 13.2 文本确认处理

当前的 early confirmation guard 应从“统一提示点卡片”调整为：

```text
if is_short_confirmation(userText):
    if has_active_pending:
        return try_apply_active_pending_from_short_text(userText)
    return no_pending_guard
```

注意：

- `is_short_confirmation` 只判断非常短的确认类表达。
- 一旦文本里包含新对象或新条件，不能当确认，必须回到 Agent 理解。
- 不做复杂自然语言动作解析。

### 13.3 RequestContext 命名

当前代码里存在 `confirmed_via_card` 语义。

设计上建议改成：

```text
confirmed_via_pending=true
confirmation_entry=card | short_text
```

原因：

- apply 的本质凭证是 pending，不是卡片本身。
- 短文本兜底同样要通过 pending 执行。
- 便于后续统一审计。

迁移期可以保留兼容字段，但新代码应逐步使用 `confirmed_via_pending`。

### 13.4 输出保护

保留窄口径输出保护：

- 只处理模型说了“确认后执行/回复确认即可”但本轮没有 pending/card 的情况。
- 保护目标是防止用户看到不可执行的假确认承诺。
- 不用它来识别用户意图，不用它来触发执行。

如果能从结构化工具结果生成 pending，应优先生成卡片；如果不能，就提示重新整理确认卡片。

## 14. 测试矩阵

### 14.1 意向/要求

| Case | 预期 |
| --- | --- |
| 想去北京 | 生成偏好卡片 |
| 不太想去江苏 | 生成不优先偏好卡片；如无命中可 no-op |
| 不去天津 | 生成硬要求卡片 |
| 只学金融 | 生成硬要求卡片 |
| 护理不要 | 生成硬要求卡片 |
| 法学财政学优先，护理不要 | 同卡片披露偏好和要求 |
| 用户点击采纳 | 写入并触发推荐 stale/刷新 |
| 用户短文本“确认”且 active pending 存在 | 走统一 apply |
| 用户短文本“确认”但无 pending | 不执行 |
| 用户“确认，但只排除江苏” | 不消费旧 pending，重新理解 |

### 14.2 方案调整

| Case | 预期 |
| --- | --- |
| 按录取率排序 | 生成排序确认卡片 |
| 按院校层次排序 | 生成排序确认卡片，指标披露正常 |
| 把第 5 个挪到第 2 个 | 生成移动确认卡片 |
| 删除汉语言文学 | 能定位则生成删除确认卡片；不能定位则澄清 |
| 把太贵的去掉 | 明确操作时生成删除预览和确认卡片 |
| 专业组整体移动 | 按专业组整体处理 |
| 专业组内单专业移动 | 不支持时说明边界，不误执行 |
| 确认卡片点击 | 执行 apply，方案待重新审查 |
| 短文本确认 active plan pending | 执行同一 pending |
| 旧方案版本确认 | 标记 expired，不执行 |

### 14.3 旧链路和异常

| Case | 预期 |
| --- | --- |
| 旧 Intent 卡片点击 | 转新 pending card，不直接写入 |
| 旧 Plan preview 只有文本 | 不执行，提示重新生成 |
| 新 pending 替代旧 pending | 旧卡片置灰，点击不执行 |
| 模型说“回复确认即可”但无 pending | 输出保护替换为重新生成卡片提示 |
| 工作区刷新卡片 | 不作为确认卡片展示 |
| 只读方案审查 | 不被误替换成确认提示 |

## 15. 验收标准

- 所有意向、要求和方案更新在 pending 创建前不生效。
- 卡片确认和短文本确认进入同一执行方法。
- 无 active pending 的文本确认不会执行任何更新。
- 模型自然语言承诺不会成为执行凭证。
- 新 pending 会替代旧 pending，旧卡片刷新后不可点击。
- 软意向和硬要求的文案、状态写入、推荐刷新和方案影响边界一致。
- 专业+大学和院校专业组两种方案结构在移动、删除、排序、导出和卡片披露里不混用。
- 旧 `planEditCache`、`pending_plan_action`、`pending_intent_change` 不再作为新会话主状态。
- 所有 pending 创建、确认、取消、替代、过期、执行失败都有事件可追踪。

## 16. 后续落地顺序

1. 统一服务端 `apply_pending_confirmation`，让卡片确认和短文本兜底共用。
2. 将 `confirmed_via_card` 迁移为 `confirmed_via_pending`，保留短期兼容别名。
3. 调整 early confirmation guard：active pending 下允许短文本兜底确认，无 pending 继续阻断。
4. 修复模型无 pending 假确认输出保护，只做窄口径防护。
5. 更新原有“文本确认必须点击卡片”的测试，改为 active pending 可兜底执行。
6. 增加冲突观测事件，记录 short_text 确认时的 pending 摘要和最近助手确认语义。
7. 清理旧工具 confirm/apply 旁路，确保执行层只认 `confirmed_via_pending`。
8. 完成旧卡片状态回写和刷新后置灰。
9. 回归 88 个对话 case、open-quality case、pending protocol、plan execution、intent state、前端人工操作。

## 17. 当前阶段结论

3.0.3 的目标不是让 Agent 更激进地理解自然语言并直接改状态，而是把所有高副作用动作收口到可追踪、可展示、可回放的 pending 协议里。

最终用户体验应是：

- 用户说想法，系统整理成清晰卡片。
- 用户能看到采纳后具体影响。
- 用户点卡片最稳；只说“确认”也能在当前卡片明确时继续。
- 没有卡片或卡片已过期时，系统不会猜测执行。
- 后续推荐、候选和方案状态都能解释清楚为什么变化。

## 18. 2026-06-05 落地记录：短文本确认兜底接入统一 Pending

本阶段完成了“卡片主路径 + 短文本兜底”的第一批实现。

已完成：

- `RequestContext` 新增 `confirmed_via_pending` 和 `confirmation_entry`，用来表达服务端已经校验过 pending，来源可以是 `card` 或 `short_text`。
- `execute_plan_action(apply)` 的 mutating guard 仍然不信任模型自然语言；只有 `confirmed_via_pending=true` 或兼容字段 `confirmed_via_card=true` 时才允许执行。
- 后端 active `pendingConfirmation(status=active)` 优先于旧 history fallback：
  - active plan pending + 用户只回复“确认/可以/好的”等确认词：走同一个 `handle_pending_confirmation` apply 路径。
  - active intent pending + 用户只回复“确认/确认偏好/确认要求”等确认词：走同一个 intent apply 路径。
  - 旧 history-only plan pending 仍不支持短文本执行，只提示使用确认卡片或重新生成。
- 短文本兜底只接受确认-only 表达，不接受带新动作或新范围的表达，例如“确认生成”会回到 Agent 理解，不消费 pending。
- 类型不一致时不执行：
  - 当前 active pending 是方案调整，但用户说“确认这个偏好”，提示当前等待确认的是方案调整。
- 无 pending 的“确认/可以”仍不执行。
- 修复无 pending 可执行 payload 时模型回复“回复确认即可执行替换”这类假确认文案残留，最终回复会删除这类句子并补充安全边界。
- `handle_pending_confirmation` 中读取 planning workspace 不再强制把 `session_id` 转成整数，避免非数字测试会话产生无意义告警。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/agent/context.py app/tools/plan_execution_tool.py tests/factories.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
.venv/bin/python -m pytest tests/regression/test_execution_apply.py tests/regression/test_pending_protocol.py -q
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py tests/unit/test_intent_state_tool.py tests/unit/test_ws_compat.py -q
```

验证结果：

- `test_chat_service_history_persistence.py`：`166 passed`。
- `test_execution_apply.py + test_pending_protocol.py`：`166 passed`。
- `test_plan_execution_tool.py + test_intent_state_tool.py + test_ws_compat.py`：`278 passed`。

## 19. 2026-06-05 落地记录：短文本确认观测与冲突保护

本阶段继续收口短文本确认兜底，重点不是扩大自然语言匹配范围，而是让兜底确认可观测、可阻断、可追踪。

已完成：

- 新增 `pending_confirmation_event` 结构化事件，记录：
  - `pendingId`、`kind`、`actionFamily`、`pendingSummary`
  - `confirmationEntry=card|short_text`
  - `assistantConfirmationSummary`
  - `consistencyStatus=matched|unknown|conflict|not_checked`
  - `blockedReason`
  - `sourceBackendVersion`
  - `result=applied|blocked|failed`
- 卡片确认仍是主路径，卡片点击不受最近模型文本影响，事件里 `consistencyStatus=not_checked`。
- 短文本确认只在 active backend pending 存在时尝试执行，并增加最近助手确认内容一致性检查。
- 冲突保护只检查系统自己生成的确认形态：
  - 优先读取最近助手消息中的 `pendingConfirmationCard` JSON。
  - 文本 fallback 只识别系统确认标题，如“确认采纳这次偏好”“确认方案排序”“确认移出志愿”等。
  - 不根据用户自然语言推断要执行什么业务动作。
- 如果最近助手确认类型与 active pending 类型明显冲突，短文本确认会阻断并提示用户点击最新确认卡片或重新说明。
- 如果已经因为一致性冲突被阻断，用户再次只回复“确认”仍保持阻断，避免被上一条阻断提示覆盖历史后误执行；该阻断会绑定当前 `pendingId`，后续重新生成的新卡片不受旧阻断影响。
- 正常短文本确认仍走统一 `handle_pending_confirmation` apply 路径，并把 `confirmed_via_pending=true` 传给执行层。

设计边界：

- `unknown` 不代表失败。它表示最近助手文本没有明显确认卡片/标题冲突，当前阶段允许继续执行 active pending。
- `conflict` 只用于明显的系统确认类型错位，例如最近助手可见内容是“确认采纳这次偏好”，但后端 active pending 是方案排序。
- 不做学校、专业、地域等实体级模糊匹配，避免把自然语言内容重新变成脆弱路由规则。
- 后续如果要做实体级一致性，应基于结构化 card payload 或 pending payload，而不是正则解析用户输入。

验证命令：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py tests/unit/test_chat_service_history_persistence.py
.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q
.venv/bin/python -m pytest tests/regression/test_execution_apply.py tests/regression/test_pending_protocol.py tests/unit/test_plan_execution_tool.py tests/unit/test_intent_state_tool.py tests/unit/test_ws_compat.py -q
```

验证结果：

- `test_chat_service_history_persistence.py`：`170 passed`。
- `test_execution_apply.py + test_pending_protocol.py + test_plan_execution_tool.py + test_intent_state_tool.py + test_ws_compat.py`：`444 passed`。

## 20. 2026-06-05 落地记录：session 130 硬要求采纳与候选池语义修复

人工走查 session 130 时发现：用户采纳“不学法”后，回复里出现“按这条要求过滤后，候选大约还有 1327 个，整体候选大约是 1439 个”，但当前方案里仍有法学相关志愿。

定位结论：

- 基础候选池没有被真正改小，`1439 -> 1327` 只是旧链路按 `negativeMajorKeywords=["法学类"]` 做的一次临时查询结果。
- 硬要求采纳本来不应直接删除当前方案。当前方案中的法学志愿需要另走方案调整确认卡片后才会移除。
- 旧 `userprofile` 已写入 `negative_major_intent.level2=["法学类"]`，但 planning 显式画像没有同步更新；同时正负向冲突清理不完整，可能出现 `法学类` 同时在正向和负向里，导致后续方案分析/检查仍按旧画像理解。
- `intent_state_tool` 旧实现会在 constraint apply 后构建 `candidateFilters`、查询 `filteredTotal/baseTotal` 并返回候选区刷新联动，容易让用户误解为候选池已经永久变化。

修复：

- `ProfileManager` 写入旧用户画像后，同步 PATCH planning 显式画像：
  - 专业意向同步到 `majorPreferences.positive/negative`。
  - 院校意向同步到 `schoolPreferences.positive/negative`。
  - 地域意向同步到 `regionPreferences.positive/negative`。
- 负向新增会从对应正向列表中移除冲突项，正向新增也会从负向列表中移除冲突项。
- Java `UpdateExplicitProfileReq` 改为 nullable 字段，支持 partial PATCH；只传专业时不会把学校、地域、选科等未传维度清空。
- constraint apply 不再构建或返回 `candidateFilters`，不再查询或展示 `filteredTotal/baseTotal`。
- constraint apply 仍会标记 planning stale，并 best-effort 触发 recommendation overlay refresh；这表示后续推荐/检查需要复看，不表示本轮直接过滤基础候选池。
- 硬要求采纳后只返回方案查看引导，不返回候选区隐藏筛选联动。

用户侧预期：

- 点击“采纳”后，系统回复会复述本次确认内容，并说明这条要求会作为后续报考参考。
- 回复不再出现“候选过滤后还有 X 个 / 整体候选 Y 个”。
- 当前方案不会在意向采纳这一步自动删除法学志愿；如果用户要从当前方案移出，需要生成并点击方案调整确认卡。
- 后续方案检查、推荐解释和调整边界会读取同步后的 planning 显式画像，避免旧画像和 planning 状态不一致。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/services/profile_manager.py app/util/internal_client.py app/tools/intent_state_tool.py app/tools/intent_response_tool.py app/service.py
.venv/bin/python -m pytest tests/unit/test_profile_manager.py tests/integration/test_profile_persistence.py tests/unit/test_intent_state_tool.py tests/unit/test_planning_intent_scenarios_sync.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py -q
```

结果：`356 passed`。

## 21. 2026-06-05 落地记录：具体专业硬要求命中当前方案时转方案调整卡

人工走查 session 130 后继续发现：用户输入“不学会计”“不学经济与金融”时，系统可能把具体专业泛化成专业类，例如“会计”被整理成“工商管理类”，“经济与金融”被整理成“经济学类”；点击采纳后又只写入要求，不移出当前方案里的命中志愿，用户会看到“已经采纳但方案没变”。

定位结论：

- `经济与金融` 是本科目录中的三级专业，当前方案里也确实存在该具体专业，不能退化成 `经济学类`。
- 模型或上游抽取有时只返回父级或同门类专业类；旧 `_refine_major_intents_by_explicit_mentions` 只能在“父级 + 子级同时出现”时去掉父级，不能在“模型只返回父级”时把用户明确说出的三级专业补回来。
- `remove_units` 的结构化范围匹配只看 `item.majorName`，没有检查专业组内的 `majorItems`，也没有按官方专业目录区分三级专业、二级专业类和一级门类。
- 纯 `intent_change` 卡片采纳只会写入偏好/要求并刷新推荐参考，不会移除当前方案。这符合确认协议，但对于“硬要求 + 当前方案已有命中项”的场景，用户期望应是先生成方案调整确认卡。

修复：

- 意向抽取后增加目录关系修正：
  - 用户最新话术明确命中三级专业时，优先保留三级专业。
  - 如果模型只返回同父级或同门类的二级专业类，并且用户没有明确提到该专业类，则补回具体三级专业并移除误泛化的专业类。
  - 示例：`不学会计` -> `negative_level3=["会计学"]`，不再展示 `工商管理类`；`不学经济与金融` -> `negative_level3=["经济与金融"]`，不再展示 `经济学类`。
- `remove_units` 结构化范围匹配改为目录层级匹配：
  - 三级专业只做官方名/受控别名等值匹配，不用“金融”等短 token 做宽包含，避免误移出 `金融学`。
  - 二级专业类按 `majorCategory/subCategoryName` 或三级专业的官方父级匹配。
  - 一级门类按 `majorDiscipline/categoryName` 或父级映射匹配。
  - 同时支持专业+大学模式的顶层志愿，以及院校专业组模式下 `majorItems` 内的子专业；子专业有 `volunteerId` 时优先移出子专业 id，不误扩大成整组。
- 服务端创建意向确认卡前增加转换：
  - 如果结构化 preview 是 `intentMode=constraint`，且只包含一类硬排除范围（专业/院校/地域之一），先用现有 `execute_plan_action(remove_units, preview)` 检查当前方案是否命中。
  - 如果命中，返回 `pendingConfirmationCard(kind=plan_mutation, actionFamily=remove_units)`，并把原硬要求放入 `intentPayload`。
  - 用户确认后，先写入硬要求，再执行方案移除；仍然保持“执行只认 active pending”的协议：卡片点击是主入口，短文本确认只能作为该 pending 的兜底入口。
  - 如果当前方案没有命中，仍返回普通 `intent_change` 卡片，仅写入后续报考参考，不制造空移除。

用户侧预期：

- “不学经济与金融”且当前方案里有经济与金融：看到的是“确认移出志愿”卡片；确认后当前方案里的经济与金融志愿会移出，并同步把这条要求写入后续报考参考。
- “不学经济与金融”但当前方案没有命中：看到的是“确认采纳这次要求”卡片；采纳后只影响后续推荐、方案检查和调整边界。
- 回复和卡片不再展示“候选过滤后还有 X 个 / 整体候选 Y 个”，也不暗示基础候选池被改小。

验证：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/tools/intent_state_tool.py app/tools/plan_execution_tool.py app/service.py
.venv/bin/python -m pytest \
  tests/unit/test_intent_state_tool.py \
  tests/unit/test_plan_execution_tool.py \
  tests/unit/test_chat_service_history_persistence.py \
  -q
```

结果：`433 passed`。

## 22. 2026-06-05 补充设计：实体规范化与确认后刷新边界

人工走查 session 130 后继续发现三类回退：

- 用户说“不学经济与金融”时，结构化意向有时被泛化成“经济学类”，导致当前方案里的具体“经济与金融”没有按预期移出。
- 用户说“不要内蒙”“不要广西师大”这类简称时，方案移除 preview 需要能命中规范实体，否则卡片和实际执行容易错位。
- 点击采纳后，工作区会先刷新一次，随后又跳到候选模块；同时回复里仍可能残留“按这条要求过滤后，候选大约还有 X 个，整体候选 Y 个”的旧语义。

设计边界：

- 大模型负责识别用户语义，包括是软偏好还是硬要求、提到的是专业/院校/地域/职业等维度，以及抽取候选实体文本。
- 实体规范化放在大模型或 extractor 输出之后、写入画像/生成确认卡/执行方案调整之前。
- 最终用于状态变更的实体必须经过确定性 resolver：专业走专业目录和受控简称表，院校走学校目录和简称 resolver，地域走省市目录和地域别名 resolver。
- 大模型可以输出规范化候选，但不能作为最终 canonical source。尤其不能把明确的三级专业扩大成二级专业类或一级门类后直接写入。
- 如需提升召回，可以在大模型前注入常用简称提示；但这只作为理解上下文，不作为最终写入和匹配依据。

本轮修复：

- 新增 `region_entity_resolver`，基于 `data/option/province_city.json` 规范化省市实体，支持 `内蒙 -> 内蒙古` 等常用地域简称。
- `execute_plan_action(remove_units)` 的结构化范围匹配接入学校/地域规范化：
  - `school_keyword=["广西师大"]` 会先解析为 `广西师范大学` 再匹配当前方案。
  - `province_keyword=["内蒙"]` 会先解析为 `内蒙古` 再匹配当前方案。
  - `city_keyword=["上海"]` 会保留为 `negative_city=["上海"]`，不会混入 `negative_province`。
- 服务端将硬要求转换为方案移除确认卡前，同样对院校和地域排除项做规范化，确保卡片内容、pending payload 和 plan preview 使用一致实体。
- `handle_pending_confirmation` 在“方案调整 + 意向写入”确认成功后过滤掉 `candidate` 工作区 followup，避免确认后自动跳到候选模块；候选区只应由显式候选查询或用户点击进入。
- 前端 pending 确认点击后不再主动 `setFetchFlag`，统一由后端 `planningWorkspaceAction(refresh=true)` 驱动一次工作区刷新，避免双刷新竞争。
- 服务层清理旧采纳回复里“候选大约/整体候选”的后续使用说明。采纳偏好或要求不表示基础候选池被永久过滤，也不应向用户展示这种数量口径。

用户侧预期：

- “不要内蒙”如果当前方案有内蒙古志愿，会生成移出这些志愿的确认卡；点击确认后写入硬要求并移出命中志愿。
- “不要广西师大”会按广西师范大学处理，不会靠宽泛字符串误伤广西科技大学等其他学校。
- 硬要求命中当前方案时，确认后停留在方案/审查相关工作区，不自动跳到候选。
- 回复不再出现“候选过滤后还有 X 个 / 整体候选 Y 个”，只说明这条要求会作为后续报考参考，或说明本次方案移除结果。

新增回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/domain/entity_resolution.py app/domain/region_entity_resolver.py app/tools/plan_execution_tool.py app/service.py
.venv/bin/python -m pytest \
  tests/unit/test_entity_resolution.py \
  tests/unit/test_plan_execution_tool.py::test_execute_plan_action_remove_preview_matches_region_alias \
  tests/unit/test_plan_execution_tool.py::test_execute_plan_action_remove_preview_keeps_city_scope_in_intent_update \
  tests/unit/test_plan_execution_tool.py::test_execute_plan_action_remove_preview_matches_school_alias \
  tests/unit/test_chat_service_history_persistence.py::test_sanitize_reply_removes_legacy_candidate_filter_count_after_intent_apply \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_pending_plan_confirmation_applies_intent_payload_before_plan \
  -q
```

验证结果：

- 编译通过。
- 针对性回归：`17 passed`。
- 相关宽回归：`tests/unit/test_intent_state_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py`，`457 passed`。
- 前端执行 `./node_modules/.bin/tsc --noEmit --pretty false` 仍有既有全局类型错误，集中在 `src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts`；本次修改文件 `sessionDetailV2/MessageList/index.tsx` 未出现在错误列表。

## 23. 2026-06-05 补充设计：专业实体类型与确认边界

人工走查 session 130 继续暴露一个更细的实体边界问题：用户说“不想学工商管理”，系统不能把它扩大成“不想学工商管理类”。招生计划里还可能出现学校自定义展示名，例如“工商管理类(包含专业:工商管理、市场营销、人力资源管理)”，它也不能直接等同于官方专业目录里的二级“工商管理类”。

需要区分的专业实体类型：

- 官方具体专业：三级专业，例如 `工商管理`、`经济与金融`、`会计学`。用户确认后只作用于这个具体专业，不自动扩大到同一专业类下的其他专业。
- 官方专业类：二级专业类，例如 `工商管理类`、`金融学类`。用户明确说“工商管理类都不要”时，才按该专业类及其目录子专业处理。
- 官方专业门类：一级门类，例如 `管理学`、`经济学`。只有用户明确表达门类级要求时，才写入门类级约束。
- 招生计划展示名/招生专业类：学校或计划侧展示字段，例如 `工商管理类(包含专业:工商管理、市场营销、人力资源管理)`。它可用于展示和辅助定位，但默认不作为用户长期意向里的官方实体；除非后端同时提供了明确的 `majorCategory/subCategoryName` 等目录字段。

统一机制：

- 大模型或 extractor 仍负责抽取用户提到的实体文本，但所有专业实体在生成确认卡、写入画像、构造方案调整 pending 前都必须经过 `major_entity_resolver` 的目录规范化。
- 规范化顺序是：模型输出 -> 官方目录 re-bucket -> 结合用户最新原话做边界收窄 -> 生成 typed pending payload。
- 如果模型把 `工商管理类` 放到 `negative_level3`，会先按目录归位成 `negative_level2`。
- 如果用户原话明确是 `工商管理`，而模型只返回其父级 `工商管理类`，会收窄为 `negative_level3=["工商管理"]`。
- 如果用户原话明确是 `工商管理类`，则保留 `negative_level2=["工商管理类"]`。

方案调整链路：

- `execute_plan_action(remove_units)` 在主入口解析出 `PlanActionPlan` 后，会先规范化专业 scope，再进入 preview/apply。
- 规范化后的范围会回写到 action：
  - `source_major_names` 使用规范后的官方实体名。
  - `filters.major_level1/major_level2/major_level3` 表达明确层级。
  - 原始 `major_keyword/major_tags/negative_level*` 不再作为执行范围混读。
- preview、pending source payload、`intent_update` 和最终 apply 使用同一份 typed scope。
- 确认卡片和回复文案展示明确边界：
  - `具体专业：工商管理`
  - `专业类：工商管理类`
  - `专业门类：管理学`

匹配边界：

- 具体专业匹配只按官方名或受控别名等值匹配，不因为 `工商管理类` 包含 `工商管理` 就命中。
- 专业类匹配才会使用 `majorCategory/subCategoryName` 或三级专业到二级专业类的目录父级映射。
- 专业组模式下仍支持 `majorItems` 内的子专业定位；子专业有独立 `volunteerId` 时优先移除子专业，不扩大成整组。
- 专业+大学模式下仍按单个志愿行处理。
- `replace_units` 的候选筛选暂不使用这套 remove scope 重写，因为它的 `major_keyword` 表示替换目标候选，不是要移除/写入约束的来源范围。

用户侧预期：

- “不想学工商管理”：如果当前方案有具体 `工商管理`，确认卡显示“具体专业：工商管理”，确认后只移出该具体专业并写入具体专业级硬要求；不会移出 `会计学/审计学/财务管理`。
- “不想学工商管理类”：确认卡显示“专业类：工商管理类”，确认后按官方专业类范围处理。
- 如果当前方案只有招生计划展示名类似“工商管理类(包含专业:...)”，但没有明确目录字段能证明它是官方二级专业类，系统不默认按具体 `工商管理` 删除；应提示用户确认是否要排除整个招生专业类/专业类。

新增回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/domain/major_entity_resolver.py app/tools/intent_state_tool.py app/tools/plan_execution_tool.py app/service.py
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_plan_execution_tool.py -q
.venv/bin/python -m pytest tests/regression/test_execution_apply.py tests/regression/test_pending_protocol.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py -q
```

验证结果：

- 编译通过。
- 专业实体和方案执行目标回归：`269 passed`。
- pending/apply/history/ws 相关回归：`358 passed`。

### 23.1 session 130 补充：重新纳入与正负冲突清理

人工走查 session 130 时出现新的状态问题：

- 历史链路曾把“不学会计 / 不想学工商管理”泛化成 `工商管理类`，并把 `工商管理类` 错写到了 `negative_level3`。
- 后续用户说“想学工商管理”“是的，重新纳入”时，系统只看到正向 `major_intent.level2=["工商管理类"]` 已存在，于是返回“当前已经在报考参考里，不用重复采纳”。
- 实际 profile 同时存在正向 `工商管理类` 和负向残留，状态并不一致；这个回复是错误的。

修复规则：

- 意向预览不能只判断“正向是否已存在”。如果正向已存在但相反方向仍有同名、父级或子级冲突，仍要生成确认项，文案表达为“重新纳入 / 从不优先或排除范围里移出”。
- `ProfileManager.get_current_profile` 读取历史画像时，会先按专业目录把错层级实体归位，例如 `negative_level3=["工商管理类"]` 会归位到 `negative_level2=["工商管理类"]`。
- `ProfileManager.update_major_intent` 在保存前会按专业目录清理正负冲突：
  - 新确认正向专业类，会清掉相同负向专业类及其负向子专业。
  - 新确认正向具体专业，会清掉相同负向具体专业以及相反的父级排除。
  - 新确认负向专业类/门类，会清掉被覆盖的正向子项。
  - 新确认负向具体专业仍允许作为正向大类下的例外，例如“整体偏好工商管理类，但不考虑会计学”。

用户侧预期：

- 如果用户已排除过 `工商管理类`，又说“重新纳入工商管理类”，应出现确认卡；点击采纳后会清掉旧的负向排除，并同步 planning 显式画像。
- 如果用户只说“想学工商管理”，默认仍按 `具体专业：工商管理` 理解；若当前有 `工商管理类` 相关历史排除，需要在确认卡里说明是否会取消父级排除。
- 不应再回复“这个想法已经在报考参考里，不用重复采纳”，除非同方向已存在且没有相反方向冲突。

新增回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/services/profile_manager.py app/tools/intent_state_tool.py app/domain/major_entity_resolver.py
.venv/bin/python -m pytest tests/unit/test_profile_manager.py tests/unit/test_intent_state_tool.py -q
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py tests/regression/test_execution_apply.py tests/regression/test_pending_protocol.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py -q
```

验证结果：

- 编译通过。
- `tests/unit/test_profile_manager.py tests/unit/test_intent_state_tool.py`：`157 passed`。
- 方案执行、pending 和历史持久化相关回归：`482 passed`。

## 24. 2026-06-05 回归修复：混合偏好和硬排除命中当前方案时的确认卡一致性

open-quality live 回归时发现一个边界问题：

- 用户输入“我倾向会计学和审计学，但土木工程不要”。
- 模型先正确识别为专业意向的正负混合，但由于 `土木工程不要` 是硬排除，且当前方案存在命中项，服务层把 pending 转成 `remove_units` 方案调整卡。
- 旧卡片只展示“移出土木工程相关志愿”，没有披露 `会计学/审计学` 这两个正向偏好；用户点击确认后虽然 `intentPayload` 里有机会携带完整 selected，但卡片披露、pending 摘要和实际执行预期不一致。
- 另一个隐患是 `constraintState` 同步只有整张卡一个 `intentMode`。正负混合且整体为 `constraint` 时，正向“倾向/还能接受”有被写入 hard must-include 的风险。

修复规则：

- 混合意向仍必须先走 `preview_current_major_intent_confirmation`，由结构化 preview 给出正向偏好和负向要求。
- 如果负向硬要求命中当前方案，可以转成同一张 `pendingConfirmationCard(kind=plan_mutation, actionFamily=remove_units)`，但卡片必须同时披露：
  - 当前方案将移出的命中项；
  - 同步写入后续报考参考的完整意向，例如 `偏好专业：会计学、审计学；排除专业：土木工程`；
  - 点击确认前不改方案，确认后执行方案调整并同步更新报考参考。
- `constraintState` 同步按结构化 payload 拆分：
  - 如果本次是 `constraint` 且同时有正向和负向值，正向值按 `preference` 写入 soft preferences；
  - 负向值按 `constraint` 写入 hard constraints；
  - 单纯硬正向要求（例如“只去北京”）仍按 constraint 写入 hard must-include；
  - 单纯软负向偏好（例如“不太想去江苏”）仍按 preference 写入 soft avoid。
- 旧 `userprofile` 仍保存正负向专业/院校/地域，用于兼容旧画像；planning `constraintState` 承担 soft/hard 的语义区分。

用户侧预期：

- “会计审计还行，土木不要”且方案中有土木：出现一张“确认移出志愿”卡，卡片里能看到会计/审计会作为偏好、土木会作为排除要求。
- 点击确认后，先写入报考参考，再移出当前方案命中项；执行内容仍只认 active pending，不认模型自然语言。
- 如果当前方案没有命中负向要求，则返回普通意向确认卡，不制造空移除。

新增回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m py_compile app/service.py app/tools/intent_state_tool.py
.venv/bin/python -m pytest \
  tests/unit/test_intent_state_tool.py::test_apply_mixed_constraint_intents_syncs_positive_soft_and_negative_hard \
  tests/unit/test_chat_service_history_persistence.py::test_chat_service_mixed_intent_plan_hit_card_keeps_positive_preference_summary \
  -q
.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py -q
.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py tests/regression/test_execution_apply.py tests/regression/test_pending_protocol.py -q
```

验证结果：

- 编译通过。
- 新增针对性回归：`2 passed`。
- `tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py`：`328 passed`。
- `tests/unit/test_plan_execution_tool.py tests/regression/test_execution_apply.py tests/regression/test_pending_protocol.py`：`290 passed`。

补充 live 回归：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8037/gaotu-assistant-agent/plus/chat/1/bot/1/do \
  --cases examples/dialog_regression_303_open_quality_cases.json \
  --response-timeout 180 \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_303_open_quality_live_after_mixed_fix.json \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --internal-service-url http://127.0.0.1:8080
```

结果：

- `steps=23`，`successfulSteps=23`，`failedSteps=0`，无断言失败。
- 原失败场景“我倾向会计学和审计学，但土木工程不要”已返回已有报考参考，包含会计学、审计学、土木工程，不再生成只保留移除范围的错误卡片。
- 混合软硬场景“会计审计这类还行，土木建筑那种别碰”返回 `pendingConfirmationCard(kind=intent_change)`，卡片包含 `偏好专业：会计学、审计学` 和 `不优先专业：土木工程、建筑学；不优先专业类：土木类`。
- 只读方案查询后用户回复“确认”被 guard 阻断，没有误消费 pending。
- 方案排序预览仍返回 `pendingConfirmationCard(kind=plan_mutation, actionFamily=sort_ordered_plan)`。
- 延迟仍偏高：`median=25655ms`，`p95=57269ms`，`max=67023ms`。慢点主要在 full agent 的模型请求和最终整合回复，后续性能优化应在不降低回复质量的前提下继续处理。

离线质量门：

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_quality_gate.py --execute --mode local
```

结果：`1109 passed`。

## 25. 2026-06-06 补充：pending 只读影响追问与基础候选池语义

### 25.1 只读影响追问

用户在待确认卡片生成后，可能不会立即点击采纳，而是继续问：

- `先不确认，看看这个偏好会影响当前方案吗`
- `采纳后专家优选会变吗`
- `这个要求会删掉哪些志愿`

预期行为：

- 如果后端 `pendingConfirmation.status=active`，服务层优先读取 active pending。
- 只读影响追问只解释 pending 采纳后的影响，不执行、不取消、不清空 pending。
- 回复必须明确当前状态：不点击确认时，当前方案不会移出、加入、移动或重排任何志愿。
- 如果 pending 是意向变更，影响说明可以包括：
  - 当前方案命中项；
  - 后续报考参考将新增或调整的偏好/要求；
  - 采纳后会用于推荐系数、专家优选、方案检查和调整参考。

本轮 live 验证：

- 输入 1：`我倾向会计学和审计学，但土木工程不要`
- 输入 2：`先不确认，看看这个偏好会影响当前方案吗`
- 结果：第二轮走 `pending_readonly_impact`，不调用 full Agent，不消费 pending；回复披露当前方案命中土木工程 3 条志愿，同时说明会计学/审计学偏好和土木工程排除会同步写入后续参考。

### 25.2 基础候选池语义

3.0.3 的确认协议里，采纳偏好或要求不代表基础候选池被永久删除或缩小。

正确语义：

- 软偏好：影响推荐系数、专家优选和补位排序。
- 硬要求：作为后续候选查看、方案检查和方案调整的过滤/排除参考。
- 当前方案中已经存在冲突项时，需要通过方案调整确认卡片移除；不能仅靠意向采纳静默删除。
- 基础候选池的原始数据不在“采纳偏好/要求”这一步物理缩小。

用户侧禁用表达：

- `自动过滤候选`
- `候选池会变小 / 候选池会大幅收窄`
- `这些方向不再进入候选`
- 无卡片时说 `确认后才会生效`

用户侧推荐表达：

- `基础候选池本身不会因此缩小。`
- `采纳后会作为后续推荐、方案检查和方案调整的参考。`
- `如果要正式采用，我可以整理成确认卡片；采纳/确认前不会生效。`

实现边界：

- 这次只在用户可见回复的出站清洗层处理候选池误导表达。
- 不改变候选查询真实筛选、不改变 pending 执行、不改变方案调整链路。
- 该清洗只在意向/要求/影响语境下触发，避免误伤用户显式查询候选时的“筛选结果”表达。

验证：

- `tests/unit/test_chat_service_history_persistence.py`
- `tests/unit/test_intent_state_tool.py`
- `tests/unit/test_planning_intent_scenarios_sync.py`
- `tests/unit/test_tool_reply_policy.py`
- `tests/unit/test_dialog_regression_runner.py`

结果：`425 passed`。

targeted live：

- 输入：`医学护理这些别碰，财会还能接受，先看看影响`
- 输出：只做分析，不生成 pending；说明医学/护理会作为过滤参考、财会作为可接受方向；明确基础候选池不缩小；只询问是否整理确认卡片。
- 输出文件：`/private/tmp/zhiyuan_303_intent_candidate_pool_semantics_live_final2.json`。

最终 open-quality 验证：

- 输出文件：`/private/tmp/zhiyuan_303_open_quality_live_after_candidate_pool_semantics_final_pass.json`
- 结果：`steps=23`，`successfulSteps=23`，`failedSteps=0`。
- pending 影响追问、no-pending guard、只读候选查询、排序预览确认卡片、调稳预览、医学/护理影响分析均通过。
- 剩余问题仅为延迟 warning，集中在专业对比和职业方向 full Agent 总结；确认状态机和候选池语义没有新增失败。
