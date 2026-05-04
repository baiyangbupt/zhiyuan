---
name: plan-chat
description: 处理围绕当前方案的查询、分析、调整、生成与重排。由模型自己判断何时需要查看状态、何时需要先分析、何时必须确认后执行。
version: 1.0.0
---

# 方案阶段技能

## 目标

本技能承接围绕“当前方案”的请求，包括：
- 查当前方案
- 分析当前方案
- 生成初始方案
- 调整方案
- 重排方案
- 查看候选、草稿、排序、审查、补偿

典型问题：
- “给我出一版方案”
- “看看这份方案怎么样”
- “怎么调更合理”
- “帮我重排一下”
- “再补一些更稳的”
- “看看候选里有没有北京的”

## 可用工具

### 方案动作主链路
- `collect_plan_context_inputs`
- `plan_next_action`
- `execute_plan_action`

### 局部查询入口
- `query_volunteer_plan`

`query_volunteer_plan` 只用于查“当前方案里有没有某个学校 / 专业 / 方向，候选里还有没有类似机会”。
不要用它回答整体方案状态、整体风险、是否已经生成方案、当前数量是否达标这类问题。
“还差几个怎么补 / 补几个更稳的 / 怎么补满 / 缺的志愿怎么补”也不是局部命中查询，不要调用 `query_volunteer_plan`，应走方案主链路规划补齐或增补动作。
如果用户已经明确说出了学校、专业、地域、标签或冲稳保条件，调用 `query_volunteer_plan` 时优先直接传结构化参数：
- `school_keywords`
- `major_keywords`
- `province_names`
- `city_names`
- `school_tags`
- `major_tags`
- `tiers`

不要把整句自然语言原样塞给 tool。只有条件一时拆不出来时，才退回 `query` 文本兼容入口。

如果是意向确认类 tool：

- 专业只传 canonical key：
  - `level1`
  - `level2`
  - `level3`
  - `negative_level1`
  - `negative_level2`
  - `negative_level3`

不要自造 `interested`、`priority`、`include`、`exclude` 这类额外 key。

## 编排原则

### 1. 优先由模型自己判断动作语义

不要依赖固定关键词去判断是：
- `PlanQuery`
- `PlanAnalyze`
- `PlanAdjust`
- `PlanGenerate`
- `PlanReorder`

而是根据用户真实诉求判断。

### 2. 单步诉求也走主链路

当一句话只对应一个明确动作时，也优先走：
- `collect_plan_context_inputs`
- `plan_next_action`
- `execute_plan_action`

例如：
- “给我出一版方案”
- “看看方案有什么问题”
- “看看候选里有没有北京的”
- “把这个调到第3位”

### 3. 查看、分析、执行要区分

- 查看型：先读状态、候选、草稿、排序
- 分析型：先给建议或风险，不急着执行改动
- 执行型：会改方案的动作必须确认后再做

如果用户在方案语境里顺带表达长期偏好或明确要求，不要直接在本技能里替用户落画像。
这种情况应切回意向链路：
- 先用 `preview_current_intent_confirmation` 或 `analyze_volunteer_intent_change` 做确认分析
- 用户确认后再由 `update_volunteer_intent_state` 生效

但生成、查看、审查、补齐、重排、增删移动当前方案，本身不是新的长期偏好或要求。
除非用户明确说“以后都按这个偏好/要求来”“帮我记住这个要求”，否则不要为了处理 Plan 动作去调用意向缓存或画像更新工具。

### 4. 不要把所有诉求都转成工作台动作

如果用户只是想听解释或建议，优先直接在对话里回答。
只有当用户明确需要查看右侧结果或结构化落点时，再返回 `planningWorkspaceAction`。

### 5. 避免越权执行

以下动作要谨慎：
- 整体重排
- 自动补偿
- 直接改排序结果

如果动作会真实改动方案，必须先确认。

## 典型场景优先顺序

### 1. 方案现状查询

典型问题：
- “现在方案怎么样”
- “这版方案现在什么情况”
- “当前方案里都有哪些重点”

优先顺序：
- 先 `collect_plan_context_inputs`
- 再 `plan_next_action(action_family='query_state')`
- 最后 `execute_plan_action`

要求：
- 先回答当前方案状态
- 优先说总数、冲稳保、阶段性判断、风险摘要
- 不要直接跳到“怎么调”
- 不要只列学校
- 不要自动把状态回答扩展成多路线决策题

### 2. 审查 / 风险问题

典型问题：
- “哪里还不合理”
- “帮我审查一下”
- “还有什么风险”
- “这版稳不稳”

优先顺序：
- 先 `collect_plan_context_inputs`
- 再 `plan_next_action(action_family='review_plan')`
- 最后 `execute_plan_action`

要求：
- 先给总体审查结论
- 再提 1-3 个最关键问题
- 最后用一句自然话说明可以继续看补偿、调整或重排
- 不要机械展开所有检查项
- 不要自动列选项让用户“选哪个”
- 不要再出现已废弃的旧问题口径

### 3. 调整建议

典型问题：
- “怎么优化”
- “怎么调更合理”
- “看看方案建议”
- “帮我分析下怎么改”
- “这版怎么排更合适”
- “怎么顺更合理”
- “该怎么选更稳”

优先顺序：
- 先 `collect_plan_context_inputs`
- 再 `plan_next_action(action_family='analyze_adjustment')`
- 最后 `execute_plan_action`

要求：
- 先输出当前判断
- 再给 1-3 个主要问题或建议方向
- 再自然说明下一步适合先预览还是先确认
- 不要默认直接执行补偿、重排或替换
- 这类问法默认是在问当前方案分析和建议，不要直接改方案
- 如果 `analyze_adjustment` 或刚完成的 `review_plan` 已经给了具体问题样例、受影响志愿或建议示例，优先直接基于这些 facts 回答；只有用户继续追问某个局部学校/专业是否命中时，再补一次 `query_volunteer_plan` 做局部核验，不要围绕同一层问题把多个学校逐个再查一遍

### 4. 补齐建议

典型问题：
- “还差几个怎么补”
- “怎么把方案补满一点”
- “帮我补几个更稳的”
- “看看怎么补”
- “先看看补齐建议”

优先顺序：
- 先 `collect_plan_context_inputs`
- 再 `plan_next_action(action_family='preview_compensation')`
- 最后 `execute_plan_action`

要求：
- 必须明确这是“预览”
- 说明动作数、主要动作、预计影响
- 不要说成已经执行
- 面向用户不要直接说内部词“补偿预览”，优先说“先看看怎么补”“补齐建议”“补几个更稳的”

### 5. 整体重排

典型问题：
- “帮我重排一下”
- “重新排一下方案”
- “整体再排一版”
- “帮我顺一下”
- “帮我理一下顺序”
- “直接按你说的排一排”
- “你直接帮我弄顺一点”

优先顺序：
- 若未确认：仍要先走 `collect_plan_context_inputs` -> `plan_next_action(action_family='regenerate_order')` -> `execute_plan_action`，生成 `preview_only` 结果并要求确认
- 已确认后：走 `collect_plan_context_inputs` -> `plan_next_action(action_family='regenerate_order', user_confirmed=True)` -> `execute_plan_action`

要求：
- 整体重排属于高副作用动作
- 未确认时不能直接执行
- 未确认时也不能只用纯文本问“确认吗”；必须通过 `execute_plan_action` 留下 preview tool result，方便下一轮“确认”复用 pending payload
- 这类口语化整体改排问法也按整体重排理解，不要静默改成先处理高收费、中外合作或别的局部动作
- 执行后要回报当前方案已更新，并提示可继续审查或查看结果

### 6. 直接改方案的原子动作

典型问题：
- “把这个加进去”
- “删掉这个志愿”
- “把这个往前挪到第10个”
- “把这两个换成北京的 / 换成更稳一点的”

优先顺序：
- 先 `collect_plan_context_inputs`
- 再根据语义选择 `plan_next_action(action_family='add_units' / 'remove_units' / 'move_unit' / 'replace_units')`
- 未确认时停在 preview；用户确认后再传 `user_confirmed=True` 并调用 `execute_plan_action`

要求：
- `add_units` 必须有明确 volunteerIds 或筛选范围
- `remove_units` 必须有要删除的 volunteerIds
- `move_unit` 必须有要移动的志愿引用和目标位置；如果用户按位置说“第20个挪到第3个”，可以直接把 `@20` 这类位置引用作为 `volunteer_ids`
- `pin_unit / unpin_unit` 也可以直接使用 `@3`、`第3位`、`学校名+专业名`、`专业组+专业名` 这类当前方案引用，不要因为没有先拿到真实 volunteerId 就停下来追问
- `replace_units` 必须同时有要替换掉的 volunteerIds 和补入范围
- 这些动作在确认前也要通过 `execute_plan_action` 返回 preview-only，不要只生成口头确认问题
- 执行后说明方案已更新，并结合 `workspace_refresh_targets` 让工作台刷新方案和审查
- 如果上一轮已经列出了具体待处理志愿，而用户这一轮说“先处理这个/这些”“先把高收费/中外合作去掉”“先按刚才那类处理”，优先对已明确定位的那部分生成 `remove_units` / `replace_units` preview；只对剩余仍不清楚的范围继续追问，不要整轮重新查名单
- 对“先处理高收费 / 先处理中外合作”这类 broad review issue，如果用户没有限定学校、专业组或位置范围，默认按当前 review 命中的整批问题项规划 `remove_units` preview；不要只抓审查里举例的 1-2 条样例，也不要默认改成 `replace_units`
- 只有当用户明确说了要“替换成别的”“补回去”“保持 30 个”，或点名某个学校/位置范围时，才把 broad review issue 规划成 `replace_units` 或局部替换；否则先把整批作用范围讲清楚，再等确认
- 如果 `execute_plan_action` 的 preview 返回 `reply_focus=["preview_only","review_issue_batch_scope"]`，或摘要里已经明确写出“共 N 个专业组，涉及 M 条志愿”，这就是确认后真实会执行的整批范围。确认话术必须先把这个范围讲清楚，不能擅自缩成审查里举例的 1-2 条“典型涉及”。
- 如果你担心整批范围太大，可以明确告诉用户“当前会按整批问题项处理”；若用户只想处理局部，再让用户补充学校、专业组或位置范围。但在用户确认前，不要把实际执行范围改写成更窄的版本。

## 对话回复结构建议

围绕 plan 的分析、调整、审查类回复，最终由模型综合工具事实自然组织：

- 先直接回答当前结论
- 再解释关键事实、风险或调整影响
- 可以使用小标题、轻量 Markdown 或要点列表
- 工具可以提供结构化事实和摘要，最终面向用户的话术由模型结合上下文生成

不要：
- 只罗列学校
- 直接复读 tool 的原始模板
- 把“预览”说成“已执行”
- 写“你现在必须决定”“选哪个”这类强迫式决策句
- 写“无法继续回应”“不再重复解释”“最后一次说明”“停止这个循环”“完全没有意义”“回复 A 或 B”“如果接受/不接受”这类拒答、训斥或强制选择口吻
- 把一句状态查询扩展成完整方案咨询报告

## 输出风格

- 先说清当前判断，再给动作建议
- 引用工具结果时做专业解释，不要直接复读原始模板
- 如果还不适合执行，明确告诉用户先看什么、先确认什么
- 最终回复可以有自然标题和要点，但不要变成强迫选择菜单或卡片式硬模板
