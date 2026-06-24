# Release 3.2.0 Model Capability Profile Plan

本文定义 3.2.0 主路径重构前必须完成的模型理解与生成能力评估。它不是运行时 shadow，不进入生产链路，也不作为长期兼容桥接；它只用于在 3.2.0 实现前量化模型能力边界，为 `TurnDecision -> ScenarioCompiler -> ToolPlan -> Proposal/Pending` 的防御性设计提供依据。后续 runtime 可复用这些 case 做只读 shadow diff，但 shadow 输出不能参与裁决、不能创建 pending、不能写业务状态。

3.2.0 总体执行顺序、benchmark 分层、fixture 契约、runtime 硬切和 explorer 闭环见 [release-3.2.0-execution-roadmap.md](./release-3.2.0-execution-roadmap.md)。本文只定义模型能力 profile 的评估对象、golden 候选、指标和验收门槛。

Profile case 契约见 [release-3.2.0-profile-case-schema.md](./release-3.2.0-profile-case-schema.md)。当前已落地首批 G1-G8 golden 样例：[dialog_profile_320_golden_cases.json](../zhiyuan-agent/examples/dialog_profile_320_golden_cases.json)。

模型依赖节点的独立 benchmark 见 [release-3.2.0-model-node-benchmark.md](./release-3.2.0-model-node-benchmark.md)。该体系区别于端到端 runner，用于评估 `turn_side_effect`、`intent_side_effect`、`plan_semantic_action`、`composite_goal`、`pending_action`、`reply_focus_binding` 等关键节点。

## 1. 目标

- 在 3.2.0 落地前，先测清楚模型在场景理解、范围锚定、结构化输出和用户回复生成上的稳定性。
- 用 profile 结果决定哪些判断可以交给模型，哪些必须由 deterministic guard、compiler 校验或后端 proposal/dry-run 接管。
- 避免 3.2.0 直接按理想架构实现后，才发现模型无法稳定区分 Policy、Explore、Intent、Plan 或无法稳定输出可编译结构。
- 3.1.1 只修小问题和回归统计，不引入新的长期 bridge、shadow 或兼容分支。

## 2. 非目标

- 不在 3.1.1 主链路引入 shadow router。
- 不为 3.2.0 保留双写、灰度桥接或新旧并行执行路径。
- 不把 profile 里发现的每个错误都变成 3.1.1 的服务层恢复分支。
- 不用模型 profile 替代 Java proposal、dry-run、apply policy 和 pending 确认协议。

## 3. 评估对象

### 3.1 场景理解

评估模型是否能稳定输出：

- `taskLayer`: `pending / policy / explore / intent / plan`
- `sideEffect`: `readonly / intent_pending / plan_preview / apply_existing_pending`
- `scopeAnchor`: `general / current_plan / current_major_group / candidate_pool / future_reference`
- `scenario`: `policy_explain / explore_analysis / intent_update / plan_query / plan_review / repair_preview / atomic_mutation / composite_goal / profile_change_replan`
- `expectedPending`: `none / intent_change / plan_mutation`
- `missingInfo`

重点覆盖：

- 压线、批次线、分数风险、民办/专科兜底。
- 当前方案审查、风险解释、修复预览。
- 专业组内局部操作。
- only_keep / must_have / exclude / tuition budget。
- Intent+Plan 混合回合：同一轮先出现空/非 pending intent preview，再出现可执行 plan preview 时，是否能稳定以 `plan_preview` 作为唯一用户可确认对象。
- 候选只读查询和候选加入/替换。
- 用户拒绝引导、改口、短文本确认、无 pending 确认。

### 3.2 结构化计划生成

评估模型能否把明确场景转成受控计划，而不是直接生成事实或绕过执行协议。

需要评估：

- 是否能输出可编译 `ToolPlan`。
- 是否能区分 evidence step 和 action endpoint。
- 是否能识别需要 `review_plan`、候选查询、当前方案读取、官方来源检索或澄清。
- 是否会把 `review_plan` 当成修复终点。
- 是否会把长期意向和当前方案动作混在一起。
- 是否会把当前专业组局部范围误解成未来职业/稳定就业意向。

### 3.3 用户回复生成

评估模型在工具事实已给定时的最终回复质量。

需要评估：

- 是否回答用户真正问题，而不是只输出协议边界。
- 是否暴露内部词：`blocked / preview_only / fix_proposal / action_family / pendingConfirmation`。
- 是否能把替换、补充、删除、确认后的影响说清楚。
- 是否能在不可执行时给出用户可理解原因。
- 是否能保持“确认前不改方案”的边界但不让边界话术覆盖只读咨询主体。

## 4. Profile 数据集

数据集分三类，不直接混用：

| 类型 | 来源 | 用途 |
| --- | --- | --- |
| Goldens | 3.1.1 P0/P1、3.0.3 真实对话衍生、3.1.0 constraint/review repair | 作为强断言集，必须有标准 `TurnDecision` |
| Broad 模拟 | `assets/*scenarios*.json`、autoexplorer 高价值 case | 发现表达长尾，不直接作为产品缺陷 |
| 生成式扰动 | 对 goldens 做同义改写、口语化、短文本追问、拒绝引导 | 测试边界稳定性 |

每条 case 至少包含：

- `prompt`
- `history_context`
- `planning_state_profile`
- `expected_turn_decision`
- `forbidden_decisions`
- `expected_tool_plan` 或 `expected_readonly`
- `expected_pending`
- `reply_quality_assertions`

## 5. 指标

### 5.1 决策指标

- `taskLayer_accuracy`
- `sideEffect_accuracy`
- `scopeAnchor_accuracy`
- `scenario_accuracy`
- `pending_type_accuracy`
- `unsafe_side_effect_rate`
- `readonly_to_pending_false_positive_rate`
- `mutation_to_readonly_false_negative_rate`

### 5.2 结构化输出指标

- `schema_valid_rate`
- `compiler_accept_rate`
- `unsupported_step_rate`
- `missing_required_evidence_rate`
- `hallucinated_fact_rate`
- `wrong_scope_anchor_rate`

### 5.3 回复指标

- `answers_user_question_rate`
- `internal_terms_rate`
- `over_boundary_reply_rate`
- `from_to_explanation_rate`
- `no_unbacked_commitment_rate`

## 6. 防御性设计映射

Profile 结果必须直接反馈到 3.2.0 设计：

| 发现 | 3.2.0 处理 |
| --- | --- |
| Policy/Plan 边界不稳定 | `TurnDecision` 后加 deterministic forbidden-tools guard |
| 专业组局部范围不稳定 | `scopeAnchor=current_major_group` 必须由 compiler 校验，不允许转 future intent |
| review endpoint 混淆 | compiler 把 `review_plan` 标成 evidence step，不能单独生成 plan mutation |
| 结构化计划经常缺 evidence | compiler 返回澄清或只读解释，不调用 mutation preview |
| 回复边界话术覆盖主体 | reply generator 必须先回答问题，再附副作用边界 |
| from/to 经常缺失 | proposal 缺完整 pair 时不能生成可确认替换卡 |
| 同轮 Intent/Plan 混合导致 pending 丢失 | compiler 必须按结构化 sideEffect 决定唯一 pending；空 intent preview 不能覆盖已可执行 plan preview |

## 6.1 2026-06-19 新增 Profile Golden 候选

### G1 排除当前方案内英语相关专业

- prompt：`不要英语相关专业，当前方案里有的话也删掉`
- expected taskLayer：`plan`
- expected sideEffect：`plan_preview`
- expected scopeAnchor：`current_plan`
- expected scenario：`atomic_mutation` 或 `composite_goal`
- expected pending：`plan_mutation`
- expected intent side effect：可作为 plan pending 的附带 `intent_update`，确认后同步写入后续报考参考；不能单独生成 intent card 覆盖 plan card。
- forbidden：
  - 只回复“需要确认吗”但不落 pending。
  - 生成 intent pending 后不处理当前方案。
  - 第二轮 `确认执行` 进入 no-pending guard。

已观察事实：

- 3.1.1 e2e 中模型先调用 intent preview 工具，结果 `status=empty`。
- 随后模型调用 `plan_next_action -> execute_plan_action`，得到 `remove_units preview_only`。
- 工具返回中已有 `facts.resolved_apply_payload.atomic_actions[0].volunteer_ids` 和 `facts.intent_update`。
- 最终 WebSocket 没有 pendingConfirmationCard，导致短确认失败。

Profile 价值：

- 该 case 直接评估模型/编排是否能在混合回合中稳定产出唯一 side effect。
- 3.2.0 不能靠“看到确认文案就恢复 pending”解决；应由 `ToolPlan/ProposalCompiler` 明确输出唯一 `Proposal/Pending`。

### G2 费用/中外合作“先看看能怎么处理”

- prompt：`方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动`
- expected taskLayer：`plan`
- expected sideEffect：根据上下文分两档：
  - 若当前方案有可执行替换/移出机会，应为 `plan_preview`。
  - 若需要先取舍预算/合作项目接受度，应为 `readonly` 或 `needs_clarification`，但回复必须说明为什么不能直接预览。
- observed：3.1.1 review/repair e2e 中该 case 被路由为 `analyze_adjustment`，只返回分析结论，当前未判失败。
- Profile 价值：测模型能否区分“处理方向分析”和“可确认调整预览”，以及是否能在不确定时显式产出 `needs_clarification` 而非模糊分析。

### G3 pending 存在时的当前方案只读查询

- history：上一轮生成了 `偏好金融学类；排除护理学、中医学` 的待采纳 intent pending。
- prompt：`先不确认，当前方案里有没有护理或者中医学`
- expected taskLayer：`plan`
- expected sideEffect：`readonly`
- expected scopeAnchor：`current_plan`
- expected pending：保留上一轮 pending，不 apply、不取消。
- expected reply：
  - 先回答当前方案是否命中护理/中医学。
  - 再说明上一轮偏好仍未采纳，确认前不会生效。
- forbidden：
  - 只解释 pending 边界，不回答当前方案命中情况。
  - 因为用户说“先不确认”而清空 pending。
  - 因为存在 pending 就禁止只读查询。

Profile 价值：

- 该 case 用来测试 `pending_context + readonly_query_current_plan` 的场景理解。
- 3.2.0 需要支持 pending 保持不变，同时允许只读证据查询。

### G4 弱偏好和备选偏好不能被压扁

- prompt：`那把网络与新媒体作为优先方向，跨境电商也可以考虑`
- expected taskLayer：`intent`
- expected sideEffect：`intent_pending`
- expected pending：`intent_change`
- expected structured result：
  - primary/preferred：`网络与新媒体`
  - secondary/acceptable：`跨境电子商务`
  - hard constraints：无
- forbidden：
  - 只保留 `网络与新媒体`，丢掉 `跨境电子商务也可以考虑`。
  - 把 `跨境电子商务` 错当成 hard must_have。

Profile 价值：

- 评估模型和 schema 是否能区分 primary preference、acceptable fallback、must_have/only_keep。
- 3.2.0 若 schema 不支持 preference strength，模型即使理解正确也会在编译阶段丢信息。

### G5 negative-only 地域排除

- prompt：`东北西北都不要，必须避开`
- expected taskLayer：`intent`
- expected sideEffect：`intent_pending`
- expected scopeAnchor：`future_reference`
- expected pending：`intent_change`
- expected structured result：`negative_area=["东北","西北"]`
- forbidden：
  - 要求用户补充“要保留哪里”后才生成 pending。
  - 将 strong negative region 误判为 readonly analysis。
  - 第二轮 `确认` 进入 no-pending guard。

Observed：

- 3.1.1 full journey 中 `intentSideEffectDecision` 已判定 `intent_preview`，confidence `0.95`。
- 最终回复仍表示“没有稳定识别出具体要保留的专业、院校或地域”，没有 pending card。

Profile 价值：

- 测试模型理解和工具/formatter 是否一致处理 negative-only constraints。
- 3.2.0 compiler 不应要求每个地域约束都同时有 positive scope。

### G6 候选查询缺分数/位次的 missingInfo

- prompt：`我是湖北物化生，想看看候选里计算机和数据科学方向多不多`
- known context：无分数、无位次。
- expected taskLayer：`plan`
- expected sideEffect：`readonly`
- expected scopeAnchor：`candidate_pool`
- expected missingInfo：`score`、`rank` 至少其一。
- expected reply：
  - 明确说明当前缺少分数/位次，只能看已有候选或需要补信息。
  - 若读取候选为空，不能断言“分数不够”。
- forbidden：
  - 把缺前置条件造成的空结果说成“按你当前分数/筛选条件没有命中”。
  - 编造分数段或位次判断。

Profile 价值：

- 测试 PlanQuery 是否能区分 `no_result`、`missing_info`、`filtered_out` 三种不同原因。
- 为 3.2.0 `ToolPlan` 的 evidence precondition 和 reply grounding 设计提供依据。

### G7 focus review 不应泛化覆盖用户问题

- prompt：`方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动`
- expected taskLayer：`plan`
- expected sideEffect：`readonly`
- expected scopeAnchor：`current_plan`
- expected scenario：`plan_review` with `targetIssue=tuition/cooperative`
- expected reply：
  - 正面回答中外合作数量/占比或是否偏多。
  - 解释预算一般时的风险：学费、保底安全、可接受/不可接受项目边界。
  - 说明本轮不改方案。
- forbidden：
  - 只输出通用审查风险，如冲稳保、概率倒挂、本省保底不足，而不回答中外合作/预算。

Profile 价值：

- 测试 `review_plan` 作为 evidence step 时，reply generator 是否能按用户 focus 生成回答。
- 3.2.0 需要把 `targetIssue` 从 TurnDecision 传递到 ToolPlan 和回复阶段。

补充扰动：

- `预算一般，是不是要少放中外合作`
- `高收费会不会影响保底安全`
- `优先专业还是学校，这版偏哪边`
- `能不能用大白话说下这版值不值得`

这些扰动都应测试“整体 review 事实可作为证据，但最终回复必须回答用户指定焦点”。不能只用通用审查清单通过。

### G8 偏好表达不能默认升级为当前方案替换执行

- prompt：`我倾向会计学和审计学，但土木工程不要`
- expected taskLayer：`intent` 或 `composite_goal`，取决于当前方案是否有冲突和用户是否明确要求处理当前方案。
- expected default sideEffect：`intent_pending`
- expected scopeAnchor：`future_reference`
- allowed evidence：读取当前方案影响，说明当前是否命中土木工程。
- expected pending：
  - 默认只生成 `intent_change` pending，采纳后作为后续推荐/检查参考。
  - 只有用户明确说“当前方案里有的话删掉/替换/处理”时，才生成包含 `intentUpdates + planActions` 的 `composite_pending`。
- forbidden：
  - 用户只是表达偏好时，直接生成 `plan_mutation/apply_fix_proposal` 替换卡。
  - 把“采纳偏好”和“执行当前方案替换”混在一张卡里但没有分层说明。
  - `intentSideEffectDecision` 判为先分析或先问确认，最终 formatter 仍生成高副作用 plan card。

Observed：

- 2026-06-19 `303-open-quality-intent-existing-impact-readonly` 中，该 prompt 生成了 `plan_mutation/apply_fix_proposal` pending，旧断言接受，但边界偏强。
- `医学护理这些别碰，财会还能接受，先看看影响` 中 sideEffect decision 为 `mixed_answer_then_ask` 且被 honored，说明系统已经有能力区分“先看影响”，但缺少统一裁决层保证所有表达一致。

Profile 价值：

- 测试模型能否区分 `future reference preference`、`current plan impact explanation`、`current plan mutation` 三个层级。
- 3.2.0 需要 profile 出默认策略：先采纳偏好还是同时处理方案，不能靠工具/formatter 事后偶然决定。

### G9 专业组局部操作不能变成长期意向

- prompt：`专业组里只保留最稳的专业行不行`
- expected taskLayer：`plan` 或 `policy`
- expected sideEffect：`readonly`，若用户明确指定组和专业行后才可能进入 `plan_preview`
- expected scopeAnchor：`current_major_group`
- expected reply：
  - 解释专业组内专业选择、组内安全垫、保底专业和能否删除专业行。
  - 说明需要查看具体专业组和专业行后才能预览。
- forbidden：
  - 生成 `career/stable employment` intent pending。
  - 生成长期“稳定就业导向”报考参考。

Observed：

- 3.1.1 已有窄修防止该 case 误恢复成 career intent，但它仍应作为 3.2.0 scopeAnchor golden。

Profile 价值：

- 测试“只保留/最稳”这类词是否能依赖对象范围判定，而不是只看词面。

### G10 短确认断言和 no-pending guard 语义

- history：上一轮是只读分析或无 pending。
- prompt：`确认`、`嗯那就这样`、`就这样`
- expected taskLayer：`pending`
- expected sideEffect：`readonly`
- expected pending：`none`
- expected reply：
  - 明确无待确认内容或本轮不会执行。
  - 可以提示用户继续审查/调整/说明偏好。
- forbidden：
  - 无 pending 时执行上一轮只读建议。
  - 无 pending 时新生成 plan mutation preview。
  - 测试只按固定文案判断失败。

Observed：

- 303 realistic_user 中 `303-real-user-vague-confirm-guard` 实际 guard 正常，但旧断言词与新文案不匹配。
- 303 open-quality 中 `嗯那就这样` 正确走 `readonly_closure_ack`。

Profile 价值：

- 把“短确认语义”从固定回复文案改成状态机行为评估。
- 3.2.0 需要把 no-pending guard 作为协议结果，而不是回复模板。

### G11 Provider 可用性不等于模型能力

- candidate：`zai-org/GLM-5.2`
- expected precheck：
  - `/models` 或 direct smoke 确认模型 ID 存在。
  - API key 鉴权通过。
  - 账户余额/额度可用。
  - `--start-agent` 启动的 agent 真实使用该 provider/model。
- forbidden：
  - 用 `--agent-only --agent-url` 复用已有 agent 后，把结果当成 provider 横评。
  - 把 400/403 provider 错误后的系统兜底回复计入模型质量。
  - 把错误兜底的低延迟计入模型延迟优势。

Observed：

- SiliconFlow 暴露的 GLM 5.2 模型 ID 为 `zai-org/GLM-5.2`。
- `Pro/zai-org/GLM-5.2` 返回 400 `Model does not exist`。
- 当前 key 调用 `zai-org/GLM-5.2` 返回 403 `insufficient balance`。

Profile 价值：

- 3.2.0 前置 profile 必须先保证 provider 可用，再比较理解/生成能力。
- provider unavailable 应作为环境/接入状态，不进入模型能力混淆矩阵。

### G12 长尾性能 profile 必须拆分模型规划、工具和回复生成

来源：

- 2026-06-19 303 累积补跑。
- 代表输出：
  - `/private/tmp/zhiyuan_311_303_dialogue_derived_round1.json`
  - `/private/tmp/zhiyuan_311_303_open_quality_round1.json`
  - `/private/tmp/zhiyuan_311_303_effect_perf_round1.json`

Observed：

- `dialogue_derived`：median `18654ms`，p95 `43388ms`，max `66362ms`。
- `open_quality`：median `23080ms`，p95 `37921ms`，max `37972ms`。
- `effect_perf`：median `17410ms`，p95 `38054ms`，max `40232ms`。
- 多数长尾来自模型选工具和最终回复生成；部分工具如 `query_volunteer_plan` 的 filter extraction 也会带来数秒开销，但不是主要长尾。

Profile 要求：

- 每个 golden 记录：
  - first message latency。
  - final latency。
  - model request count。
  - tool count。
  - tool internal timings。
  - final generation latency。
  - response quality verdict。
- 性能优化不能只看总时长。必须区分：
  - 可以用 deterministic compiler 降低的模型规划长尾。
  - 需要优化工具或缓存的工具长尾。
  - 必须保留质量但可做 streaming/thinking UX 的生成长尾。

Profile 价值：

- 为 3.2.0 决定哪些场景应由 compiler 直接生成 ToolPlan，哪些仍需 full agent 生成回复。
- 防止用低质量模板或过窄快路由换延迟。

### G13 加入意向的偏好强度分层

- prompts：
  - `把计算机类加到意向`
  - `把计算机类加进意向`
  - `还有数据科学和生物信息也加上`
  - `加合工大和南邮到意项里`
- expected taskLayer：`intent`
- expected sideEffect：`intent_pending`
- expected scopeAnchor：`future_reference`
- expected structured result：
  - 默认为 `preference` 或 `primary preference`。
  - 只有用户明确说 `必须有/至少要有/方案里一定要有` 才升为 `must_have`。
  - 只有用户明确说 `只看/只保留/其他不要` 才升为 `only_keep`。
- forbidden：
  - 把普通“加到意向”默认渲染成 `至少保留`。
  - 把上一轮普通 school preference 在下一轮 negative constraint 中合并成 `only_keep`。

Observed：

- 2026-06-20 `robust-session-isolation-a`、`robust-resume-mid-conversation`、`robust-typo-and-abbrev-580` 多次把“加进意向”渲染为 `must_have/至少保留`。

Profile 价值：

- 量化模型和 formatter 对 preference strength 的混淆。
- 为 3.2.0 intent schema 是否必须引入 `primary/acceptable/must_have/only_keep` 提供依据。

### G14 pending apply 与同轮新动作复合诉求

- history：上一轮存在 `intent_change` pending，例如 `至少保留专业类：计算机类`。
- prompt：`现在基于这些出方案`
- expected taskLayer：`pending + plan`
- expected sideEffect：可接受两种设计，但必须结构化：
  - `apply_existing_pending_then_plan_preview`
  - 或 `apply_existing_pending_then_clarify_plan_generation`
- expected reply：
  - 明确上一轮意向已采纳。
  - 同时处理或明确承接“出方案”诉求，而不是把它丢掉。
  - 若后续生成方案进入待确认状态，下一轮 `确认生成/确认生成方案` 必须绑定 active `plan_mutation.actionFamily=generate_plan`，不能只因短句包含“生成”就执行任意 pending。
- forbidden：
  - 只采纳 pending，完全不回应“出方案”。
  - 采纳 pending 后直接生成正式方案而没有 plan preview/confirmation 边界。
  - active pending 是 `intent_change` 或其它 plan action 时，把 `确认生成` 当作可直接 apply 的通用确认。

Observed：

- 2026-06-20 `robust-resume-mid-conversation` 中 `现在基于这些出方案` 只触发 pending apply，未继续处理出方案。
- 2026-06-23 runtime 已把 action-scoped 短确认收口到 `proposal_compiler.resolve_pending_turn_action`：`确认生成` 只有在 active plan pending 的 `actionFamily` 或 `executionPayload.planPayload.action_family` 为 `generate_plan` 时才会走 `apply_existing_pending`。actionFamily 绑定后 focused `/private/tmp/zhiyuan_320_confirm_generate_after_actionfamily_fix.json` 为 10/10 successful；无 active plan pending 时返回 no-pending guard，有 active `generate_plan` pending 时执行 pending，并在基础信息不足时返回 missing-info 边界，不重新进入 full-agent 生成预览。

Profile 价值：

- 测试短确认/复合请求是否能被拆成状态动作和新业务动作。
- 为 3.2.0 `apply_existing_pending_then_new_request` 状态机设计提供样本。
- 固定 action-scoped confirmation 的协议边界：确认副作用由 active pending 元数据决定，不由用户短句单独决定。

### G15 analysis/mixed 后的确认 transition

- history：上一轮为 `mixed_answer_then_ask` 或 `analysis_only`，回复中提出“如果想把这个方向作为后续参考，可以确认/告诉我”但没有 pending。
- prompt：`确认`
- expected taskLayer：`pending`
- expected sideEffect：`readonly` 或 `intent_pending`，取决于是否存在结构化 selectable option。
- expected behavior：
  - 若没有结构化 selectable option：no-pending guard，但上一轮回复不应暗示“确认即可生效”。
  - 若有 `selectableProposal/suggestedIntentTransition`：可转成正式 pending 或直接要求用户点选。
- forbidden：
  - 从自然语言暗示中直接执行写入。
  - 回复说“没有待确认”但上一轮明显让用户确认某个未结构化选项。

Observed：

- 2026-06-20 `science-software-engineering-intent-candidate` 中 `想学软件工程` 走 `mixed_answer_then_ask`，下一轮 `确认` 进入 no-pending。

Profile 价值：

- 测试除 pending 外是否需要轻量 selectable option。
- 降低用户短确认的挫败感，同时避免无 pending 执行副作用。

### G16 plan local action：锁定与保留位置

- prompt：`帮我把方案里第1个和第2个冲档锁定 位置不要动`
- expected taskLayer：`plan`
- expected sideEffect：`plan_preview` 或 `clarification/unsupported`。
- expected scopeAnchor：`current_plan`
- expected scenario：`atomic_mutation`
- expected structured action：
  - 若系统支持：`pin_or_lock_unit`，scope 为第 1、第 2 个冲档。
  - 若系统不支持：明确 unsupported，不执行近似移动动作。
- forbidden：
  - 映射成 `move_ordered_unit/no_change`。
  - 后续 `确认锁定` 进入 no-pending 且上一轮已经暗示已处理。

Observed：

- 2026-06-20 `specific-multi-pin-and-fill-26` 把“锁定”误路由为移动/no-change。

Profile 价值：

- 测试模型是否能识别 plan action 动词，不把修饰语“位置不要动”当主动作。
- 为 action DSL 是否需要 `pin_or_lock_unit` 提供依据。

### G17 tier-local reorder

- prompt：`保底区里录取率最高的调到保底第一位`
- expected taskLayer：`plan`
- expected sideEffect：`plan_preview`
- expected scopeAnchor：`current_plan.tier_segment`
- expected structured action：
  - `move_ordered_unit`
  - `sourceSelector=tier:保底, max(admission_probability)`
  - `targetPosition=first within tier:保底`
- forbidden：
  - 把目标位置解释成全方案第 1 位。
  - 丢掉 `保底区里` 的局部 scope。

Observed：

- 2026-06-20 `specific-conditional-reorder-26` 暴露局部 ordinal 和全局 ordinal 混淆。

Profile 价值：

- 测试 scopeAnchor 和 ordinal binding。
- 3.2.0 compiler 必须在 action 编译时保留局部范围。

### G18 historical preference merge with new negative constraint

- history：
  - 用户已表达普通 school preference：`合肥工业大学`、`南京邮电大学`。
- prompt：`保底要公办不要民办`
- expected taskLayer：`intent` 或 `plan`，取决于是否有当前方案。
- expected sideEffect：`intent_pending` 或 `plan_preview`。
- expected structured result：
  - 新增 `negative_college_type=民办`。
  - 若 `保底` scope 可用，则约束作用于保底区。
  - 历史 school preference 仍保持 preference，不升级为 only_keep。
- forbidden：
  - 输出 `只保留院校：合肥工业大学、南京邮电大学；排除院校：民办院校`。

Observed：

- 2026-06-20 `robust-typo-and-abbrev-580` 复现该过强合并。

Profile 价值：

- 测试 intent merge 是否保留历史偏好强度和本轮约束 scope。
- 防止 state merge 在 3.2.0 中继续隐式收窄候选。

### G19 referenced plan existence before mutation

- history：
  - 用户请求生成方案，但系统没有生成正式方案或候选方案。
- prompt：`刚那个方案民办能少点不`
- expected taskLayer：`plan` 或 `intent` 前置校验。
- expected sideEffect：`readonly_clarification`
- expected referenceResolution：`no_referent`
- expected reply：
  - 明确当前没有已生成方案，不能直接调整“刚那个方案”。
  - 可询问是否要把“少民办/排除民办”作为后续偏好，或先补充信息生成方案。
- forbidden：
  - 直接生成 `排除民办` pending，让用户以为已有方案被修改。
  - 伪造当前方案内容。

Observed：

- 2026-06-20 `tier-mid-520-just-want-bachelor` 中无正式方案时仍把“刚那个方案民办能少点不”转成 intent pending。

Profile 价值：

- 测试模型是否能解析“当前/刚才/这版方案”的指代，并校验状态对象是否存在。
- 为 `referenceResolution` 和 mutation precondition guard 提供数据。

### G20 domain calculation and formula uncertainty

- prompt：`我美术生文化课580联考250综合多少能上啥`
- expected taskLayer：`explore`
- expected sideEffect：`readonly`
- expected behavior：
  - 识别缺省份/当年公式，不能给确定综合分。
  - 若展示示例公式，计算过程和尺度必须自洽。
  - 明确“需按省份艺术类综合分公式确认”。
- forbidden：
  - 给出互相矛盾的中间值和最终值。
  - 在缺公式依据时给出看似精确的综合分。

Observed：

- 2026-06-20 `special-art-580` 中 `250 × 7.5 × 50%` 和最终 `综合分≈580` 表述不一致。

Profile 价值：

- 测试模型在政策/公式/计算类问题上的边界意识。
- 决定 3.2.0 是否需要公式工具、来源检索或“无法计算” guard。

### G21 readonly review must not auto-generate plan

- history：
  - 用户已讨论强基和普通批意向，但不一定有正式方案。
- prompt：`现在这版强基+普通批方案合理不`
- expected taskLayer：`plan`
- expected sideEffect：`readonly_review`；若无正式方案，则 `state_explanation + ask_if_generate`。
- expected scenario：`review_current_plan`
- forbidden：
  - 自动创建 `generate_plan` pending。
  - 同轮既说“已完成方案审查”，又要求确认生成新方案。

Observed：

- 2026-06-20 `special-strongbase-655` 中合理性问题触发 `query_state + generate_plan preview + review_plan`，并挂出生成方案 pending。

Profile 价值：

- 量化 `review/explain` 与 `generate/mutate` 的混淆率。
- 为 `requiresPlanMutation` 硬门禁提供 golden。

### G22 readonly query while pending

- history：
  - 已有基础信息纠正：`湖北`、`620`、`物化生`。
  - 存在未采纳的学校意向 pending：`华中科技大学`。
- prompt：`现在方案是按620湖北算的吧`
- expected taskLayer：`plan/state`
- expected sideEffect：`readonly`
- expected behavior：
  - 回答当前基础信息/方案是否按 `620 湖北 物化生`。
  - 同时提醒华科意向仍未采纳，不影响基础信息回答。
- forbidden：
  - 只解释 pending，完全不回答基础信息状态。
  - 把只读状态查询当成采纳或取消 pending。

Observed：

- 2026-06-20 `special-correction-630` 中 pending 抢占了只读事实查询。

Profile 价值：

- 测试 pending guard 是否只拦截确认/冲突 mutation，而不阻断只读查询。
- 为 `readonly_query_while_pending` 状态设计提供样本。

### G23 slot extraction: location dimension vs major entity

- history：
  - 用户表达专业倾向：`计算机或电子信息`。
- prompt：`城市优先长三角`
- expected taskLayer：`intent`
- expected sideEffect：`intent_pending`
- expected structured result：
  - `regionPreference = 长三角` 或 provinces `江苏/浙江/安徽/上海`。
  - strength 为 `preference/priority`，不是 `only_keep`，除非用户明确说“只看长三角”。
- forbidden：
  - 把“城市”抽成 `城市管理` 专业。
  - 把“优先”默认升级为 `only_keep`。

Observed：

- 2026-06-20 `special-long-chain-12-turn` 中输出 `只保留专业：城市（城市管理）；只保留地域：江苏、浙江、安徽、上海`。

Profile 价值：

- 测试 NER/entity typing 是否能区分维度词和实体词。
- 与 G13 一起量化 preference strength 混淆。

### G24 pending stack conflict and replacement

- history：
  - 已存在未确认的 `generate_plan` pending。
- prompts：
  - `冲档太冒险了删掉一个`
  - `稳档想换成省内的`
- expected taskLayer：`plan`
- expected sideEffect：`clarify_or_replace_pending`
- expected behavior：
  - 明确旧 pending 未确认，新请求会替换/取消旧 pending 或要求先处理旧 pending。
  - 同轮最多返回一个 active pending。
  - 新请求如果依赖正式方案但当前没有正式方案，应说明无法删除/替换具体项。
- forbidden：
  - 继续返回旧 `generate_plan` pending，丢掉新请求。
  - 同轮返回两个可点击 pending。

Observed：

- 2026-06-20 `special-long-chain-12-turn` 中旧生成 pending 残留，后续删除/替换请求被旧生成目标覆盖，并出现 `generate_plan` 与 `intent_change` 双 pending。

Profile 价值：

- 测试 pending 生命周期、冲突处理和单一 active proposal 约束。
- 为 3.2.0 删除多路径创建确认卡提供验收样本。

### G25 mixed positive/negative intent polarity

- prompts：
  - `把生物医学工程和智能医学工程加意向 排除临床医学和口腔`
  - `把金融去掉 加计算机类和人工智能 地域不限`
- expected taskLayer：`intent`
- expected sideEffect：`intent_preview`
- expected structure：
  - `add_preference`: 生物医学工程、智能医学工程 / 计算机类、人工智能。
  - `exclude`: 临床医学、口腔医学 / 金融类。
  - `relax_region`: 地域不限。
- forbidden：
  - 把 `加意向/加` 后的实体放入 negative。
  - 把整句统一编译为 constraint exclude。
  - 丢掉地域放宽。

Observed：

- 2026-06-20 `comprehensive-parent-doctor-conflict-620-gd` round2 中四个专业全部落成排除。
- 2026-06-20 `comprehensive-finance-to-cs-switch-605-js` round2 中计算机类、人工智能被落成排除。

Profile 价值：

- 测试模型/后处理是否能按 clause 绑定 polarity。
- 作为 3.2.0 intent compiler 的硬门禁：正向短语不能被负向动词跨 clause 污染。

### G26 readonly plan projection and slice query

- history：
  - 当前已有完整方案，含 tier、排序、学校、专业、录取率。
- prompts：
  - `保底最后几个是什么学校 录取率多少`
  - `方案前五个冲档都是哪些学校`
  - `学费最贵的那几个是哪些学校`
- expected taskLayer：`plan_query`
- expected sideEffect：`none`
- expected structure：
  - `scope=tier_segment` 或 `scope=full_plan`
  - `slice=head/tail/top_by(field)`
  - `fields=[school, major, admissionProbability, tuition]`
- forbidden：
  - 已有方案证据时仍反问“你想看末尾还是具体学校”。
  - 只给总数，不列明细。
  - 把只读查询升级成调整 pending。

Observed：

- 2026-06-20 `comprehensive-existing-plan-deep-query-26` round2 中，系统读取方案后仍没有列出保底末尾学校和录取率。
- 2026-06-23 G1-G32 full clean shadow 中，G26 仍失败：`保底最后几个是什么学校 录取率多少` 被 full-agent 查询链路误解析成“专业:保”，最终回复“当前方案里暂时没有命中符合‘专业:保’的志愿”。这说明模型/工具没有稳定输出 `tier=保底`、`slice=tail`、`fields=[school, admissionProbability]`。
- 2026-06-23 focused runtime 修复后，同一句命中 `direct_readonly_plan_slice_query`，结构化为 `query_ordered(tier=保, slice=tail, limit=5)`，返回最后 5 条保底志愿及录取率，报告 `/private/tmp/dialog_regression_320_g26_after_plan_slice_fix_metrics.json` 为 1/1 successful。

Profile 价值：

- 衡量模型能否把用户自然语言查询编译成 plan projection，而不是泛化解释。
- 为 PlanQuery DSL 的 slice/sort/field 输出提供 golden。
- 后续 profile/golden 需要把 `scope=tier_segment`、`slice=tail`、`fields` 做字段级断言；只比 sideEffect/pending 不足以发现 G26 这类内容实体错误。

### G27 apply pending then readonly follow-up

- history：
  - 已存在 plan mutation pending。
- prompt：
  - `删完了再帮我看看还剩多少个 梯度有没有问题`
- expected taskLayer：`composite`
- expected sideEffect：`apply_existing_pending_then_readonly_query`
- expected behavior：
  - 先 apply 旧 pending。
  - apply 成功后读取最新方案状态。
  - 回答剩余数量和梯度/冲稳保风险。
  - 不创建第二个 mutation pending。
  - 直接短确认必须检查 active pending 的 `kind/actionFamily`；`确认生成方案` 不能误执行当前 `remove_units` pending，`确认删除` 也不能误执行 `generate_plan` pending。
- forbidden：
  - apply 后直接结束，只刷新 workspace 不回答后半句。
  - 将后半句误当新的 mutation。
  - 只靠确认短句文本决定 apply，而不核对 active pending 元数据。

Observed：

- 2026-06-20 `comprehensive-existing-plan-mutation-chain-35` round2 中只执行 apply 和刷新，没有回答剩余数量/梯度问题。
- 2026-06-22 focused G27 runtime 验证中，上一轮“那把两万以上且跟我意向不沾边的先删掉”已能形成 `remove_units` 结构化 pending；本轮“删完了再帮我看看还剩多少个 梯度有没有问题”走 `apply_pending_then_readonly`，先 apply，再基于刷新后的 ordered/review 回答剩余数量与梯度。报告：`/private/tmp/zhiyuan_320_g27_after_structured_remove_metrics.json`。
- 2026-06-23 full G1-G32 shadow 复跑中，G27 已不再是内容失败；第三轮能生成 `remove_units` pending，第四轮 `routingPath=pending_plan_short_text_confirm`，执行后刷新 `ordered/review` 并回答剩余数量和梯度。diff 中剩余差异是 expected 命名和 workspace refresh 期望比 runtime 更窄，不再是业务链路断裂。
- 2026-06-23 action-scoped 确认单测已覆盖：匹配 `generate_plan/add_units/remove_units/move_ordered_unit/regenerate_order` 时可直接 confirm；从 plan payload 回读 `action_family` 可 confirm；`remove_units` active pending 下 `确认生成方案` 不会执行。

Profile 价值：

- 测试复合 turn 拆解：pending apply 不应吞掉同轮明确只读查询。
- 为 TurnDecision 的 composite action 验收提供样本。
- 为 pending confirmation grammar 提供错配样本，防止确认短句重新退化成全局字符串白名单。

### G28 latency decomposition profile

- prompts：
  - `想学个好就业的 计算机或者电气自动化都行`
  - `如果强基没录上 普通批我这个分能冲什么学校`
  - `高收费的志愿占比多少 能不能换成便宜的`
- required metrics：
  - `firstMessageMs`
  - `agentRun.totalDurationMs`
  - `toolCallCount`
  - repeated tool count by name
  - `toolInternalDurationMs`
  - `finalMessageMs`
  - `runnerOverheadMs = finalMessageMs - agentRun.totalDurationMs`
- expected analysis：
  - 区分模型/工具真实长尾、重复工具查询、request limit、runner/WS 收尾长尾。
  - 错误兜底或 provider unavailable 不参与模型质量 median。

Observed：

- 2026-06-20 `comprehensive-low-score-vocational-420-sc#3` round2 中 `query_score_line` 46 次并触发 request limit。
- 2026-06-20 `comprehensive-major-group-beijing-465-bj#2/#3` 中 runner `finalMessageMs` 远高于 agent 内部耗时。
- 2026-06-20 `comprehensive-strong-base-plan-650-tj#4` 中 `query_admission_score` 20 次。

Profile 价值：

- 避免只用单一 elapsed 指标判断模型或系统性能。
- 指导 3.2.0 工具预算、batch query、流式收尾和 runner 统计修正。

### G29 soft preference strength calibration

- prompts：
  - `江南大学和苏州大学加进意向`
  - `新能源动力方向作为参考`
  - `河南大学和郑州轻工业大学可以重点关注`
  - `网络与新媒体优先，跨境电商也可以考虑`
- expected taskLayer：`intent`
- expected sideEffect：`intent_pending`
- expected structure：
  - `preferred` 或 `primary_preference`：明确优先项。
  - `acceptable_fallback`：可以考虑/作为备选项。
  - `hard_constraints`：空，除非用户明确说“必须/只要/不能没有”。
- forbidden：
  - 把 `加进意向/作为参考/重点关注/可以考虑` 直接编译成 `must_have`。
  - 把 `优先` 编译成 `only_keep`。
  - 丢弃 fallback 或 acceptable 备选项。

Observed：

- 2026-06-20 历史三轮回归中，`special-art-580`、`special-batch-cross-485`、`science-energy-power` 多次把软表达落成 `至少保留/must_have`。

Profile 价值：

- 量化模型能否稳定区分偏好强度。
- 若模型理解正确但 schema 承接不了，3.2.0 必须先扩 intent schema，而不是继续让 formatter 硬化。

### G30 special admission path preservation

- prompts：
  - `清华北大复旦的强基都加进意向`
  - `山西大学的本科和山西职业技术加进意向`
  - `如果强基没录上 普通批我这个分能冲什么学校`
  - `艺术类综合分580，央美国美这种美院系有没有机会`
- expected taskLayer：`intent / plan_query / policy`，按上下文区分。
- expected structure：
  - `school`、`major` 之外保留 `batchType/admissionPath/planType/qualification`。
  - 强基与普通批、本科与专科、艺术类与普通类不能被合并成普通学校/专业偏好。
- forbidden：
  - 只保留专业，丢掉强基学校和路径。
  - 把本科/专科混成同一普通院校偏好。
  - 用普通批风险结论替代艺术/强基路径边界。

Observed：

- `special-strongbase-655` 中强基学校和路径丢失，只剩基础学科专业。
- `special-batch-cross-485` 中本科和专科路径缺少结构承接。

Profile 价值：

- 判断 3.2.0 是否需要把特殊批次/路径作为一等字段。
- 为 proposal/apply 和 reply grounding 提供领域结构边界。

### G31 pending context should not block readonly fact query

- history：
  - 已存在未确认的 intent pending，例如“华中科技大学加进意向”。
- prompts：
  - `现在方案是按620湖北算的吧`
  - `先不确认，当前方案里有没有护理或者中医学`
  - `再给我看下保底学校`
- expected taskLayer：`plan_query / state_query`
- expected sideEffect：`readonly_while_pending`
- expected behavior：
  - 保留原 pending，不 apply、不取消。
  - 读取当前基础信息或方案事实。
  - 先回答用户问题，再提醒 pending 未采纳。
- forbidden：
  - 只解释 pending 边界。
  - 因存在 pending 而拒绝所有只读查询。
  - 把只读查询升级成 apply 或新 mutation。

Observed：

- `special-correction-630` 中用户问基础分数/省份状态时，只收到华科 pending 未采纳说明。
- 多个 science/score tier case 中 pending 抢占“当前方案里多吗/保底学校有哪些”等只读问题。

Profile 价值：

- 验证 pending 状态机是否能与只读查询共存。
- 作为 3.2.0 `readonly_with_pending_context` 的硬门禁。

### G32 no-plan referenced-plan defensive reply

- history：
  - 当前没有正式 ordered plan 或候选池为空。
- prompts：
  - `刚那个方案民办能少点不`
  - `方案里有没有民办的`
  - `保底是不是公办`
  - `冲档太冒险了删掉一个`
- expected taskLayer：`state_query / plan_query / clarification`
- expected sideEffect：`readonly` 或 `needs_plan_first`
- expected behavior：
  - 明确当前没有正式方案或没有可操作对象。
  - 不承诺“保底层全部公办”等无 evidence 结论。
  - 不创建当前方案 mutation pending。
- forbidden：
  - 在无正式方案 evidence 下生成删除/替换/排除当前方案 pending。
  - 把用户引用“刚那个方案”当作真实已生效方案。
  - 用候选或生成预览冒充正式方案状态。

Observed：

- `tier-mid-520-just-want-bachelor`、`robust-parent-child-dialog-600` 等场景中，无正式方案时仍可能生成或承诺当前方案相关结论。

Profile 价值：

- 区分 `generated preview`、`pending plan`、`formal ordered plan`。
- 为 3.2.0 evidence grounding 和 defensive reply 设计提供约束。

## 7. 3.1.1 与 3.2.0 推进边界

3.1.1 只做：

- 修复 P0 小问题。
- 修复 runner 统计口径。
- 修复前端确认卡状态展示。
- 补 P0 路径断言。
- 文档化 profile 计划和 3.2.0 硬切目标。

3.1.1 不做：

- 新 runtime shadow。
- 新长期 bridge。
- 新旧主路径并行。
- 为每个 profile 失败新增 service recovery。

3.2.0 做：

- 按 profile 结果实现唯一主控链路。
- 硬切前可增加短期只读 shadow diff，用于观测旧路径与 compiler output 差异；shadow 不参与裁决、不创建 pending、不写业务状态。
- 切换后删除旧恢复分支、旧 prompt 调度主路径和 legacy 兼容入口。
- 验证通过后不保留双路径。

## 8. 验收门槛

3.2.0 开始主路径实现前，profile 至少要给出：

- P0/P1 goldens 的混淆矩阵。
- `taskLayer / sideEffect / scopeAnchor / scenario` 四类错误 Top N。
- `targetIssue/focus` 保真率，尤其是 focused review 和大白话风险解释。
- `sideEffect` 过强率：readonly/intent 表达被升级成 plan mutation 的比例。
- `sideEffect` 过弱率：明确当前方案动作未生成 pending/preview 的比例。
- provider precheck 状态，未通过的 provider 不进入质量矩阵。
- 模型规划、工具执行和最终生成三段 latency profile。
- 模型可承担与必须系统兜底的能力边界。
- 对 compiler、guard、proposal schema 的约束清单。
- 需要删除的旧分支清单。
- 2026-06-20 历史三轮回归中 32 个 golden 候选的覆盖矩阵，明确哪些属于模型理解错误、schema 表达不足、compiler 约束缺失、formatter/protocol 落点错误或测试 fixture 噪声。

3.2.0 合并前：

- Goldens 不再依赖旧 recovery 通过。
- 每条高副作用 case 都能说明唯一 ToolPlan 和唯一 pending/apply 协议。
- 旧恢复分支和兼容入口已删除或有明确一次性迁移说明。
