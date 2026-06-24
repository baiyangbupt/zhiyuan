# Release 3.2.0 Structural Plan Framework Analysis

本文记录 3.1.1 对话回归中暴露出的 Plan 结构性框架问题，并作为 3.2.0 后续架构优化储备。3.1.1 不实施大框架切换，仍沿着当前 3.1.0/3.1.1 已有链路做小问题修补、回归验证和一致性保护；本文中的动态计划、统一 `ScenarioDecision / PlanGoal / CompositeProposal` 方案只作为后续版本设计方向。

3.2.0 不采用长期 shadow、双写或兼容桥接。主路径实现前必须先完成离线模型能力 profile，评估模型在场景理解、结构化计划和回复生成上的能力边界；profile 计划见 [release-3.2.0-model-capability-profile-plan.md](./release-3.2.0-model-capability-profile-plan.md)。profile 只作为 3.2.0 设计依据，不进入 3.1.1 runtime。后续允许增加短期只读 shadow 用于硬切前对比，但 shadow 不参与裁决、不创建 pending、不写业务状态、不改变用户响应。

3.2.0 的工程推进顺序、fixture 契约、benchmark 分层、runtime 硬切和旧路径删除口径见 [release-3.2.0-execution-roadmap.md](./release-3.2.0-execution-roadmap.md)。本文只记录问题根因和目标架构分析。

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

#### 2.6.1 文本确认承诺与真实 pending/card 脱钩

现象：

- 生产出现过“让加一个志愿到方案”，本轮没有弹 `pendingConfirmationCard`，但文本回复让用户确认操作。
- 实际状态没有生效，也没有 active pending；用户后来又追问一次，系统才弹卡。
- 同族问题还包括模型文本说“确认加入方案吗”“确认后会执行”“已为你整理好调整内容”，但当前轮没有可靠的 `plan_next_action/execute_plan_action` preview、Java `FixProposal`、intent preview payload 或 `CompiledProposal`。

本质问题：

- 这不是“文本场景要补弹卡”，而是“自然语言承诺”和“结构化可执行协议”断裂。
- 旧 service recovery 曾尝试从无工具文本、空 intent preview 或 classifier 结果反向补 pending/card；这会把模型一句不可靠的确认话术升级成业务状态。
- 一旦文本、pending store、前端卡片三者不一致，下一轮确认就会进入 no-pending guard，或通过另一条路径重新生成卡，形成多路径、不收敛的用户体验。

3.1.1/3.2.0 过渡处理：

- 无结构化候选的自然语言承诺恢复必须删除或阻断：不能从纯文本“确认加入/确认执行/准备采纳”反向创建 pending/card。
- 如果当前轮已经有结构化 preview payload，却没有同轮弹卡，这是 pending/card 挂载缺陷，必须修挂载链路，而不是靠文本 guard 掩盖。
- 如果当前轮没有结构化 preview payload，只能清理不安全确认话术，并明确回复“本轮没有生成可执行调整内容/不会改动方案”。
- 该类 case 必须进入回归：断言无 envelope/card、无 pending、无 recovery classifier 调用、历史中保存的是清理后的回复。

当前正确降级分两类：

- 方案动作文本承诺：如“确认加入方案吗/确认后删除/确认执行”，无结构化 preview 时只能返回“未生成可执行调整内容，当前方案不会改动”；不能补 pending/card。
- 报考参考文本承诺：如“如果你确认，我会把安徽作为后续避开的地域”，无 intent preview payload 时应保留用户目标实体，但清理“确认后写入”的承诺，并返回“未列出可采纳内容，未写入后续参考”；不能调用 intent recovery 补卡。
- 只读请求误生成 mutating preview：如“候选里还有没有更稳一点的会计审计，别直接加”却生成 add preview，必须移除本轮 preview 并补无改动边界；不能留下“预览已生成/会补入”的半截回复。

3.2.0 设计要求：

- `ProposalCompiler` 是唯一能把候选升级成 pending/card 的层。
- 回复生成只能渲染 compiler 输出的 `displayPayload/replyPlan`；不能自己承诺“确认后执行”。
- `pending_action` 前必须有 deterministic guard：没有 active pending 或 compiled selectable proposal 时，“确认”不能执行或创建新动作。

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
- 上一轮有 `plan_mutation` pending。
- 用户说 `删完了再看还剩多少，梯度还稳不稳`。
- 系统如果只执行 pending 并回复“需要后续检查”，用户仍拿不到本轮明确追问的只读结果；如果不先执行 pending 又直接回答，则会基于旧方案状态误答。

本质问题：

- 当前 pending guard/state machine 把短确认和含确认意味的复杂句都压成 `apply_existing_pending`。
- 缺少 active pending 复合 turn 表达：`apply_pending_then_new_request` 用于“先采纳已有 pending，再进入新的高副作用诉求/澄清”；`apply_pending_then_readonly` 用于“先执行已有 pending，再基于新状态做只读查询/审查”。
- `apply_pending_then_readonly` 的关键不是再跑一个 pending classifier，也不是从文本承诺反向补卡，而是把 `postApplyEvidencePlan` 作为执行后取证契约：apply 成功后刷新 workspace，用新状态回答数量、梯度、风险；刷新失败时才保留证据边界。

3.2.0 设计要求：

- `TurnDecision` 必须解析确认部分和新请求部分：
  - `applyExistingPending=true`
  - `nextIntent=generate_plan`
  - `requiresNewPending=true`
- 对只读 follow-up，`nextIntent` 应是 `readonly_query/review`，并带 `EvidencePlan.targetIssues`，例如 `remaining_count/tier_distribution/risk_review`。
- compiler 决定是否：
  - 先 apply pending 后生成 plan preview。
  - 先 apply pending 后要求用户确认是否继续生成方案。
  - 先 apply pending 后读取最新 workspace 并回答只读问题。
  - 因 pending 与新请求冲突而澄清。
- 不允许靠自然语言“确认/基于这些”触发无 pending 的执行。
- apply 失败、版本失效或刷新无证据时，不得追加“执行后还剩/风险已变”的结论。

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

结论：

- 修复类动作和修复提议必须进入统一提议/动作编排空间，否则 review/fix recovery 会继续成为 `intent/plan` 之外的第三条 pending 创建路径。
- 统一的不是“执行算法”，而是“对话层裁决和 pending 创建权”。Java `FixProposal`、dry-run、candidate shortage、replacementPairs 和 apply policy 仍是修复类方案变更的权威。
- Python Agent 只能把 review issue、用户目标和 downstream policy 编译成 `ProposalCandidate(type=java_fix_proposal_request|java_fix_proposal_reference|plan_action_candidate|intent_update_candidate)`，再由 compiler 统一决定是否生成 `CompiledProposal`。
- 如果 Java repair proposal 没有 ready action、缺候选、缺 version guard 或只有 rank-only/soft-avoid gap，compiler 必须输出 readonly/diagnostic/clarification，不能由 service 后处理恢复成普通原子动作。
- 因此 3.2.0 的 hard cut 不应继续保留 promised preview recovery、unmatched fix proposal fallback、atomic recovery 这类“修复失败后本地补动作”的业务路径。

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

PlanGoal 需要是一等 typed goal，而不是一个字符串标签。至少包含：

- `goalType`：如 `exclude_scope`、`only_keep_scope`、`must_include_scope`、`tuition_budget_scope`、`repair_review_issue`、`plan_local_reorder`、`apply_pending_then_readonly`、`readonly_explanation`。
- `targetLayer`：`future_reference`、`current_plan`、`review_issue`、`candidate_pool`、`pending_state`。
- `scopeAnchor`：例如 `current_plan.tier_segment`、`current_plan.major_group`、`future_reference.region`、`review.issue`。
- `priority`：`must`、`primary`、`preferred`、`acceptable`、`avoid_soft`，用于后续候选选择和替换保护。
- `conflictPolicy`：遇到 active pending、无正式方案、候选不足、目标互斥时是阻断、澄清、合并还是只读解释。

这样多类型场景不是靠增加更多 if/else，而是让 compiler 面对一组 typed goals 做合成和裁决。

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

修复类 proposal 也必须进入 `CompositeProposal` 空间：

- `sourceReviewIssue` 指向 Java review/repair issue。
- `repairProposalRef` 指向 Java `FixProposalDTO`、`proposalId`、`sourceVersionGuard` 和 dry-run observation。
- `planActions` 可以为空；如果需要方案变更，应引用 Java fix proposal action，而不是在 Agent 本地重新生成 replacementPairs。
- `intentUpdates` 可与修复 proposal 合并，例如“去掉高收费，同时以后也少推荐高收费”必须在同一张确认卡里表达方案调整和未来参考更新。
- `validationPlan` 必须包含 apply 后读取当前方案、复审风险、刷新工作台目标。

这保证修复提议、用户目标提议和原子方案动作最终只竞争同一个 pending slot。

### 4.4.1 多目标和动作编排规则

同一轮可以有多个目标，但只能有一个高副作用 compiled output。compiler 的合成顺序：

1. 先判定 state guard：无正式方案、active pending、缺分数/省份、provider unavailable、version guard 缺失。
2. 将用户表达拆成 typed goals：只读解释、未来偏好、当前方案动作、review issue 修复、pending apply、候选补位策略。
3. 将 goals 归一成 proposal candidates：intent update、Java user-goal request、Java fix proposal reference、plan action DSL、readonly evidence answer。
4. 按副作用和依赖排序：`apply_existing_pending` 优先于新 mutation；当前方案 mutation 依赖 formal plan；repair mutation 依赖 Java ready proposal；rank-only policy 不能生成 mutation。
5. 合并兼容目标：例如 `exclude_hard + future_reference` 可合并为 `intentUpdates + Java user-goal proposal`；`apply pending + readonly query` 可合并为 `apply_then_readonly`。
6. 阻断冲突目标：两个互斥 mutation、active pending 下的新 mutation、无 formal plan 的 current_plan mutation、Java ready-without-actions、候选不足但回复承诺替换。
7. 输出一个 `CompiledProposal`：pending/card、readonly、clarification 或 diagnostic；不能同时返回多张可点击 pending。

动作空间分三层，避免“统一”后变成 Agent 重写业务算法：

| 层 | 内容 | 权威 |
| --- | --- | --- |
| Goal space | 用户目标、偏好强度、目标层、范围、冲突策略 | TurnDecision/Profile |
| Proposal space | intent update、Java user-goal request、Java fix proposal reference、plan action DSL、readonly evidence | ProposalCompiler |
| Execution space | intent apply、Java fix proposal apply、受控 plan action apply、workspace refresh | 后端/Java apply policy/active pending guard |

修复类动作适合统一在 Proposal space，不适合统一到 Agent 本地 Execution space。这样既能解决多路径 pending/card 的问题，也不破坏 Java repair 的规则权威。

### 4.5 ProposalCompiler

职责：

- 把模型输出的目标和步骤编译成受控后端 proposal 或原子 preview。
- 过滤非法、缺参、不可执行、绕过 policy 的计划。

编译目标：

- 优先使用 Java `UserGoalFixProposalReq` / `FixProposal`。
- Web 和 Agent 共享 Java proposal/dry-run/apply policy。
- 只有非常明确的原子动作才走 `plan_next_action -> execute_plan_action`。
- 修复类 `FixProposal` 只能作为 `repairProposalRef` 或 `java_fix_proposal_candidate` 进入 compiler；pending 创建权在 compiler，不在 review formatter、promise recovery 或 service 后处理。
- 多个 proposal candidates 必须先进入 arbitration：能合并则生成一个 composite pending；不能合并则澄清或只读说明，不能按先后顺序分别出卡。

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
- 硬切前可用只读 shadow diff 对比 fixed route。

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

### 阶段 2：Plan DSL profile 和只读 shadow diff

- 新增离线 profile / fixture replay，先不进入 runtime。
- 硬切前可加只读 shadow diff：记录旧路径观测结果和 3.2.0 DSL/compiler output 差异。
- shadow diff 不能创建 pending、不能写 backend extra data、不能改变回复、不能触发 apply 或 workspace refresh。
- 对比现有 fixed route 的观测结果和 3.2.0 目标 DSL 输出。
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
- 已删除：`plan_next_action` 半桥接补执行、mismatched plan_next/execute 后局部补救、缺 scope 再调 `plan_next_action` 的补救。`plan_next_action` 只保留为结构化计划/缺参 evidence，不能在 service 后处理阶段补生成 `execute_plan_action` pending/card。
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

apply 成功后的结果应成为后续只读查询的 evidence；不能只 apply 并刷新 workspace 后丢掉同轮后半句。

2026-06-22 当前 runtime 已完成这条链路的最小收口：active pending 回合先由 `proposal_compiler.resolve_pending_turn_action` 识别 `reject_pending`、`ask_pending_impact`、`confirm_pending`、`apply_pending_then_readonly`、`apply_pending_then_new_request` 和 `conflict_with_existing_pending`。`ask_pending_impact` 保持 pending 不变并返回影响说明；`confirm_pending` 只覆盖短文本确定性协议；`apply_pending_then_readonly` 会先按现有 pending 校验并执行 apply，普通 plan apply 成功后读取最新 workspace，并基于刷新后的 `ordered/review` 状态回答剩余数量、冲稳保梯度和风险审查，刷新失败或字段缺失时才保留 evidence 边界；`apply_pending_then_new_request` 在 active intent pending 下会先采纳待采纳内容，再由 `proposal_compiler.compile_apply_then_generate_plan_source` 生成 `generate_plan` plan confirmation candidate，并通过统一 plan sink 创建新的“确认生成方案”卡，确认后才正式生成方案；`conflict_with_existing_pending` 会在已有 active pending 时阻断删除、加入、替换、只保留、排除、补齐、生成、重排等新高副作用诉求，不调用模型、不创建第二张卡、不覆盖旧 pending。该路径不调用模型或 pending classifier；apply 失败时只返回失败/失效结果，不追加只读结论。runtime 已删除 `classify_pending_confirmation_action` 调用，也删除了 service 本地 active pending direct-confirm 白名单；无 active pending 的短文本确认 guard 也迁入 `proposal_compiler.pending_turn_looks_no_active_pending_confirmation`。active pending 的采纳/取消只允许 compiler 确定性 resolution 或卡片确认触发。长文本重复目标、细化目标或新诉求不再自动 apply。剩余工作是把 intent_change 采纳后的独立影响评估节点，以及 pending merge/replace/放弃后重建接入完整 TurnDecision/EvidencePlan，而不是恢复 classifier 作为桥接实现。

2026-06-23 继续收紧 action-scoped 短确认：`确认生成/确认删除/确认移动/确认加入` 不再作为全局短语白名单直接 apply。compiler 只在 active pending 为 `plan_mutation` 时读取 pending state 的 `actionFamily` 或 `executionPayload.planPayload.action_family`，再判断用户短确认是否与当前 action family 同类。边界如下：

- 通用 `确认/确认执行/执行` 仍是 pending 协议确认。
- `确认生成方案` 只会确认当前 `generate_plan` pending；如果 active pending 是 `remove_units`，不会执行删除。
- active pending 为 `intent_change` 时，`确认生成` 不会采纳意向；它会回到模型判断或后续冲突/无 pending guard。
- 无 active pending 时，确认类短句仍进入 no-pending guard，不会反向制造 plan action。

这不是新增业务话术路由，而是把短确认解释权绑定到 active pending 的结构化元数据。后续新增 plan action 时，应扩展 action family 的确认语义表，并保持错配不 apply 的单测边界，不能把更多中文短句散落到 service 分支。

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

### 11.5 当前 runtime pending/card 入口清单

2026-06-21 结合代码读取，当前可创建或恢复 `pendingConfirmationCard` 的入口集中在 `zhiyuan-agent/app/service.py`。这些入口大多是 3.0.x/3.1.x 为具体问题止血形成的局部路径，3.2.0 硬切时必须收敛到 `CompiledProposal`。

| 入口 | 当前职责 | 风险 | 3.2.0 处理 |
| --- | --- | --- | --- |
| `_create_pending_intent_confirmation_response` | 保存 `pendingConfirmation(kind=intent_change)` 并返回卡片 | 只能作为 compiled intent sink；缺 `compiledProposalId` 会阻断 | 保留为落库/渲染 sink，调用者必须先通过 intent sink contract |
| `_create_pending_intent_confirmation_from_preview_payload` | 从 intent preview payload 构造 `_IntentPreviewCandidate`，再编译为 intent pending；constraint 命中 Java user-goal ready proposal 时转 plan mutation | sink 已 compiled-contract-first；风险转到仍调用该 helper 的结构化 recovery/candidate 来源 | 保留 candidate/compiled sink 适配；禁止无结构化候选的自然语言承诺恢复调用它补卡 |
| `_create_pending_plan_confirmation_response` | 从 plan confirmation candidate 保存普通 plan mutation pending | 工具 preview 与 service 抽取规则共同决定创建卡 | 改为消费 compiler 输出；原子动作必须带 `referenceResolution/scopeAnchor/versionGuard` |
| `_create_pending_fix_proposal_confirmation_response` | 从 Java `FixProposal` ready proposal 保存 `apply_fix_proposal` pending | Java proposal 权威是对的，但创建入口仍独立于 compiler | 保留 Java proposal/apply 权威，创建权移到 compiler；函数只做 compiled output 到 backend/card 的转换 |
| `_constraint_user_goal_fix_candidate_from_preview` / `_create_pending_fix_confirmation_from_user_goal_candidate` | constraint preview 构造 Java user-goal fix candidate，sink 已 compiled-contract-first | 调用源仍可能来自 legacy preview/recovery，需要继续删除不合规入口 | 保留 candidate/evidence 构造；fix pending 只允许 compiler output 调用 fix sink |
| `_structured_user_goal_fix_candidate_from_source` / `_structured_goal_intent_candidate_from_source` | structured goal 只拆成 user-goal fix candidate 或 intent candidate；candidate sink 已 compiled-contract-first | 调用源仍在 service 后处理内，后续必须变成 compiler candidate/evidence，不能恢复直接创建权 | 保留 candidate/evidence 构造；是否创建 pending 必须由 compiler 决定 |
| `_create_runtime_compiled_plan_pending` | 接收已生成的 compiled plan proposal，通过 plan sink contract 后调用低层 plan sink 创建 pending | 仍是 runtime 过渡入口，compiled proposal 目前由 `app/domain/proposal_compiler.py` 从 `execute_plan_action` preview candidate 构造，而不是完整 TurnDecision 输出 | 保留为短期 compiled entry；下一步把 TurnDecision 输入交给正式 ProposalCompiler |
| `_create_runtime_compiled_review_fix_pending` | 接收已生成的 compiled review/fix proposal，通过 fix sink contract 后调用低层 fix sink 创建 pending | Java proposal 权威保留；runtime compiled contract、deterministic fix proposal arbitration、target-scope 归一/过滤和 blocking reason 已抽出 service；模型 target-scope 调用本身仍在 service 主流程内 | 保留为短期 compiled entry；下一步把模型 target-scope 调用和 TurnDecision 输入交给 ProposalCompiler |
| 已删除：`_fetch_fix_proposal_confirmation_source` | 旧路径中，Agent 调了 `generate_planning_fix_proposals` 但没有结构化 preview 时，service 会再拉 Java proposal 并补卡 | 典型兼容桥：绕过 `execute_plan_action(preview_fix_proposal)` 与 compiler，直接把文本/旧工具输出升级成 pending | 已从 runtime 删除；Java proposal evidence 后续只能通过 compiler/adapter dry-run 接入，不从 service 缺卡补捞 |
| 主流程 `pending_intent_card` | 显式 intent preview、兴趣工具 confirmable payload 和 structured goal intent fallback 可进入 compiled intent sink | 独立的 `recovered_pending_intent_card` 旧变量路径已删除；剩余风险在调用源是否继续由 service recovery 决定创建业务 pending | 只允许结构化 candidate 进入 compiler；后续继续把 composite/interest fallback 调用源迁移到统一 candidate/proposal 编排 |
| `handle_pending_confirmation` | 卡片/短文本确认 apply active pending | 这是执行入口，不应删除 | 保留；只消费 compiler 生成的 active pending，继续做 pending id/status/version/一致性校验 |

受控 shadow 可以观测这些入口的旧路径结果与 `CompiledProposal` 的差异，但不能双写 pending，也不能让 shadow 输出改变当前回复。硬切后，每张 `pendingConfirmationCard` 必须能追溯到一个 `CompiledProposal`，否则视为旧路径残留。

2026-06-21 已把这张清单落成可执行静态审计：

- 工具：[runtime_pending_entrypoint_audit.py](../zhiyuan-agent/examples/runtime_pending_entrypoint_audit.py)。
- 入口 fixture：[runtime_pending_entrypoints_320.json](../zhiyuan-agent/examples/runtime_pending_entrypoints_320.json)。
- 期望：[runtime_pending_entrypoints_320_expectations.json](../zhiyuan-agent/examples/runtime_pending_entrypoints_320_expectations.json)。
- 报告：`/private/tmp/runtime_pending_entrypoint_audit_320_latest.json`，`passed=true`。

当前统计：

```text
total=8
missing=0
legacyRiskCount=0
deleteAfterCutCount=0
byKind:
  sink_keep=1
  compiler_sink_after_cut=4
  compiler_entry_after_cut=2
  execution_keep=1
```

审计口径：

- `compiler_sink_after_cut=4`：保留落库/渲染函数或 compiled adapter，但调用权必须限制为 compiler output。
- `compiler_entry_after_cut=2`：主流程 plan candidate 和 review/fix proposal 已迁到统一 runtime compiled pending 入口；该入口只消费已生成的 compiled proposal，并通过 sink contract 创建 pending/card。
- `delete_after_cut=0`：当前已无独立待删变量入口；无结构化候选的自然语言承诺恢复、只读误路由恢复、no-tool intent 恢复、composite goal recovery、预算/学费误路由 recovery 和主流程 `recovered_pending_intent_card` 变量路径已经删除。
- `execution_keep=1`：保留 `handle_pending_confirmation`，继续校验 active pending、status、version 和 apply policy。

这里的 `legacyRiskCount=0` 只说明 service 已没有分散的直接创建/恢复业务 pending/card 调用源。旧的 Java proposal 补捞函数、runtime fix proposal selector、纯文本承诺补卡和 plan recovery classifier 补执行链均已删除；主流程 plan/fix pending 创建已收口到 `_create_runtime_compiled_plan_pending` / `_create_runtime_compiled_review_fix_pending`。`_extract_plan_confirmation_candidate` 等候选抽取仍可保留为 evidence/candidate 解析，但不能直接越过 compiled entry 和 sink contract 创建 pending。

2026-06-21 进一步删除了 runtime `classify_plan_recovery_action -> plan_next_action -> execute_plan_action` 本地补执行链，并清理对应死代码。`classify_plan_recovery_action` 仍可作为 model-node benchmark/profile 的独立节点，用来衡量模型在误路由后的结构化恢复能力，但它不能再进入 service 运行时后处理、不能补调工具、不能创建 pending/card。

2026-06-21 已补 runtime hard-cut forbidden symbol 审计单测：[test_runtime_hard_cut_audit.py](../zhiyuan-agent/tests/unit/test_runtime_hard_cut_audit.py)。该测试把以下内容固定为 [service.py](../zhiyuan-agent/app/service.py) 禁止项：`classify_plan_recovery_action`、`classify_composite_goal_action`、旧 plan/fix pending wrapper、`recovered_pending_intent_card`、旧 plan recovery 死代码和旧 `select_fix_proposal_candidate` 调用。口径是约束 runtime，不删除 [plan_semantic_action_tool.py](../zhiyuan-agent/app/tools/plan_semantic_action_tool.py) 中用于模型节点 benchmark/profile 的工具函数。当前单测 2/2 通过。

2026-06-21 又补了一层 sink 调用点审计：

- 工具：[runtime_pending_sink_call_audit.py](../zhiyuan-agent/examples/runtime_pending_sink_call_audit.py)。
- 调用点 fixture：[runtime_pending_sink_calls_320.json](../zhiyuan-agent/examples/runtime_pending_sink_calls_320.json)。
- 期望：[runtime_pending_sink_calls_320_expectations.json](../zhiyuan-agent/examples/runtime_pending_sink_calls_320_expectations.json)。
- 报告：`/private/tmp/runtime_pending_sink_call_audit_320_latest.json`，`passed=true`。

当前统计：

```text
actual=15
legacyDirectCreateCount=0
compilerOnlySinkCallCount=9
compilerEntryCallCount=0
statusUpdateKeepCount=6
```

这层审计说明，当前风险不只是“有哪些函数能创建 pending”，还包括“哪些调用者还在直接调用这些 sink”。当前 `legacy_direct_create=0`，表示底层 intent/plan/fix pending sink 已全部要求 compiled output；9 个 `compiler_sink_call` 是已收紧为 compiled output 的落库/渲染调用，其中 plan/fix runtime entry 已直接消费 compiled proposal 后调用低层 sink；`compiler_entry_call=0` 表示旧 plan/fix 中层 wrapper 已删除；6 个 `status_update_keep` 属于 apply/cancel/expire/fail 状态更新，应保留并继续作为 pending guard 的一部分。

当前 sink 层迁移分组：

```text
legacy_direct_create: 0
compiled_runtime_plan_sink: 1
compiled_runtime_review_fix_sink: 1
```

注意：sink 层归零不等于完成 3.2.0 架构切换。当前只是把主流程 plan/fix 调用源收口到 `_create_runtime_compiled_plan_pending` / `_create_runtime_compiled_review_fix_pending`，删除旧 plan/fix wrapper，并把 runtime compiled proposal/contract、deterministic fix proposal arbitration、target-scope 归一/过滤和 blocking reason 抽到 [proposal_compiler.py](../zhiyuan-agent/app/domain/proposal_compiler.py)；agent 中断后的 plan pending recovery 已删除，只保留异常说明/只读 fallback 和 workspace refresh；无结构化候选的自然语言承诺恢复、只读误路由恢复、no-tool intent 恢复、composite goal recovery、预算/学费误路由 recovery、runtime plan recovery classifier 补执行链和主流程 `recovered_pending_intent_card` 变量路径也已删除。普通 plan candidate 也已新增 `resolve_plan_confirmation_candidate` / `compile_runtime_plan_confirmation_source`：action family、plan payload JSON、apply stage、requiresConfirmation、sourceVersionGuard 和 blocking reason 由 compiler 统一解析，plan sink 不再接受只有 `compiledProposalId + actionFamilies` 的旧形状，必须带 `plan_confirmation_candidate`。active pending 回合也已迁入 `resolve_pending_turn_action`：短确认、取消、只读影响查询、无 active pending 确认 guard、`apply_pending_then_readonly`、`apply_pending_then_new_request` 和新高副作用诉求冲突由 compiler 确定性输出；其中 `apply_pending_then_readonly` 现在会先执行已有 pending，并在普通 plan apply 成功后基于刷新 workspace 回答数量、梯度和风险；`apply_pending_then_new_request` 会先采纳 active intent pending，并创建新的 `generate_plan` plan pending card，确认后才正式生成方案；`conflict_with_existing_pending` 先保持旧 pending active 并阻断第二张卡。runtime pending semantic classifier 和 service 本地 active/no-active pending 确认白名单已删除。后续仍要把 intent_change 采纳后的独立影响评估、pending merge/replace/放弃后重建、模型 target-scope 调用本身和 TurnDecision 输入替换为正式 ProposalCompiler 输出，不能把 runtime entry 当长期兼容桥。

`proposal_compiler.select_fix_proposal_candidate_for_runtime` 现在统一返回 `FixProposalSelectionResult`，把 `selectedProposalId`、target scope 归一、唯一 ready 命中、target empty 和 blocking reason 收到一个对象里。`FixProposalTargetScopeResolution` 进一步把显式 result scope、selected id、无 ready proposal、是否需要 semantic decision 和 decision scope 归一收到 domain 层；`runtime_fix_proposal_confirmation_source_from_result` 把 `execute_plan_action(preview_fix_proposal)` tool call payload 与 result 是否可作为确认源的判断也收到 domain 层；`compile_runtime_review_fix_source` 将 selection、sourceVersionGuard、proposalSource 和 compiled review/fix proposal 统一产出。service 主流程只消费这些对象，不再重复展开 proposal 选择规则或自行拼装 compiled proposal，只在 domain 判定需要时调用 semantic classifier。`selectedProposalId` 命中缺失或不可 ready 时返回 `selected_fix_proposal_not_ready_or_missing`，不会 fallback 到其他 ready proposal；显式 target 空、target 无 ready、target 歧义、多 ready 无唯一目标、semantic decision precheck、confirmation source 过滤、`target_match_empty`、compiled source 成功和缺 version guard 阻断都已有领域层单测固定。

user-goal Java proposal 选择也已收口到 `proposal_compiler.select_user_goal_fix_proposal`。constraint preview 和 structured goal 不再各自从 Java 返回里按 goalType 展开 ready proposal 选择；缺 goalType 时阻断并保留 fallback proposal 用于解释或 intent fallback，不会退化为第一条 ready proposal。这里仍然只引用 Java `FixProposal` 的 ready/dry-run/action/version 事实，Agent 不复制 replacement pairs、候选替换或 apply policy。

intent pending 输入边界已收口到 `proposal_compiler.resolve_intent_select_input` / `resolve_intent_preview_input`。service 继续负责工具 payload 解析、merge 和展示文案，但 selected 非空、merged 非空、constraint scope 是否完整、constraintIntentType 归一由 compiler 规则统一裁决；direct select、intent preview 和 structured intent fallback 均走同一 resolution。展示层仍可扫描 preview `items[].value` 来生成“适当靠后/优先”等文案，但这不参与 pending 输入裁决。关键边界：`only_keep/must_have` 的原始意图如果没有正向 scope 必须阻断，不能降级成 exclude/default intent card；否则“只保留/至少保留”的误识别会把纯排除内容错误保存为可采纳条件。

2026-06-21 已新增并加硬 compiled pending sink contract：

- 工具：[compiled_pending_sink_contract.py](../zhiyuan-agent/examples/compiled_pending_sink_contract.py)。
- 样例：[compiled_pending_sink_contract_320_cases.json](../zhiyuan-agent/examples/compiled_pending_sink_contract_320_cases.json)。
- 当前本地门禁：7/7 通过。

该 contract 固定 hard cut 后 sink 的输入边界：

- intent sink 只接受 `pendingType=intent_change`、`executionPayload.kind=pending_intent_change` 和结构化 `intentPayload`。
- plan sink 只接受 `pendingType=plan_mutation`、`executionPayload.kind=pending_plan_mutation`、明确 action family 和 `proposalCandidates[].type=plan_confirmation_candidate`；candidate 内的 `planPayload.stage` 必须是 `apply`，不能仍要求 confirmation，且 action family 不能与 execution payload 冲突。
- fix proposal sink 只接受 `java_fix_proposal_reference`，并要求 `sourceVersionGuard`、actions 和 dry-run observation。
- readonly、缺 `compiledProposalId`、plan 缺 `plan_confirmation_candidate`、plan candidate 非 apply、Java fix 缺 actions/dry-run/version 都必须在进入 service sink 前阻断。

第一条低风险 runtime 入口选择 `handle_intent_select`，因为它只涉及 intent pending，不触碰 Java repair/replacement。2026-06-21 已新增离线 adapter：

- 工具：[intent_select_compiler_adapter.py](../zhiyuan-agent/examples/intent_select_compiler_adapter.py)。
- 样例：[intent_select_compiler_adapter_320_cases.json](../zhiyuan-agent/examples/intent_select_compiler_adapter_320_cases.json)。
- 报告：`/private/tmp/intent_select_compiler_adapter_320_latest.json`，4/4 通过。

adapter 验证 `selectedData -> CompiledProposal(intent_change) -> compiled sink request` 的协议链路，并覆盖空选择和 only_keep 无范围的阻断。runtime 已硬切：direct `selectedData` 分支始终先生成 compiled intent proposal 并做 sink contract 校验，再调用 `_create_pending_intent_confirmation_response`。pending state 顶层、`compilerSink` 和 `executionPayload` 会写入同一个 `compiledProposalId`。

2026-06-21 继续补了显式 intent preview follow-up 的离线 adapter，并把 `_create_pending_intent_confirmation_from_preview_payload` 收紧为 compiled-contract-first：

- 工具：[intent_preview_compiler_adapter.py](../zhiyuan-agent/examples/intent_preview_compiler_adapter.py)。
- 样例：[intent_preview_compiler_adapter_320_cases.json](../zhiyuan-agent/examples/intent_preview_compiler_adapter_320_cases.json)。

当前行为：

- preview payload 先解析为 `_IntentPreviewCandidate`，再生成 `CompiledProposal(intent_change)` 并通过 intent sink contract。
- constraint preview 如果 Java user-goal 返回 ready fix proposal，则进入 `CompiledProposal(java_fix_proposal_reference)`；ready 但缺 actions/dry-run/version guard 会阻断，不降级。
- Java user-goal 没有 ready proposal 时，fallback intent pending 也必须带 `intent-preview:` compiled id。
- 这不代表 recovery 创建权已经完成删除：无结构化候选的自然语言承诺恢复已经删除，但结构化 composite/interest fallback 和主流程后处理仍可能调用该 helper，因此下一步要继续删调用源，而不是再加兼容桥。

2026-06-21 constraint/structured user-goal candidate 已推进到 compiled-contract-first：

- `_create_pending_fix_confirmation_from_user_goal_candidate` 必须先构造 `CompiledProposal(java_fix_proposal_reference)` 并通过 fix sink contract，才允许调用底层 fix sink。
- Java proposal ready 但缺 `actions`、`sourceVersionGuard` 或 dry-run observation 时直接阻断 pending/card，不再降级成 intent card，也不由 Agent 补 replacementPairs。
- `_create_pending_intent_confirmation_from_structured_goal_candidate` 必须先构造 compiled intent proposal 并通过 intent sink contract，才允许调用底层 intent sink。
- 代码结构已拆成 `_UserGoalFixCandidate`、`_constraint_user_goal_fix_candidate_from_preview`、`_structured_user_goal_fix_candidate_from_source`、`_structured_goal_intent_candidate_from_source` 和两个 compiled candidate sink，并删除 `_maybe_create_plan_confirmation_from_constraint_preview`、`_maybe_create_plan_confirmation_from_structured_goal`、`_maybe_create_intent_confirmation_from_structured_goal` 旧混合 helper。

这一步仍没有复制 Java 候选选择、替换配对或 apply policy；它只是把已拆出的 candidate sink 从“直接落 pending”收紧为“compiled contract 通过后落 pending”。随后 review/fix proposal main/semantic 入口也已改成统一 runtime compiled entry，promised preview recovery、agent interruption plan recovery、legacy generate 补捞、runtime fix proposal selector、无结构化候选的自然语言承诺恢复、只读误路由恢复、no-tool intent 恢复、composite goal recovery 和预算/学费误路由 recovery 均已删除；plan candidate 落库也已改成统一 runtime compiled entry，删除旧 plan/fix wrapper，并把 runtime compiled proposal/contract、deterministic fix proposal arbitration、target-scope 纯归一逻辑抽到 `app/domain/proposal_compiler.py`。active pending 下的“先不确认，看看影响”已由 compiler 确定性解析为 `ask_pending_impact`，保持 pending active，不调用模型或 pending classifier；“删完了再看”这类复合句现在会先执行已有 pending，普通 plan apply 成功后读取刷新 workspace 并回答数量、梯度和风险，刷新失败才回到 evidence 边界；“现在基于这些出方案”会先采纳 active intent pending，并创建新的 `generate_plan` plan pending card；已有 pending 下的新高副作用诉求会被确定性阻断为 `conflict_with_existing_pending`，避免模型生成第二条 pending 或后处理 recovery 再清理；长文本重复 only_keep 目标不再自动采纳；否定确认词会阻断裸 `确认/执行` 误判。sink 审计因此保持 `legacyDirectCreateCount=0`、`compilerOnlySinkCallCount=9`、`compilerEntryCallCount=0`；entrypoint 审计保持 `legacyRiskCount=0`。剩余风险转到正式 ProposalCompiler 接入、模型 target-scope 调用上移、TurnDecision 输入替换、intent_change 采纳后的独立影响评估和 pending merge/replace 编排。

2026-06-22 增量：`needs_plan_first` 已先落 deterministic guard。用户显式引用“当前/刚才/方案里”的方案对象，且后端 planning summary 明确为无正式方案、无工作方案时，runtime 在模型前直接返回需要先生成方案的防御回复，不创建 intent pending、不写偏好、不改方案；后端状态未知时不触发该 guard，避免把读取失败当成无方案。该实现只覆盖 G19/G32 类 reference guard 的最小运行时防线，完整的 `referenceResolution=no_referent` 仍应进入 TurnDecision/ProposalCompiler schema，而不是长期停留在 service 前置判断。

2026-06-22 targeted 增量：G4/G23/G25 的阻塞点已经从“无 pending card/只 refresh/文本让用户确认但实际不生效”收口到统一 pending 协议。实现上没有恢复旧直写：显式 no-tool intent 兜底只能在无本轮工具调用、无 active pending、非只读、非 plan chain 时触发，且必须经过 `analyze_volunteer_intent_change` 和 compiled intent sink 创建 `pendingConfirmationCard`。G25 另一个实际根因是本地极性补偿：模型 `intentSideEffectDecision` 已正确输出 positive/negative span，但 `intent_state_tool` 把“加意向 排除”整句归到 negative，导致正向项被冲突清理删掉；现已按动作边界拆分并补“加意向”正向 marker。

当前先用 `dialog_regression_runner.py --runtime-shadow-output` 从真实回归导出旧路径 observation，再交给 `runtime_shadow_diff.py` 离线比较。该方式不接服务主链路，适合先覆盖 G1-G32 和历史重点 case；只有当本地固定回归不足以暴露差异时，才考虑短期开启服务内只读 shadow hook。

runner observation 的字段口径：

- `caseId` 必须显式映射到 profile case；多步 case 只能用 step 级 `profileCaseId/shadowCaseId`，避免确认轮误覆盖原始 G case。
- `pendingCards` 只记录 `kind/pendingId/actionFamily/targetView/executionPayload.kind`，不保存完整业务 payload。
- `workspaceRefreshTargets` 只记录目标视图，用于发现只读场景意外刷新或 apply 后缺刷新。
- `sideEffect/outputType/pendingType` 来自可见 card、direct pending confirm route、pending apply action/message code 和 pendingExists profile；不根据自然语言承诺猜 pending。
- 不能把 `review_plan/query_state/query_ordered/analyze_adjustment` 的 `applied=true` 当成 `apply_existing_pending`。这些工具里的 `applied` 表示工具已执行或快照已读取，不代表业务 pending 被采纳。

2026-06-21 r1 corrected shadow 结论：

- runner 层：52 step，49 successful，3 content failure；21 个 profile case 形成 runtime observation。
- corrected observation：`readonly=10`、`readonly_while_pending=4`、`intent_pending=5`、`plan_preview=2`；`apply_existing_pending=0`。这说明 raw 观测中的 apply 数量主要是只读工具 `applied=true` 的分类噪声，不应当作为业务 apply 结论。
- compiler diff：32 total、21 observed、9 clean、1 blocking、11 major、11 missing observation。
- 真实 blocking：G1 “不要英语相关专业，当前方案里有的话也删掉”旧路径做了 remove preview 并在文本承诺确认后删除，但没有 pending card。根因是文本生成和 pending 协议创建分离。
- 真实 major：
  - G8 软偏好/排除意图被升级为 plan mutation，根因是 intent candidate 与 plan proposal 没有统一 sideEffect 裁决。
  - G16 “锁定第1/2个冲档位置”被降级为 query_state，根因是缺 plan local action DSL 和 ordinal/tier scope。
  - G27 active pending 后的“删完了再看还剩多少/梯度”没有进入 apply pending then readonly query，根因是 pending state machine 只能处理短确认，不能表达复合回合。
  - G2/G7/G12/G17/G26/G31 主要是 `workspaceRefreshTargets`、diagnostic/conditional presentation 或 ordered/review refresh 缺失，根因是 workspace/display 输出不在 compiler 单点生成。
  - G19/G32 旧路径防御回复基本合理，但 compiler 将其细分为 `needs_plan_first`；3.2.0 需要在 TurnDecision taxonomy 中保留该语义，而不是靠兼容话术补齐。

因此 r1 后的根因定性更准确地收敛为：旧系统不是“到处都在乱 apply”，而是缺少唯一 compiler 导致文本、pending card、workspace refresh、display presentation 和 local action scope 各自为政。3.2.0 应硬切到单一 `TurnDecision -> ProposalCandidate -> CompiledProposal` 路径，不能继续在旧 formatter/service 里补桥接。

2026-06-21 r2/r3 shadow 复跑结论：

- r2：52 step，47 successful，5 content failure；diff 为 32 total、21 observed、9 clean、3 blocking、9 major、11 info。
- r3：52 step，49 successful，3 content failure；diff 同为 32 total、21 observed、9 clean、3 blocking、9 major、11 info。
- r2/r3 observation 稳定在 `readonly=10`、`readonly_while_pending=4`、`intent_pending=6`、`plan_preview=1`。这说明 shadow 权限没有扩大，也没有观测到业务 apply；差异来自旧 runtime 输出和 compiler 目标协议不一致。
- r2/r3 增加的 blocking 主要是 G17/G19。G17 表明 tier-local reorder 没有可执行 DSL，旧路径只能在 move/query/error/no_change 之间波动；G19 表明无正式方案引用没有先进入 `needs_plan_first`，会误创建“排除民办”意向 pending。
- 三轮 E2E 失败步数分别为 3/5/3，但 compiler diff 的 clean 始终只有 `9/32`。因此不能再用“断言失败少”作为系统收敛判断；必须看 sideEffect、pendingType、presentation、workspaceRefreshTargets 和 replyPlan 是否一致。

2026-06-22 targeted clean shadow 复跑结论：

- 命令必须同时清本地 history、后端 `pendingConfirmation/planEditCache` 和 planning intent；否则上一轮 pending 会被带入下一轮，active pending guard 会返回 `conflict_with_existing_pending` 假失败。
- clean run `/private/tmp/runtime_shadow_320_blocking_probe_after_polarity_fix_clean.json` 只覆盖 G4/G23/G25，3 个 observation 均为 `intent_pending` + `intent_change` + `confirmation_card`；diff `/private/tmp/runtime_shadow_diff_320_blocking_probe_after_polarity_fix_clean.json` 在 observed case 上 `clean=3`，无 blocking/major/minor。
- G25 clean 输出为“偏好专业：生物医学工程、智能医学工程；排除专业：临床医学、口腔医学”，说明极性绑定问题已从 runtime targeted 层修复；同时已收紧 G25 case 断言，后续只弹卡但极性错不再算通过。
- G4 clean 输出保留 primary/acceptable 两个实体，但耗时 `173176ms`，这不是协议问题而是 intent preview 工具内部/模型链路长尾，必须进入 EvidencePlan/tool budget/latency decomposition，而不是在 service 里继续加补救路径。

2026-06-22 post-targeted full clean shadow R1 复跑结论：

- 完整 G1-G32 e2e shadow 子集用同样 clean 参数重跑，报告 `/private/tmp/dialog_regression_320_g1_g32_clean_full_r1_metrics.json` 为 52 step、47 successful、5 content failure；runtime observation 21 条，diff `/private/tmp/runtime_shadow_diff_320_g1_g32_clean_full_r1.json` 为 32 total、21 observed、8 clean、3 blocking、10 major、11 info，cleanRate `0.25`。
- 这轮更准确地说明：targeted clean 只证明 G4/G23/G25 的小集合路径可以被补丁覆盖，不代表 full runtime 平均态稳定。G25 在完整多步 case 中仍把“加意向”的生物医学工程/智能医学工程写入 negative；G23 仍把“城市优先长三角”的“城市”误抽为“城市管理”，且把“优先”升级为 only_keep；G4/G29 仍没有稳定表达 primary/acceptable 的下游语义。
- 三个 blocking 分别是 G17 缺 tier-local reorder pending、G19 无方案引用误创建 intent pending、G30 同轮多 pending。G27 虽不在 blocking 计数里，但仍是 major：active pending 下“删完了再看数量/梯度”没有先 apply，也没有 post-apply evidence/workspace refresh。
- 这轮额外确认两个协议级问题：第一，文本可以要求用户“确认采纳院校意向”但没有真实 pending/card（G31），这和生产“文本确认但没有弹卡/未生效”同类；第二，special admission path 仍会把学校+强基路径退化为数学类/物理学类，甚至同时触发 generate_plan。
- 因此后续不再把“补 no-tool 兜底/文本清理/局部 marker”作为主路径。G23/G25/G30 必须回到 `intent_entity_extraction -> TurnDecision -> ProposalCompiler -> displayPayload/replyPlan` 的硬切链路；service 层只允许保留已验证的前置 guard 和 compiler sink，不继续增加 shadow 或兼容桥。

三轮稳定根因矩阵：

| 类别 | 代表 case | 三轮表现 | 根因 |
| --- | --- | --- | --- |
| pending 协议断裂 | G1 | 三轮稳定缺 pending card | plan preview、自然语言承诺、pending card 创建不在同一个 compiler |
| pending 复合回合 | G14/G27 | G27 三轮不能 apply 后继续 readonly/review，G14 曾只采纳 pending 丢掉“出方案”；当前 G27 已补到 plan apply 后刷新 workspace 回答数量/梯度/风险，G14 已补到先采纳 intent pending 并创建新的 `generate_plan` pending card | 剩余是 intent_change 采纳后的独立影响评估，以及 pending merge/replace 编排 |
| 无方案引用 | G19/G32 | G19 r2/r3 误出 intent pending；当前已补明确无方案前置 guard | `needs_plan_first` 已有最小 runtime 防线，但一等 sideEffect 和 reference resolution 仍需进入 TurnDecision/ProposalCompiler |
| 局部方案动作 | G16/G17 | 结果在 query/move/no_change/error 间波动 | action DSL 缺 pin/lock、tier-local ordinal、unsupported action |
| 偏好强度 | G4/G29/G32 | “优先/也可考虑/加意向”常被压成 `must_have`；当前 G4 targeted clean 已出 intent pending 并保留两个实体 | intent schema 缺 `primary/acceptable/preferred/must_have` 类型保护；runtime 仍需把 strength 交给 compiler/downstream policy，不在 service 猜 |
| 极性绑定 | G25 | targeted clean 曾修正为正负混合 pending，但 full clean R1 在完整多步场景中仍把“加意向”的 A/B 写入 negative | 不是单纯模型理解问题，而是模型 span、工具本地补偿、历史上下文和冲突清理之间缺统一极性事实源 |
| 特殊路径 | G21/G30 | 学校实体能保留，但“强基”未进 payload | school intent 与 admission path 分离缺失 |
| reply focus | G2/G7/G12/G26/G31 | 可答一部分，但 focus/presentation/refresh 不稳 | review/query evidence 没有统一 replyPlan 和 workspaceRefreshTargets |
| 性能长尾 | G21/G22/G26/G30 | 多轮 p95/max 集中 | ToolPlan 缺预算、批查询和重复工具治理 |

三轮后的定性：

- 问题根源不是“模型完全不能用”，也不是“旧系统到处误 apply”。模型在 G23、G32、G10 等场景能给出可用判断；旧路径多数也能保持只读不写。
- 真正无法收敛的是“模型判断、工具事实、pending 协议、workspace 展示和最终回复”缺少同一个结构化事实源。
- 继续做 3.1.x 式桥接会让系统形成更多入口：intent card、plan card、review recovery、promise recovery、pending guard、formatter 升级各自补洞，最终更难验证。
- 3.2.0 必须把模型能力降到“给 TurnDecision/selector/candidate”，把高副作用协议、展示和刷新交给 deterministic compiler。
- 业务内 shadow hook 不是下一步重点。已有 runner shadow 三轮足够支撑设计；只有固定回归覆盖不足时才允许短期开启只读 hook，并且必须默认关闭、不创建 pending、不写后端、不触发 apply/refresh、不改变响应。

2026-06-21 离线 compiler 已补上的协议承载：

- `evidenceContract`：把 required inputs、evidence steps、tool budget、noResultReason 放进 compiled output，为 G21/G22/G26/G30 的工具预算和重复查分治理提供入口。
- `planActionDsl`：支持 G16/G17 需要的 `pin_or_lock_unit`、`scopeAnchor=current_plan.tier_segment`、`targetTier`、`ordinalScope=within_tier`、`selector`、`targetPosition`。
- `entityPolaritySpans`：支持 G25 的 clause-bound polarity，不再只靠 positive/negative 集合推断。
- `preferenceScope`：支持 G18 这类“保底区排除民办但不升级历史学校偏好”的范围绑定。
- `admissionPath`：支持 G30/G21 的强基路径，不再退化为普通 school intent。
- `downstreamPolicy`：把偏好强度编译成候选选择和替换策略，避免下游继续猜“优先/可以考虑/不要”到底怎么影响补位。

这些字段目前只在离线 compiler/profile 层生效，不改变 runtime。下一步是把 live-node adapter 输出对齐到这些字段，再通过 fixture replay 验证，最后才接入 pending/card 创建路径。

`downstreamPolicy` 的关键约束：

- `exclude_hard` 和 `only_keep` 是 candidate/rank 前的硬约束或替换优先级，不能被 rank boost 抵消。
- `must_have` 是覆盖要求，不等于 only keep，不能把其它非冲突项清空。
- `primary/preferred/acceptable` 只影响排序、补位和替换优先级；其中 `acceptable` 是兜底，不应抢占 primary/preferred，也不应被当作可随意替换的弱项。
- `avoid_soft` 只能降权或提示风险，不能静默变成 hard exclude；否则“预算一般/不太想高收费”会被误处理成强删除。
- 预算/学费这类数值约束必须有明确 cap 和不可满足说明，不能只靠“高收费”标签猜测。
- `preferenceScope` 必须随策略进入下游，例如“保底要公办不要民办”只影响保底区。
- `admissionPath` 必须随路径实体进入下游，例如强基学校意向不能混成普通批学校偏好。
- 容量不足和 no-result 必须作为结构化诊断输出，不能让 rank/replacement 静默返回空列表后由回复模型补话术。

最新离线报告 `/private/tmp/proposal_compiler_320_g1_g32_downstream_policy_latest.json` 为 32/32 通过、`blockingReasons={}`。这只证明策略契约可编译，不代表 Java candidate/rank/replacement 已接入。

2026-06-21 已新增并扩展 downstream policy fixture replay：

- 工具：[downstream_policy_replay.py](../zhiyuan-agent/examples/downstream_policy_replay.py)。
- 样例：[downstream_policy_replay_320_cases.json](../zhiyuan-agent/examples/downstream_policy_replay_320_cases.json)。
- 报告：`/private/tmp/downstream_policy_replay_320_latest.json`，9/9 通过。

replay 结果说明：

- G4 中 primary 可以压过更高 baseScore 的 acceptable，acceptable 仍保留为兜底。
- G18 中 `preferenceScope=保底` 阻止“不要民办”污染稳档；保底民办进入 replace-first，历史 preferred 公办学校被保护。
- G25 中 positive/negative span 同时影响选取和替换：negative 医学方向先排除，positive 工程方向优先补位并保护。
- G30 中强基路径过滤普通批同校候选，说明 `admissionPath` 不是学校名的附属文本。
- replay-only inline policy 已覆盖 `only_keep`、`mustCover`、`avoid_soft`、预算/学费上限、容量不足和 no-result。inline policy 只用于补齐下游语义边界，不要求 G1-G32 golden 反向改造。
- 最新 replay summary：`capacityStatuses={satisfied:4, insufficient_candidates:4, no_result:1}`，`missingMustCoverCount=1`。这说明 replay 已能把“策略正确但候选不足/覆盖不足”从普通失败里拆出来。

这仍是离线 replay，不调用 Java/rank/replacement。下一步是把 candidate/rank/replacement adapter 的只读 dry-run 输出对齐这些字段；如果真实服务无法返回 `capacityStatus/noResultReason/missingMustCover`，就应记录为 adapter/contract gap，而不是让回复模型临时解释。

2026-06-21 已新增 downstream adapter dry-run：

- 工具：[downstream_adapter_dry_run.py](../zhiyuan-agent/examples/downstream_adapter_dry_run.py)。
- 样例：[downstream_adapter_dry_run_320_cases.json](../zhiyuan-agent/examples/downstream_adapter_dry_run_320_cases.json)。
- 报告：`/private/tmp/downstream_adapter_dry_run_320_latest.json`，5/5 通过。

adapter 结果说明：

- Java `FixProposalDTO` 的 `actions/replacementPairs/dryRunResult/candidateShortages` 已能归一到 3.2.0 下游观测字段。
- ready replacement 可以输出 `capacityStatus=satisfied`、replacement from/to 和候选补入项。
- blocked shortage 可以输出 `capacityStatus=no_result` 和具体 `noResultReason`。
- `must_include_scope` 可以归一到 `mustCoverSatisfied/missingMustCover`。
- ready 但没有 action 的响应会被标记为 `contractGaps.ready_without_actions`，不能被 formatter 当成可执行处理预览。

因此 3.2.0 下游接入的原则更明确：Java proposal/dry-run/apply 仍是方案变更权威；Agent 不复制候选选择、替换配对或 apply policy。Agent 只把 `downstreamPolicy` 编译成 Java 可理解的 taxonomy/request，并把 Java 只读 dry-run 归一成可回归观测。

2026-06-21 已新增 downstreamPolicy -> Java user-goal request mapper：

- 工具：[downstream_policy_java_request.py](../zhiyuan-agent/examples/downstream_policy_java_request.py)。
- 样例：[downstream_policy_java_request_320_cases.json](../zhiyuan-agent/examples/downstream_policy_java_request_320_cases.json)。
- 报告：`/private/tmp/downstream_policy_java_request_320_latest.json`，7/7 通过，`requestReady=5`、`requestNotReady=2`。

mapper 结果说明：

- `only_keep`、`mustCover/must_have`、`exclude_hard`、`tuition_cap` 分别可进入 Java `only_keep_scope`、`must_include_scope`、`exclude_scope`、`tuition_budget_scope`。
- `primary/preferred/acceptable` 是排序/补位偏好，不是方案变更请求；纯软偏好不能生成 pending。
- 纯 `avoid_soft` 是降权或提示风险，不是删除/替换请求。
- `admissionPath=strongbase` 暂可转成 Java `program_type` scope 做只读 dry-run，但报告必须保留 `program_type_text_match_only`，因为这还不是稳定的一等特殊路径协议。

这一步把 3.2.0 下游边界进一步收紧：只有 `requestReady=true` 的策略才允许进入 Java proposal 预览；有 `rank_only_policy/soft_avoid_rank_only/program_type_text_match_only` 的策略必须先停在只读 adapter/profile 层，不能为了“看起来能处理”而在 runtime service 中补桥。

2026-06-21 已新增 downstream contract gate：

- 工具：[downstream_contract_gate.py](../zhiyuan-agent/examples/downstream_contract_gate.py)。
- 报告：`/private/tmp/downstream_contract_gate_320_latest.json`，`gatePassed=true`。
- 组件结果：policy replay `9/9`，Java request mapper `7/7`，adapter dry-run `5/5`。

gate 当前暴露的预期缺口：

- `rank_only_policy:primary,acceptable`：偏好强度对 rank/补位有效，但不能直接进入 Java mutation request。
- `soft_avoid_rank_only`：软避让只能降权或提醒，不能直接删除/替换。
- `program_type_text_match_only`：强基等路径暂靠 program_type 文本匹配，仍缺一等 admissionPath 协议。
- `ready_without_actions`：Java 响应若 ready 但没有 action，必须作为 contract gap 阻断 formatter 承诺。

gate 的结论不是“下游已经接完 runtime”，而是把接入边界固定住：策略语义、Java request 映射、Java dry-run 观测都已有离线门禁；runtime 只能按这些门禁硬切，不能再新增 shadow 旁路、兼容桥或 Agent 本地候选选择。

2026-06-21 节点 benchmark 已把 G4/G13/G18/G23/G25/G29/G30 的断言升级到 3.2.0 profile 字段：

- `rawActual` 保留旧节点原始输出，`profileActual` 只做安全归一。
- `schemaGaps` 统计 live-node 缺失的新字段，不用 legacy `constraintIntentType` 桥接通过。
- `legacyOnlyFields` 统计“旧字段存在但新字段缺失”的阻塞项，例如只有 `constraintIntentType` 不能满足 `preferenceStrength.primary/acceptable`。
- `contains` 支持对象数组子集匹配，用于验证 `entityPolaritySpans` 的 span 级 polarity。
- 离线目标基线 `/private/tmp/model_node_320_profile_schema_latest.json` 为 33/33 通过、`schemaGaps={}`；这证明目标协议完整，不证明 runtime 已支持。

这进一步收窄了问题定性：3.2.0 不是把旧 `constraintIntentType` 提示词再调细，而是要删除“一个粗字段决定软/硬偏好”的协议前提，让模型输出 entity/span/strength/path，再由 compiler 决定是否能形成 pending、如何展示、确认后刷新哪里。

2026-06-22 网络恢复后重跑 schema 相关 live-node adapter，进一步把问题拆清：

- 修前 3 轮 `/private/tmp/model_node_320_live_intent_schema_r3_before_prompt_fix.json` 为 24 case、6 通过、18 失败；失败不是 provider/env，而是新 schema 输出本身不稳定。
- 主要根因是 `intent_side_effect` 虽能理解 primary/acceptable/preferred/exclude_hard，但把 `preferenceStrength` 输出成“实体 -> 强度列表”的反向结构；G18 还会丢失 `structuredIntents` 中已经抽取出的正向院校，只保留公办/民办抽象类型。
- 这类问题不能通过 runtime service 桥接 `constraintIntentType` 解决；正确处理是把 live-node 输出契约钉死为 3.2.0 schema，并让 benchmark 继续把不合规输出计为 `schemaGaps/legacyOnlyFields`。
- 修后 3 轮 `/private/tmp/model_node_320_live_intent_schema_after_optional_path_fix_r3.json` 为 24/24 通过，`schemaGaps={}`、`legacyOnlyFields={}`、stablePassRate `1.0`。对应离线 `model-node` 33/33 和 `proposal_compiler` 32/32 仍通过。

这说明 `preferenceStrength/entityPolaritySpans/admissionPath` 可以先在模型节点层收敛，再交给 compiler；不需要也不应该在 service/formatter 层增加新旧字段兼容桥。随后 `turn_side_effect` 也按同一原则接入 live-node adapter：初始单轮 `/private/tmp/model_node_320_live_turn_decision_r1.json` 为 13 case、1 通过、12 失败，问题集中在 `scenario` 输出不是枚举、`pendingExists/formalPlanPresent` 未作为权威输入、候选池/专业组 taskLayer 边界和 JSON 输出格式。收紧 `turn_decision_tool` 的 allowedValues、状态权威规则、典型边界例子和单 JSON object 后，三轮 `/private/tmp/model_node_320_live_turn_decision_after_prompt_fix3_r3.json` 为 39/39 通过、stablePassRate `1.0`、`schemaGaps={}`、`legacyOnlyFields={}`、latency median `4392ms`、p95 `9567ms`、max `9993ms`。

这次更准确的定性是：TurnDecision 能通过 schema/prompt 收敛，但前提是让模型只做结构化分类，不让 service/formatter 在后面根据自然语言回复、旧字段或 pending 恢复路径补裁决。随后 `reply_focus_binding` 和 `reply_generation_grounding` 也接入 benchmark-facing `reply_profile_tool`，三轮 `/private/tmp/model_node_320_live_reply_profile_r3.json` 为 6/6 通过、stablePassRate `1.0`、`schemaGaps={}`、`legacyOnlyFields={}`；G7 能稳定绑定 `cooperative_program/tuition_budget` 和 `readonly_no_apply`，G20 能稳定识别缺省份/艺考公式并禁止精确分数编造。

旧 adapter 的缺口也按同一原则收敛：`pending_action` 增加 no-active-pending 硬门禁；`plan_semantic_action` 在只读 `none` 中保留 reply focus；`plan_recovery_action` 增加 `unsupportedAction=pin_or_lock_unit` 和 tier-local ordered move；`intent_side_effect` 固定 `primary/preferred/acceptable` 边界并保留 structured positiveSchools。单轮全量 `/private/tmp/model_node_320_live_supported_all_after_g24_fix_r1.json` 为 30/30；全量三轮 `/private/tmp/model_node_320_live_supported_all_after_g18_fix_r3.json` 为 89/90，唯一 G8 `taskLayer` 漂移已通过后续 TurnDecision 三轮 `/private/tmp/model_node_320_live_turn_decision_after_g8_intent_layer_fix_r3.json` 的 39/39 验证修复。

2026-06-22 最终全量复跑又暴露两个平均态问题，并按节点边界修正：G18 偶发把“保底要公办不要民办”降级为 `mixed_answer_then_ask`，修正为可直接 `intent_preview` 但禁止升级 `only_keep=公办`；G16 偶发把 optional list/bool 字段输出成 `null`，修正为 `PlanRecoveryActionDecision` schema 边界规范化空集合和布尔默认值，不补造缺失核心字段。最终全量 `/private/tmp/model_node_320_live_supported_all_after_plan_recovery_null_coerce_final_r3.json` 为 90/90，stablePassRate `1.0`，`fieldFailures={}`、`schemaGaps={}`、`legacyOnlyFields={}`。

剩余重点不再是证明这些节点“能不能输出字段”，而是把已验证的 TurnDecision、intent profile、reply profile 输出交给 ProposalCompiler/replyPlan/displayPayload contract 做 hard-cut 前验证，并确保 runtime 回复只渲染 compiler evidence，不再自行承诺 pending 或补动作。

### 11.6 after G27 refresh fix 的新定性

2026-06-22 after G27 refresh fix full clean shadow 结果：

- e2e runner：`/private/tmp/dialog_regression_320_g1_g32_after_g27_refresh_fix_metrics.json`，52 step、52 successful、0 content failure。
- runtime observation：21 条，`sideEffect={plan_preview:2, readonly:9, readonly_while_pending:4, intent_pending:6}`。
- shadow diff：`/private/tmp/runtime_shadow_diff_320_g1_g32_after_g27_refresh_fix.json`，32 total、21 observed、9 clean、0 blocking、12 major、11 info，`cleanRate=0.2812`。
- 性能：median `16109ms`、p95 `97361ms`、max `144494ms`，6 条超过 60s。

这轮的意义不是“系统已经收敛”，而是把问题从硬失败推进到了协议差异：

- G4/G19/G25/G30 等内容断言失败已经消失，说明 targeted 小修和 pending/card 边界有阶段性收益。
- 但 compiler/runtime diff 仍有 12 个 major，说明用户可见结果能过断言，不代表 sideEffect、pendingType、presentation、workspaceRefreshTargets、EvidencePlan 已经对齐。
- 后续验收不能只看 e2e successfulSteps，必须同时看 shadow diff 的 cleanRate、major diff 类型和性能长尾。

2026-06-22 focused G31/G32 修复验证：

- 聚焦跑 G31/G32 当前服务路径，报告 `/private/tmp/dialog_regression_320_g31_g32_after_needs_plan_observability_8041_metrics.json` 为 10 step、10 successful、0 failed。
- runtime shadow observation 为 2 条：G31 `readonly_while_pending + unchanged_existing_pending + workspaceRefreshTargets=["ordered"]`，G32 `needs_plan_first + pendingType=none`。
- diff `/private/tmp/runtime_shadow_diff_320_g31_g32_after_needs_plan_observability_8041.json` 在 observed case 上 G31/G32 均 clean、0 blocking、0 major；其余 30 条是聚焦 run 未覆盖的 `missing_observation` info。
- G31 的根因是 pending readonly ordered query 虽拿到了 `ordered_snapshot`，但没有把 ordered workspace action 写入运行时 contract；G32 的根因不是回复内容错，而是 fixture 与 golden 不一致叠加 `needs_plan_first` route observability 未持久化。

2026-06-22 after G31/G32 contract full clean shadow 结果：

- 完整 G1-G32 e2e shadow 子集在当前代码服务 `8042` 上重跑，报告 `/private/tmp/dialog_regression_320_g1_g32_after_g31_g32_contract_8042_metrics.json` 为 52 step、51 successful、1 content failure；唯一失败是 G27 最后一轮缺 `planningWorkspaceAction`。
- runtime observation 仍为 21 条，但 sideEffect 分布更新为 `plan_preview=2`、`readonly=7`、`readonly_while_pending=4`、`intent_pending=6`、`needs_plan_first=2`；G19/G32 均能归一到 `needs_plan_first`。
- full diff `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g31_g32_contract_8042.json` 为 32 total、21 observed、12 clean、0 blocking、9 major、11 info，`cleanRate=0.375`。相对 after G27 refresh fix，clean 从 9 提到 12，major 从 12 降到 9。
- clean case 为 G4、G8、G10、G19、G21、G22、G23、G25、G29、G30、G31、G32；说明 preference strength、极性绑定、admissionPath、no-plan guard、pending 下只读 ordered query 这些 targeted contract 已在 full run 中稳定。
- 性能仍不收敛：median `19360ms`、p95 `42739ms`、max `49585ms`，最慢为 G30 基础学科/强基意图分析、G12 学费替换分析、G21 强基普通批衔接、G7 中外合作预算审查、G17 tier-local reorder。相比上一轮 max 降低，但 40s 级长尾仍说明 full-agent 自由工具循环和最终回复生成没有被 EvidencePlan/tool budget 约束。

关键残留及根因：

| 问题 | 最新表现 | 根因定性 |
| --- | --- | --- |
| G27 费用阈值 + 意向贴合删除 | full run `8042` 中“两万以上且不沾边先删掉”仍只得到 blocked `preview_fix_proposal`，没有形成可执行删除 pending；focused 修复后单 case 已形成 `remove_units` pending，后续“删完了再看”能 `apply_pending_then_readonly` 并刷新 ordered/review | 根因不是 apply 刷新分支，而是复合 selector/action DSL 缺失。已补 `tuition >= 20000`、`preferenceFit=unrelated`、delete scope 的 preview/apply 共用 selector；仍需全量 G1-G32 clean shadow 验证 full diff 收敛 |
| G2 审查到处理建议 | 能回答审查，但缺 conditional options presentation 和 review refresh | `review_plan` 仍容易作为终点；缺 `review evidence -> candidate fix options -> no apply` 的统一 display contract |
| G17 保底区局部重排 | 能出 `move_unit` pending，但缺 ordered workspace refresh；本轮仍需 4 次模型/工具链路、耗时 `41858ms` | tier-local ordinal DSL 与 workspace refresh 不由同一个 compiler 输出，且 full-agent 多模型请求链路过长 |
| G21 强基/普通批合理性 | full diff 已 clean：不会误生成普通方案，也不会 unexpected review refresh；但多轮政策/衔接问答仍有重复检索和 40s 级长尾 | `admissionPath` 节点和 guard 已阶段性稳定，剩余是 EvidencePlan/tool budget 和正式特殊路径 review contract |
| G31 pending 下只读保底查询 | full run 已 clean：能回答、pending 未采纳、ordered workspace refresh 已对齐 | 最小 runtime contract 已补齐；后续仍应把 readonly while pending 的 evidence/display contract 纳入 compiler 单主路径 |
| G32 无正式方案引用 | full run 已 clean：明确无正式方案时归一为 `needs_plan_first`，不调用模型、不创建 pending | 最小 deterministic guard 已补齐；完整形态仍应进入 TurnDecision 的 referenceResolution/noReferent taxonomy |

2026-06-22 focused G27 修复验证：

- 代码层补齐 `plan_next_action` 的 `min_tuition_per_year / max_tuition_per_year / preference_fit` 参数，`execute_plan_action(remove_units)` preview 与 apply 使用同一个结构化 selector 解析 ordered volunteerIds。
- service 层没有新增文本 recovery/pending bridge；只是让 semantic `preview_fix_proposal` 快捷路由在用户明确删除当前方案范围时返回 full Agent，由模型走 `plan_next_action -> execute_plan_action` 主链。
- 单 case 报告 `/private/tmp/zhiyuan_320_g27_after_structured_remove_metrics.json` 为 4/4 successful，第三轮产出 `pendingConfirmationCard(actionFamily=remove_units)`，第四轮 `routingPath=pending_plan_short_text_confirm`、`route=apply_pending_then_readonly`、`postApplyEvidencePlan` 存在，followup 刷新 `ordered` 和 `review`。
- 这说明 G27 的根因定性已从“pending apply 后刷新缺失”修正为“前一轮 selector/action DSL 缺失”；后续动作是全量 G1-G32 clean shadow 复跑，确认没有引入新的 presentation/workspace refresh 差异。

因此当前根因应更新为：

- 模型节点已经可以通过 schema/prompt 在 G1-G32 关键节点上达到三轮稳定，但这些节点输出还没有成为 runtime 的唯一事实源。
- `service.py` 中大量旧恢复路径已经删除，pending sink 调用也已收口到 compiled contract；但 full-agent 主路径仍会直接产生工具调用、回复、workspace refresh 和 pending observation，导致 display/presentation/evidence 与 compiler 目标不一致。
- 3.2.0 的下一步不是继续增加字符串匹配或 shadow 接管，而是把 `TurnDecision -> ToolPlan/EvidencePlan -> ProposalCandidate -> CompiledProposal -> replyPlan/displayPayload` 接成单主路径，并用 diff cleanRate 验证旧路径删除。

不同模型横评的位置也应明确：

- 可以对 Kimi、GLM、MiniMax、DeepSeek、GPT 系列做 model-node benchmark，比较 schema 输出、字段准确率、稳定性和延迟。
- 横评只用于判断“哪些节点可交给模型输出候选，哪些必须 deterministic guard/compiler 接管”。
- 即使某模型在 G27/G17/G21 上更好，也不能绕过 action DSL、EvidencePlan、pending sink contract 和 workspace display contract 直接接 runtime。

2026-06-23 after G27 structured remove full clean shadow 复跑结果：

- e2e runner：`/private/tmp/dialog_regression_320_g1_g32_after_g27_structured_remove_8037_metrics.json`，52 step、51 successful、1 content failure。
- 唯一内容失败：G26 `保底最后几个是什么学校 录取率多少`。runtime 查询链路把“保底”误绑定成专业关键词，最后回复“没有命中符合‘专业:保’的志愿”，没有回答 tier=保底、tail slice、school、admissionProbability。
- runtime observation：21 条，`sideEffect={plan_preview:2, readonly:7, readonly_while_pending:3, intent_pending:6, needs_plan_first:2, apply_pending_then_readonly:1}`。
- shadow diff：`/private/tmp/runtime_shadow_diff_320_g1_g32_after_g27_structured_remove_8037.json`，32 total、21 observed、16 clean、0 blocking、5 major、11 info，`cleanRate=0.5`。G27 已从 full diff major 中移除。

这轮把剩余问题重新分层：

| 问题 | 现象 | 根因定性 |
| --- | --- | --- |
| G26 PlanQuery 切片查询 | “保底最后几个”被抽成 `专业:保`，多次 query 后仍答空结果 | 这不是内容润色问题，而是 plan projection/slice 结构缺失；需要 `tier=bao / slice=tail / fields=[school, major, admissionProbability]` 的 DSL 和 deterministic query mapper |
| G16 锁定/固定位置 | “锁定第1个和第2个冲档”被误走 `move_ordered_unit`，返回“已在第1位，不需要移动” | unsupported local action 与可执行 move 没分开；必须先输出 `unsupportedAction=pin_or_lock_unit` 或一等 pin/lock DSL，不能用 move/no-change 消解 |
| G22/G31 profile 变更后重来 | 用户明确“基于620湖北物化生重来”后应先识别为当前学生资料变更；临时测算/帮别人问不能污染当前 profile；后续追问“现在是不是按新资料算”不能继续读成普通方案状态 | 已落 `TurnDecision -> compile_profile_change_replan_source` 主路径：`current_student_update` 产生 `ProfileChangeReplan` 和 stale-state；`adhoc_scenario` 产生 `ProfileReplanAdhoc`，不更新 profile、不让旧方案失效；`ambiguous` 产生 `ProfileReplanAmbiguous`，只澄清范围。compiler 只消费 `profileScenario/proposedProfile/profile_change_state_query`，不从用户原话匹配“基于/重来/重新/临时”。状态追问进入 TurnDecision `profile_change_state_query` 主路径。仍缺后续可执行状态机：确认资料更新、清理或继承旧 pending、触发候选和方案重算 |
| G17 tier-local reorder | 能出 `move_unit` pending，但链路重复 `plan_next_action/execute_plan_action/query_volunteer_plan`，耗时 23s+ | tier-local selector、ordinal binding、ordered refresh 没被同一个 EvidencePlan/Compiler 接管，仍依赖 full-agent 自由工具循环 |
| G29 preference strength 展示 | 用户说“优先/也可以考虑”，卡片 summary 曾只显示平铺偏好专业 | 已定位为 display gap：runtime pending payload 的 `selectedData.entityProfile.preferenceStrength` 保留 `primary/acceptable`，但 `displaySummary` 过去由扁平 `major_intents` 汇总。当前已改为从结构化 `preferenceStrength/entityPolaritySpans` 生成用户可见摘要，例如 `优先专业：网络与新媒体；可以考虑专业：跨境电子商务`，执行 payload 不变 |

这轮也修正一个重要判断：G26 在 shadow diff 中是 clean，因为 diff 只比 sideEffect/pending/presentation，不检查内容实体和字段；真实 runner 仍失败。因此 3.2.0 验收不能只看 shadow diff cleanRate，还必须把内容断言、reply quality profile 和 plan query field assertions 纳入 gate。

2026-06-23 focused G26 修复验证：

- runtime 新增无 pending、已有正式方案下的只读切片查询，观测路由保留为 `direct_readonly_plan_slice_query`。查询意图不再在 service 中按原句硬拆，也不继续依赖 compiler 内置词表作为主路径；当前主路径改为 `TurnDecision(plan/current_plan/readonly plan_query*) -> plan_query_profile_tool -> proposal_compiler.compile_runtime_plan_query_profile_source -> PlanQuery DSL`。`TurnDecision` 只负责判断“本轮是不是当前方案只读查询场景”，`plan_query_profile` 再负责输出 `queryType/dimensions/filters/projection/pendingReferenceType`；compiler 只校验结构化 profile 并生成 `query_ordered` payload。
- `PlanQuery` compiler 当前支持 `readonly_plan_slice_query`、`readonly_plan_query` 和 `readonly_pending_reference_query` 三类：切片表达 `tier + head/tail + fields`，普通查询表达 `tuition` 等结构化 filter + projection，pending reference 则从 active pending 的 `selectedData/entityProfile` 读取相关专业/学校实体。compiler 不再从用户原话判断查询维度；mutation/none profile 会被拒绝，避免只读 query 与高副作用 proposal 混线。
- G26 被编译为 `query_ordered`，DSL 为 `queryType=readonly_plan_slice_query`、`dimensions=["tier_segment"]`、filters 为 `tier=保`、`slice=tail`、`limit=5`、`include_fields=[school, major, admission_probability]`，handler 直接读取 ordered plan 的末尾保底条目并输出学校、专业、录取率和位置。
- focused e2e `/private/tmp/dialog_regression_320_g26_after_plan_slice_fix_metrics.json` 为 1/1 successful，耗时 `2583ms`，`toolCallCount=1`，无模型调用、无 pending 创建，刷新 `ordered`。
- 最新 focused 复核 `/private/tmp/dialog_regression_320_g26_planquery_slice_8000_metrics.json` 为 1/1 successful，耗时 `2528ms`，`routeDecision.planQueryDsl.queryType=readonly_plan_slice_query`；diff `/private/tmp/runtime_shadow_diff_320_g26_planquery_slice_8000.json` 为 1 observed、1 clean、0 blocking、0 major。
- G27 的只读费用阈值查询也进入同一 PlanQuery profile/DSL：`两万以上的都算贵 帮我看看有几个` 应先由 `TurnDecision` 输出 `taskLayer=plan/scopeAnchor=current_plan/sideEffect=readonly/scenario=plan_query`，再由 `plan_query_profile` 输出 `queryType=readonly_plan_query`、`dimensions=["tuition"]`、filters 为 `min_tuition_per_year=20000`，最后由 compiler 走 `query_ordered` count/examples；而 `那把两万以上且跟我意向不沾边的先删掉` 不属于 readonly plan query，应继续走 `tuition range + preference_fit -> remove_units` preview/apply。focused G27 `/private/tmp/dialog_regression_320_g27_planquery_tuition_8000_metrics.json` 为 4/4 successful，第二轮 `toolCallCount=1`、`routingPath=direct_readonly_plan_query`；diff `/private/tmp/runtime_shadow_diff_320_g27_planquery_tuition_8000.json` 为 1 observed、1 clean、0 blocking、0 major。
- 费用相关两条路径的关系保持不变：只读查询是 `PlanQuery -> query_ordered(current_plan filters/projection)`；方案变更是 `tuition range + preference_fit -> remove_units/replace_units preview/apply`，由 action DSL 和执行层 selector 解析 volunteerIds。二者以 `query profile` 的 `queryType/sideEffect` 互斥，不靠 service 字符串或单 case 分支区分。
- 2026-06-23 追加复核：G26 失败的真实根因不是 PlanQueryProfile，而是 TurnDecision 在 `pendingExists=false` 时仍输出 `readonly_while_pending/plan_query_while_pending`。`turn_decision_tool` 现在用权威 `planningStateProfile.pendingExists` 做状态一致性归一：无 active pending 时，while-pending 的只读方案查询会归一为 `readonly/plan_query`。这属于结构化 payload 约束，不是中文 prompt 词表。
- 同轮补齐 full-agent preview 边界：如果模型先产生不可执行的 mutation preview，随后又用只读 `query_state/query_ordered/query_candidates` 覆盖最终回复，且没有 pending card，service 用结构化 `action_family/result_kind/applied` 识别为 `non_actionable_plan_preview_boundary`，清掉 workspace refresh/view，避免“无卡 preview 被方案概览冲掉”。单一 preview-only 的缺候选/缺范围等更具体回复不被覆盖。focused `/private/tmp/zhiyuan_320_plan_query_gate_metrics_after_fix.json` 为 5/5 successful：G26 为 `direct_readonly_plan_slice_query -> query_ordered`，G27 阈值只读为 `direct_readonly_plan_query`，后续删除形成 `pendingConfirmationCard(remove_units)`，最后走 `apply_pending_then_readonly`。
- 全量 G1-G32 fresh `8000` 复跑 `/private/tmp/zhiyuan_320_g1_g32_after_plan_query_gate_metrics.json` 为 52/52 successful、0 failed；runtime shadow `/private/tmp/zhiyuan_320_g1_g32_after_plan_query_gate_shadow.json` 观测 22 条，sideEffect 分布为 `plan_preview=2`、`readonly=6`、`readonly_while_pending=4`、`intent_pending=6`、`plan_preview_or_clarification=1`、`needs_plan_first=2`、`apply_pending_then_readonly=1`。shadow diff `/private/tmp/zhiyuan_320_g1_g32_after_plan_query_gate_diff.json` 为 32 total、21 observed、21 clean、0 blocking、0 major、0 minor、11 info，cleanRate `0.6562`。这轮确认 G26/G27 PlanQuery gate 没有引入其它协议回退；剩余明显风险转到 latency 长尾和 G29 `primary/acceptable` 展示压扁。
- 后续统一条件合同暂不在本轮改 Java：Java 当前已有 `candidate-pool/query`，条件 DTO 为 `CandidatePoolQueryReq.Filters`，支持 tier、省/市、院校/专业关键词、院校/专业标签和 negative 条件；但当前没有 `ordered-plan/query` endpoint，`CandidatePoolQueryReq.Filters` 也尚未覆盖学费上下限。后续如果要完整下推，应先定义统一 `PlanQueryCondition`（字段对齐 Java DTO，并补齐 tuition/preference-fit/ordered scope），再新增或复用 Java 查询执行能力。当前 3.2.0 runtime 只保持最小 `PlanQueryProfile -> Python query_ordered` 路径，不在 Python 里继续扩完整筛选器。

下一步客观优先级：

1. 用下一轮全量 G1-G32 验证 G26/G27 PlanQuery grammar 后是否继续 clean，并把 PlanQuery DSL 字段补进 compiler/profile gate。
2. 为 `profile_change_replan` 定义一等动作和状态策略，明确旧方案/旧 pending 是否废弃、是否需要用户确认、如何触发重算。当前已完成 TurnDecision/编译边界收口：`current_student_update` 才能产生 `ProfileChangeReplan` 和 stale-state，`adhoc_scenario` 只能作为临时测算，`ambiguous` 只澄清范围；这三类均先于 PlanQuery/local action/semantic plan 处理，状态追问已进入 TurnDecision `profile_change_state_query` 主路径。service 只消费结构化场景和历史 DSL，旧 `plan_semantic_action.replyFocus` 仅作兼容 fallback。后续 profile update/replan 的可执行动作不能退回 service 文本匹配；单字段纠错与承接式“按这组资料重来”也应继续收进 TurnDecision/profile node，由 compiler 统一裁决副作用与状态机。
3. 把 G16 pin/lock 从 move action 中拆出，未支持时返回受控 unsupported clarification；支持时进入 planActionDsl。
4. 压缩 G17/G30/G7 的自由工具循环：EvidencePlan 明确 required inputs、tool budget、batchable query 和 replyPlan。
5. 核对 G29 runtime pending payload 的 `preferenceStrength`，确认是 display gap 还是 schema gap。

2026-06-23 G29 复核结论：这是 display gap，不是 schema gap。`intent_entity_profile` 输出和 pending `selectedData.entityProfile` 均保留 `preferenceStrength.primary/acceptable`；service 现在只在展示层基于结构化 profile strength 生成 `displaySummary`，不从用户原文匹配“优先/也可以考虑”，也不改写后端 apply payload。

2026-06-23 review/repair preview bridge 与 action-scoped confirm 复核：

- G1-G32 golden 在 review/repair bridge 后跑两轮：round1 `/private/tmp/zhiyuan_320_g1_g32_round1_after_review_repair_bridge_metrics.json` 为 52 step、51 successful、1 个 style failure；round2 `/private/tmp/zhiyuan_320_g1_g32_round2_after_style_fix_metrics.json` 为 52 step、51 successful、1 个 performance failure，G12 `182070ms > 180000`。两轮 shadow 均为 32 total、21 observed、21 clean、0 blocking/major/minor、11 missing observation。
- mainline extended regression `/private/tmp/zhiyuan_320_mainline_after_review_repair_bridge.json` 为 123/123 successful，median `9671ms`、p95 `22180ms`、max `34744ms`。唯一重复工具观察为 `explore-region-to-region-intent-to-plan`，重复 `analyze_current_region_interest` 和 `analyze_current_interest_profile`。
- action-scoped confirm focused WebSocket 初版 `/private/tmp/zhiyuan_320_confirm_generate_after_fix.json` 为 10/10 successful，median `8433ms`、p95/max `24972ms`。actionFamily 绑定改造后复跑 `/private/tmp/zhiyuan_320_confirm_generate_after_actionfamily_fix.json` 为 10/10 successful，median `6648ms`、p95/max `10772ms`。最新结果显示两类边界都正确：无 active plan pending 时 `确认生成` 进入 no-pending guard；存在 active `generate_plan` pending 时 `确认生成` 才按 pending 执行，执行层因基础信息不足返回补全信息要求。两者都没有重新进入 full-agent 生成预览。
- 仍需保留的结构问题：连续 intent pending 当前为单 active 替换语义，缺 append/replace/conflict 一等裁决；空方案/无数据时 workspace refresh 与 evidence 有不一致；apply 后 review 偶发“执行成功但复审说失败”；职业负向方向如“不想走体制内”还缺 career-direction intent schema；G12/G7 等 long tail 需进入 EvidencePlan/tool budget，不作为文案风格问题处理。

2026-06-24 G27 结构化预览被同轮只读查询覆盖的补充定性：

- 真实失败链路不是“没有理解两万以上/意向不相关”，也不是需要在 service 里重新按中文原句解析。模型已经先通过 `plan_next_action` 产出结构化 `remove_units` preview，`atomic_actions.filters` 中包含 `min_tuition_per_year=20000` 和 `preference_fit=unrelated`，并带有 `planning_version`。随后同一轮又调用只读 `execute_plan_action(query_ordered)`，旧候选抽取逻辑把最终焦点让给只读结果；同时 `composite_proposal.goal.needs_clarification=true` 又会压掉可执行 atomic mutation scope，导致本该进入 pending 的删除预览被澄清/查询分支覆盖。
- 本轮修复只调整结构化候选优先级：如果 `plan_next_action` payload 已有可执行 atomic mutation scope，`composite_proposal.needs_clarification` 不能覆盖它；如果同一 turn 后续出现 `query_state/query_ordered/query_candidates` 这类只读结果，service 保留最近的可执行 `plan_next_action` preview 作为 PlanAction pending candidate。候选仍由结构化 `action_family/atomic_actions/filters/planning_version` 构造，不读取 raw user text，不恢复 `classify_plan_recovery_action`，也不让单独 `plan_next_action` 在没有可执行 scope 时补卡。
- 这个修复和 2026-06-23 的 PlanQuery gate 是互补关系：只读费用查询仍走 `TurnDecision -> plan_query_profile -> query_ordered`，不生成 pending；费用阈值 + 意向贴合删除仍走 action DSL 的 `remove_units` preview/apply。二者靠结构化 `sideEffect/queryType/action_family` 互斥，不靠中文字符串区分。
- 与 Java 侧统一查询能力的关系：当前没有实施 Java ordered-plan query 下推，也没有在 Python 内继续扩完整筛选器。后续如要统一，应定义 `PlanQueryCondition`，对齐 Java `CandidatePoolQueryReq.Filters` 并补齐 ordered scope、tuition range、preference-fit，再交由 Java 查询/筛选能力执行；本轮只修 runtime pending 候选抽取优先级。
- 已验证的最小门禁：`test_extract_plan_confirmation_candidate_keeps_preview_after_readonly_query_result`、`test_extract_plan_confirmation_candidate_keeps_filter_remove_preview_after_readonly_query`、`test_extract_plan_confirmation_candidate_ignores_plan_next_action_preview_result_without_execute`、`test_extract_plan_confirmation_candidate_clears_plan_next_preview_after_execute_error` 通过；`test_runtime_hard_cut_audit.py`、runtime compiler selection 关键子集、plan orchestration/execution 的 tuition + preference-fit selector 子集通过。后续还需要在 fresh `8000` 上重跑 focused G27，再跑 G1-G32 两轮和更大范围回归，确认平均性能、shadow diff 和内容断言没有回退。

### 11.7 回归资产先修契约，再修业务

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

### 11.8 三轮后优先级

3.1.1：

- 继续只做窄修和文档收口。
- 不新增 shadow、bridge 或兼容路径；受控 shadow 只允许进入 3.2.0 硬切准备阶段。
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
