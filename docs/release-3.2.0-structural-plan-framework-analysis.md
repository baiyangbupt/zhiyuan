# Release 3.2.0 Structural Plan Framework Analysis

本文记录 3.1.1 对话回归中暴露出的 Plan 结构性框架问题，并作为 3.2.0 后续架构优化储备。3.1.1 不实施大框架切换，仍沿着当前 3.1.0/3.1.1 已有链路做小问题修补、回归验证和一致性保护；本文中的动态计划、统一 `ScenarioDecision / PlanGoal / CompositeProposal` 方案只作为后续版本设计方向。

3.2.0 不采用长期 shadow、双写或兼容桥接。主路径实现前必须先完成离线模型能力 profile，评估模型在场景理解、结构化计划和回复生成上的能力边界；profile 计划见 [release-3.2.0-model-capability-profile-plan.md](./release-3.2.0-model-capability-profile-plan.md)。profile 只作为 3.2.0 设计依据，不进入 3.1.1 runtime。

## 1. 背景

3.0.3 到 3.1.0 已经完成了大量对话、确认卡、意向和方案联动、审查修复的优化。当前主线能力包括：

- 意向和要求更新统一走 `preview -> pendingConfirmation -> apply`。
- 方案高副作用动作统一要求预览和确认。
- 审查修复使用 Java `FixProposal`、dry-run、apply policy 和 `RepairReport`。
- `only_keep / must_have / exclude` 已开始通过 Java `source=user_goal` proposal/apply 主链路处理。
- 对话侧积累了 3.0.3 真实对话衍生 case、3.1.0 constraint/review repair case、open quality、autoexplorer 和前端人工走查问题。

但最新回归仍持续暴露一个更底层的问题：系统里同时存在“审查/修复链路”“普通原子方案动作链路”“复合用户目标链路”。这些链路的执行协议大体一致，但入口、终点和后处理恢复逻辑仍不完全统一。

最典型的表现是：模型一旦先走 `review_plan`，系统容易认为本轮已经完成，后续不再继续把审查结果转成方案调整预览。用户感知上就是“我明明让你把太贵的去掉看看，你只是审查了一遍”。

## 2. 已遇到的典型问题

### 2.1 审查走成终点

现象：

- 用户说“把太贵的那几个先去掉看看”。
- 模型调用 `review_plan`，拿到高收费或中外合作提醒。
- 最终只返回 broad review 或处理建议，没有继续生成 `remove / replace` 预览卡。

本质问题：

- `review_plan` 被当成 action 终点。
- 但在这类语境里，审查应该只是取证步骤，用来定位 `review issue` 和影响范围。

### 2.2 只读咨询和调整诉求混淆

现象：

- 用户问“一年学费最多两三万，方案里高收费多吗”。
- 系统可能误走处理建议或确认卡。
- 用户问“高收费会不会影响保底安全”，系统可能返回不可处理说明。

本质问题：

- 缺少统一的 `ScenarioDecision` 区分只读解释、风险评估和方案调整。
- 不能只因为出现高收费、中外合作、风险等 issue，就进入修复链路。

### 2.3 only_keep / must_have / exclude 仍偏固定场景

现象：

- “仅保留医学”“必须有临床医学”“不学法学”等场景已经有 user-goal proposal 主链路。
- 但这些能力仍主要依赖系统内置目标类型。
- 一旦用户表达成复合诉求，例如“只保留临床医学，但稳的别全删”“不要中外合作，学费两万以内，保底多一点”，固定分支就开始绕。

本质问题：

- 当前复合目标不是模型自由规划出来的通用结构，而是系统对若干高频类型做了固定映射。
- 继续扩展固定类型会越来越像补丁，而不是统一框架。

### 2.4 专业组局部操作误入意向

现象：

- 用户问“专业组里只保留最稳的专业行不行”。
- 系统曾误恢复成“只保留发展方向：稳定就业导向”的长期意向。

本质问题：

- 局部方案操作、政策规则解释和长期意向更新边界不够稳。
- “只保留”这类语义不能脱离对象范围判断：当前专业组、当前方案、长期意向是不同领域。

### 2.5 压线政策咨询误回确认边界

现象：

- 用户说“分数刚压本科线，别给我画大饼”。
- 回复落成“这轮不会改动当前方案，也不会写入后续报考参考”。

本质问题：

- Policy/风险解释被 Plan/Intent 确认协议污染。
- 协议保护话术不应成为只读政策问题的主体回复。

### 2.6 Intent+Plan 混合回合的 pending 丢失

现象：

- 用户说“不要英语相关专业，当前方案里有的话也删掉”。
- 模型先尝试 Intent preview，工具返回 `status=empty`。
- 同一回合继续走 `plan_next_action -> execute_plan_action`，后者返回可执行 `remove_units preview_only`，并带有 `resolved_apply_payload` 和 `intent_update`。
- 最终回复说“如果后续采纳，会把这 3 条移出当前方案”，但没有生成 `pendingConfirmationCard`。
- 用户下一句“确认执行”时，系统进入 no-pending guard。

本质问题：

- 当前系统没有一个先验的唯一 `sideEffect` 决策层，同一回合可以出现 intent preview、plan preview、composite recovery 多个候选对象。
- 最终 pending 落点依赖多段后处理分支之间的互斥条件，而不是由统一 compiler 决定“本轮唯一可确认对象”。
- 当 intent preview 是 empty/non-pending，而 plan preview 已经可执行时，理论上应以 plan pending 为准；当前链路存在被混合路径压掉的风险。

3.1.1 处理边界：

- 只修“已有可执行 plan preview 必须落 pending card”的协议落点。
- 不新增“从上一轮自然语言确认文案恢复执行”的桥接。
- 不扩展新的 runtime shadow router。

3.2.0 设计要求：

- `TurnDecision` 必须先输出唯一 `sideEffect`：`readonly / intent_pending / plan_preview / apply_existing_pending / clarification`。
- `ToolPlan` 可以包含多个 evidence step，但只能有一个 proposal endpoint。
- `ProposalCompiler` 负责把 endpoint 编译成唯一 `Proposal/Pending`；empty intent preview 只能作为 evidence/error，不能覆盖已可执行 plan preview。
- 若同一轮产生多个高副作用候选，compiler 必须返回冲突澄清或按明确优先级保留一个，不能靠回复后处理抢分支。

### 2.7 前端和执行状态问题

现象：

- 确认卡点击后标题仍显示“待确认”。
- 替换预览只展示被替换项，没有展示补入项。
- 补充候选没有按用户 intent、推荐系数、录取风险、院校层次、专业相似度排序。

本质问题：

- 预览和 apply 事实没有统一成用户可理解的 `from -> to`、影响、状态和复审结果。
- 候选选择策略仍需要进入统一 proposal engine，而不是分散在多个入口。

### 2.8 pending 上下文与只读查询抢焦点

现象：

- 上一轮已经生成 intent pending，例如“偏好金融学类；排除护理学、中医学”。
- 用户下一轮说“先不确认，当前方案里有没有护理或者中医学”。
- 系统只解释 pending 未采纳的边界，没有读取当前方案回答“有没有”。

本质问题：

- 当前 pending guard 更像“确认/取消状态机”，缺少 `pending_context + readonly_query` 的合法场景。
- pending 存在时，用户仍可能要求只读查询、影响解释、范围澄清；这些不应 apply pending，也不应被 pending 边界话术覆盖。

3.2.0 设计要求：

- `TurnDecision` 需要显式区分：
  - `apply_existing_pending`
  - `cancel_existing_pending`
  - `readonly_with_pending_context`
  - `new_side_effect_conflicts_with_pending`
- 对 `readonly_with_pending_context`，compiler 保留 pending 不变，只执行 evidence/query step。
- 回复顺序应是“回答用户问题 -> 提醒 pending 状态”，而不是反过来。

### 2.9 弱偏好、备选偏好和硬约束缺少统一权重模型

现象：

- 用户说“网络与新媒体作为优先方向，跨境电商也可以考虑”。
- 最终 pending 只展示“至少保留专业：网络与新媒体”，备选的跨境电商丢失。

本质问题：

- 当前 intent schema 和 formatter 更擅长表达 `positive / negative / only_keep / must_have`。
- 用户真实表达中常见的 `primary preference / acceptable fallback / weak avoid / hard exclude` 没有稳定结构。
- 一旦 schema 表达不了，模型理解正确也会在 pending 编译时被压扁。

3.2.0 设计要求：

- Intent/Goal schema 应支持 preference strength：
  - `primary`
  - `acceptable`
  - `avoid_soft`
  - `exclude_hard`
- ProposalCompiler 必须把强弱差异传给候选排序和用户卡片。
- 硬约束不足时才阻断；弱偏好不足时应降权/解释，而不是生成不可执行错误。

### 2.10 negative-only constraint 不应依赖 positive scope

现象：

- 用户说“东北西北都不要，必须避开”。
- 模型侧 sideEffect 判断为高置信 `intent_preview`。
- 最终工具/回复却要求“补充要保留的范围”，没有生成 pending。

本质问题：

- only_keep/地域范围逻辑和 negative exclusion 逻辑耦合。
- “只考虑 A/B”需要 positive scope；“不要 X/Y”不需要。

3.2.0 设计要求：

- Compiler 对 positive scope 和 negative scope 分别校验。
- negative-only constraint 可以独立生成 `intent_change`。
- 只有当用户要求“只保留/只考虑”但 positive scope 缺失时，才进入 clarification。

### 2.11 查询缺前置条件时必须返回 missingInfo，而不是空结果解释

现象：

- 用户只说“我是湖北物化生，想看看候选里计算机和数据科学方向多不多”，没有给分数/位次。
- 系统查询候选为空后，回复“按你当前的分数和筛选条件暂时没匹配到”，暗示已有分数参与判断。

本质问题：

- Plan query 没有把 `missingInfo`、`no candidate data`、`filter no result`、`score not enough` 区分成不同结果。
- 回复阶段缺少 grounding：不能把没有的前置条件写成原因。

3.2.0 设计要求：

- `EvidencePlan` 每个工具 step 必须声明 required inputs。
- 缺少分数/位次时，compiler 可以选择：
  - 只读已有候选，但 reply 必须说明“只基于现有候选”。
  - 或返回 clarification/missingInfo。
- `no_result_reason` 应结构化输出，禁止模型自行推断。

### 2.12 Full journey 回归资产需要显式 fixture 契约

现象：

- 2026-06-19 full journey 扩展回归 69 step 中 16 step 失败。
- 多数失败来自 case 假设当前 session 已有方案/候选/基础报考信息，但 runner 清理后实际为空。
- 系统对移动、删除、替换、补入空方案的请求返回 no-op/信息不足；case 却期待 ordered refresh。

本质问题：

- 回归 case 把“场景流程”和“会话前置数据”绑在隐含 session id 上。
- 清理策略、真实会话状态和断言预期没有统一契约。

3.2.0 前置要求：

- 稳定回归必须显式声明 fixture 类型：
  - empty plan
  - existing plan
  - existing candidate pool
  - accepted profile
  - pending exists
- runner 必须能 clone 或构造对应 backend state。
- case 断言要按 fixture 分叉：空方案下期待 no-op/clarification；有方案下才期待 pending/apply/refresh。

### 2.13 短确认不能承担新动作规划

现象：

- 用户先说“先看看少的这些怎么补，别急着直接改”，系统只读分析。
- 下一轮用户说“确认”，系统有时把它解释为生成方案 preview，而不是 no-pending guard 或对上一轮只读建议的澄清。

本质问题：

- 当前短确认语义依赖上一轮回复和内部 pending 状态，但没有统一决策：
  - 有 pending：apply pending。
  - 无 pending 且上一轮是只读建议：不能自动规划新动作。
  - 无 pending 但上一轮明确提出可执行选项：应要求用户选择具体动作，而不是直接生成。

3.2.0 设计要求：

- `apply_existing_pending` 必须只由实际 pending 状态触发。
- `confirm_without_pending` 是独立场景，只能：
  - 回复无待确认内容；
  - 或在上一轮有 explicit selectable option 时要求用户明确选项。
- 禁止“确认”触发新的 plan mutation preview，除非上一轮已经落了结构化 `pending` 或 `selectableProposal`。

### 2.14 review result rendering 缺少 focus binding

现象：

- 用户问“方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动”。
- 系统正确选择了 `review_plan` 取证，没有生成 pending，断言层面也通过。
- 最终回复却是通用审查结论：冲稳保、本省保底、概率倒挂等。
- 用户真正问的中外合作数量/占比、预算承受力、高收费是否影响保底安全没有被回答。
- 同类表达还包括“预算一般，是不是要少放中外合作”“高收费会不会影响保底安全”“优先专业还是学校，这版偏哪边”“能不能用大白话说下这版值不值得”。

本质问题：

- `review_plan` 目前只稳定产出整体审查事实，没有把用户的 `targetIssue`、`replyTone`、`comparisonAxis` 一起传递到最终回复生成。
- 模型看到 review result 后倾向总结“系统认为最重要的风险”，而不是回答“用户刚刚问的风险”。
- 这导致回归断言可能全过，但产品体验仍不收敛：用户觉得答非所问，系统却认为已经完成审查。

3.2.0 设计要求：

- `TurnDecision` 必须显式保留用户焦点：
  - `targetIssue`：如 `tuition/cooperative/safety/major_vs_school/readability`
  - `replyMode`：如 `colloquial / structured / brief / compare`
  - `scopeAnchor`：如 `current_plan`
- `review_plan` 只能作为 evidence step。它返回的全量风险要再被 `ReviewFocusBinder` 或 compiler 过滤/重排。
- Reply generator 的输入必须包含：
  - 用户原问题的 focus。
  - review evidence 中与 focus 相关的命中项。
  - 与 focus 无关但必须提醒的高风险项。
- 回复顺序应是“先回答用户焦点 -> 再补充必要系统风险”，不能反过来。

3.1.1 边界：

- 不为每个口语化 review prompt 增加字符串分支。
- 不新增 runtime shadow reviewer。
- 只把该类 case 纳入 3.2.0 profile，作为 focus 保真率指标。

### 2.15 sideEffect 决策与 directToolReturn/formatter 没有单一裁决层

现象：

- `我倾向会计学和审计学，但土木工程不要` 在部分 session 中直接生成 `plan_mutation/apply_fix_proposal` pending，把偏好采纳和当前方案替换绑在一起。
- `医学护理这些别碰，财会还能接受，先看看影响` 的 `intentSideEffectDecision` 明确判为 `mixed_answer_then_ask`，最终没有出卡，说明模型能识别“先看影响”。
- `我倾向法学和财政学，但护理不要` 在部分回归中内部 sideEffect 决策认为不应直接 pending，但最终 direct tool return 仍可能输出确认卡。
- `专业组里只保留最稳的专业行不行` 曾被误当成长期“稳定就业导向”意向；后续虽做了 3.1.1 窄修，但根因仍是缺少对象范围和 sideEffect 的统一裁决。

本质问题：

- 当前一轮对话中可能同时存在多个“候选裁决”：
  - 模型自然语言理解出的 `intentSideEffectDecision`。
  - intent preview 工具返回的 payload。
  - plan action 工具返回的 preview。
  - directToolReturn 认为可直接展示的卡片。
  - service 层后处理恢复逻辑。
- 这些候选对象没有统一进入一个 `SideEffectArbiter`，而是在不同 formatter 和 recovery 分支中被局部消费。
- 结果是：内部判断、工具事实、用户可见卡片、下一轮 pending 状态可能不一致。

3.2.0 设计要求：

- 每轮必须先形成一个唯一 `TurnSideEffect`：
  - `readonly`
  - `intent_pending`
  - `plan_preview`
  - `composite_pending`
  - `apply_existing_pending`
  - `clarification`
- 所有工具结果都只能作为 evidence 或 proposal candidate 输入 `ProposalCompiler`。
- `directToolReturn` 不应直接绕过 compiler 创建用户可确认对象；它只能表示“当前工具结果足以生成回复/候选 proposal”。
- formatter 不能自行升级 sideEffect。formatter 只能渲染 compiler 给出的唯一输出。
- 当 `intentSideEffectDecision` 与工具 candidate 冲突时：
  - 若用户明确只读/先看影响，所有高副作用 candidate 必须降为影响说明或询问。
  - 若用户明确当前方案动作，intent update 只能作为 composite proposal 的附带更新。
  - 若多个高副作用 candidate 都成立，返回澄清或展示一个 composite proposal，不能生成多张卡或丢 pending。

3.1.1 边界：

- 只修明确协议落点问题，例如“已有可执行 plan preview 未落 pending card”。
- 不在 service 层继续扩展“模型说了确认/采纳就恢复执行”的文本桥接。
- 不新增 intent 与 plan 双路径兼容。

### 2.16 偏好强度与历史状态合并缺少类型保护

现象：

- `把计算机类加到意向`、`把计算机类加进意向` 多次生成 `must_have/至少保留`。
- `加合工大和南邮到意项里` 后，用户说 `保底要公办不要民辨`，系统输出 `只保留院校：合肥工业大学、南京邮电大学；排除院校：民办院校`。

本质问题：

- 当前 intent schema 更像 positive/negative 集合，缺少 `preference strength` 和 `scope binding`。
- “加入意向”这种 soft preference 没有稳定容器，容易落到 `must_have`。
- 新一轮 hard negative constraint 与历史 positive preference 合并时，缺少“只更新本轮约束，不升级旧偏好”的类型保护。

3.2.0 设计要求：

- Intent state 必须保留：
  - `sourceTurn`
  - `strength`
  - `scopeAnchor`
  - `entityType`
  - `mergePolicy`
- `preferred`、`acceptable`、`must_have`、`only_keep`、`exclude_hard` 必须是不同结构，不应由 formatter 文案临时决定。
- 合并逻辑必须单调：本轮 negative constraint 不能把历史 positive preference 升级成 only_keep。

### 2.17 pending apply 不能吞掉同轮业务诉求

现象：

- 上一轮有 `intent_change` pending。
- 用户说 `现在基于这些出方案`。
- 系统只采纳 pending，未继续处理“出方案”。

本质问题：

- 当前 pending guard/state machine 把短确认和含确认意味的复杂句都压成 `apply_existing_pending`。
- 缺少 `apply_pending_then_new_request` 的复合 turn 表达。

3.2.0 设计要求：

- `TurnDecision` 必须解析确认部分和新请求部分：
  - `applyExistingPending=true`
  - `nextIntent=generate_plan`
  - `requiresNewPending=true`
- compiler 决定是否：
  - 先 apply pending 后生成 plan preview。
  - 先 apply pending 后要求用户确认是否继续生成方案。
  - 因 pending 与新请求冲突而澄清。
- 不允许靠自然语言“确认/基于这些”触发无 pending 的执行。

### 2.18 analysis/mixed 回复需要结构化 selectable transition

现象：

- 用户说 `想学软件工程`，系统做了适配分析，并自然提示“如果希望作为后续参考，可以...”
- 用户下一轮 `确认`，系统进入 no-pending。

本质问题：

- 回复文案暗示存在一个可确认动作，但系统状态里没有 pending 或 selectable option。
- 只有 pendingConfirmation 一种结构，不足以表达“这只是一个建议，是否要我整理成待采纳内容”。

3.2.0 设计要求：

- 增加轻量 `selectableProposal` 或 `suggestedTransition`，只用于低副作用的下一步选择。
- 短确认只能消费真实 pending 或 selectable option。
- 如果没有结构化对象，回复生成不得暗示“确认即可生效”。

### 2.19 plan action DSL 缺少锁定/局部范围/ordinal 表达

现象：

- `锁定第1个和第2个冲档，位置不要动` 被映射为 `move_ordered_unit/no_change`。
- `保底区里录取率最高的调到保底第一位` 容易把“第一位”理解成全方案第一位。

本质问题：

- 当前 action family 偏向移动、删除、补入、替换等常规动作。
- 缺少 `pin_or_lock_unit`、`preserve_position_constraint`、`tier-local ordinal` 等结构。
- 模型只要看到“位置/第一位”，就容易走最近似的 move action。

3.2.0 设计要求：

- Plan DSL 增加局部 scope 和 unsupported action 表达：
  - `scopeAnchor=current_plan.tier_segment`
  - `targetTier=保底`
  - `ordinalScope=within_tier`
  - `action=pin_or_lock_unit`
  - `unsupportedAction`
- compiler 不支持的 action 必须返回不可执行原因，不能自动改写成近似 action。

### 2.20 工具预算、批查询和重复工具治理必须前置到 ToolPlan

现象：

- `河南物化生464分，先看看郑州和洛阳的学校有没有合适的` 出现 24 次工具调用。
- `帮我规划一下两个批次怎么搭配` 出现 19 次工具调用。
- `985的计算机我够不够` 出现 11 次工具调用。
- `如果合工大没录上，下面接着的是什么，会不会断档` 出现 10 次 `query_score_line`。

本质问题：

- 模型按自然语言逐个查学校/专业/批次，缺少批量取证计划。
- 当前工具层没有统一预算，重复工具调用只有观测，没有阻断或合并。

3.2.0 设计要求：

- `EvidencePlan` 编译时必须声明：
  - expected tool count。
  - max tool budget。
  - batchable queries。
  - repeated tool policy。
- 对 score line/admission/candidate 类查询优先构造 batch request。
- 超预算时返回 partial evidence + 继续条件，不能无限追加模型-工具循环。

## 3. 之前为兜住问题做过的补丁式机制

这些机制大多是为快速止血而做，部分仍有价值，但不应继续扩展成主链路。

### 3.1 语义快路由和场景 guard

曾尝试通过小模型或结构化路由区分：

- 高置信只读分析。
- unavailable guidance。
- shortage boundary。
- targeted review。
- preview fix proposal。

价值：

- 能降低 full agent 长尾。
- 能避免部分重复工具调用。

问题：

- 如果 route 本身没有统一 `Scenario / PlanGoal` 层，很容易变成新的分支表。
- 一旦 guard 依赖过多局部 focus，就会出现“问风险却进入不可处理说明”“普通咨询被审查修复劫持”等问题。

### 3.2 字符串和泛化 marker

曾出现过针对用户话术、模型回复或系统文本的 marker 判断，例如是否包含某些确认、只读、不可用、风险、专业边界表达。

价值：

- 对最终回复协议保护有用，例如清理无依据的“确认后执行”“点击采纳”等承诺。

问题：

- 不能用于用户意图识别。
- 用户自然语言无法枚举，模型回复也无法稳定匹配。
- 容易以偏概全，把“能不能/算不算/不太想”等虚词误判成动作。

结论：

- 文本标记只能作为低风险输出保护，不应作为路由和动作规划依据。

### 3.3 审查后恢复预览

曾增加过类似后处理：

- 如果模型只返回 `review_plan`，但用户似乎想看处理预览，则再调用 `preview_fix_proposal`。
- 如果 `plan_next_action` 生成了 preview 但模型又错执行 broad review，则尝试恢复未执行预览。
- 如果 fix proposal 没有匹配 ready card，则尝试恢复成原子 `remove_units`。

价值：

- 能救回部分 bad case。
- 能避免 broad review 覆盖用户真正想要的调整。

问题：

- 这是“模型走错后补救”，不是主链路。
- 容易和只读解释、复合目标、原子动作抢路由。
- 如果继续扩展，会形成 review recovery、promise recovery、atomic recovery、composite recovery 多套并行机制。

### 3.4 intent preview 和 plan mutation 的混合恢复

曾处理过：

- 用户表达约束时，模型错误生成意向卡但没有调整方案。
- 用户表达方案动作时，模型错误写入偏好。
- 文本确认和卡片确认之间的状态不一致。

价值：

- 保证所有更新都要 pending 确认。
- 避免模型自然语言承诺直接生效。

问题：

- 如果 Intent 和 Plan 没有统一到 `CompositeProposal`，就会出现“意向写了，方案没动”或“方案动了，意向没写”的不一致。
- 2026-06-19 的 `exclude major` e2e 进一步说明：即使执行层已返回可执行 plan preview 和 intent update，pending 落点仍可能被混合路径压掉，导致“方案没动、意向也没写、短确认无效”。

### 3.5 Java repair proposal 和 Python agent 编排并存

当前 Java 侧已有：

- `FixProposal`
- `RepairCandidateSelector`
- dry-run
- apply policy
- `RepairReport`
- `UserGoalFixProposalReq`

Python 侧也有：

- `plan_next_action`
- `execute_plan_action`
- composite goal recovery
- fix preview recovery
- semantic action/recovery classifier

价值：

- Java 负责业务规则和 apply 安全。
- Python 负责对话理解和工具编排。

问题：

- 如果 Python 侧继续自行恢复成普通原子动作，就可能绕开 Java repair apply policy。
- Web 和 Agent 对同类修复的策略可能不一致。

## 4. 一致性终态设计

目标不是让模型自由执行，而是让模型动态生成结构化计划，再由系统编译、校验和执行。

统一链路：

```text
用户表达
  -> ScenarioDecision
  -> PlanGoal
  -> EvidencePlan
  -> CompositeProposal
  -> ProposalCompiler
  -> dry-run / preview
  -> pendingConfirmation
  -> apply
  -> validate / review
  -> 用户态回复
```

### 4.1 ScenarioDecision

职责：

- 判断当前是只读解释、政策咨询、意向更新、原子方案动作、复合方案调整、审查驱动调整还是澄清。
- 只决定“走哪类链路”，不决定最终执行细节。

示例：

| 用户表达 | ScenarioDecision |
| --- | --- |
| 高收费多吗，会不会影响保底 | `readonly_review_explanation` |
| 把太贵的那几个去掉看看 | `review_driven_mutation` |
| 只保留临床医学，其他不要 | `composite_plan_mutation` |
| 专业组里只保留最稳专业行不行 | `plan_local_policy_or_preview` |
| 分数刚压本科线别画大饼 | `policy_risk_explanation` |

### 4.2 PlanGoal

职责：

- 表达用户真正目标，而不是底层动作。

示例 goal：

- `only_keep_scope`
- `must_include_scope`
- `exclude_scope`
- `tuition_cap`
- `reduce_risk`
- `rebalance_structure`
- `local_group_safety`
- `mixed_adjustment`
- `readonly_explanation`

### 4.3 EvidencePlan

职责：

- 明确需要哪些事实才能继续。

常见 evidence：

- 当前方案命中项。
- 候选池可补项。
- 已确认偏好/要求。
- 推荐系数和排序指标。
- 审查 `reviewIssues`。
- 政策/招生章程检索结果。

关键原则：

- `review_plan` 是 evidence step，不是默认终点。
- 无 evidence 不生成可执行预览。
- 允许多个取证步骤，例如读取当前方案、定位命中项、查询候选、审查风险。
- 但只允许一个 proposal endpoint，避免同一回合同时生成 Intent card 和 Plan card。

### 4.4 CompositeProposal

职责：

- 把用户目标、证据、意向更新、方案动作、影响、取舍和校验计划放到一个可确认单元。

应包含：

- `goal`
- `sourceReviewIssue`
- `evidence`
- `intentUpdates`
- `planActions`
- `fromToPairs`
- `candidateSelectionReason`
- `tradeoffs`
- `feasibility`
- `validationPlan`

对于“排除当前方案命中项，同时写入后续报考参考”这类场景，`CompositeProposal` 必须显式同时包含 `intentUpdates` 和 `planActions`，并由同一张 pending 卡确认。确认后先写入报考参考，再按 version guard 执行方案动作和复审。

### 4.5 ProposalCompiler

职责：

- 把模型输出的目标和步骤编译成受控后端 proposal 或原子 preview。
- 过滤非法、缺参、不可执行、绕过 policy 的计划。

编译目标：

- 优先使用 Java `UserGoalFixProposalReq` / `FixProposal`。
- Web 和 Agent 共享 Java proposal/dry-run/apply policy。
- 只有非常明确的原子动作才走 `plan_next_action -> execute_plan_action`。

### 4.6 Apply 和 Validate

职责：

- apply 只消费 active pending。
- apply 后刷新方案和审查状态。
- `RepairReport` 或 mutation result 必须转成用户可理解结果。

## 5. 动态计划的可行性

可以让模型动态生成计划，但只能生成受控 DSL。

模型可以输出：

```json
{
  "scenario": "composite_plan_mutation",
  "goal": {
    "goal_type": "mixed_adjustment",
    "constraints": [
      {"type": "exclude_scope", "entity": "中外合作"},
      {"type": "tuition_cap", "max": 20000},
      {"type": "rebalance_structure", "target": "more_safety"}
    ]
  },
  "evidence_steps": [
    "read_current_plan",
    "read_confirmed_intents",
    "run_targeted_review",
    "query_replacement_candidates"
  ],
  "proposal_steps": [
    "build_replace_or_remove_preview",
    "validate_tier_ratio",
    "validate_intent_alignment"
  ]
}
```

系统必须限制：

- step 只能来自白名单 DSL。
- action 只能映射到已有 Java proposal 或受控原子动作。
- 模型不能直接生成最终 `volunteerIds` 当事实，除非来自工具返回。
- 是否可 apply 由 Java apply policy 决定。
- 高副作用动作必须 pending 确认。
- 候选选择、from/to、dry-run、post validation 必须由后端或受控工具产生。

## 6. 能实际解决的问题

### 6.1 走了审查就不继续

通过 `EvidencePlan` 把 `review_plan` 降级为取证步骤。审查结果中命中的 `high_tuition / cooperative_program / group_inner_safety_guard` 等 issue 会进入 `sourceReviewIssue`，后续再生成 proposal。

### 6.2 只读和动作混淆

通过 `ScenarioDecision` 区分：

- `readonly_review_explanation`：只解释，不生成卡。
- `review_driven_mutation`：审查取证后继续生成预览。

### 6.3 only_keep 等固定分支膨胀

把 `only_keep / must_have / exclude` 从特殊分支提升为 `PlanGoal.goal_type`。后续新增“大区”“预算”“体制内”“学校层次”等目标时，不再新增整套旁路，而是扩 DSL 和 compiler。

### 6.4 意向和方案联动不一致

通过 `CompositeProposal.intentUpdates + planActions` 把“写入报考参考”和“调整当前方案”放到同一张预览里。确认后先写 intent，再基于最新 version 重建 proposal 并 apply。

这也覆盖 Intent+Plan 混合回合：empty/non-pending intent preview 只能作为失败 evidence，不能压掉已可执行 plan preview；可执行 plan preview 中携带的 intent update 应并入同一个 `CompositeProposal`。

### 6.5 替换和补充信息不完整

通过 compiler 要求 proposal 必须返回：

- 被移出项。
- 补入项。
- from/to pair。
- 候选选择依据。
- 影响摘要。
- 复审结果。

缺任一关键字段时不能生成可确认替换卡。

### 6.6 指代对象和状态前置条件必须进入 plan compiler

历史 round1 暴露了一个反复出现的状态问题：用户说“刚那个方案”“现在这版方案”“当前方案”时，系统直接进入 intent 或 plan mutation，而没有先确认被引用对象是否存在。

典型样本：

- `tier-mid-520-just-want-bachelor`：没有正式方案时，`刚那个方案民办能少点不` 被转成排除民办 pending。
- `special-correction-630`：用户问 `现在方案是按620湖北算的吧`，系统被未采纳华科 pending 抢焦点，没有回答基础信息状态。

3.2.0 需要把 `referenceResolution` 放到 plan compiler 前置阶段：

- `current_plan`：存在正式方案，可以审查/编辑。
- `candidate_preview`：存在候选或预览，只能解释/确认，不能当正式方案编辑。
- `pending_proposal`：存在待确认 proposal，需要判断是否确认、取消、替换或只读查询。
- `no_referent`：无被引用对象，只能状态说明或澄清。

任何 plan mutation 都必须带上可解析的对象版本和来源。缺少引用对象时，不允许退化成长期 intent 写入，也不允许伪造方案状态。

### 6.7 pending 不是全局拦截器，需要单一 active proposal 和冲突决策

当前 pending 既会过度拦截只读查询，也会在长链路中残留并污染后续请求。

典型样本：

- `robust-resume-mid-conversation`：`现在基于这些出方案` 只采纳旧 intent pending，丢掉“出方案”。
- `special-correction-630`：只读事实查询被 pending 状态说明覆盖。
- `special-long-chain-12-turn`：旧 `generate_plan` pending 残留后，`冲档太冒险了删掉一个` 仍返回旧生成预览；`稳档想换成省内的` 同轮出现两个 pending。

3.2.0 的 pending 模型必须收敛为单一 active proposal：

- 新输入是确认/取消：处理 active proposal。
- 新输入是只读查询：允许读取状态并回答，同时提示 pending 未采纳。
- 新输入是兼容复合动作：显式 `apply_then_new_request`，生成新的 proposal。
- 新输入与旧 pending 冲突：要求用户选择替换/取消旧 pending，或系统明确取消旧 pending 后创建新 proposal。

同一轮不能返回多个可点击 pending；多路径工具结果只能并入一个 `CompositeProposal`，或降级为澄清。

### 6.8 review/explain/generate 三类 scenario 必须互斥

`special-strongbase-655` 中，用户问 `现在这版强基+普通批方案合理不`，系统同时执行审查和生成方案 pending。这说明当前链路会把“无正式方案/需要补齐”隐式推导为 generate mutation。

3.2.0 需要硬性区分：

- `review_current_plan`：只读审查已有方案；无方案时只说明无法审查。
- `generate_new_plan`：用户明确要求“出一版/生成/重来”。
- `repair_existing_plan`：用户明确要求对已有方案做删除、替换、补齐、重排。

`review_current_plan` 可以产生 evidence 和建议，但不能自动创建 `generate_plan` 或 repair pending。是否生成新方案必须来自用户明确 mutation 目标。

### 6.9 领域计算和政策回答需要 evidence guard

`special-art-580` 暴露艺术综合分计算公式和尺度不一致。类似问题还包括专项、强基、提前批、退档补录等政策解释。

这类回答应进入独立的 evidence guard：

- 有官方/结构化公式时，工具或 deterministic calculator 负责计算。
- 缺省份、年份、批次公式时，不给精确数值，只说明需要哪些信息。
- 模型可以解释概念和边界，但不能自由口算后输出确定结论。

这不是 3.1.1 的小补丁范围，但必须进入 3.2.0 profile。否则系统即使协议正确，也会在高风险政策/计算类场景给出不可靠答案。

## 7. 可能带来的副作用

### 7.1 计划层增加一次模型调用

风险：

- 增加延迟。
- 模型供应商长尾仍可能出现。

控制：

- 小模型只做结构化 `ScenarioDecision / PlanGoal`。
- 复杂回复仍由主模型整合，质量优先。
- 前端 thinking hint 展示取证、预览、复审进度。

### 7.2 动态计划不稳定

风险：

- 同一类问题输出不同 step。
- 生成系统不支持的步骤。

控制：

- DSL 白名单。
- compiler 校验。
- 不支持的 step 进入澄清或只读解释。
- shadow run 对比 fixed route。

### 7.3 误把只读问题变成调整

风险：

- 用户只是问影响，系统生成确认卡。

控制：

- `requiresPlanMutation` 是硬门禁。
- 没有明确 plan mutation 目标时，不能创建 pending。
- 只读路径不允许输出 `planActions`。

### 7.4 绕过 Java apply policy

风险：

- Python 根据审查 issue 自行生成普通 `remove_units/replace_units`，绕过 repair policy。

控制：

- 审查驱动复合目标优先进入 Java proposal engine。
- 原子动作只用于明确的当前方案编辑，如“删除第 8 个”“把 X 移到第 12 位”。
- preview-only/blocked repair 不允许翻译成普通 action apply。

### 7.5 测试复杂度上升

风险：

- 输出不再是固定 action，断言难。

控制：

- 测 DSL schema。
- 测 compiler output。
- 测 pending/apply 协议。
- 场景回归关注最终行为：有无卡、卡内容、from/to、是否刷新、是否误写状态。

## 8. 推进策略

以下推进策略面向 3.2.0 或更后续版本。3.1.1 只吸收其中的边界原则，不做 DSL、compiler 或主链路替换。

### 阶段 1：文档和观测统一

- 明确 `review_plan` 是 evidence step，不是复合调整终点。
- 将当前 bad case 按 `ScenarioDecision` 重新分类。
- 在回归报告中记录模型输出的 scenario/goal/action/pending。

### 阶段 2：Plan DSL shadow run

- 新增只读 shadow planner，不执行。
- 对比现有 fixed route 和模型动态计划。
- 重点覆盖：
  - only_keep / must_have / exclude。
  - 高收费/中外合作。
  - 专业组局部操作。
  - 预算和保底复合诉求。
  - 高层目标，如“更偏体制内”。

### 阶段 3：compiler 接入现有 Java proposal

- `source=user_goal` 继续承接 only_keep/must_have/exclude。
- 扩展支持 `sourceReviewIssue`，让审查驱动调整也进入 Java proposal。
- 补齐 from/to、候选选择依据和 post validation。

### 阶段 4：收敛旧恢复分支

逐步删除或降级：

- review 后 promised preview recovery。
- broad review refocus 中会抢只读路径的逻辑。
- mismatched plan_next / execute 后的局部补救。
- intent/plan 混合恢复中已经被 CompositeProposal 覆盖的分支。

保留：

- 最终回复协议保护。
- pending 版本和状态保护。
- 无 evidence 时不生成执行卡的保护。

### 阶段 5：回归和发布验收

必须覆盖：

- 3.0.3 真实对话衍生 88 case。
- 3.1.0 constraint plan action case。
- 3.1.0 review repair case。
- open quality。
- career direction。
- full journey。
- autoexplorer 生产风格 follow/diverge。
- 前端人工：确认卡、审查详情、修复预览、方案刷新、候选筛选。

## 9. 当前结论

动态计划可行，但只能作为结构化计划层，不能直接执行。

正确方向是：

```text
模型理解和拆解目标
  -> 系统校验和编译计划
  -> Java/受控工具生成预览和 dry-run
  -> pending 确认
  -> apply policy 执行
```

不应继续推进：

- 为单个用户话术加字符串匹配。
- 为某个审查 issue 单独加恢复分支。
- 在 Python 里绕过 Java proposal/apply policy 自行生成 repair mutation。
- 同时保留多套能创建确认卡的兼容路径。

3.2.0 的框架目标是把链路定义清楚：审查、普通复合目标、原子动作和意向更新都进入同一套计划、预览、确认和执行协议。这样后续新增目标时扩 DSL 和 compiler，而不是继续补旁路。

3.1.1 当前执行原则：

- 不引入新的动态 Plan DSL。
- 不替换现有 Java `FixProposal` / `UserGoalFixProposalReq` 主链路。
- 不新增大规模 `ScenarioDecision` 主路由。
- 继续在现有结构下修复明确 bad case：只读咨询不误触发卡片、审查结果不覆盖用户原问题、约束采纳后方案联动正确、确认卡状态和预览信息完整。
- 修补必须保持当前链路稳定一致，避免新增多套确认卡或执行旁路。

## 10. 2026-06-20 round2 新增结构约束

### 10.1 intent polarity 必须按 clause 绑定

`comprehensive-parent-doctor-conflict-620-gd` 和 `comprehensive-finance-to-cs-switch-605-js` 表明，同一句里同时出现“加意向/加”和“排除/去掉”时，当前链路会把负向极性扩散到正向实体。

3.2.0 需要把 intent extraction 输出为独立 operation：

```text
add_preference(生物医学工程)
add_preference(智能医学工程)
exclude(临床医学)
exclude(口腔医学)
```

compiler 只允许在 operation 局部绑定 polarity，禁止全句级 negative 传播。若模型输出与原文强动词近邻冲突，系统必须阻断或澄清，不能生成反向 pending。

### 10.2 PlanQuery 需要一等 DSL，不能只依赖泛化回复

`保底最后几个是什么学校 录取率多少` 这类请求已经包含明确 projection：范围、排序/切片、字段。3.2.0 应把它编译为只读 query：

```text
PlanQuery(scope=tier_segment("保底"), slice=tail(3..5), fields=[school, major, admissionProbability])
```

只要当前方案存在，就必须返回明细；不能读取状态后仍退回泛化澄清。PlanQuery 与 PlanMutation 必须互斥，查询不能创建确认卡。

### 10.3 pending apply 不是 turn 终点

`删完了再帮我看看还剩多少个 梯度有没有问题` 属于 `apply_existing_pending_then_readonly_query`。3.2.0 的 TurnDecision 至少要支持：

```text
apply_pending_only
apply_pending_then_readonly_query
apply_pending_then_new_mutation_request
new_request_conflicts_with_pending
```

apply 成功后的结果应成为后续只读查询的 evidence。当前做法只 apply 并刷新 workspace，会丢掉同轮后半句。

### 10.4 性能 profile 要拆分 agent、tool、runner/WS 三层

`comprehensive_r2` 显示两类长尾同时存在：

- 真实规划长尾：重复 `query_score_line` 46 次、`query_admission_score` 20 次，甚至触发 request limit。
- 流式/runner 收尾长尾：部分样本 `finalMessageMs` 显著大于 `agentRun.totalDurationMs`。

3.2.0 profile 和验收不能只看 dialogue runner 的 elapsed，需要拆：

```text
firstMessageMs
agentRun.totalDurationMs
toolCallCount / repeatedToolCount
toolInternalDurationMs
finalMessageMs
runnerOverheadMs
```

工具预算、batch query、重复工具 guard 解决第一类；runner/WS 统计和流式结束协议解决第二类。

## 11. 2026-06-20 三轮回归后的根因收敛

历史三轮最终结果显示，系统不是所有链路都失败，也不是单靠某个补丁能收敛。三轮总计 `2283` step、`2209` pass、`74` fail，主线、生命周期、robust、science、score tier、special 等集合断言全过，但 full journey/enriched 暴露出大量 fixture 契约和结构性边界问题。

这说明 3.2.0 的目标不是“再加一层兼容路由”，而是把当前多处能创建确认对象、能解释工具事实、能恢复 pending 的分支收敛到一个主控裁决层。

### 11.1 当前多路径来源

一轮对话中现在可能同时出现：

- 模型侧 `intentSideEffectDecision`。
- intent preview 工具返回的 `intent_change` payload。
- `plan_next_action -> execute_plan_action` 返回的 plan preview。
- review/repair Java proposal 返回的 fix proposal。
- directToolReturn 直接格式化的卡片。
- ChatService 后处理恢复分支。
- pending guard 对短确认/取消的拦截。

这些分支各自局部合理，但缺少统一仲裁后会出现：

- 可执行 plan preview 没有落 pending。
- intent empty preview 覆盖 plan preview。
- 只读查询被 pending 边界话术抢占。
- 同轮返回两个 pending。
- apply existing pending 后吞掉同轮后半句。
- 软偏好被编译成硬约束。
- 正负 polarity 在 clause 之间串扰。

### 11.2 3.2.0 必须形成单一 active sideEffect

每轮只能有一个 `TurnSideEffect`：

```text
readonly
intent_pending
plan_preview
composite_pending
apply_existing_pending
apply_pending_then_readonly_query
cancel_existing_pending
clarification
conflict_with_existing_pending
```

所有工具、formatter、proposal 和 pending 保存只能消费这个裁决结果。directToolReturn 不能绕过它创建卡片；ChatService 后处理也不能再独立恢复另一张卡。

### 11.3 compiler 比 prompt 更重要

模型负责理解和候选结构化，但 compiler 必须做以下确定性约束：

- positive/negative polarity 只能按 clause operation 绑定。
- soft preference 不能升级成 hard constraint，除非原文有强制词。
- negative-only constraint 不需要 positive scope。
- 当前方案 mutation 必须有 formal plan evidence 或明确可操作对象。
- review_plan 只能是 evidence step，不能自动推出 generate_plan 或 repair mutation。
- PlanQuery 与 PlanMutation 互斥，读取明细不能创建确认卡。
- pending 存在时，只读 query 允许执行；冲突性 mutation 必须先处理 pending。
- 同轮多个高副作用候选必须澄清或替换旧 pending，不能并存。

### 11.4 旧代码删除原则

3.2.0 合并时不能保留新旧并行创建 pending 的路径。需要删除或降级：

- intent direct card formatter 中能独立保存 pending 的分支。
- plan action recovery 中不经过 compiler 的 pending 保存。
- review 后 promised preview recovery 中会绕过 proposal endpoint 的逻辑。
- pending guard 中把所有非确认文本都压成 pending 边界说明的全局拦截。
- 基于最终自然语言“是否像确认文案”恢复执行的桥接。
- 只为旧 fixture 断言服务的 keyword/文案兼容。

保留：

- Java proposal/dry-run/apply policy 的执行保护。
- pending version/status 校验。
- 无 evidence 不生成执行卡的保护。
- provider 不可用、工具异常和 schema invalid 的安全兜底。

### 11.5 回归资产先修契约，再修业务

`full_journey` 三轮 47 个失败里，大部分来自隐含 session state 不成立。3.2.0 前要把 case 分成：

```text
empty_plan
formal_plan_present
candidate_pool_present
accepted_intent_present
pending_exists
generated_plan_preview_only
```

只有 fixture 契约满足时，才把移动、删除、替换、补入、refresh 失败归为业务缺陷。空方案下系统返回 no-op 或需要先生成方案，应该是正确防御行为，不能通过业务兼容去满足旧断言。

### 11.6 三轮后优先级

3.1.1：

- 继续只做窄修和文档收口。
- 不新增 shadow、bridge 或兼容路径。
- P0 小修完成后复跑 current gate 和关键历史集。

3.2.0 profile：

- 先跑模型理解、结构化计划、回复生成和 latency decomposition。
- 产出混淆矩阵和能力边界。

3.2.0 实现：

- 先实现 `TurnDecision` 与 `ProposalCompiler`。
- 再接 Java proposal/apply。
- 最后删除旧恢复分支和多路径 pending 创建逻辑。

验收：

- 每个高副作用回合都能解释唯一 sideEffect 和唯一 pending/apply 协议。
- 每个只读回合都能说明 evidence、projection 和为什么不会写状态。
- 每个 pending 上下文回合都能说明是 apply、cancel、readonly while pending 还是 conflict。
