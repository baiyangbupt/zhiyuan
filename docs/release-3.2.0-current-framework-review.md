# Release 3.2.0 Current Dialogue Framework Review

本文基于当前 3.2.0 实现状态，复盘最初设计、已经发生的结构调整、当前运行链路的完整性、常见对话场景覆盖、异常路径处理和后续维护约束。它是当前态文档，不替代历史 roadmap 和 structural analysis；历史文档里的早期节点、桥接和 benchmark 记录按时间保留，但以后判断“当前系统是什么样”以本文为准。

## 1. 当前结论

3.2.0 当前推进方向总体仍对齐最初目标：高副作用动作正在从多处 service/formatter/tool 后处理收敛到 `TurnDecision -> structured candidate -> ProposalCompiler -> pending/reply/apply`。已经删除了几类明确有问题的旧链路：

- 旧 runtime/model recovery 节点：`pending_action`、`plan_recovery_action`、`composite_goal`。
- 无结构化工具结果时从自然语言承诺反向补 pending/card 的恢复链路。
- service 里基于特定用户话术的 direct remove、tuition budget mutation、review/fix 补捞、plan_next 半桥接执行等路径。
- runtime 直接调用旧 `select_fix_proposal_candidate` 选卡路径。

但当前还没有完全达到最初理想的单一路径。`service.py` 仍承担大量编排、历史持久化、卡片挂载、回复清理、workspace refresh、异常兜底和若干结构化 reroute/refocus。当前可接受的原因是这些逻辑大多已经改成消费结构化状态或 compiler 输出，而不是 raw prompt 字符串；但它仍是后续继续拆分的主要风险点。

当前稳定性策略是：

- 业务语义进入 `TurnDecision / PlanQueryProfile / action DSL / ProposalCompiler`。
- service 只允许做协议编排、模型/工具调用、pending sink、历史保存、observability 和输出保护。
- 如果结构化路由缺失、模型节点失败、候选不满足 compiled contract，默认 fail closed，不创建 pending、不 apply、不把文本承诺升级成业务状态。

## 2. 初始 3.2.0 设计

roadmap 中定义的目标链路是：

```text
TurnDecision
  -> EvidencePlan
  -> ProposalCandidate
  -> ProposalCompiler
  -> Pending / Reply
  -> Apply
  -> Validate / Review
```

核心约束：

- 每轮只有一个 active side effect。
- `review_plan`、方案查询、候选查询只能作为 evidence step，不能直接绕成 pending。
- 工具和 formatter 不创建确认卡；确认卡只能来自 compiler 输出。
- 当前方案 mutation 必须有 formal plan evidence、可操作对象和 source version guard。
- active pending 存在时，短确认/取消是协议动作；只读查询可以保留 pending；新的高副作用诉求必须冲突澄清或先处理 pending。
- 无结构化候选时，模型文本中的“确认后执行/采纳/加入方案”不能生成 pending。

这个设计的本质不是把所有场景都写成规则，而是把“理解、取证、候选、编译、执行、验证”的职责拆开，避免 service 后处理在最后一刻补业务语义。

## 3. 当前实际结构

当前代码已经形成以下运行结构：

```text
用户输入
  -> service 加载 history / pending / score / profile / planning workspace
  -> TurnDecision 或场景专用 structured model node
  -> ProposalCompiler deterministic gate
  -> 必要时执行 plan_execution_tool 取证或 preview
  -> compiler sink contract 创建 pending card 或 readonly reply plan
  -> handle_pending_confirmation 受控 apply
  -> workspace refresh / review readback / history observability
```

当前不是所有路径都已经先生成完整 `EvidencePlan` 对象。实际落地分成几条已收敛的 typed source：

- `ProfileChangeReplanCompiledSource`：当前学生资料更新、临时测算、范围不明三类。
- `RuntimePlanQueryCompiledSource`：当前方案/待采纳上下文里的只读查询。
- `RuntimeCurrentPlanMutationCompiledSource`：intent preview 被 TurnDecision 判定为当前方案 mutation 时，转为方案预览。
- `RuntimeAtomicPlanActionSource` / `RuntimeLocalPlanActionSource`：原子方案动作和局部方案动作 DSL。
- `RuntimeReviewFixCompiledSource`：结构化 review/fix proposal 进入 Java FixProposal pending。
- `PendingTurnResolution`：active pending 下的 apply/cancel、apply 后只读、apply 后新请求、冲突、只读上下文。
- sink contracts：intent/plan/fix 三类 pending 创建前的 deterministic 校验。

也就是说，完整的抽象目标还在，但 runtime 先以一组 typed compiler source 逐步替换旧分支。

## 4. 发生过的关键调整

### 4.1 删除 recovery 节点

早期曾用 `plan_recovery_action`、`composite_goal`、`pending_action` 来弥补模型漏调工具、文本承诺无卡、复合目标不落 pending 等问题。现在这些节点已经删除，不再作为 runtime 或 benchmark-only 桥接维护。

当前替代方式：

- 方案动作进入 `classify_plan_atomic_action_dsl` / `classify_local_plan_action_dsl` 和 compiler。
- 复合 user-goal 只能消费已有结构化 tool result，并通过 compiled user-goal/fix/intent sink。
- active pending 语义进入 `TurnDecision -> compile_runtime_pending_turn_decision_source`。

### 4.2 hard cut 从“补救”变成“前置协议”

当前 hard cut 逻辑分三层：

- 协议级：active pending 下，短文本确认/取消可以直接消费当前 pending；没有 active pending 时，短确认只返回 no-pending guard。
- 业务级：active pending 下的只读查询、pending impact query、apply-then-readonly、apply-then-new-request 必须由 TurnDecision 和 pending compiler 决定。
- 输出级：如果文本承诺“确认后执行/采纳/加入方案”，但本轮没有 compiled pending/card，service 只清理或替换成无改动边界，不恢复业务动作。

这回答了 hard cut 的边界：短语匹配只允许识别“确认/取消”这类协议动作和清理无依据输出；不能用来判断“用户想删什么、查什么、改什么”。

### 4.3 当前方案状态优先

`formalPlanPresent=false` 时，用户提到“当前方案/刚那个方案/方案里”不能靠话术反推成有方案。当前逻辑通过 `needs_plan_first` guard 阻断当前方案事实查询和 mutation，不创建 pending。

如果有正式方案但 TurnDecision 缺失或失败，full-agent intent pending 会 fail closed，返回结构化路由校验边界，不保存 pending、不生成卡。这避免了“当前方案 mutation 被误写成未来偏好”的不一致。

### 4.4 pending 后续状态一致性

active pending 的阶段演进当前定义为：

- `confirm_pending`：只消费真实 active pending。
- `reject_pending`：取消真实 active pending。
- `readonly_while_pending`：保留 pending，执行只读 evidence/query。
- `conflict_with_existing_pending`：不创建第二个 pending。
- `apply_pending_then_readonly`：先 apply pending，成功后基于新 workspace 读证据；apply 或刷新失败时不追加执行后结论。
- `apply_pending_then_new_request`：先 apply intent pending，再创建新的 plan pending 或进入澄清；不直接 apply 新动作。

这使“前轮 TurnDecision 要 apply pending，但没有 active pending”的异常路径可定义为 no-pending guard，而不是重新规划新动作。

当前确认边界还应再细分为三类：

- intent preview 采纳后，默认刷新 `candidate`，不等同于当前方案已改变。
- 真实 plan mutation 只有在有可追溯 pending/card 时才会继续走 `ordered`/`review` 刷新。
- 没有 active pending 时，`确认/采纳` 必须返回 no-pending guard，不补创建新动作。

### 4.5 plan query 从 service 迁向 profile/compiler

当前方案只读查询不再用 service 里按 prompt 判断的业务快路由作为主依据。现在是：

```text
TurnDecision
  -> PlanQueryProfile
  -> compile_runtime_plan_query_profile_source
  -> execute_plan_action(query_*)
  -> grounded reply / pending boundary
```

这覆盖 pending 下的“先不确认，看看当前方案有没有 X”、普通方案列表/保底/梯度查询、缺分数/候选池的 missingInfo 边界。

### 4.6 review/fix 不再本地补救

Java `FixProposal`、dry-run、sourceVersionGuard、apply policy 仍是修复类执行权威。service 不能因为用户文本或回复 hint 去补捞 Java proposal 或恢复成本地原子动作。

当前 runtime 只有在结构化 `preview_fix_proposal` 结果、显式 selected proposal、唯一 ready proposal 或结构化 target 唯一命中时，才通过 `compile_runtime_review_fix_source` 生成 fix pending。

### 4.7 structured goal 仍是过渡区

旧 `composite_goal` 模型节点已删除。当前 service 仍会消费工具结果中的 `composite_proposal` 字段，但它表示结构化 proposal payload，不是一个独立模型 recovery 节点。代码已将内部 helper 命名收敛为 `structured_goal` / `structured_proposal`，后续应继续把这块迁到 compiler candidate 层。

## 5. 模块职责

| 模块 | 当前职责 | 明确不该做的事 |
| --- | --- | --- |
| `turn_decision_tool.py` | 输出 `taskLayer/sideEffect/scopeAnchor/scenario/missingInfo/profileScenario`，决定本轮业务层和副作用边界 | 不创建 pending，不调用业务工具，不写状态，不根据历史话术覆盖权威状态 |
| `plan_query_profile_tool.py` | 把只读方案查询转成 queryType、dimensions、filters、projection、missingInfo | 不裁决 mutation，不保存 pending，不回答用户 |
| `plan_semantic_action_tool.py` | 结构化 review/analyze/preview 边界、fix target scope、atomic/local plan action DSL | 不保留 plan recovery/composite goal/pending action 独立节点，不从文本承诺恢复执行 |
| `proposal_compiler.py` | deterministic 编译和 gate：pending turn、profile replan、plan query、current-plan mutation、review fix、sink contract、blocking reasons | 不调用模型，不读写后端状态，不从 raw prompt 推断业务对象 |
| `plan_execution_tool.py` | 执行或预览受控 plan action，查询当前方案/候选/审查事实，返回结构化 evidence/result | 不决定本轮 sideEffect，不保存 pending，不绕过 compiler apply policy |
| `service.py` | 加载上下文、调用模型/工具、应用 compiler 输出、保存历史、发卡、refresh、observability、异常兜底、输出清理 | 不新增基于 raw prompt 的业务路由，不从模型纯文本补 pending，不把 formatter 结果升级为 sideEffect |
| `dialog_regression_runner.py` / `model_node_benchmark.py` / `runtime_shadow_diff.py` | 验证、归因、观测、回归资产扩展 | 不参与 runtime 裁决，不写业务状态，不作为长期 shadow bridge |

## 6. 常见场景覆盖矩阵

| 场景 | 当前期望路径 | 失败/异常策略 |
| --- | --- | --- |
| 普通政策/兴趣只读 | full agent 或 readonly tool evidence，输出只读回复 | 不生成 pending；若回复含确认承诺则清理 |
| 未来偏好更新 | `TurnDecision(intent_pending/future_reference)` -> intent entity/profile -> compiler sink | schema 不完整则 blocking/clarification；不落当前方案 mutation |
| 当前方案只读查询 | `TurnDecision(readonly/current_plan)` -> `PlanQueryProfile` -> query compiler -> `execute_plan_action(query_*)` | formal plan 缺失走 needs-plan-first；缺 evidence 不编造事实 |
| 当前方案原子 mutation | `TurnDecision(plan_preview/current_plan)` -> action DSL / execute preview -> plan compiler sink | 缺 formal plan、缺 selector、缺 version、无 executable scope 都不创建 pending |
| review/fix 预览 | `review_plan` evidence -> `preview_fix_proposal` structured result -> review fix compiler | 多 ready proposal 且无唯一 target 不选卡；只读 review 不升级 mutation |
| active pending 短确认 | protocol direct confirm -> `handle_pending_confirmation` | 无 active pending 返回 no-pending guard |
| active pending 短取消 | protocol direct cancel -> expire pending | 不执行、不创建新 pending |
| pending 下只读查询 | `readonly_while_pending` -> query profile/compiler -> 保留 pending | 先回答问题，再提醒 pending 未采纳 |
| pending impact query | `readonly_while_pending/pending_reference` -> pending state reply/evidence | 不 apply，不取消，不重新生成 |
| apply 后只读 | `apply_pending_then_readonly` -> apply -> refresh/read evidence -> reply | apply/refresh 失败时只返回执行或证据边界 |
| apply 后出方案 | `apply_pending_then_new_request` -> apply intent -> generate plan pending | 不直接正式生成方案；仍需新 pending 确认 |
| pending 冲突新 mutation | `conflict_with_existing_pending` | 不创建第二张卡，不覆盖旧 pending |
| 无正式方案但问方案内事实 | `needs_plan_first` | 不把“刚那个方案”当 evidence |
| profile 更新重算 | `profile_change_replan` -> compiled profile DSL | 标记旧方案未按新资料重算；不自动改当前 profile 或方案 |
| 临时测算/帮别人问 | `profile_replan_adhoc` | 不让当前方案继承临时资料 |
| profile 范围不明 | `profile_replan_ambiguous` | 先澄清，不 invalid 当前方案 |
| 局部专业组策略 | `current_major_group/readonly` 或 local DSL | 不写成长期“稳定就业导向” |
| 模型文本承诺但无结构化候选 | output guard | 清理承诺，不补卡 |

## 7. 异常路径和一致性约束

### 7.1 模型节点失败

- 当前有正式方案或 active pending，且结构化路由不可用时，高副作用路径 fail closed。
- 只读回复可以降级到已有工具 evidence、workspace state 或安全边界，但不能落 pending。
- provider/API key/model 不可用应归因到 `provider_env`，不能当作模型质量或业务成功。

### 7.2 工具返回不完整

- preview 缺 `atomic_actions`、缺 selector、缺 `resolved_apply_payload`、缺 source version 或 action family 不在白名单时，不创建 pending。
- Java fix proposal 缺 actions、缺 ready、缺 version guard 或 target 不唯一时，只能 readonly/clarification。
- query 返回空时必须区分 missingInfo、empty plan、filter no result、tool error，回复不能把无分数/无候选说成“按你当前分数不够”。

### 7.3 pending 状态异常

- 没有 active pending 时，`确认/采纳/执行` 不能创建新动作。
- pending stale/version drift 时，先 expire 或要求重新生成预览。
- pending kind 与用户确认入口不一致时，返回 mismatch guard。
- pending apply 成功但 workspace refresh/readback 失败时，不追加“执行后结果如何”的事实结论。

### 7.4 回复和状态不一致

- 有 compiled pending/card 时，primary reply 以 card payload/compiled summary 为准。
- 没有 card 时，回复中不得出现“点确认后执行/已整理可采纳内容”等暗示。
- 输出保护可以使用文本 marker 清理模型话术，但不能反向识别业务意图或创建状态。

## 8. service 中仍需控制的区域

当前 service 里仍保留以下过渡职责，需要继续拆，不应继续扩：

- review refocus：基于结构化 review result 和 semantic target 重跑 focused review 的 payload/evidence 编译已迁入 `ProposalCompiler`。service 仍负责调用 semantic classifier、执行 `review_plan` 和合成回复；入口处的解释类 raw prompt guard 仍是过渡保护，不能继续扩展成业务路由。
- review-to-fix-preview：review/analyze 后按结构化 target 转 `preview_fix_proposal` 的 payload/target scope 编译已迁入 `ProposalCompiler`。service 仍负责执行 preview、选择 Java proposal、落 pending sink 和渲染回复。
- structured goal candidate 消费：`composite_proposal`/structured goal result 到 Java user-goal request、intent fallback payload、clarification resolution 的输入编译已迁入 `ProposalCompiler`。service 仍负责调用 Java proposal endpoint、落 pending sink 和渲染卡片，但不再本地解析结构化 goal scope。
- reply cleanup/guard：当前仍在 service 里做无依据确认话术清理、内部词归一、fallback reply。它是输出保护，不应参与业务路由。
- workspace refresh/presentation：`execute_plan_action` result/call family 到 `workspaceRefreshTargets/workspaceViewTargets` 的确定性编译已迁入 `ProposalCompiler`。semantic plan action 的 `displayPayload/replyPlan` 也已迁入 `ProposalCompiler`。service 仍负责解析当前 turn 的 tool message、构造 WS followup、处理 history/observability；其它 reply fallback/display contract 仍待统一到 compiler 输出。

需要继续禁止的 service 行为：

- 新增 `_prompt_requests_*` 这类从用户措辞直接裁决业务动作的 helper。
- 从纯文本回复恢复 pending/card。
- 在 service 里展开 Java fix proposal 选择策略或本地候选补足策略。
- 为某个 golden case 增加特定字符串分支。
- 保留“旧节点名 + 新逻辑”的桥接命名，容易让后续误以为双路径存在。

## 9. 当前完备性评估

当前链路对常见用户场景已经比 3.1.1 多路径状态更完整：

- 意向、方案、pending、profile replan、只读查询、review/fix、no-plan reference 都有结构化边界。
- active pending 的常见复合 turn 已定义，不再把所有文本压成 apply。
- 无结构化候选不会补卡，文本承诺和真实状态的一致性更稳。
- 旧 recovery 节点已删除，并有 hard-cut audit 防止回流。

仍不完备的地方：

- 还没有全量统一 `EvidencePlan -> ProposalCandidate` 对象，runtime 仍是 typed compiler source 逐步收敛。
- service 仍是过大的 orchestrator，尤其 review refocus/reroute 的模型调用与工具执行、structured goal 的 Java 调用与 sink 编排、reply cleanup、workspace WS followup 构造仍缠在主流程。
- plan query 还在 Python query path，Java 统一 `PlanQueryCondition` 未完成。
- `selectableProposal/suggestedTransition` 还没有成为一等结构，所以“只读建议后用户说确认”的体验仍主要靠 no-pending guard。
- display/replyPlan 已开始由 compiler 输出：semantic plan action 的 conditional options/confirmation/readonly presentation 已迁入 compiler；其它 fallback reply 与非 semantic display contract 仍未完全统一。

结论：当前不是要再做一次大方向推翻，而是继续把 service 中剩余的结构化过渡区迁入 compiler/EvidencePlan，并用 audit/golden 阻止旧补丁层回流。

## 10. 后续推进顺序

P0:

- 把本文作为当前设计入口，后续新增 runtime 行为必须先说明归属模块和 sideEffect 契约。
- 扩大 G1-G32 和 mainline live regression，优先统计语义正确性：sideEffect、pendingType、card presence、display/replyPlan、workspace refresh/view、no unbacked commitment。
- 继续审查 service helper：凡是业务路由依赖 raw prompt marker 的，迁入 TurnDecision/DSL/compiler 或删除。
- 将 structured goal candidate 消费迁入 compiler candidate 层，service 只处理 sink result。

P1:

- 定义 Java `PlanQueryCondition`，把 ordered plan/candidate pool 查询条件、projection、no-result reason 统一。
- 把 review focus/refocus 变成 EvidencePlan/ReviewFocusBinder，不作为 service reroute。
- 让 compiler 继续统一其它 `displayPayload/replyPlan` 与 fallback reply，并把 workspace/display presentation source 接入更完整的 `EvidencePlan -> ProposalCandidate` 对象，减少 service fallback reply 分支。
- 增加 `selectableProposal/suggestedTransition`，让低副作用建议和短确认状态一致。

P2:

- Tool budget/batch query 接入 runtime，减少长尾和重复工具。
- plan local action DSL 到 Java proposal endpoint。
- Explorer issue normalization 和 golden promotion 自动化，避免 case 修复留在临时报告。

## 11. 新行为准入清单

新增或修改对话链路前必须回答：

- 本轮 sideEffect 从哪里来：TurnDecision、PlanQueryProfile、action DSL 还是 compiler？
- 是否有 formal plan / pending / candidate pool / profile evidence？
- pending/card 是否能追溯到 compiled proposal 和 sink contract？
- apply 失败、version stale、workspace refresh 失败时如何 fail closed？
- 回复是否只渲染 evidence/compiled output，是否可能无卡承诺确认？
- 是否增加了 service raw prompt 业务路由？如果是，不能合入。
- 是否有 node benchmark、compiler/unit regression、dialog regression 或 audit 覆盖？

只要这些问题不能回答清楚，就不能把逻辑塞进 service 主流程。

## 12. 效果回归开闸标准

这里的“效果回归”指用户可见对话效果，不是手机端适配。当前不能把最终效果验收提前到协议仍在迁移期间，否则会把协议差异、回复表现和前端展示混成同一类问题。3.2.0 后续按三层启动：

### 12.1 现在可以启动的回归

可以立即启动“协议/效果冒烟”：

- 使用隔离环境：Backend `18290`、Agent `18291`、Rank `18292`、Web `3201`。不再使用历史 `8000` 或错后端端口做结论。
- 跑当前代码的 G1-G32 isolated live/shadow，输出 metrics、runtime shadow observation 和 diff。
- 重点观察用户可见协议字段：`sideEffect`、`pendingType`、pending card presence、`displayPayload.presentation`、`replyPlan.focus`、`workspaceRefreshTargets/workspaceViewTargets`、无卡确认承诺、apply 后 readback 边界。
- 回归结果必须按 `compiler_gap / runtime_service_gap / model_schema_gap / fixture_mismatch / provider_env / latency_longtail / frontend_display_gap` 归因，不能只记录“文案不顺”。

这一层可以现在开，因为它服务于框架收口，目标是发现协议和效果不一致，不作为最终发布验收。

### 12.2 正式效果回归开闸

正式效果回归应在最近一轮 current-code G1-G32 isolated live/shadow 达到以下门槛后启动：

- content failure 为 0，或只剩明确非框架阻塞的 provider/env 问题。
- shadow diff 中 `blocking=0`，`major=0`；剩余 `info/missing_observation` 必须有 fixture 或覆盖原因。
- card presence、`displayPayload.presentation`、`replyPlan`、workspace refresh/view 与 compiler contract 一致。
- 没有“无 pending/card 但回复要求确认执行/采纳/写入”的用户可见承诺。
- active pending 下的只读、apply-then-readonly、apply-then-new-request 和 conflict 场景均能保持单一 active side effect。
- G7/G12/G17/G21/G27/G31 等长尾 case 有 latency 归因，不把耗时问题伪装成回复效果问题。

达到这个门槛后再开完整用户效果回归，才有意义区分“协议已经对齐但体验需要优化”和“协议还没对齐导致前端/文案表现混乱”。

### 12.3 最终效果验收范围

最终效果验收不只看回复文本，应覆盖：

- 只读问答：政策/兴趣/当前方案查询不会创建 pending，不会刷新不该刷新的 workspace。
- 意向待采纳：卡片摘要、selectedData、displaySummary 和回复一致；未确认前不声称已写入。
- 当前方案 mutation：必须有确认卡、可执行 payload、source version guard；确认前不改方案。
- review/repair：`conditional_options`、`confirmation_card`、`readonly_answer` 三种 presentation 与回复一致。
- active pending 复合 turn：短确认/取消、先不确认只读、删完了再看、先采纳再出方案、新高副作用冲突。
- apply 后 readback：成功后只回答有 evidence 的数量、梯度、风险；刷新失败时 fail closed。
- workspace 行为：只读 evidence 只开 view 或不动作，mutation preview/apply/post-apply 才刷新目标视图。

## 13. 2026-06-25 实现收口记录

本轮继续按“service 只编排，compiler 做确定性裁决”的方向收口，重点不是补新 case，而是把输出保护、原子方案动作入口和回归资产契约继续向结构化协议靠拢。

### 13.1 Reply guard 迁入 compiler

- 新增 `RuntimeReplyGuardSource` 和 `compile_runtime_reply_guard_source`，统一裁决以下输出保护：
  - 无 pending/card 但回复要求确认执行当前方案调整。
  - 无 pending/card 但回复表现为已列出调整预览。
  - 无 intent pending/card 但回复声称已写入后续报考参考。
  - 无工具/无 pending 的兜底动作边界。
- 将 service 中的 `_reply_has_plan_confirmation_request`、`_remove_unbacked_plan_confirmation_copy`、`_reply_claims_intent_recorded_without_pending`、`_normalize_unbacked_no_tool_action_boundary` 等判断改为委托 compiler；service 保留边界文案渲染、history 替换和响应编排。
- `proposal_compiler.py` 现在承担 reply guard 的 deterministic source；`service.py` 不再展开这类 marker 规则，也不从这些规则反向创建 pending/card。
- `test_proposal_compiler_runtime_selection.py` 增加 reply guard 单测，覆盖无卡确认、预览无卡、无 pending 记录意向、no-tool 边界。
- `test_runtime_hard_cut_audit.py` 增加审计，阻止无卡确认承诺判断重新散回 service。

### 13.2 官方来源工具循环输出保护

`BaseAgent` 的重复工具调用 guard 原来会在 `search_official_admission_sources` 连续触发时复用最近一次 tool return。该 tool return 是 JSON 协议字段，包含 `reply_strategy/raw_result_count/results` 等内部字段；如果 guard 直接把原文拼回用户回复，就会把协议 payload 暴露给用户。

当前修复只改用户侧渲染，不改工具协议：

- `render_tool_loop_guard_output_from_history()` 读取最近 tool return 后，会通过 `_tool_return_user_text()` 做工具类型化转换。
- `search_official_admission_sources` 的 JSON 会被 `_official_source_search_user_text()` 转成用户可读的官方来源摘要、来源标题和链接；解析失败时才退回原文本。
- 新增 `test_run_repeated_official_source_loop_renders_json_as_user_text`，固定重复 official-source loop 下不泄漏 `reply_strategy/raw_result_count/results`。

这属于输出保护，不参与意图识别，也不创建 pending。

### 13.3 Atomic plan action 入口接入 TurnDecision gate

`RuntimeAtomicPlanActionSource` 新增 `turn_decision_dsl`，`compile_runtime_atomic_plan_action_source()` 支持 `turn_decision` 和 `require_turn_decision`。当前方案原子动作的直接入口必须先满足：

- `TurnDecision.taskLayer=plan`
- `TurnDecision.sideEffect=plan_preview`
- `TurnDecision.scopeAnchor=current_plan`
- `TurnDecision.scenario=atomic_mutation`

`service._maybe_handle_direct_atomic_plan_action()` 现在先用 compiler probe 校验 TurnDecision，再调用 `classify_plan_atomic_action_dsl`。如果 Atomic DSL 编译失败，阻断原因会写入 `agent_observability.atomicPlanActionCompiler`；如果通过，则把 `turnDecisionDsl` 和 `planActionDsl` 写入 routeDecision。这样 G27 这类“当前方案中按学费和意向贴合度删除”的入口不再依赖旧 review history 或 service 里的中文话术分支。

验证点：

- `test_compile_runtime_atomic_plan_action_requires_current_plan_turn_decision`
- `test_compile_runtime_atomic_plan_action_keeps_turn_decision_dsl`
- `test_chat_service_direct_atomic_plan_action_creates_remove_units_pending`

### 13.4 G27 回归资产契约修正

G27 原始目标是 `apply_pending_then_readonly`：用户已有 active plan pending 后说“删完了再帮我看看还剩多少个，梯度有没有问题”，系统应先 apply 当前 pending，再基于执行后的 ordered/review evidence 回答。

之前 live shadow case 把两件事绑在一个 journey 里：

1. 先动态制造一个“删除两万以上且不贴合意向”的 pending。
2. 下一轮再验证 apply-then-readonly。

这不是稳定 fixture。当前探针拆出了两个问题：

- source35 当前方案中“两万以上”命中 0，动态删除会 `no_change`，不会生成 pending。
- source26 虽有高学费项，但缺少稳定用户意向/profile 贴合 evidence，“两万以上且跟我意向不沾边”仍可能 `no_change` 或回 full-agent。

所以不能为了 G27 伪造 pending，也不能把 `no_change` 强行升级成 pending。当前回归资产已改为：

- `320-shadow-G27-tuition-readonly-and-atomic-selector-observation`：只验证当前方案学费阈值只读查询，以及 `TurnDecision + AtomicPlanActionDsl` 能进入 `remove_units` 工具链；`preview_only` 和 `no_change` 都是合法执行层结果。
- `G27-apply-pending-then-readonly-followup` 仍保留在 profile golden 和 unit contract 中，fixtureContract 明确要求 `activePending + orderedPlan`。
- 后续要把 G27 放回 live 效果回归，必须先提供显式 active `plan_mutation` pending fixture。可选做法是让 runner 支持审计化 `seedPendingConfirmation`，但 seed 内容必须来自真实 preview sink 或 Java FixProposal sink，包含已解析的 `resolved_apply_payload` 或 `proposalId/sourceVersionGuard`，不能在 runner 里手写 selector 绕过 sink contract。

runner 同步增加 `assertResultKindsContainAny`，用于表达这类“同一协议下 preview/no-change 均可接受”的观测断言，避免把数据命中差异误判成框架失败。

### 13.5 本轮回归状态

已完成的 focused live/单测结论：

- G30 focused live：3/3 successful，未复现官方来源 JSON 泄漏；泄漏路径由 `test_base_agent.py` 单测固定。
- G27 source35/source26 focused 探针：验证 atomic TurnDecision gate 已接通，`routeDecision` 能包含 `TurnDecisionDsl` 和 `AtomicPlanActionDsl`；剩余失败归因为 fixture mismatch，而不是 runtime 入口断链。
- 当前不能开正式效果回归。可以继续开“协议/效果冒烟”，但正式效果回归需要先清理 G27 这类 fixture contract，至少不能把动态 pending 生成失败算作 apply-then-readonly 失败。

本轮启动过 Agent 18291 以跑 focused live，Backend 18290 和 Rank 18292 保持运行。下一步应先跑 current-code G1-G32 isolated live/shadow 协议冒烟，并把失败按 `compiler_gap / runtime_service_gap / model_schema_gap / fixture_mismatch / provider_env / latency_longtail / frontend_display_gap` 归因；达到 12.2 后再开完整用户效果回归。

### 13.6 2026-06-25 G1/G2/G19 收口

这轮把两个真实缺口收干净了：

- `full_agent` 兜底现在也写 `displayPayload/replyPlan`，带修复选项的 review/fix boundary 会稳定落 `conditional_options`；纯只读风险审查仍保持 `readonly_answer`。
- plan confirmation candidate 在缺少显式 `target_view` 时默认走 `ordered`，G1 的 pending card 现在会带 `planningWorkspaceAction(ordered)`，不会只剩卡不带刷新。

最新 live shadow 结论：

- G1：`followupTargets=["ordered"]`
- G2：`displayPayload.presentation="conditional_options"`
- G19：`needs_plan_first`

这意味着当前剩余问题已经不是展示/挂载层面的临时补丁，而是后续继续拆 service 过渡区时要保持的统一协议。

### 13.7 本轮实现细节

- `full_agent` 路径现在也会复用 compiler 的 semantic plan display contract；只要当前 turn 是带修复选项的 review/repair preview 且没有 pending card，就会写 `displayPayload={"presentation":"conditional_options"}` 和对应 `replyPlan`，纯只读审查仍保持 `readonly_answer`。
- plan confirmation candidate 在没有显式 `target_view` 时默认按 `ordered` 编译，`compile_plan_confirmation_proposal()` 也会同步写入 `workspaceRefreshTargets=["ordered"]`，因此 direct atomic / plan pending 不再只挂卡不挂刷新。
- focused live 已复核：G1 有 `planningWorkspaceAction(ordered)` + `pendingConfirmationCard`，G2 保持 `conditional_options`，G19 稳定 `needs_plan_first`。

### 13.8 方案生成 pending 的前置条件

full-journey 回归暴露出一个真实协议问题：在没有完整分数资料、没有正式方案的上下文中，runtime 仍可能把“优先保留广西师大统计”一类诉求编译成 `generate_plan` 待确认卡。用户看到的是“确认生成方案”，但确认后执行层才发现缺省份、分数、选科等基础资料。这不是文案问题，而是 pending sink 过早承诺了不可执行动作。

当前收紧为 sink feasibility 规则：

- `generate_plan` 属于高副作用方案生成动作，只有在 compiled proposal 已存在且基础 score evidence ready 时才允许创建 `pendingConfirmationCard`。
- score evidence 的最低条件是：省份非空、总分大于 0、选科列表非空。后端 `subjectList` 兼容对象列表和字符串列表，避免解析格式差异把有效选科误判为空。
- 不满足条件时，`_create_runtime_compiled_plan_pending()` 返回 `missing_generate_plan_score_detail`，不保存 pending、不发卡、不把自然语言承诺升级成业务状态。
- 这条规则不是针对具体中文 case 的补丁；它是 `ProposalCandidate -> pending sink` 的可执行性约束。当前落在 service，是因为 plan pending 的保存/发卡仍由 service 编排。长期归属应迁到 `ProposalCompiler` 或 `EvidencePlan` feasibility contract，让 compiler 统一表达“可执行/缺什么/是否能落 pending”。

同轮还收紧了无 pending 短确认入口：

- `analyze_adjustment/adjustment_analysis` 是只读分析或建议，不再允许下一轮短“确认”绕过 no-pending guard 进入 full-agent。
- 无 active pending 时，短确认只能返回 no-pending 边界；只有结构化 review 结果带 ready `fix_proposals`，或 `preview_fix_proposal` 已形成可继续预览证据时，才允许进入后续 agent 路径。

新增单测：

- `test_runtime_plan_pending_blocks_generate_plan_without_score_detail`
- `test_chat_service_blocks_adjustment_analysis_confirmation_without_pending_action`

### 13.9 当前剩余风险

- `generate_plan` 前置条件目前只覆盖最低 score readiness，候选池、批次、招生计划版本、profile completeness 仍应继续进入 EvidencePlan feasibility，而不是在 service 中扩散更多局部判断。
- full-journey focused live 仍观察到 candidate refresh 长尾，曾出现 120s runner timeout、180s service timeout。这是 `full_agent/tool loop` 的 latency debt，不能通过放宽断言掩盖。
- full-agent 后的 plan confirmation candidate、workspace refresh 和 display reply 已收敛一部分，但 service 仍承担过多 sink 编排。后续要继续把 Java proposal 调用、workspace target、reply plan fallback 迁入 compiler/EvidencePlan。

### 13.10 不可执行 mutation preview 的统一边界

本轮 focused live 还暴露出另一类结构问题：full-agent 已经通过结构化工具链进入 `add_units/replace_units` preview，但执行层返回 `result_kind=error`、`reply_focus=needs_volunteer_selection / missing_inputs` 时，最终用户回复仍可能残留模型原话，例如“信息还不够完整”“还没有唯一匹配”，没有明确说清“这轮没有生成可执行调整内容、不会改动当前方案”。

当前收口为统一 reply guard：

- 只要本轮没有 pending/card，且最新高副作用 `execute_plan_action` 结果本身就是 `error/no_change/preview_only(non-actionable)`，service 会复用 `_non_actionable_plan_preview_boundary()` 覆盖模型原回复。
- `needs_volunteer_selection` 现在明确落“没有生成可执行的调整内容 + 不会改动当前方案 + 重新定位影响范围”边界，不再只说“没唯一匹配到志愿”。
- `missing_inputs` 现在明确提示这是生成或加入方案所需的基础信息缺失，例如省份、分数/位次、选科，并声明不会改动当前方案。
- 这条 guard 仍然只消费结构化 `action_family/result_kind/reply_focus/missing_inputs`，不按 case 文本匹配。

新增单测：

- `test_chat_service_rewrites_latest_non_actionable_plan_mutation_error`
- `test_chat_service_rewrites_add_units_missing_inputs_boundary`

### 13.11 intent / constraint 的稳定语义边界

当前 3.2.0 的 intent 语义已经不再是单一 `constraintIntentType`。稳定边界应按四层理解：

- `preferenceStrength` 是语义强度层，描述“这句话是优先参考、普通偏好、可接受备选，还是硬排除”。
- `constraintIntentType` 是合同层，只描述这轮是否进入硬约束合同，取值只保留 `default / only_keep / must_have`。
- `goal_type` 是动作层，决定是 `only_keep_scope / must_include_scope / exclude_scope / tuition_budget_scope / prefer_scope` 这类可执行目标。
- `policy / compiler` 是决策层，决定软偏好只影响排序/补位/展示，还是要进入 pending / apply contract。

语义规则以代码为准：

- `primary`：明确优先、首选、最想要。
- `preferred`：普通偏好、感兴趣、加到意向、加入后续参考。
- `acceptable`：也可以、也能接受、作为备选。
- `must_have`：至少要有。
- `only_keep`：只保留、只考虑、只看这些。
- `exclude_soft`：轻度不优先。
- `exclude_hard`：明确不要、必须避开、排除。

协议上的关键分界：

- 软偏好只应该影响 `candidate` 排序、补位和展示，不应自动升级成 `must_have` 或 `only_keep`。
- `only_keep / must_have / exclude_hard` 才进入结构化 contract。
- `只考虑江苏浙江` 走 `only_keep` 是正确的，因为它是合同层“只保留”语义，不是普通偏好。
- `优先参考` 不能自动升级成 `must_have`。
- `必须避开` 不能降级成 `exclude_soft`。

当前落地链路是：

`intent_entity_profile_tool` 抽取 `preferenceStrength/entityPolaritySpans`
-> `service` 只做 selectedData/summary 组装
-> `proposal_compiler.resolve_intent_*`
-> `compile_intent_preview_proposal`
-> intent pending / apply

这里的长期要求是：`future_reference` 只表示未来参考的 scope，不代表一定要落 `candidate` 或 `ordered`；真正是否刷新 `candidate` 还是 `ordered`，由 intent contract 和 apply 结果决定。软偏好确认后通常刷新候选推荐和展示，硬约束确认后才可能触发更强的方案侧刷新。

### 13.12 无正式方案时的 mutation / intent 分界

本轮 live 回归确认了一个框架层面的歧义：用户说“把会计审计相关替换成新媒体或跨境电商相关”时，模型可以抽出 `新媒体 / 跨境电子商务` 作为正向偏好，但句子的动作锚点是“替换”。如果当前没有正式方案，系统并没有可替换的 plan referent。继续把它落成 intent pending 会让用户误以为已经存在可执行调整对象，后续短“确认”也会错误采纳一个并未明确声明的未来偏好。

当前收紧为 compiler guard：

- `resolve_needs_plan_first_guard()` 新增 current-plan mutation 动词识别：删除、移出、去掉、替换、换成、换掉、调整、重排、排序、移动、挪到等。
- 在 `formalPlanPresent=false` 且没有“以后/后续/偏好/意向/记录”等未来参考锚点时，这类 mutation 统一返回 `needs_plan_first / no_referent`，不允许 runtime intent hard cut 抢先生成待采纳卡。
- 这不是针对“会计审计”或“新媒体”的 case 补丁；它是 `EvidencePlan` 层的 referent feasibility：plan mutation 必须有当前方案或明确的未来参考语义，否则只能给无方案边界。
- “以后少推荐民办，优先公办”“把华中科技大学加到意向”这类未来参考仍可继续进入 intent pending，不被该 guard 拦截。

新增/更新验证：

- `test_needs_plan_first_guard_blocks_plan_mutation_without_formal_plan_referent`
- `test_chat_service_needs_plan_first_guard_blocks_no_plan_mutation_before_intent_hard_cut`
- `full-journey-major-soft-hard-adjust-review` 同步收紧第 8/9 步断言：无正式方案时替换请求返回 needs-plan-first，后续短“确认”返回 no-pending guard。

### 13.13 本轮 focused live 回归结果

使用临时 agent `127.0.0.1:18298` 加载当前代码，后端 `18290`、rank `18292` 保持现有服务。输出文件：

- `/tmp/dialog_regression_320_stable_region_20260625.json`
- `/tmp/dialog_regression_320_major_soft_hard_after_guard_20260625.json`

结果：

- `full-journey-career-stable-region-fix-boundary`：9 steps，8 successful，1 failed。
  - 失败是首轮“我先想看看体制内和读研哪个更适合我，别急着给我改方案” request timeout，runner 150s 超时，服务端 180s 超时。
  - 日志停在 `_maybe_handle_runtime_intent_hard_cut -> classify_turn_decision` 的模型请求链路，属于 provider/full-agent 长尾，不是协议失败。
  - 后续链路验证通过：`先把体制内稳定就业当成优先参考` 走 `preference/default`，确认后 `followupTargets=["candidate"]`；`地域上只考虑江苏浙江，东北西北都先排除` 走 `constraint/only_keep`，确认后 `followupTargets=["ordered","candidate"]`。

- `full-journey-major-soft-hard-adjust-review`：10 steps，10 successful。
  - `网络与新媒体` 抽为 `preferenceStrength.primary`，`跨境电子商务` 抽为 `acceptable`，确认后只刷新 `candidate`。
  - `会计/审计不要，必须避开` 抽为 `exclude_hard`，进入 constraint pending，确认后刷新 `ordered + candidate`。
  - 无正式方案下的“把会计审计相关替换成新媒体或跨境电商相关”现在稳定走 `needs_plan_first_guard`，不会生成新的 intent pending。
  - “调整后再帮我审查一下”在无正式方案下也走 `needs_plan_first_guard`，不再进入 `full_agent -> replace_units error` 长路径。

当前剩余风险：

- intent hard cut 仍依赖 `TurnDecision + intent_entity_profile + side_effect_arbitration` 多次模型请求，典型 intent pending 仍在 17s-23s 区间；这是 latency debt。
- 专业对比/方向探索仍会触发多工具、多轮模型请求，最大约 30s。本轮没有立即处理，因为这是 full-agent/tool-loop 架构债，不应靠压缩断言掩盖。
- `TurnDecision` 对无方案审查/调整语义仍可能在 reason 中自相矛盾；当前 compiler guard 能兜住无 referent 的 mutation，但长期应把 referent feasibility 前移到 EvidencePlan，减少 service 里的多处前置 guard。

### 13.14 本轮协议收紧与 live 回归补充

本轮继续做的不是补业务 case，而是把两个仍容易漂移的边界收成稳定协议：

- `candidate_pool readonly + missing score/rank`：
  - 当前用户说“候选列表按计算机方向刷新一下，先看当前能选的结果”这类话时，真实语义是候选池查询，不是生成正式方案。
  - service 新增候选池缺信息边界回复：当当前 turn 已经表现为 `plan/readonly/candidate_pool`，且工具结果显示缺 `score_or_rank` 或当前候选未生成时，优先保留“候选/方向/结果/分数位次”语义，不再泛化成“要生成志愿方案”。
  - 这一步仍不创建 pending，也不刷新 workspace；只是把 query contract 写清楚。

- `needs_plan_first` 用户文案统一：
  - 无正式方案时的 move/remove/replace 等 plan mutation，回复统一包含“当前还没有生成正式方案”“不会改动当前方案/不会改动方案”。
  - 这样 live 行为、单测断言和 fixture 断言使用的是同一套边界文案，不再因 service cleanup 的不同改写分支出现漂移。

新增验证：

- `test_chat_service_candidate_pool_missing_info_preserves_candidate_query_boundary`
- 复跑 focused 集合 13 条：全部通过。
- `py_compile app/service.py app/tools/intent_entity_profile_tool.py app/domain/proposal_compiler.py app/tools/turn_decision_tool.py`：通过。
- `git diff --check`：通过。

新增 live 结果：

- `full-journey-candidate-refresh-results-add-apply`：5/5 passed。
  - 第 2 步“候选列表按计算机方向刷新一下，先看当前能选的结果”不再掉到 `generate_plan missing_inputs` 的泛化回复，而是稳定保留 candidate query 语义。
  - 第 3 步“湖北工程学院的计算机科学与技术如果在候选里，就加入方案”当前仍是只读候选确认边界，没有 pending；这是符合当前实现的，但说明“条件式 candidate add”还没有统一迁回 compiler contract。
  - 首步仍出现 `105s` 长尾；日志显示真正的 candidate query 工具耗时约 `3.3s`，长尾主要在前置模型/agent 链路，不是 query tool 本身。

- `full-journey-school-region-major-group-unit-adjust`：9/9 passed。
  - `把第3个专业组移到第5位` 在无正式方案下仍然不会生成 pending；本轮 fixture 已按当前 3.2.0 真结构收紧，不再假设必须返回某一个旧文案。

本轮之后仍保留的工程债：

- `candidate_pool` 查询大多还在 `full_agent + query_volunteer_plan` 路径，虽然协议已经收紧，但首轮 candidate query 仍可能出现明显长尾；长期应把候选查询 DSL 和 missing-info 判定前移到 `EvidencePlan/PlanQueryCondition`。
- “如果合适就加入/优先保留”这类条件式 candidate mutation 仍在 `intent preview / readonly candidate query / non-actionable boundary` 之间摆动，尚未形成统一 compiler candidate。当前先保证不会错误地产生 pending 或 apply。
- no-plan 当前方案查询/调整虽然已有 compiler guard，但 full-agent 仍可能先给出不一致 reason，再由 service 后处理收口；这说明 referent feasibility 还没有完全从 service 迁走。

### 13.15 条件式候选加入的只读边界

本轮继续收紧 `如果合适就加入 / 如果在候选里就加入` 这类条件式 candidate mutation。它表面包含“加入方案”，但执行前置条件不是完整 plan mutation，而是候选池可行性和候选选择是否成立：

- 如果缺分数、位次、选科、省份等基础输入，不能创建 `add_units` pending，只能返回候选可行性缺信息边界。
- 如果还没有定位到具体候选，不能把“如果合适”解释成已选中目标，也不能创建 pending；只能提示先补学校、专业、地域等筛选范围，或在候选列表里点选目标。
- 如果执行层返回 `no_change` 或候选里没有稳定命中，仍是 readonly feasibility result，不会加入方案、不会改动当前方案。

实现上新增 `ConditionalCandidateReadonlyBoundaryResolution` 和 `resolve_conditional_candidate_readonly_boundary()`，由 compiler 基于结构化 `action_family/result_kind/reply_focus/missing_inputs/summary` 判断是否命中只读边界。service 只负责把这个 resolution 渲染成用户回复，并清空不该刷新的 workspace target。

本轮同时清掉了一个不符合框架原则的回复层残留：早期 helper 为了让 focused case 的文案更自然，曾在 service 中内置 `广西师范大学 / 广西师大 / 湖北工程学院 / 统计 / 会计 / 审计 / 计算机` 等样例词做回显。这些词不参与路由或 pending 创建，但会误导维护者，以为系统依赖特定学校/专业 case。当前已删除这类 raw prompt 关键词回显。后续如果需要在回复里展示学校或专业，只能来自结构化 payload/evidence，例如 `PlanQueryProfile`、candidate selection、plan payload 或 tool result，不能在 service 里维护样例词表。

新增/更新验证：

- `test_resolve_conditional_candidate_readonly_boundary_for_selection_scope`
- `test_resolve_conditional_candidate_readonly_boundary_for_missing_inputs`
- `test_resolve_conditional_candidate_readonly_boundary_ignores_non_add_units`
- `test_chat_service_rewrites_add_units_missing_inputs_boundary`
- `test_chat_service_rewrites_add_units_selection_scope_to_candidate_readonly_boundary`

当前剩余工程债：

- 条件式 candidate add 仍只是只读边界 source，还没有形成完整 `CandidateFeasibilityPlan -> ProposalCandidate`。长期应把候选选择、候选可行性和 add_units preview 的前置条件统一放到 EvidencePlan/ProposalCompiler。
- service 里仍保留候选边界回复文案渲染，这是输出层过渡。下一步应把 reply plan/display payload 也改成 compiler 输出，service 只做渲染。

### 13.16 full-journey 大回归与 workspace action 协议收紧

本轮在当前代码 agent `127.0.0.1:18299` 上跑完整 full-journey 集合，后端 `18290`、rank `18292` 复用现有服务。有效输出：

- `/tmp/dialog_regression_320_full_journey_18299_20260626_rerun.json`
- `/tmp/dialog_regression_320_full_journey_shadow_18299_20260626_rerun.json`

结果摘要：

- 69 steps，68 successful，1 failed。
- 唯一失败是内容断言：`full-journey-career-stable-region-fix-boundary` 的“先看看少的这些怎么补，别急着直接改”没有命中 fixture 里列出的旧边界短语。实际回复没有创建 pending、没有 apply；问题更接近 no-plan analyze/reply boundary 的 fixture/服务边界不一致，不是高副作用事故。
- latency：median `13595ms`，p95 `32775ms`，max `43803ms`。最慢请求集中在 full-agent 多模型/多工具链路；已观察到 candidate query 工具自身常在数秒级，长尾主要来自模型链路和前置分类/抽取。
- `runtime_shadow` 本轮没有新增 observation，说明当前 shadow 还没有覆盖到这些 full-journey 框架债；后续要补 shadow rule，而不是把 absence 当成无风险。

本轮确认的主要框架债：

- no-plan 下 review/analyze/refocus 仍有少量路径会先进入 `full_agent -> execute_plan_action(query_state/review_plan/analyze_adjustment)`，再由文案兜回“没有正式方案”。多数不会产生 pending/apply，但会污染耗时、observability 和 workspace followup。
- active pending 的“确认刚才的偏好和排除要求”曾出现由 full_agent 重新生成 pending 的风险，说明 pending reference confirmation 还要继续前移到 `PendingTurnResolution / ProposalCompiler`，不能交给普通模型回合。
- `TurnDecision.reason` 仍会出现 `pendingExists=true` 或 `formalPlanPresent=true` 的错判文字，尽管执行结果被 guard 收住。这是 model schema drift，不能作为 runtime事实源。
- followup/workspace action 之前仍有过渡逻辑：硬约束采纳后默认 `ordered + candidate`，即使当前没有正式方案也会提示“请查看方案”。

本轮已收紧的实现：

- 新增 `_post_apply_intent_workspace_targets()`：intent apply 后的 workspace target 先尊重显式 `postApplyEvidencePlan.workspaceRefreshTargets`；没有 EvidencePlan 时，读取采纳后的 planning summary。
- 新增 `_workspace_targets_allowed_by_planning_summary()`：只有读到正式方案（`ordered_total > 0` 或 `working_total > 0`）时，fallback 才允许 `ordered/review`；空方案或读不到 summary 时 fail closed，只保留 `candidate` 等不依赖当前方案实体的刷新。
- `handle_pending_confirmation()` 的 constraint intent 分支改为调用上述 helper，避免 future-reference 硬约束在无正式方案时错误驱动 ordered/review workspace action。
- 这不改变 intent 落库、pending apply、preference/constraint 抽取，也不影响已有正式方案下的 `ordered + candidate` 正常刷新。

新增/更新验证：

- `test_chat_service_pending_intent_constraint_confirm_skips_ordered_refresh_without_formal_plan`
- `test_chat_service_pending_constraint_confirmation_refreshes_plan_and_candidate` 明确补充已有正式方案 workspace 前提。
- `pytest tests/unit/test_chat_service_history_persistence.py -q`：469 passed。
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py tests/unit/test_runtime_hard_cut_audit.py -q`：125 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py`：通过。

下一步优先级：

- 继续收 `no-plan review/analyze/refocus` 的服务绕行：当 compiler/TurnDecision 已能判定 `missing_formal_plan/no_referent` 时，不应再让 full_agent 进入 review/analyze 工具。
- 补 pending reference confirmation 的结构化 apply 入口，避免“确认刚才...”生成新 pending。
- 为 full-journey 回归补 shadow rules：关注 no-plan 工具绕行、workspace action 与 formal plan presence、pending apply vs new pending。

### 13.17 3.0.2+ 累积用例全量并行回归

本轮补了两个只服务于回归执行和结果汇总的脚本，不改变业务运行语义：

- `examples/dialog_regression_parallel_runner.py`：把已有 `dialog_regression_runner.py` 按 case 拆成多个子进程并行执行，每个 case 独立临时 JSON、metrics 和 log。
- `examples/dialog_regression_parallel_report.py`：只读扫描并行输出目录，按原 case 文件计算 expected/completed/missing、失败类型、慢 case 和前若干失败详情。

本轮全量范围为 3.0.2 以来积累的 25 个 case 文件，不包含 3.0.1 及更早集合。运行时使用本地服务 Backend `18290`、Agent `18291`、Rank `18292`，并发度 `6`，单 case response timeout `240s`。输出目录：

- `/tmp/dialog_regression_320_full_20260626/parallel-summary.json`
- `/tmp/dialog_regression_320_full_20260626/final-report.json`
- `/tmp/dialog_regression_320_full_20260626/*.metrics.json`
- `/tmp/dialog_regression_320_full_20260626/*.log`

最终结果：

| 指标 | 数值 |
| --- | --- |
| expected cases | 401 |
| completed cases | 401 |
| missing cases | 0 |
| passed cases | 334 |
| failed cases | 67 |
| assertion failures | 119 |
| warnings | 25 |

失败断言类型分布：

| 类型 | 数量 | 说明 |
| --- | ---: | --- |
| `content_contract` | 66 | 回复文案、关键词、旧内容断言未命中 |
| `followup_protocol` | 30 | 旧 fixture 期望 followup target/refresh/card，与当前协议不一致或缺失 |
| `latency` | 16 | `maxElapsed` 或 latency warning 超阈值 |
| `other` | 7 | thinking/tool/综合断言等未被归入上面三类 |

按 case 文件看，`dialog_regression_mainline_cases` 40/40、`dialog_regression_lifecycle_cases` 6/6、`dialog_regression_plan_cases` 6/6、`dialog_regression_advanced_cases` 8/8、`dialog_regression_robust_cases` 10/10、`dialog_regression_science_cases` 40/40、`dialog_regression_score_tier_cases` 12/12、`dialog_regression_special_cases` 9/9 均无 case-level failure。问题主要集中在旧 302/303 断言、open quality、plan correctness、full journey 和 enriched/comprehensive 效果集合。

本轮问题分层：

1. **旧 fixture / 断言漂移**
   - 多个旧 case 假设存在正式方案或工作区可刷新，但当前 session 实际没有 formal plan。当前协议返回 `needs_plan_first` 或 no-pending guard 是正确方向，旧断言仍在期待 `冲/稳/保`、`ordered refresh`、`pendingConfirmationCard`。
   - 典型样本：`302-query-after-mutation`、`302-move-unit-major-group`、`320-shadow-G16-plan-local-pin-or-lock-action`、`320-shadow-G17-tier-local-reorder`。
   - 处理方向：更新 fixture contract，把“需要正式方案”的前置状态显式 seed 出来；否则断言应改成 no-plan/no-pending 边界，而不是要求方案内容。

2. **真实框架边界问题**
   - 全量长跑暴露过无正式方案下的当前方案 mutation 误入未来 intent pending：`把会计审计相关替换成新媒体或跨境电商相关` 曾被当作 `future_reference/intent_pending`，后续短“确认”采纳了一个新偏好。这是 current-plan referent 缺失时的 intent/mutation 边界漏口。
   - 当前文档 13.12 已记录并收紧 `needs_plan_first` guard；这类失败应保留为长期 golden，防止后续 runtime intent hard cut 抢在 referent feasibility 前生成 pending。
   - 另一个框架债是 TurnDecision 已能表达 `needs_plan_first`，但部分路径仍进入 `full_agent -> plan_next_action/execute_plan_action` 再返回边界，导致工具绕行、耗时和 observability 混乱。典型样本：`302-move-unit-major-group`。

3. **followup / workspace 协议迁移债**
   - 30 条 followup 失败里，很多来自旧工作区协议：旧断言默认 plan mutation preview/apply 后必须刷新 `ordered`，或无方案动作也要发 confirmation card。
   - 当前长期原则是 workspace action 必须来自 compiler/sink/display contract，并受 formal plan presence 约束。没有 pending/card、没有正式方案、没有可执行 preview 时，不能为了满足旧 followup 断言刷新 ordered。
   - 需要继续把 fixture 从“期望某个 UI target”改成“期望 compiler contract 合法”：pending card presence、target view、refresh target、formal plan evidence 必须一起断言。

4. **内容效果问题**
   - `content_contract` 数量最高，但不是一类问题：一部分是旧关键词断言，一部分是真实回复质量不足。
   - 真实质量问题包括：不可执行 plan action 只回复“信息不够完整”，没有充分回显用户实体和缺失条件；open quality 场景期待更自然的职业/专业解释；条件式 candidate add 仍只能给只读边界，无法形成完整 candidate feasibility proposal。
   - 长期处理方向不是恢复 service 关键词表，而是让 `PlanQueryProfile / CandidateFeasibilityPlan / ProposalCompiler replyPlan` 输出可展示实体、缺失项和下一步动作，service 只渲染结构化结果。

5. **长尾耗时**
   - 最慢 case 达到约 `182s`，包括 `302-special-plan-eligibility-explanation`、`303-dialogue-local-special-no-eligibility-risk`、`303-dialogue-computer-pressure-alternative`、`303-dialogue-color-weakness-major-avoid`。
   - 长尾集中在 303 dialogue derived/open quality 的 full-agent 多模型链路。已观察到部分 query tool 本身只有数秒，主要耗时来自前置分类、模型请求、tool loop 或服务端 180s fallback。
   - 当前先记录为 `latency_longtail` 工程债，不通过放宽断言掩盖。后续应把候选/政策/当前方案只读查询 DSL 前移，减少进入 full-agent 多轮链路。

6. **回归资产本身需要分层**
   - 这次全量回归证明主干高副作用链路并非整体失控：mainline、science、robust、score-tier、special 全部通过。
   - 67 个失败不能直接等价为 67 个 runtime bug；其中相当一部分是旧 fixture 没有表达 formal plan/pending 前置条件，或还在断言旧文案/旧 workspace target。
   - 后续 triage 应按 `runtime_service_gap / compiler_gap / fixture_mismatch / content_quality / latency_longtail` 给每个失败打标签，再决定是改代码、改 fixture，还是补 shadow/golden。

### 13.18 并行回归测量校准与当前优化切入点

本轮继续对 13.17 的全量并行回归做根因校准，重点先解决“测量是否可信”，再判断框架是否覆盖真实用户诉求。

回归工具只做观测层改动，不改变 runtime 业务语义：

- `dialog_regression_runner.py` 在使用 `--session-offset` 拆并发 case 时，如果 fixture contract 明确要求 `orderedPlan/formalPlan/candidatePool/reviewState/specialPathContext/activePending`，会自动把原始 session 的后端状态 clone 到 offset session。这样 G16/G17 这类正式方案 fixture 不会因为 session id 偏移而跑成空方案。
- `dialog_regression_parallel_report.py` 增加 report-only root cause 归因：`fixture_state_clone_gap / fixture_mismatch_no_formal_plan / assertion_noise_old_pending_expectation / assertion_noise_thinking / selector_gap_no_executable_preview / review_fix_focus_gap / intent_context_merge_gap / reply_focus_gap / latency_longtail / environment_setup`。这些标签只用于 triage，不进入 runtime 裁决。
- `dialog_regression_parallel_runner.py` 默认拒绝复用已有 metrics/log 的输出目录，必须显式 `--reuse-output-dir` 才允许写入，避免旧失败指标混进新运行。

重新用干净目录跑 G1-G32 shadow 集合：

- 输出目录：`/tmp/dialog_regression_320_g1_g32_after_clone_fix_clean_v2`
- 结果：21/21 completed，21/21 passed，0 failures，0 warnings。
- G16：已有正式方案 fixture clone 后稳定走 unsupported lock boundary，不再误判无方案。
- G17：已有正式方案 fixture clone 后稳定进入 `direct_local_plan_action`，`move_ordered_unit/no_change`，不再出现 `formalPlanPresent=false` 或 `当前方案共 0/0`。
- G26/G27/G31/G32 等 pending、只读、no-plan reference 组合均通过，说明当前核心协议覆盖了这些用户真实诉求：当前方案只读查询、pending 下只读、no-plan 防御回复、局部方案动作边界、学费相关只读和删除观测。

13.17 的旧全量报告经新 root cause 归因后，失败不应再按断言类型直接排序，而应按下面优先级处理：

| 根因桶 | 数量 | 处理判断 |
| --- | ---: | --- |
| `reply_focus_gap` | 19 | 真实效果优先级最高。重点看只读解释、职业/专业咨询、不可执行边界回复是否准确回显用户关注点。修复方向是结构化 `replyPlan/displayPayload`，不是 service 关键词补文案。 |
| `latency_longtail` | 16 | 独立 P0 性能债。集中在 policy/explore/open quality/full-agent 多模型链路，很多 tool 本身不慢，主要是模型 loop 和前置分类链路长。 |
| `selector_gap_no_executable_preview` | 14 | 需要在 action DSL / Java proposal / compiler sink 里补选择器和可执行 preview 表达；不能靠文本承诺补 pending。 |
| `assertion_noise_old_pending_expectation` | 7 | 多为旧断言仍期待确认卡、ordered refresh 或旧 pending 行为，应改 fixture/assertion。 |
| `assertion_noise_thinking` | 6 | thinking 文案断言噪音，不能算业务效果失败。 |
| `fixture_mismatch_no_formal_plan` | 6 | case 期望方案事实，但 fixture 没有正式方案；应补 fixture 或改成 no-plan 边界。 |
| `fixture_state_clone_gap` | 2 | 已由 session offset clone 修复，G1-G32 clean rerun 已验证。 |
| `intent_context_merge_gap` | 2 | 真实框架债，集中在“那两个都加吧 + 新城市”等上下文合并；应进入 intent/history merge 结构化 source。 |
| `review_fix_focus_gap` | 1 | 独立计数少，但作为 secondary mention 出现更多；后续仍要把 review focus binder 从 service 迁出。 |

当前框架覆盖判断：

- **已覆盖且应保持**：no-plan 当前方案 referent guard、无 active pending 的短确认 guard、active pending 下只读查询、intent 强弱偏好、当前方案只读查询、当前方案原子/局部动作的 DSL gate、review/fix conditional options、无结构化 preview 不补 pending。
- **覆盖不完整但边界安全**：条件式 candidate add、不可执行 add/remove/replace、review/fix 无唯一 proposal、no-plan review/analyze/refocus。这些场景现在大多 fail closed，不会误改方案；问题是回复焦点、缺失项和下一步动作表达不够好，或仍多走 full-agent 长路径。
- **尚需结构化补齐**：上下文合并型意向、selector/action DSL、CandidateFeasibilityPlan、ReviewFocusBinder、PlanQueryCondition、统一 reply/display contract。
- **不应再投入的方向**：按 prompt 关键词在 service 里补业务路由、从模型自然语言承诺恢复 pending/card、为旧 fixture 迁就 ordered refresh 或 confirmation card。

快速推进顺序：

1. **先清 measurement**：全量报告必须使用新 report root cause；复跑时必须用干净输出目录；所有 formal plan/pending fixture 必须 clone 或 seed 后端状态。
2. **先改 fixture/assertion，不急着改 runtime**：把 `fixture_state_clone_gap / fixture_mismatch_no_formal_plan / old_pending_expectation / thinking` 从产品缺陷池剥离。
3. **第一批真实优化做 reply focus**：选 `reply_focus_gap` 里的 5-8 个高频用户诉求，按 `PlanQueryProfile / ReviewFocus / CandidateFeasibility / replyPlan` 增加结构化输出和渲染，避免继续堆 service 文案。
4. **第二批做 selector/action DSL**：针对仍期待 pending 但无 executable preview 的 case，补 `remove/replace/add/sort/move` 的 selector scope、no-result reason、`resolved_apply_payload` 和 sink contract。
5. **并行拆 latency**：对 30s+ case 按 `TurnDecision / intent entity / semantic action / tool / final generation` 分段，优先把 policy/explore/read-only/candidate query 从 full-agent 多轮链路前移。
6. **最后跑扩大回归**：G1-G32 clean 绿后，再选 `reply_focus_gap + selector_gap + latency_longtail` 三组代表 case 做 focused rerun；全量 401 用于阶段性验收，不作为每个小改动的反馈环。

### 13.19 reply_focus_gap 首轮收口：错路 intent preview 的结构化边界

本轮从 `reply_focus_gap` 中选了一个低风险框架缺口先修：`TurnDecision` 已判定当前方案 mutation，但 full-agent 实际只调用了 intent preview tool。旧逻辑正确阻断了 intent pending/card，但回复退化成通用边界：

```text
这轮识别为当前方案调整诉求，但没有形成可确认的调整预览调整预览...
```

这个边界是安全的，但用户看不到自己刚说的“临床医学 / 江苏”等对象，效果上像系统没听懂；同时“方案调整预览”经过现有术语归一后出现重复。

当前收口方式：

- 新增 `RuntimeBlockedIntentPreviewReplySource` 和 `compile_blocked_intent_preview_for_plan_route_reply_source()`。
- compiler 只消费结构化 `TurnDecision + intent preview payload`，从 selected item 的 `value` 字段提取实体值，例如 `临床医学`、`江苏`。
- service 在 full-agent intent preview 被 TurnDecision 阻断时调用该 source 生成边界回复；不创建 pending、不发 card、不从文本恢复 plan action。
- 若 compiler source 不匹配，仍回退原有通用 fail-closed 边界。

新边界示例：

```text
我识别到你想让当前方案至少满足：临床医学。

但这句话的锚点是当前方案调整，本轮没有形成可执行的调整内容，所以不会创建长期意向卡，也不会改动当前方案。

需要先定位当前方案中的命中项并生成调整预览；确认前不会执行。
```

这次修的是“阻断回复的焦点保真”，不是把 must_have/only_keep 当前方案调整重新解释为未来意向。它符合当前原则：有 current-plan mutation 锚点但没有可执行 plan preview 时，只能 readonly boundary，不能落 intent pending。

新增/更新验证：

- `test_compile_blocked_intent_preview_for_plan_route_reply_preserves_selected_items`
- `test_blocked_intent_preview_for_plan_route_reply_preserves_structured_focus`
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "blocked_intent_preview or reply_guard or conditional_candidate"`：9 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "blocked_intent_preview_for_plan_route_reply or full_agent_intent_preview_is_blocked_for_current_plan_atomic_mutation"`：2 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py`：通过。
- current-code focused live 使用临时 Agent `127.0.0.1:18301` 验证：
  - `310-prod-must-have-clinical-medicine`：passed，回复保留 `临床医学`，无 followup/card。
  - `310-prod-only-keep-region`：passed，回复保留 `江苏`，无 followup/card。
  - metrics：`/tmp/dialog_regression_320_reply_focus_fix_310_v3.metrics.json`。

后续同类扩展方向：

- 对其它 `reply_focus_gap`，优先看是否已有结构化 payload/evidence 可以渲染；有则新增 compiler reply source，service 只替换文本。
- 不为单个 case 增加 prompt 关键词文案；无法从结构化 payload/evidence 取到对象时，继续使用通用边界。
- 下一批可以处理 `303-quality-career-fit-readonly-no-workspace` 这类 no-plan/current-plan query 边界：保留“体制内稳定就业/承接”焦点，同时明确没有正式方案不能评估方案内支撑。

### 13.20 reply_focus_gap 第二轮收口：no-plan 当前方案查询的焦点保真

第二个切口处理 `303-quality-career-fit-readonly-no-workspace`：

```text
当前方案对体制内稳定就业方向承接得怎么样，先不要改方案
```

这个 case 在 session offset 后没有正式方案。框架上正确路径不是恢复 3.0.3 的职业方向 full-agent/fast-route 分析，也不是把“体制内稳定就业”写成未来偏好；因为用户锚定的是“当前方案承接”，而当前没有可引用的正式方案。旧回复虽然安全地走 `needs_plan_first_guard`，但焦点退化成通用“这类方案范围要求”，效果上丢了用户真实关注点。

本轮收口方式：

- `NeedsPlanFirstResolution` 增加 `primary_reply / display_payload / reply_plan`，由 compiler 产出结构化 no-plan 边界。
- no-plan guard 在 compiler 内识别当前方案查询中的职业方向焦点，输出 `targetIssues=["career_direction_support"]` 和 `focusLabel=体制内/考公导向、稳定就业导向的方案承接`。
- service 只消费 compiler 的 `primary_reply`，并把 `displayPayload/replyPlan` 写入 route observability；fallback 旧文案仅在 compiler 没有 primary reply 时使用。
- 仍不调用 full-agent、不调用 `analyze_current_career_direction`、不创建 pending/card、不保存偏好、不改方案。

新边界示例：

```text
当前还没有生成正式方案，所以没法判断或调整“刚才/当前方案”里的具体志愿。你这轮关注的是体制内/考公导向、稳定就业导向的方案承接；需要先有正式方案，才能评估方案内是否承接。这轮不会把体制内/考公导向、稳定就业导向的方案承接写成新的报考偏好，也不会改动当前方案。也就是说，这轮不会改动方案。你可以先让我生成一版方案；有了正式方案后，我再按这条要求检查或调整。
```

新增/更新验证：

- `test_needs_plan_first_guard_preserves_career_direction_focus_without_formal_plan`
- `test_chat_service_needs_plan_first_guard_preserves_career_direction_focus`
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "blocked_intent_preview or needs_plan_first_guard or reply_guard or conditional_candidate"`：14 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "blocked_intent_preview_for_plan_route_reply or full_agent_intent_preview_is_blocked_for_current_plan_atomic_mutation or needs_plan_first_guard"`：6 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py`：通过。
- `git diff --check`：通过。
- current-code focused live 使用临时 Agent `127.0.0.1:18302` 验证：
  - `303-quality-career-fit-readonly-no-workspace`：passed，`elapsedMs=2217`，`routingPath=needs_plan_first_guard`，无 tool、无 followup/card。
  - metrics：`/tmp/dialog_regression_320_reply_focus_fix_303_career_v1.metrics.json`。

这个修复说明 `reply_focus_gap` 不一定要进入昂贵 full-agent 链路才能改善效果。只要已有 deterministic guard 能确定边界，就应把用户关注点放进 compiler 的 display/reply contract；service 继续保持协议编排角色。

### 13.21 reply_focus_gap 第三轮收口：no-plan 意向冲突查询的已采纳要求保真

第三个切口来自 `302-soft-hard-intent-mix-with-plan-impact` 的后续问法：

```text
财经类可以优先，但是护理和中西医结合不要
确认
现在方案里哪些和这些要求冲突
```

前两步是未来参考意向更新和采纳；第三步锚定“当前方案”和“这些要求冲突”。如果当前还没有正式方案，正确边界仍是 `needs_plan_first_guard`，不能编造方案内冲突，也不能把已采纳意向重新落成 pending。但旧回复把“冲突”里的“冲”误归为“冲稳保或风险这类要求”，丢失了已采纳的 `财经类 / 护理学 / 中西医结合类`。

本轮收口方式：

- `resolve_needs_plan_first_guard()` 增加可选 `recent_intent_summary` 输入。
- service 从 backend `pendingConfirmation` 的结构化 applied/active intent state 提取 summary，必要时再从 recent intent preview payload 回退；不从当前 prompt 里猜实体。
- compiler 仅在用户有明确“这些要求/这些条件/这些偏好/冲突/不符合”等当前方案冲突查询表达时，输出 `targetIssues=["intent_conflict_check_without_referent"]`。
- 新回复保留已采纳要求，同时仍 fail closed：没有正式方案就不能逐项判断冲突，不调用 full-agent、不创建 pending/card、不改方案。

新边界示例：

```text
当前还没有生成正式方案，所以没法判断或调整“刚才/当前方案”里的具体志愿。你这轮关注的是已采纳要求（优先专业：财经类；排除专业：护理学、中西医结合类）的方案冲突检查；需要先有正式方案，才能逐项判断哪些志愿冲突或不符合。这轮不会把已采纳要求（优先专业：财经类；排除专业：护理学、中西医结合类）的方案冲突检查写成新的报考偏好，也不会改动当前方案。也就是说，这轮不会改动方案。你可以先让我生成一版方案；有了正式方案后，我再按这条要求检查或调整。
```

新增/更新验证：

- `test_needs_plan_first_guard_preserves_recent_intent_conflict_focus`
- `test_chat_service_needs_plan_first_guard_preserves_applied_intent_conflict_focus`
- focused unit：
  - `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "recent_intent_conflict_focus or career_direction_focus or needs_plan_first_guard_blocks_current_plan_reference"`：3 passed。
  - `pytest tests/unit/test_chat_service_history_persistence.py -k "applied_intent_conflict_focus or career_direction_focus or needs_plan_first_guard_blocks_no_plan_current_plan_reference"`：3 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py`：通过。
- `git diff --check`：通过。
- current-code focused live 使用临时 Agent `127.0.0.1:18303` 验证：
  - `/tmp/dialog_regression_320_intent_conflict_focus_case.json`：3/3 passed。
  - 第三步 `elapsedMs=2114`，`routingPath=needs_plan_first_guard`，`targetIssues=["intent_conflict_check_without_referent"]`，无 tool、无 followup/card。
  - metrics：`/tmp/dialog_regression_320_reply_focus_fix_intent_conflict_v1.metrics.json`。

这次修复进一步说明：no-plan guard 不是只会输出固定“没有方案”文案。它应该携带当前用户查询所引用的结构化上下文，例如已采纳意向、职业方向、候选/审查 focus；但这些上下文必须来自 durable state 或 tool payload，不能从原句里的“这些”反推。

### 13.22 reply_focus_gap 第四轮收口：无 pending 短确认的直给边界

第四个切口来自真实用户话术：

```text
嗯可以
```

旧逻辑已经正确阻断了无 active pending 的短确认，不调用 agent、不执行方案、不采纳意向；但回复写成“没有上一轮正在等待采纳或执行的内容”，对用户不够直接，也没有命中回归 case 期望的“没有上一轮待确认 / 没有待执行 / 下一步”表达。这个问题不需要新增路由，也不能让短确认重新进入模型自由解释。

本轮收口方式：

- `_no_pending_confirmation_guard_reply()` 改为 canonical 边界：“没有上一轮待确认，也没有待执行...下一步可以直接说...确认前不会改方案”。
- 只改已有 direct guard 的用户可见文案，不改变 `pending_turn_looks_no_active_pending_confirmation()` 判定，不增加 pending/card，不调用 full-agent。
- 同步更新 service 单测里的 no-pending helper，避免旧句式变成隐性契约。

同时复核了 `303-real-user-school-abbrev-query`：

- 底层 `query_volunteer_plan` 已有“青城 -> 青岛城市学院”的 plan alias 能力，单测覆盖 `test_query_volunteer_plan_raw_query_uses_current_plan_school_alias_without_candidate_fallback`。
- 旧全量 metrics 中该 case 的后端日志显示 session `17800017` 的 ordered/working/legacy volunteer plan 均不可用，真实运行没有可引用正式方案；这种情况下 runtime 不能编造“青岛城市学院命中”。
- `dialog_regression_parallel_report.py` 增加窄口径 report-only 归因：no-plan + 局部方案命中期望归为 `fixture_mismatch_no_formal_plan`，不再误占 `reply_focus_gap`。该归因只用于 triage，不进入运行时裁决。

新增/更新验证：

- `test_parallel_report_classifies_no_plan_local_lookup_expectation_as_fixture_mismatch`
- `pytest tests/unit/test_dialog_regression_parallel_report.py`：3 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "no_pending or pending_plan_direct or stale_plan_pending or intent_text_confirmation or direct_copy or text_confirm_requires_card or blocks_colloquial_plan_confirmation or routes_colloquial_review_followup"`：6 passed。
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "no_active_pending_confirmation"`：2 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py examples/dialog_regression_parallel_report.py`：通过。
- current-code focused live 使用临时 Agent `127.0.0.1:18304` 验证：
  - `303-real-user-vague-confirm-guard`：1/1 passed，`elapsedMs=2232`，无 tool、无 followup/card。
  - 回复命中“没有上一轮待确认 / 没有待执行 / 下一步”，metrics：`/tmp/dialog_regression_320_reply_focus_fix_vague_confirm_v1.metrics.json`。
- v4 report：`/tmp/dialog_regression_320_full_20260626/final-report-with-root-cause-v4.json`，`reply_focus_gap=19`，`fixture_mismatch_no_formal_plan=6`，`303-real-user-school-abbrev-query` 已归入 fixture mismatch。

这个切口的框架判断是：能直接由 deterministic guard 给出正确边界的真实用户话术，应优先在 guard reply contract 上补清楚；但如果用户期望的实体事实没有 durable evidence，应该修 fixture/归因，而不是让 service 按原句硬补学校名。

### 13.23 selector_gap 校准：正式方案 fixture contract 补齐

继续排查 v4 report 里的 `selector_gap_no_executable_preview` 时，`303-real-user-sort-good-school-preview` 暴露出一个测量问题：

```text
按好学校排下看看
```

旧全量并行 metrics 里，offset session `17900017` 没有正式方案，full-agent 进入 `sort_ordered_plan` 后执行层返回 error，report 归为 selector gap。用 current-code 临时 Agent `127.0.0.1:18305` 直接跑 base session `17` 后，结果是 1/1 passed：生成 `sort_ordered_plan` preview、`pendingConfirmationCard` 和 `ordered` workspace action。说明这个样本不是当前 runtime 缺 preview，而是并行 offset 后没有 clone formal plan state。

本轮修正方向：

- 为明确依赖当前正式方案的旧 case 补 `fixtureContract`：
  - `302-remove-by-school-major-abbrev-negative`
  - `302-query-after-mutation`
  - `302-effect-major-positional-move-preview-confirm`
  - `303-quality-plan-status-rich-structured`
  - `303-quality-plan-review-rich-structured`
  - `303-quality-plan-named-move-preview-fast-route`
  - `303-quality-plan-named-add-preview-fast-route`
  - `303-quality-major-group-preview-confirm-boundary`
  - `303-real-user-school-abbrev-query`
  - `303-real-user-sort-good-school-preview`
  - `303-open-quality-sort-score-preview-rich-boundary`
  - `comprehensive-existing-plan-deep-query-26`
- 这些 contract 使用 `type=formal_plan_present`，`requiredState` 至少包含 `orderedPlan/formalPlan`；需要候选池的 add/query case 额外标注 `candidatePool`。
- 这样 `dialog_regression_runner.py --session-offset` 会自动设置 `cloneBackendStateFromSessionId`，避免把空 offset session 的 no-plan/error 当成 selector/action DSL 缺口。

同时保留一个小的 runtime 防线：

- `_CURRENT_PLAN_MUTATION_MARKERS` 增加 `重新排 / 排下 / 排一下 / 排一排`。
- 只在 planning summary 明确无正式方案时触发 `needs_plan_first_guard`，防止真实空方案下排序类话术继续绕进 `plan_next_action/execute_plan_action`。

fixture clone 修正后，又暴露出第二层真实框架问题：offset session `18126017` 已能从 base session `17` 正确克隆 `planningState/userprofile/userScoreDetail`，但“按好学校排下看看”一度被 `direct_readonly_plan_query/query_ordered` 抢走，变成只读排序查询，而不是当前正式方案排序 mutation。

本轮 runtime 收口：

- direct atomic plan action 的探测顺序前移到 direct readonly plan query 之前。当前方案有正式方案时，`sort/move/remove/replace/add` 这类 mutation 必须先给 action DSL 和 compiler preview 机会，不能被只读 profile query 抢路由。
- `_maybe_handle_direct_atomic_plan_action()` 在 request context 里没有 TurnDecision 时会自行分类，不再依赖前序路径一定已经写入 `_turn_decision_object`。
- `TurnDecision` prompt 明确把“按好学校排下看看 / 按院校层次排序 / 按录取率重排”归为 `plan_preview/current_plan/atomic_mutation`；`PlanQueryProfile` prompt 明确这类当前方案重排不是 readonly query，输出 `queryType=none`。
- action DSL 增加容错：模型把 `unsupportedAction`、`reviewIssueCode` 这类可选文本字段返回成布尔 `false/true` 时归一成 `None`，避免可执行 sort preview 因 schema 噪音掉回 full-agent。
- request 级 TurnDecision 缓存复用同一份结构化分类；intent hard-cut、profile replan probe 等非匹配探测不再把未采纳的 TurnDecision 写成共享事实，避免后续路径吃到错误上下文。

focused live 复核：

- v2：fixture clone 已生效，路由修正后可通过，但主要走 `full_agent`，端到端约 `43s`，暴露 DSL optional bool 容错问题。
- v3：DSL 容错后走 `direct_atomic_plan_action`，`actionFamilies=["sort_ordered_plan"]`，pending card 和 `ordered` workspace action 正常，端到端约 `22.7s`；失败只剩旧 thinking 断言。
- v4：移除旧 thinking 断言并加 TurnDecision cache 后，offset session `18126017` 通过：`routingPath=direct_atomic_plan_action`，`actionFamilies=["sort_ordered_plan"]`，`resultKinds=["preview_only"]`，followups 包含 `planningWorkspaceAction(ordered)` 和 `pendingConfirmationCard`，端到端 `14377ms`。
- v4 metrics：`/tmp/dialog_regression_320_fixture_contract_offset_sort_v4.metrics.json`。

继续复核 selector/action DSL 代表样本 `303-quality-plan-named-move-preview-fast-route`：

- fixture clone 后路由已经稳定走 `direct_atomic_plan_action`，但旧 prompt `把青岛城市学院的国际经济与贸易改到第3位` 在当前 session `17` 的正式方案里没有真实命中项；base/offset ordered-plan 均只包含其它学校的“国际经济与贸易”，不存在“青岛城市学院 + 国际经济与贸易”组合。
- 这类情况不能强行生成 pending。runtime 正确返回“没有唯一匹配到这条志愿”，不发确认卡；旧 fixture 期待 pending 属于实体事实过期。
- compiler 仍补了一个必要的字段桥接：当 `move_unit` DSL 给出 `schoolKeyword + sourceMajorNames + targetPosition` 但没有 `volunteerIds` 时，编译为执行层契约需要的 `volunteer_ids=["学校的专业"]`，同时保留 `school_keyword/source_major_names` selector facts。
- case 实体更新为当前方案真实存在的 `中国海洋大学004专业组 · 国际经济与贸易` 后，offset session `18127017` 通过：`routingPath=direct_atomic_plan_action`，`actionFamilies=["move_unit"]`，`resultKinds=["preview_only"]`，当前位置第 50 位，目标第 3 位，followups 包含 `planningWorkspaceAction(ordered)` 和 `pendingConfirmationCard`，端到端 `14433ms`。
- metrics：`/tmp/dialog_regression_320_fixture_contract_named_move_v3.metrics.json`。

新增/更新验证：

- JSON 校验：6 个修改过的 case 文件均通过 `python -m json.tool`。
- `pytest tests/unit/test_dialog_regression_runner.py -k "fixtureContract or session_offset or backend_state_clone"`：6 passed。
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "needs_plan_first_guard"`：7 passed。
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "atomic_plan_action or implicit_sort or needs_plan_first_guard"`：9 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "needs_plan_first_guard"`：6 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "direct_atomic_sort_preempts or intent_hard_cut_probe_does_not_cache or direct_atomic_plan_action_creates_remove_units_pending or direct_readonly_tuition_count_query or pending_readonly_tuition_count_query or direct_candidate_slice_query"`：5 passed。
- `pytest tests/unit/test_plan_semantic_action_tool.py -k "atomic_action_dsl"`：3 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py`：通过。
- focused live：
  - `303-real-user-sort-good-school-preview` base session `17`：1/1 passed，`routingPath=full_agent`，`actionFamilies=["sort_ordered_plan"]`，`resultKinds=["preview_only"]`，followups 包含 `planningWorkspaceAction(ordered)` 和 `pendingConfirmationCard`。
  - metrics：`/tmp/dialog_regression_320_no_plan_implicit_sort_guard_v1.metrics.json`。
  - `303-real-user-sort-good-school-preview` offset session `18126017`：1/1 passed，`routingPath=direct_atomic_plan_action`，`firstMessageMs=1228`，`finalMessageMs=12352`，`elapsedMs=14377`。
  - `303-quality-plan-named-move-preview-fast-route` offset session `18127017`：1/1 passed，`routingPath=direct_atomic_plan_action`，`actionFamilies=["move_unit"]`，`elapsedMs=14433`。
  - `302-effect-major-positional-move-preview-confirm` offset session `18128017`：2/2 passed，首轮 `把第2个志愿移到第4位` 走 `direct_atomic_plan_action`，`actionFamilies=["move_ordered_unit"]`，`resultKinds=["preview_only"]`，followups 包含 `planningWorkspaceAction(ordered)` 和 `pendingConfirmationCard`，端到端 `19917ms`；次轮 `确认` 走 `pending_plan_short_text_confirm`，已应用并刷新 `ordered` workspace，端到端 `2571ms`。
  - positional move metrics：`/tmp/dialog_regression_320_fixture_contract_positional_move_v1.metrics.json`。旧 v4 report 把它归到 `selector_gap_no_executable_preview`，但 current-code + fixture clone 下 preview/apply 链路成立，应从当前 selector 缺口中剔除。

这个切口的结论是：`selector_gap_no_executable_preview` 里仍混有 fixture clone gap；clone 修正后还要继续区分“真 selector 不可执行”和“只读路由抢了 mutation”。当前方案排序类诉求已经能走 `TurnDecision -> action DSL -> ProposalCompiler -> pending/card/workspace`，后续 triage 不应再把这个样本归到 selector 缺口。

### 13.24 selector_gap 第二轮校准：review issue scope 与执行层 fallback

继续复核 v4 report 里的 `selector_gap_no_executable_preview`，本轮把剩余代表样本再分成三类。

第一类是 current-code + fixture clone 后已经成立的当前方案原子动作：

- `303-quality-major-group-preview-confirm-boundary` offset session `18129016`：2/2 passed。首轮 `把第4个专业组移到第2位` 走 `direct_atomic_plan_action`，`actionFamilies=["move_ordered_unit"]`，`resultKinds=["preview_only"]`，followups 包含 `planningWorkspaceAction(ordered)` 和 `pendingConfirmationCard`，端到端 `20757ms`；次轮确认走 `pending_plan_short_text_confirm` 并应用。metrics：`/tmp/dialog_regression_320_fixture_contract_major_group_move_v1.metrics.json`。
- `303-quality-plan-named-add-preview-fast-route` offset session `18131017`：1/1 passed，走 `direct_atomic_plan_action`，`actionFamilies=["add_units"]`，`resultKinds=["preview_only"]`，followups 包含 `ordered` workspace 和确认卡，端到端 `13825ms`。metrics：`/tmp/dialog_regression_320_fixture_contract_named_add_v1.metrics.json`。
- `303-open-quality-sort-score-preview-rich-boundary` offset session `18130017`：业务链路已成立，走 `direct_atomic_plan_action`，`actionFamilies=["sort_ordered_plan"]`，`resultKinds=["preview_only"]`，pending card 正常，端到端 `14704ms`；失败只剩 `assertThinkingContainsAny` 的旧 thinking 文案断言。metrics：`/tmp/dialog_regression_320_fixture_contract_open_sort_score_v1.metrics.json`。

第二类是 fixture 源事实不匹配。`310-constraint-exclude-cooperative-program-preview-and-apply` 原来 clone session `17`，但 session `17` 的 ordered plan 当前没有任何“中外合作/合作办学/国际项目”命中；runtime 返回“没有唯一匹配到要移除的志愿”是正确边界，不应强行生成 pending。本轮把该 case 的 `cloneBackendStateFromSessionId` 改成 `26`，该源方案当前有 9 条中外合作命中。

第三类是真实执行层 scope 缺口：切到 session `26` 后，`plan_next_action` 已经生成结构化 `review_issue_target={code: cooperative_program, scope_mode: full_issue}`，但后端 `reviewState` 没有提供 affected volunteer ids，执行层只信 reviewState affected ids，仍掉回“要移除的志愿”澄清。这个缺口不在 TurnDecision 或 action DSL，而在 review issue scope 的 evidence fallback。

本轮 runtime 收口：

- 在 `execute_plan_action` 的 review issue scope 解析里增加受控 fallback：只有已经存在结构化 `review_issue_target.code`，且该 issue 是 item-level scope、scope mode 为 `full_issue`、reviewState affected ids 为空时，才从当前 ordered items 召回。
- `cooperative_program` fallback 只匹配 ordered item 的学校、专业、标签、reasonCodes 等结构化字段中的“中外合作/中外合作办学/合作办学/国际项目”；`high_tuition` fallback 复用已有学费解析，匹配年学费大于 20000 的条目。
- preview 解析出的 volunteer ids 写入 `facts.resolved_apply_payload`，确认卡持久化 apply payload 时复用同一批 ids，避免确认轮再次依赖不完整 reviewState。
- 这个 fallback 不读取用户原话，不做 prompt 关键词业务路由；它只在结构化 review issue target 已经成立后补齐后端 evidence 的缺口。

focused live 复核：

- `310-constraint-exclude-cooperative-program-preview-and-apply` offset session `28040105`，clone source `26`：2/2 passed。
- 首轮 `中外合作的都排除掉，当前方案里有的话先移出去` 走 `direct_atomic_plan_action`，`actionFamilies=["remove_units"]`，`resultKinds=["preview_only"]`，定位到 8 个专业组 / 9 条志愿，followups 包含 `planningWorkspaceAction(ordered)` 和 `pendingConfirmationCard`，端到端 `15552ms`。
- 次轮 `确认执行` 走 `pending_plan_short_text_confirm`，`resultKinds=["mutation_result"]`，`applied=true`，端到端 `4236ms`。回复里仍有后端刷新/复审失败提示，但 mutation apply 和 workspace refresh followup 成立。
- metrics：`/tmp/dialog_regression_320_fixture_contract_exclude_coop_v6.metrics.json`。

新增/更新验证：

- `test_execute_plan_action_remove_preview_falls_back_to_ordered_text_for_cooperative_issue`
- `pytest tests/unit/test_plan_execution_tool.py -k "review_issue_target_without_sample_refs or falls_back_to_ordered_text_for_cooperative_issue or refreshes_review_when_issue_scope_missing"`：3 passed。
- `py_compile app/tools/plan_execution_tool.py`：通过。
- `python -m json.tool examples/dialog_regression_310_constraint_plan_action_cases.json`：通过。

这个切口的框架结论是：当前 `TurnDecision -> action DSL -> plan_next_action -> execute_plan_action -> pending/card/apply` 主干已经能覆盖排序、位置移动、专业组整体移动、具名移动、候选加入、审查问题整批移出等真实用户诉求。剩余 `selector_gap` 不能再笼统归为“模型没选对动作”，需要先看三个证据面：fixture 是否有正式方案/真实目标，DSL 是否携带结构化 selector，执行层是否能把 selector 转成稳定 ids。只有第三类才应该改 runtime。

### 13.25 durable constraint 收口：只保留/必须有不是当前方案删除

继续看 `reply_focus_gap` 时，两个真实用户话术暴露出同一个框架问题：

```text
方案里必须有法学，其他专业可以先保留
仅保留江苏的学校
```

这类话术不是简单的“当前方案里删掉某些项”。它们表达的是后续报考约束：`must_have` 表示至少保留/必须满足某个范围，`only_keep` 表示后续只保留某个范围。旧链路的问题有两层：

- `must_have` 容易被 `TurnDecision` 锚定成 `plan_preview/current_plan/atomic_mutation`，导致 full-agent 产出的有效 `intent_preview` 被仲裁层挡掉。
- `only_keep` 更危险，曾被直接 action DSL 编译成 `remove_units(province_keyword=江苏)`，语义反了：用户要保留江苏，执行层却拿江苏当要删除的 selector。

本轮 runtime 收口：

- `compile_runtime_intent_preview_turn_decision_arbitration_source()` 增加 `constraint_intent_type` 输入。只有结构化 `constraintIntentType in {"must_have", "only_keep"}` 时，才允许被 `current_plan/atomic_mutation` 误锚定的 intent preview 通过；普通当前方案删除/替换仍然走 plan action，不退回长期意向卡。
- `_maybe_handle_runtime_intent_hard_cut()` 对被 `plan_preview/readonly_or_plan_preview` 阻断的场景增加 durable constraint 探测：只在 TurnDecision 确实阻断 hard cut 时抽取一次 `intent_entity_profile`，且必须满足高置信 `only_keep/must_have`，才创建 `intent_change` pending。
- `_create_runtime_intent_hard_cut_pending_from_prompt()` 支持复用已经抽取出的 profile，避免同一轮重复模型调用。
- `TurnDecision` prompt 明确：没有显式“删除/替换/预览当前方案”的“只保留/仅保留/只看/必须有/至少保留”应判为 `intent_pending/future_reference/intent_update`。
- `PlanSemanticAction` prompt 明确：`remove_units` selector 表示要移除的对象，不能把“仅保留江苏”编译成 `provinceKeyword=江苏` 的删除动作；`only_keep/must_have` 默认应生成报考约束预览。

focused live 复核：

- `310-constraint-must-have-major-preview-boundary`：2/2 passed。首轮走 `runtime_intent_hard_cut`，pending card 为 `intent_change`，`constraintIntentType=must_have`；确认轮走 `pending_intent_short_text_confirm`，刷新 `ordered` + `candidate`。metrics：`/tmp/dialog_regression_320_intent_constraint_must_have_v2.metrics.json`。
- `310-prod-only-keep-region`：1/1 passed。首轮走 `runtime_intent_hard_cut`，pending card 为 `intent_change`，`constraintIntentType=only_keep`，不再走 `direct_atomic_plan_action/remove_units`。metrics：`/tmp/dialog_regression_320_intent_constraint_only_keep_region_v2.metrics.json`。
- 对照上一个 selector 切口，`310-constraint-exclude-cooperative-program-preview-and-apply` 仍走当前方案 mutation：2/2 passed，首轮 `direct_atomic_plan_action/remove_units/preview_only`，确认轮 `pending_plan_short_text_confirm/mutation_result`。metrics：`/tmp/dialog_regression_320_fixture_contract_exclude_coop_v6.metrics.json`。

新增/更新验证：

- `test_intent_preview_turn_decision_arbitration_allows_current_plan_durable_constraint_intent`
- `test_chat_service_allows_current_plan_must_have_intent_preview_when_no_plan_preview`
- `test_chat_service_runtime_intent_hard_cut_recovers_only_keep_region_from_current_plan_anchor`
- `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_hard_cut or full_agent_intent_preview_is_blocked_for_current_plan_atomic_mutation or allows_aligned_full_agent_intent_preview or allows_current_plan_must_have_intent_preview or direct_atomic_sort_preempts or direct_atomic_plan_action"`：15 passed。
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "intent_preview_turn_decision_arbitration or atomic_plan_action or implicit_sort or needs_plan_first_guard"`：14 passed。
- `pytest tests/unit/test_plan_semantic_action_tool.py -k atomic_action_dsl`：3 passed。
- `pytest tests/unit/test_plan_execution_tool.py -k "review_issue_target_without_sample_refs or falls_back_to_ordered_text_for_cooperative_issue or refreshes_review_when_issue_scope_missing"`：3 passed。
- `py_compile app/service.py app/domain/proposal_compiler.py app/tools/plan_semantic_action_tool.py app/tools/turn_decision_tool.py app/tools/plan_execution_tool.py`：通过。

这个切口的框架结论是：高副作用的当前方案 mutation 和长期报考约束必须在结构化层分离，不能靠原句关键词兜底。正确主干仍然是 `TurnDecision -> intent_entity_profile/action DSL -> ProposalCompiler -> pending/card/apply`：`only_keep/must_have` 由 profile 的 strength 仲裁成 durable intent，显式“当前方案里有的话删掉/移出去”仍由 action DSL 进入方案调整预览。

剩余性能债也更清楚：这两个 durable constraint 首轮仍在 `20-22s` 左右，主要成本来自 TurnDecision + intent entity profile 两次模型链路。正确性已经收口，下一步提效应优先做 profile/TurnDecision 合并或缓存复用，而不是再增加 service 里的中文关键词分支。

### 13.26 intent_context_merge_gap 收口原则：上下文指代不是 service 合并

继续看 v4 report 里的 `intent_context_merge_gap`，代表样本是：

```text
上一轮：计算机和电子信息哪个更适合我
本轮：那两个都加吧 城市的话武汉最好 长沙南京也行
```

旧结果只创建了“偏好地域：武汉、长沙、南京”的待采纳卡，漏掉上一轮只读对比里的两个专业。这不是简单展示问题，而是框架层缺口：系统缺一个稳定的“上一轮结构化实体候选 -> 本轮指代解析 -> intent profile 合并”的链路。

本轮先按框架边界做最小收口：

- `service` 只从最近上一轮的结构化工具调用/返回里提取 `recentMajorContext`，例如 `compare_majors` 的 `major_name1/major_name2` 或专业介绍工具的结构化参数。它不读取 assistant 文本，不根据“那两个/都加吧”这类原句做业务判断，也不直接把专业塞进 selected values。
- `IntentEntityProfile` 新增 `contextResolution` 输出，由模型节点判断本轮是否真的引用了 `context.recentMajorContext`。只有本轮存在明确指代且语义是加入、记下、也可以、都可以等正向采纳时，才把候选专业并入 `majorValues/preferenceStrength`；否定、排除、只是问问、先看看时不能并入。
- `ProposalCompiler` 和 intent sink 仍只消费 profile 生成的结构化 selected values。service 负责 pending/card 编排，但不拥有“那两个指什么、是否要合并”的语义裁决权。
- 确认卡摘要补了一个展示边界：当 profile 同时包含专业和地域时，不能因为存在专业强度摘要就丢掉地域；专业强度摘要只在能覆盖整张卡时使用，否则回到完整结构化摘要。

这次改动应归类为“窄口框架扩展”，不是长期完整解法。它把错误的 service 字符串合并移到结构化 profile 节点，但当前只覆盖“最近上一轮专业只读工具候选”。后续如果继续遇到“这几所学校也加上”“这些城市不考虑”“刚才那个专业作为备选”等真实诉求，不能继续在 service 增加 `_xxx_context_merge_allowed()` 或 raw prompt marker，而应单独抽象为：

```text
StructuredContextLedger / ContextReferenceCandidate
  -> ContextReferenceResolver
  -> IntentEntityProfile.contextResolution
  -> ProposalCompiler sink
```

建议的通用维护原则：

- 上下文候选必须来自 durable state、pending/card、tool call args、tool return 或 plan evidence，不能来自自然语言回复。
- 指代解析必须输出结构化 `used/source/entityType/values/confidence/reason`，便于 observability、benchmark 和回归归因。
- service 只能提供候选和记录 observability；业务语义裁决属于 profile/resolver/compiler。
- 字符串匹配只允许保留在协议层和输出保护层，例如短确认/取消、无卡确认承诺清理；不能用于“用户想把哪个专业/学校/城市加入或删除”的业务判断。
- 如果某类真实诉求没有结构化候选来源，应该标记为框架不支持并补 resolver/evidence，而不是用 prompt 关键词补 case。

新增/更新验证：

- `test_runtime_intent_entity_profile_context_recovers_recent_major_compare_tool_args`
- `test_runtime_intent_entity_profile_context_uses_latest_previous_turn_only`
- `test_chat_service_runtime_intent_hard_cut_passes_recent_major_context_to_profile`
- `test_runtime_intent_entity_profile_pending_card_uses_complete_summary_for_mixed_entities`
- `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_entity_profile_context or passes_recent_major_context_to_profile or runtime_intent_hard_cut or mixed_entities or preserves_strength_display"`：15 passed。
- `py_compile app/service.py app/tools/intent_entity_profile_tool.py`：通过。

这个切口对后续优化的意义是：`intent_context_merge_gap` 应继续作为框架项单独跟踪。当前已避免 service 临时合并和误命中风险，但语义稳定性仍依赖 `IntentEntityProfile` 模型节点。下一步如果效果不稳，优先做 `ContextReferenceResolver` 的结构化输出和基准集，而不是把“那两个/这几个/都加/也行”扩成 service 关键词表。

补充复核第二个被归到 `intent_context_merge_gap` 的样本：

```text
专业方向偏计算机和人工智能 不想学文科
```

这个样本和“那两个都加吧”不是同一类问题。日志里 `TurnDecision` 一度判成 `intent_pending/future_reference`，但 full-agent 的 `IntentSideEffectDecision` 又判成 `analysis_only`，并且已经抽到了结构化焦点：

- `preferred`: 计算机类、人工智能
- `exclude_soft`: 文学、历史学、哲学、法学等

运行结果的问题不是 service 没有把字符串“计算机/人工智能”硬塞进卡片，而是只读降级回复只围绕负向“文科排除”展开，丢掉了正向专业焦点。这里不能简单让 `TurnDecision` 强制覆盖 `analysis_only`，因为类似“数学物理是我强项想搞基础学科”确实应该先做兴趣/适配分析，不应误建待采纳卡。

本轮修正为：

- 保留 `IntentSideEffectDecision=analysis_only/mixed_answer_then_ask` 的降级权，避免兴趣画像被错误写成待采纳状态。
- 在降级后的只读回复里追加结构化焦点摘要，来源只允许是 `intentSideEffectDecision.preferenceStrength/entityPolaritySpans`，不从 prompt 字符串抽词。
- 这样回复会保留“偏好方向：计算机类、人工智能；不优先方向：文学、历史学...”这类用户真实关注点，但仍不创建 pending/card、不写状态。

新增验证：

- `test_chat_service_downgraded_intent_reply_preserves_positive_focus_from_semantic_decision`
- `test_chat_service_runtime_intent_hard_cut_does_not_convert_readonly_interest_profile` 保持通过，确认只读兴趣画像不会被误建卡。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_hard_cut_does_not_convert_readonly_interest_profile or downgraded_intent_reply_preserves_positive_focus or runtime_intent_profile_preserves_strength_split or no_tool_explicit_intent_uses_runtime_hard_cut or passes_recent_major_context_to_profile"`：5 passed。
- `py_compile app/service.py app/tools/intent_entity_profile_tool.py`：通过。

因此 `intent_context_merge_gap` 后续应拆成两个子类处理：

- `context_reference_resolution_gap`：跨轮“那两个/这些/刚才那个”的结构化指代解析。
- `readonly_intent_focus_gap`：本轮已抽到正负实体，但只读/分析回复没有完整回显结构化焦点。

二者都不能靠 service prompt 关键词修。前者需要 ContextReferenceResolver；后者需要 replyPlan/displayPayload 从 semantic/profile 节点接收结构化焦点。

### 13.27 review_fix_focus_gap 校准：fixture contract 已收口，剩余是性能拆链路

继续复核 v4 report 里的 `review_fix_focus_gap`，代表样本是 `fuzzy-delegation-what-to-remove-26`：

```text
帮我看看这个方案哪里需要调整
那你建议先删几个？
那删完以后还剩多少个方案？
```

旧报告里该 case 被归为 review/fix 回复焦点缺口，但复核后发现主因不是 runtime 不会回答“删几个/剩多少”，而是并发 offset session 没有 clone base session `26` 的正式方案状态。base session `26` 有候选池、正式方案和 review state；offset session 空，导致运行时只能按“当前方案为 0”回答。

本轮已把该 case 的 fixture 前置显式化：

```json
"fixtureContract": {
  "type": "formal_plan_present",
  "requiredState": ["orderedPlan", "formalPlan", "candidatePool", "reviewState"]
}
```

focused live 复跑结果：

- `fuzzy-delegation-what-to-remove-26` offset session `28100026`：3/3 passed。
- metrics：`/tmp/dialog_regression_320_review_fix_focus_clone_v1.metrics.json`。
- 运行时没有新增 service 业务字符串分支；该样本应从当前 `review_fix_focus_gap` runtime 缺口里剥离，归为 `fixture_contract/backend_state_clone` 校准。
- 运行中仍有 warning：本地缺 `mysql` CLI，`assistant_chat_session` row clone failed；但 volunteer data files、planningState、userScoreDetail clone 成功，所以不影响该 case 结论。

这次复核也暴露了更明确的性能问题。三轮 focused live 的端到端耗时都偏高：

| step | routingPath | total | 已记录内部耗时 |
| --- | --- | ---: | --- |
| 1 | `full_agent` | `54723ms` | `llmDurationMs=16916`，有 `execute_plan_action/review_plan` |
| 2 | `semantic_plan_action` | `91992ms` | `llmDurationMs=3072`，`toolDurationMs=663` |
| 3 | `full_agent` | `100522ms` | `llmDurationMs=10983`，`toolDurationMs=0` |

旧 observability 只能看到 route total、合成回复 LLM 耗时和工具耗时，无法解释 step2/step3 的 80s 级差额。因此本轮补的是观测框架，不是业务补丁：

- `semantic_plan_action` 事件新增 `classificationDurationMs`、`preSemanticRouteDurationMs`、`unattributedDurationMs`。
- `full_agent` 事件新增 `preFullAgentDurationMs`、`postFullAgentDurationMs`、`unattributedDurationMs`。
- `dialog_regression_runner.py` 的 `eventTimings` 和 latency diagnostic 同步透传这些字段。

字段含义：

- `classificationDurationMs`：`classify_plan_semantic_action()` 本身耗时，用于判断大 prompt 分类是否是长尾。
- `preSemanticRouteDurationMs`：从 turn 开始到 semantic classification 完成的累计时间，用于观察进入 semantic route 前是否已有上下文/前置分类成本。
- `preFullAgentDurationMs`：从 turn 开始到 full-agent 调用前的累计时间，用于观察 history/context/pending/guard 链路成本。
- `postFullAgentDurationMs`：full-agent 返回后到事件记录前的后处理成本。
- `unattributedDurationMs`：route total 减去已显式记录的主要模型/工具耗时。它不是新的业务指标，只是提醒下一轮应该继续拆哪一段。

框架结论：

- `review_fix_focus_gap` 不能继续笼统看内容断言。先确认 fixture 是否有正式方案、review evidence、candidate pool；没有结构化 state 的 case 不能算 runtime 回复焦点失败。
- 如果用户问“建议删几个/删完还剩多少”，长期解法不是在 service 里按这些中文短句做字符串匹配，而是从最近的 review/fix structured evidence 编译 `ReviewFollowupResolution`：ready/blocked proposal 数、删除项数量、预览后剩余数量、是否缺 evidence 都应来自 plan result facts 或 compiler source。
- 当前 case 已通过，因此下一步不应继续为它补业务逻辑；应先用新增 timing 字段复跑慢 case，判断长尾在 semantic classification、full-agent 前置编排、full-agent 内部 node timing，还是后处理/streaming。

新增/更新验证：

- `python -m json.tool examples/dialog_regression_enriched_cases.json`：通过。
- `pytest tests/unit/test_dialog_regression_runner.py -k "fixtureContract or session_offset or backend_state_clone"`：6 passed。
- focused live `fuzzy-delegation-what-to-remove-26`：3/3 passed。
- `pytest tests/unit/test_dialog_regression_runner.py -k "route_event_timings or latency_profile"`：2 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "full_agent_review_repair_preview_records_display_contract or semantic_plan_route_passes_target_strategies_to_payload"`：2 passed。
- `py_compile app/service.py examples/dialog_regression_runner.py tests/unit/test_dialog_regression_runner.py`：通过。

### 13.28 带 timing 字段的全量并行回归：长尾主要在 full-agent 前置链路

为了确认 13.27 新增 observability 是否真的能解释长尾，本轮新起独立 agent 端口 `18311`，使用当前代码和相同 backend/rank：

- Agent：`ws://127.0.0.1:18311/gaotu-assistant-agent/plus/chat/1/bot/test/do`
- Backend：`http://127.0.0.1:18290`
- Rank：`http://127.0.0.1:18292`
- 并发度：`4`
- response timeout：`240s`
- 输出目录：`/tmp/dialog_regression_320_full_timing_20260626_18311_v2`
- summary：`/tmp/dialog_regression_320_full_timing_20260626_18311_v2/parallel-summary.json`
- report：`/tmp/dialog_regression_320_full_timing_20260626_18311_v2/final-report.json`

执行过程校准：

- 直接在 sandbox 内跑全量会全部变成 `PermissionError: Operation not permitted`，这是网络沙箱阻断，不是 runtime 失败。
- 提权后重跑有效，全量 401 个 case 均完成，`18311` 临时 agent 已在回归后关闭。
- focused smoke `fuzzy-delegation-what-to-remove-26` 使用新字段复跑：3/3 passed，metrics `/tmp/dialog_regression_320_review_fix_timing_smoke_18311.metrics.json`。

全量结果：

| 指标 | 数值 |
| --- | ---: |
| expected cases | 401 |
| completed cases | 401 |
| missing cases | 0 |
| passed cases | 358 |
| failed cases | 43 |
| failure assertions | 67 |
| warnings | 24 |

失败类型和 root cause：

| 维度 | 分布 |
| --- | --- |
| failure categories | `content_contract=37`，`followup_protocol=20`，`other=10` |
| root causes | `reply_focus_gap=38`，`assertion_noise_thinking=7`，`selector_gap_no_executable_preview=3`，`fixture_mismatch_no_formal_plan=1` |

和 13.17 的旧全量报告相比，这轮没有 `environment_setup`、`fixture_state_clone_gap`、`intent_context_merge_gap`、`review_fix_focus_gap` 作为主失败桶。`review_fix_focus_gap` 的代表样本已由 fixture contract/clone 收口；当前剩余主问题回到 `reply_focus_gap` 和少量 selector/action 可执行性缺口。

新增 timing 字段的全量统计：

| timing 字段 | count | median | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| `totalDurationMs` | 969 | `19916ms` | `40166ms` | `179929ms` |
| `llmDurationMs` | 556 | `11427ms` | `28050ms` | `52027ms` |
| `toolDurationMs` | 85 | `3012ms` | `5583ms` | `7032ms` |
| `classificationDurationMs` | 5 | `5059ms` | `7604ms` | `7604ms` |
| `preSemanticRouteDurationMs` | 5 | `17383ms` | `26045ms` | `26045ms` |
| `preFullAgentDurationMs` | 554 | `7175ms` | `23142ms` | `161077ms` |
| `postFullAgentDurationMs` | 554 | `69ms` | `6795ms` | `15350ms` |
| `unattributedDurationMs` | 559 | `8057ms` | `25142ms` | `161078ms` |

长尾样本说明：

- `special-data-query-deep / 进去后转专业容易吗`：`elapsed=182145ms`，`full_agent total=179929ms`，`llm=18851ms`，`preFullAgent=161077ms`。这是典型的前置链路长尾，不是模型生成本身慢。
- `special-data-query-deep / 北京邮电大学计算机近三年录取最低位次多少`：`elapsed=149384ms`，`preFullAgent=131701ms`，`llm=15480ms`。
- `convergence-full-12-turn-explore-to-final-600-hb / 最终版就这样吧`：`elapsed=95266ms`，`preFullAgent=85383ms`，`llm=7761ms`。
- `303-open-quality-major-compare-colloquial-pressure / 法学会不会太卷...`：`elapsed=64484ms`，`llm=52027ms`，`preFullAgent=10171ms`。这是模型链路本身长尾。
- `fuzzy-delegation-what-to-remove-26` 全量里首轮仍显示 `preFullAgent=29196ms`、`postFullAgent=6408ms`、`llm=12609ms`，说明这个 case 当前正确性已过，但性能主要不在 plan tool。

框架结论：

- 当前最大性能债不是 `execute_plan_action` 或 review/fix 工具慢。`toolDurationMs` p95 只有约 `5.6s`，远小于 60-180s 级长尾。
- 大量长尾集中在 `preFullAgentDurationMs`，也就是进入 full-agent 前的 history/context/pending/guard/profile/TurnDecision 等前置编排链路。13.25 已经指出 durable constraint 有 TurnDecision + profile 双模型链路；这轮全量证明该问题不是单点 case，而是通用成本。
- 少数 open-quality/专业比较类长尾确实是 `llmDurationMs` 本身高，例如法学 vs 财政这类复杂咨询；这类不能靠 service guard 解决，需要减少 full-agent 多轮工具/模型请求或拆出只读分析 DSL。
- `semantic_plan_action` 样本数量少，但 `classificationDurationMs` 中位约 `5s`、`preSemanticRouteDurationMs` 中位约 `17s`，说明如果后续扩大 semantic route，也必须先拆前置分类复用，否则会把长尾带到 fast route。

下一步性能优先级：

1. **拆 preFullAgent 成明确观测项**：`historyLoadMs / backendContextLoadMs / pendingLoadMs / turnDecisionMs / intentProfileMs / guardPipelineMs`。当前 `preFullAgentDurationMs` 已证明问题在前置链路，但还不足以定位具体节点。
2. **合并或复用 TurnDecision 与 IntentEntityProfile**：对于 intent/update、durable constraint、readonly interest analysis，避免同轮重复调用多个语义模型节点。
3. **把 readonly plan query 和 score/policy deep query 前移到 DSL**：`special-data-query-deep` 的 180s 级长尾不是业务可接受状态，应优先把数据查询类从 full-agent 多轮 loop 迁到 `PlanQueryCondition / DataQueryProfile`。
4. **reply_focus_gap 继续走结构化 replyPlan/displayPayload**：当前失败主桶仍是回复焦点，不应回到 service 字符串文案补丁；应从 query/review/action result facts 生成可断言的 reply plan。

### 13.29 preFullAgent 细分观测：先定位框架瓶颈，不继续堆 service 规则

用户明确追问 `service` 里的新增逻辑到底是临时逻辑还是框架扩展，以及字符串匹配是否会误命中。结合 13.28 全量结果，本轮先做低风险观测扩展，不新增业务语义规则：

- `service.py` 的合理职责仍是编排、状态加载、工具调用、pending/card、history、observability、输出保护。
- 业务语义不能继续靠中文字符串命中来兜底。字符串匹配只适合协议 guard、短确认/取消、输出安全这类低语义边界。
- 当前更关键的问题是：性能长尾已经证明集中在 full-agent 前置链路，但旧字段无法分辨是 history/pending/backend/context/guard 哪一段慢。

本轮实现：

- `handle_message` 入口新增统一起点，`preFullAgentDurationMs` 改为从消息进入 `handle_message` 到 full-agent 调用前的真实累计耗时。
- full-agent 事件新增前置链路拆分字段：
  - `historyLoadDurationMs`
  - `pendingLoadDurationMs`
  - `initialStateLoadDurationMs`
  - `runtimeHistoryBuildDurationMs`
  - `backendContextLoadDurationMs`
  - `requestContextBuildDurationMs`
  - `guardPipelineDurationMs`
- `dialog_regression_runner.py` 的 `eventTimings` 和 `latency_profile` 同步透传这些字段。
- 单测 `route_event_timings` / `latency_profile` 已补字段断言。

字段解释：

- `initialStateLoadDurationMs` 是 history 与 pending 并行加载的 wall time。
- `historyLoadDurationMs` / `pendingLoadDurationMs` 是并行子任务各自耗时，用于识别单边慢点。
- `backendContextLoadDurationMs` 覆盖 score/init profile/planning workspace state 并行拉取。
- `runtimeHistoryBuildDurationMs` 覆盖 history 裁剪、model history 构建、recent intent 提取。
- `requestContextBuildDurationMs` 覆盖 ConversationPhase、state sync、RequestContext 构建。
- `guardPipelineDurationMs` 覆盖进入 full-agent 前的 profile change、pending turn、no plan guard、runtime intent hard cut、direct action、semantic plan action 等编排。

这轮不直接优化业务效果的原因：

- `reply_focus_gap` 是质量主问题，但应该通过结构化 `replyPlan/displayPayload/evidence` 解决，不能继续堆 `if "删几个" in content` 这类规则。
- 当前性能问题更像发布阻塞。生产 grounded probe 第三轮接近 70s，全量 p95 约 40s，最大 180s；如果不拆清楚前置链路，后续优化容易误伤质量。
- 新增字段只改变 observability，不改变路由/回复策略，因此适合作为下一轮整体回归前的框架基础设施。

验证：

- `python -m py_compile app/service.py examples/dialog_regression_runner.py tests/unit/test_dialog_regression_runner.py`：通过。
- `pytest tests/unit/test_dialog_regression_runner.py -k "route_event_timings or latency_profile"`：2 passed。

下一步用法：

1. 用当前代码拉起隔离 agent，再跑 `special-data-query-deep`、`convergence-full-12-turn`、`fuzzy-delegation-what-to-remove-26` 等慢 case 小集合。
2. 如果 `guardPipelineDurationMs` 是主因，优先拆 TurnDecision / IntentEntityProfile / semantic classification 复用。
3. 如果 `backendContextLoadDurationMs` 是主因，检查 backend 聚合接口与并发状态拉取。
4. 如果 `historyLoadDurationMs` 或 `runtimeHistoryBuildDurationMs` 高，优先处理 history store 与 runtime history 裁剪。
5. 如果 `llmDurationMs` 仍是主因，再拆 full-agent 内部 node timing 和只读查询 DSL。

### 13.30 小集合验证：性能瓶颈已拆到 guard 内部模型链路

本轮用工作区最新代码单独拉起隔离 agent：

- Agent：`ws://127.0.0.1:18312/gaotu-assistant-agent/plus/chat/1/bot/test/do`
- Backend：`http://127.0.0.1:18090`
- Rank：`http://127.0.0.1:18092`
- 固定测试环境 `18091/3001` 未被替换；`18091` 仍是 docker 镜像版本，不包含本轮新增 timing。

先跑两个代表慢 case：

- `fuzzy-delegation-what-to-remove-26`
- `convergence-full-12-turn-explore-to-final-600-hb`

输出：

- metrics：`/tmp/dialog_regression_320_prefull_breakdown_enriched_18312.metrics.json`
- shadow：`/tmp/dialog_regression_320_prefull_breakdown_enriched_18312.shadow.json`

结果：

| 指标 | 数值 |
| --- | ---: |
| steps | 14 |
| successfulSteps | 14 |
| failedSteps | 0 |
| median elapsed | `26840ms` |
| p95 elapsed | `48930ms` |
| max elapsed | `64435ms` |

按 route 聚合：

| route | count | 主要结论 |
| --- | ---: | --- |
| `full_agent` | 9 | median `totalDurationMs=25340ms`，median `llmDurationMs=10571ms`，median `guardPipelineDurationMs=6889ms`。开放咨询类主要是模型输出长，review/fix 类 guard 更重。 |
| `semantic_plan_action` | 1 | `classificationDurationMs=5006ms`，`preSemanticRouteDurationMs=27761ms`。semantic route 自身 classification 不是唯一成本，前置 guard 已经很重。 |
| `runtime_intent_hard_cut` | 2 | `totalDurationMs` 为 `24146ms` 和 `31278ms`，旧字段只知道 direct route 慢，无法解释内部节点。 |
| `pending_intent_short_text_confirm` | 1 | `totalDurationMs=161ms`，说明短确认本身不是性能问题。 |
| `needs_plan_first_guard` | 1 | `totalDurationMs=39ms`，说明结构化 no-plan guard 是高收益快路径。 |

代表样本：

- `fuzzy-delegation step1`：`total=46856ms`，`llm=12464ms`，`guardPipeline=28089ms`，`backendContext=112ms`。慢点不是后端，也不是工具。
- `fuzzy-delegation step2`：`total=62366ms`，`llm=33655ms`，`guardPipeline=28252ms`。这是 guard + full-agent 多模型双重慢。
- `fuzzy-delegation step3`：`semantic_plan_action total=28386ms`，`classification=5006ms`，`preSemanticRoute=27761ms`。说明 fast route 前已有可观语义编排成本。
- `convergence step11 / 最终版就这样吧`：`total=25340ms`，`llm=6477ms`，`guardPipeline=18755ms`。之前全量里的该样本长尾不是偶发，主要仍在 guard。

质量观察：

- `不要医学不要师范 学费别太贵 两万以内` 生成的 pending card 只保留了“排除医学/师范”，丢了“学费两万以内”。这不是 service 字符串匹配问题，而是 `IntentEntityProfile / intent selected values` 缺 budget/tuition 结构化槽位。
- `好了信息差不多了 帮我出一版方案` 先采纳上一轮 pending 后，回复说缺省份、分数、选科；但这些信息在历史里已经出现，后续轮次也能回显。这里暴露的是“生成方案前置信息”只看 backend/init state，不消费结构化 session memory/profile，不应靠 service 从自然语言里抓 `600/湖北/物化生`。
- `保底里面有没有离武汉太远的 远的去掉` 在无正式方案下走 `needs_plan_first_guard`，39ms 且安全，这是当前框架里正确的结构化边界。

随后补 guard 内部模型 timing，不改变业务逻辑：

- `turnDecisionDurationMs`
- `turnDecisionCacheHitCount`
- `intentEntityProfileDurationMs`
- `intentSideEffectDurationMs`

这些字段由 `request_context.agent_observability` 累加，写入 `runtime_intent_hard_cut`、`semantic_plan_action`、`full_agent` event，并同步到 `dialog_regression_runner.py` 的 `eventTimings` 与 `latency_profile`。

短 probe：

- 命令目标：session `92611501`
- metrics：`/tmp/dialog_regression_320_guard_inner_timing_probe_18312.metrics.json`
- prompts：
  - `计算机和电子信息感觉都不错 你觉得哪个适合我`
  - `那两个都加吧 城市的话武汉最好 长沙南京也行`

关键结果：

```text
runtime_intent_hard_cut totalDurationMs=30016
turnDecisionDurationMs=5216
intentEntityProfileDurationMs=13860
intentSideEffectDurationMs=10789
```

结论：

- runtime intent pending 慢的直接原因是同轮串行跑了 TurnDecision、IntentEntityProfile、IntentSideEffect 三个模型节点。
- 这类性能问题不能靠 service 字符串匹配解决；应合并语义判断，或让 `IntentEntityProfile` 直接输出 sideEffect / confirmability / selectedValues，减少三段串行模型调用。
- full-agent 开放咨询类还存在模型输出长的问题，例如专业对比首轮 `llmDurationMs=39633ms` 且 4 次模型请求。这类要通过只读咨询 DSL / 短回复模板 / 工具结果结构化渲染收敛，不应继续让 full-agent 自由多轮扩写。

新增验证：

- `python -m py_compile app/service.py examples/dialog_regression_runner.py tests/unit/test_dialog_regression_runner.py`：通过。
- `pytest tests/unit/test_dialog_regression_runner.py -k "route_event_timings or latency_profile"`：2 passed。

下一步优先级更新：

1. **性能 P0：合并 runtime intent hard cut 三模型链路**。目标是把 `TurnDecision + IntentEntityProfile + IntentSideEffect` 从串行三次降到一次或两次，并复用结构化 selected values。
2. **质量 P0：补 tuition/budget 结构化槽位**。`学费两万以内` 不能丢，需要进入 intent profile selected values 和 pending card summary。
3. **方案生成前置 state：建立结构化 SessionProfile/ScoreProfile memory**。历史里出现的省份、分数、选科不能只靠 full-agent 回忆，生成方案 gate 应消费结构化 state。
4. **开放咨询降耗：专业/职业比较类只读 DSL 化**。减少 full-agent 4 次模型请求和 20-40s 长回复。
5. **继续坚持 service 边界**：service 只做编排和 observability；业务语义、约束、预算、生成条件、上下文指代都应放到 profile/resolver/compiler 的结构化输出里。

### 13.31 上下文候选恢复补齐：修复 `analyze_current_major_interest` 漏专业候选

13.30 的短 probe 暴露了一个框架覆盖面问题：

```text
上一轮：计算机和电子信息感觉都不错 你觉得哪个适合我
下一轮：那两个都加吧 城市的话武汉最好 长沙南京也行
```

旧结果：

- 上一轮并没有走 `compare_majors`，而是走 `analyze_current_major_interest`。
- 真实持久化 history 里，工具调用参数有结构化候选：`major_intents.level2=["计算机类","电子信息类"]`。
- 当前 `_extract_structured_major_context_from_tool_history` 只识别 `major_name/majorName/major_names` 这类字段，漏掉 nested `major_intents`，导致传给 `IntentEntityProfile` 的 `context.recentMajorContext` 为空。
- 结果第二轮只生成“偏好地域：武汉、长沙、南京”，漏掉“计算机类、电子信息类”，并额外跑了 `IntentSideEffect`，总耗时约 `26905ms`。

本轮修复：

- `service` 的结构化上下文恢复支持：
  - 工具 args / return 顶层 `major_names/majorName/major_name1/major_name2`；
  - 工具 args / return 的 `major_intents.level3/level2/level1`；
  - 工具 return `items[].value.major_intents.level3/level2/level1`。
- 明确不从 assistant 自然语言文本提取专业，也不根据“那两个/都加吧”在 service 做语义合并。
- 明确不把 `existingItems` 当作最近上下文候选，避免把长期已记录偏好误认为“刚才那两个”。长期偏好以后应作为 durable ledger 的独立 source，而不是混入 recent readonly context。
- `IntentEntityProfile.contextResolution` 仍是唯一语义裁决点：是否使用 `recentMajorContext`，由 profile 节点结合本轮话术输出 `used/source/entityType/values/confidence/reason`。
- runtime intent hard cut 在安全条件下复用 TurnDecision 的 `intent_pending/future_reference` 判断，跳过第三个 `IntentSideEffect` 模型节点；纯单专业“适不适合我”仍保留 side-effect 仲裁，防止只读咨询误生成待采纳卡。

验证：

- `python -m py_compile app/service.py tests/unit/test_chat_service_history_persistence.py`：通过。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_entity_profile_context or runtime_intent_hard_cut_passes_recent_major_context_to_profile or runtime_intent_hard_cut_keeps_side_effect_for_pure_major_interest"`：7 passed。
- Live probe 使用当前代码拉起隔离 Agent `18313`，Backend `18090`，Rank `18092`，固定测试环境 `18091/3001` 未替换：
  - metrics：`/tmp/dialog_regression_320_structured_context_18313.metrics.json`
  - session：`92621531`
  - 2/2 successful。

Live probe 关键结果：

| 步骤 | 结果 |
| --- | --- |
| 首轮专业对比 | `full_agent`，`analyze_current_major_interest` 1 次，`totalDurationMs=19461`，`llmDurationMs=11415`。回复质量可用，但仍偏长且先追问信息。 |
| 次轮“那两个都加吧...” | `runtime_intent_hard_cut`，pending card 同时包含“偏好专业类：计算机类、电子信息类；偏好地域：武汉、长沙、南京”。 |
| 次轮性能 | `totalDurationMs=18686`，`turnDecisionDurationMs=5682`，`intentEntityProfileDurationMs=12831`，无 `intentSideEffectDurationMs`。 |
| 对比旧 probe | 旧次轮 `totalDurationMs=26905`，且 `intentSideEffectDurationMs=10873`，卡片漏专业。当前既修复质量，也减少约 8.2s direct route 耗时。 |

框架结论：

- 这不是字符串匹配补丁，而是 `StructuredContextLedger` 的局部前置实现：上下文候选来自结构化工具调用/返回，指代语义由 profile 模型裁决，最终由 compiler/sink 生成 pending。
- 字符串匹配会误命中的风险仍然存在，所以 service 里不能新增“那两个/这些/都加”等业务判断。只能保留低语义协议 guard，例如 active pending 的确认/取消、输出安全、状态边界。
- 当前框架可以覆盖“最近上一轮只读专业工具候选 -> 本轮指代加入意向”的真实诉求；但还不能系统性覆盖学校、地域、方案条目、已记录偏好、候选列表等多 source 指代。后续应单独抽象 `StructuredContextLedger / ContextReferenceResolver`，不要继续在 service 逐类加函数。
- 性能改善来自跳过第三个模型节点，但 direct route 仍有两次模型调用，20s 级别仍偏慢。真正的性能 P0 仍是合并 `TurnDecision + IntentEntityProfile`，或让 profile 直接输出 route/sideEffect/selectedValues。

下一步优先级保持：

1. **质量 P0**：补 tuition/budget 结构化槽位，解决“学费两万以内”丢失。
2. **质量 P0**：补 SessionProfile/ScoreProfile memory，解决“历史已有省份/分数/选科但生成方案 gate 仍说缺信息”。
3. **性能 P0**：合并 runtime intent direct route 的模型节点，目标把安全 intent pending 从 `18-20s` 降到 `8-12s`。
4. **框架 P1**：抽象通用 `StructuredContextLedger`，覆盖学校/地域/方案条目/候选机会的可解释指代恢复。

### 13.32 沿用当前框架扩展 typed recent context：覆盖院校/地域/发展方向

继续沿用 13.31 的框架设定：不引入完整 `StructuredContextLedger`，但把 recent context 从专业单字段扩为 typed context，尽量一次覆盖当前 intent 体系里已有结构化实体。

本轮扩展：

- `recentEntityContext.major`：来自 `major_intents.level3/level2/level1`、`major_name/majorName/major_names`。
- `recentEntityContext.school`：来自 `school_intents.colleges`、`schoolName/schoolNames/school_name1/school_name2/collegeName`。
- `recentEntityContext.region`：来自 `city_intents.province/city/area`、`province/provinces/city/cities/area/areas`。
- `recentEntityContext.career`：来自 `career_intents.positive`、`career_directions/careerDirections/directionSlots`。
- typed context 的结构化来源扩展到专业对比/介绍、院校介绍/对比、兴趣分析和各类 intent preview。
- 同一上一轮里多个结构化工具结果会合并，不再命中第一个非空工具结果就返回，避免学校、地域、职业方向分散在多个工具时被漏掉。
- 保留兼容字段 `recentMajorContext`，避免影响已有专业指代 prompt 和回归。
- `referenceResolutionHints` 改为 typed hints，仍只承载结构化候选，不承载自然语言正文。

同时补 `IntentEntityProfile` schema：

- 新增 `careerValues`，`entityType` 允许 `career`。
- prompt 明确 `recentEntityContext` 可包含专业、院校、地域、发展方向。
- `contextResolution` 继续要求输出 `used/source/entityType/values/confidence/reason`。
- runtime selected values 支持把 `careerValues` 编译成 `career_intents.positive/negative`，并用既有 career slot 标准化，例如“稳定就业导向”落到 `stable_employment`。
- runtime intent fast path 增加结构化条件：当 `TurnDecision` 为 `intent_pending/future_reference`，`IntentEntityProfile.contextResolution` 高置信使用 `recentEntityContext/recentMajorContext`，且本轮是普通正向多实体偏好时，可跳过第三个 `IntentSideEffect` 模型节点；负向和 constraint 仍保守要求更高置信或继续仲裁。

边界仍然保持：

- 不解析 assistant 自然语言回复。
- 不把 `existingItems` 当作 recent context，避免把已记录偏好误认为“刚才这些”。
- 只取正向候选作为 recent context；负向排除候选暂不作为“这些也加上”的默认上下文。
- 不覆盖当前方案条目、候选列表、active pending、durable profile 等复杂 source；这些仍应等完整 `StructuredContextLedger / ContextReferenceResolver`。

新增验证：

- `test_runtime_intent_entity_profile_context_recovers_school_region_career_payload_items`
- `test_runtime_intent_entity_profile_context_recovers_school_region_career_tool_args`
- `test_runtime_intent_entity_profile_context_merges_structured_entities_across_tools`
- `test_runtime_intent_entity_profile_pending_card_supports_career_values`
- `test_chat_service_runtime_intent_hard_cut_passes_typed_recent_context_to_profile`
- `test_chat_service_runtime_intent_hard_cut_keeps_side_effect_without_context_resolution`
- `python -m py_compile app/service.py app/tools/intent_entity_profile_tool.py tests/unit/test_chat_service_history_persistence.py`：通过。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_entity_profile_context or runtime_intent_entity_profile_pending_card_supports_career_values or runtime_intent_hard_cut_passes_recent_major_context_to_profile or runtime_intent_hard_cut_passes_typed_recent_context_to_profile or runtime_intent_hard_cut_keeps_side_effect_without_context_resolution or runtime_intent_hard_cut_keeps_side_effect_for_pure_major_interest"`：13 passed。
- Live probe 使用隔离 Agent `18313`，Backend `18090`，Rank `18092`，固定测试环境 `18091/3001` 未替换：
  - session `92621631` 首次验证语义正确，但低置信 `TurnDecision=0.85` 未命中 fast path：`totalDurationMs=67129`，`turnDecisionDurationMs=5882`，`intentEntityProfileDurationMs=11549`，`intentSideEffectDurationMs=49458`。
  - 增加 `contextResolution` fast path 后，session `92621632` 同一 prompt 仍生成完整 pending card：`偏好院校：武汉大学、华中科技大学；偏好地域：武汉、长沙；发展方向：稳定就业导向`。
  - 性能降到 `totalDurationMs=17535`，`turnDecisionDurationMs=5710`，`intentEntityProfileDurationMs=11583`，无 `intentSideEffectDurationMs`；runner 端到端 `elapsedMs=19603`。
  - metrics：`/tmp/dialog_regression_320_typed_context_fastpath_18313.metrics.json`。

当前可覆盖的真实诉求：

- “刚才那两个专业都加上”。
- “这几所学校也加入意向”。
- “这些城市也可以”。
- “这几个发展方向也按后续参考”。
- “学校 + 地域 + 发展方向”混合候选后，本轮说“这些也都加到意向里”。

仍不能宣称覆盖的诉求：

- “保底里的这几个删掉”“刚才推荐的前几个不要”这类方案/候选引用。
- “上一张卡里那些先采纳一部分”这类 active pending 精细引用。
- “已经记录的偏好里那几个不要了”这类 durable profile 引用。
- 多个同类型 source 并存时的消歧，例如上一轮工具候选和当前方案候选都包含“这些学校”。

结论：这一步不是最终 resolver，但把当前框架里的结构化上下文从“专业特例”提升到“intent 四类实体 typed recent context”。它能覆盖更多真实口语指代，同时继续避免 service 字符串匹配误命中。

### 13.33 补齐 tuition/budget 结构化槽位：覆盖未来推荐预算偏好

13.30 暴露的 `不要医学不要师范 学费别太贵 两万以内` 问题，本质不是 service 少了一条“学费/两万”字符串规则，而是 future-reference intent profile 没有预算槽位。方案 mutation 和只读查询原本已有两条学费链路：

- 当前方案调整：`tuition_budget_scope` / user-goal / Java fix proposal。
- 当前方案只读：`PlanQueryProfile` 的 tuition filters。

缺的是第三条链路：

```text
后续推荐/未来参考里的学费预算偏好
  -> IntentEntityProfile.tuitionBudget
  -> selectedData.tuition_budget
  -> pending card summary
  -> apply_selected_intents
  -> update_session_tuition_range
```

本轮补齐：

- `IntentEntityProfileResult` 新增 `tuitionBudget`，`entityType` 允许 `budget`。
- prompt 要求只抽明确年学费预算，输出元/年，例如 `两万以内 -> maxTuitionPerYear=20000`。
- prompt 明确边界：用户要求“当前方案里删/换/处理超预算志愿”时，不要伪造成普通未来偏好；这类仍走 plan/user-goal 路径。
- service 只把结构化 `tuitionBudget` 编译成 `selectedData` 的 `{"tuition_budget": {"max_tuition_per_year": [20000]}}`，并生成 summary `学费预算：每年不超过 20000 元`。
- `intent_state_tool.apply_selected_intents` 在确认后由 intent apply 层调用 `update_session_tuition_range`，而不是 service 根据原话补同步。
- `intent_response_tool` 和 `proposal_compiler.intent_payload_has_positive_value` 认识 `tuition_budget`，避免预算-only pending 被当成空 intent。
- runtime intent fast path 允许高置信 `TurnDecision(intent_pending/future_reference)` + 结构化预算 profile 直接生成 pending，避免预算-only 被第三个 `IntentSideEffect` 模型节点因无 major/school/city/career 输入而吞掉。

边界仍然保持：

- 代码不解析中文金额词，不做 `二万/两万/2w` 这类 raw prompt 正则。金额语义由 profile 模型输出结构化数字，代码只校验正整数和 min/max 合法性。
- `学费两万以内` 在“后续推荐也按这个参考/也记上”语境下进入 intent pending；在“当前方案里太贵的删掉/换掉”语境下仍应进入 plan mutation/user-goal proposal。
- budget 不是 recent context resolver；暂不支持“刚才那个预算也加上”这类跨轮预算指代。后续如果需要，应进入 `StructuredContextLedger`，不能在 service 里补“这个预算/刚才那个”字符串规则。

新增验证：

- `test_intent_entity_profile_result_keeps_budget_type_and_tuition_budget`
- `test_intent_entity_profile_result_marks_mixed_when_budget_has_other_entities`
- `test_intent_entity_profile_result_recovers_budget_when_entity_type_is_none`
- `test_runtime_intent_entity_profile_pending_card_supports_tuition_budget`
- `test_summarize_intent_values_supports_tuition_budget`
- `test_apply_selected_intents_syncs_tuition_budget_range`
- `test_chat_service_runtime_intent_hard_cut_supports_tuition_budget_only`
- `test_intent_payload_scope_helpers_detect_positive_and_negative_values` 增加 `tuition_budget`。
- `python -m py_compile app/tools/intent_entity_profile_tool.py app/service.py app/tools/intent_state_tool.py app/tools/intent_response_tool.py app/domain/proposal_compiler.py`：通过。
- targeted pytest：`7 passed`。
- 相关回归子集：career pending、mixed summary、typed recent context、user-goal tuition apply：`7 passed`。

框架结论：

- 这次是 profile/schema/selectedData/apply 的结构化扩展，不是 service 临时逻辑。
- service 的职责仍是编排结构化结果、生成 pending、保存状态和 observability；预算语义抽取在 profile，合法 pending 判断在 compiler，确认后的状态同步在 intent state tool。
- 当前 P0 质量缺口“学费两万以内丢失”已有框架闭环；下一步更高收益仍是生成方案前置 SessionProfile/ScoreProfile memory，以及合并 runtime intent direct route 的模型节点。

### 13.34 生产 micro 实体错桶修复：职业方向不再落到专业桶

本轮针对生产回捞 micro case 里的一个真实 schema 漂移做框架层修复：

```text
用户：我想要优先稳定体制内
旧回复：已列出这次报考想法预览：偏好专业：体制内。
route：runtime_intent_hard_cut / intent_pending / future_reference / pendingConfirmationCard
```

证据来自 `/tmp/dialog_regression_320_prod_asset_micro_18312.metrics.json`：该回合没有进入 full-agent，也不是当前方案 mutation；`TurnDecision` 已经正确落到未来意向，问题发生在 `IntentEntityProfile -> selectedData -> pending summary` 的实体类型归属，`体制内` 被当成 `majorValues` 编译成了 `major_intents`。

本轮处理原则：

- 不在 service 里按“体制内/考公/稳定就业”做整句路由或业务字符串匹配。
- 在共享 `career_slots` 里集中维护职业方向 alias 到 slot 的映射，例如 `体制内/考公/考编/公务员/事业单位 -> system_public_service`，`稳定就业/求稳 -> stable_employment`。
- `IntentEntityProfile` normalize 阶段只处理模型已经抽出的实体值：如果 `majorValues` 中出现明确 career alias，就迁移到 `careerValues`，同步修正 `entityType/preferenceStrength/entityPolaritySpans`。
- runtime selectedData 编译层也使用同一套 career slot 归一化，兜住单测或其他路径直接传入未规范 profile 的情况。
- `TurnDecision` prompt 增加“加入广东和江西”这类 bare region add 的 hard rule：没有当前方案、候选志愿或具体志愿项锚点时，`加入/加上/记上` 地域、院校、专业、发展方向属于 `intent_pending/future_reference/intent_update`，不能走 `add_units/plan_preview`。

新增 model node benchmark：

- `node-intent-entity-extraction-G33`
- prompt：`我想要优先稳定体制内`
- 断言：
  - `entityType=career`
  - `careerValues` 包含 `体制内/考公导向`、`稳定就业导向`
  - `majorValues` 不包含 `体制内/稳定就业`
  - `entityPolaritySpans` 的实体类型为 `career`

新增/更新验证：

- `test_normalize_career_slots_accepts_common_direction_aliases`
- `test_intent_entity_profile_normalizes_career_aliases_out_of_major_values`
- `test_intent_entity_profile_normalizes_career_value_aliases_to_labels`
- `test_runtime_intent_entity_profile_pending_card_normalizes_career_alias_major_misclassification`
- `test_turn_decision_prompt_routes_bare_region_add_as_future_intent`
- `test_chat_service_runtime_intent_hard_cut_routes_bare_region_add_to_future_intent`
- `test_model_node_benchmark_flags_career_direction_as_major_regression`
- `py_compile app/domain/career_slots.py app/tools/intent_entity_profile_tool.py app/tools/turn_decision_tool.py app/service.py ...`：通过。
- `pytest tests/unit/test_career_slots.py tests/unit/test_intent_entity_profile_tool.py tests/unit/test_turn_decision_tool.py tests/unit/test_model_node_benchmark.py -q`：37 passed。
- `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_hard_cut or runtime_intent_entity_profile_context or runtime_intent_entity_profile_pending_card" -q`：29 passed。
- `python examples/model_node_benchmark.py --cases examples/model_node_benchmark_320_cases.json --nodes intent_entity_extraction --actual-source fixture`：4/4 passed，`career_direction_bucket_accuracy=1/1`。
- `pytest tests/unit/test_proposal_compiler_runtime_selection.py -k "intent_payload_scope_helpers_detect_positive_and_negative_values or intent_preview_turn_decision_arbitration or atomic_plan_action or needs_plan_first_guard" -q`：15 passed。

随后继续做小范围 live 验证：

- 最新工作区代码临时 Agent `18316` 跑 production micro：`/tmp/dialog_regression_320_prod_asset_micro_18316_after_career_region.metrics.json`。
  - 8/8 successful，0 failed。
  - career case 回复从旧的 `偏好专业：体制内` 修正为 `发展方向：体制内/考公导向`。
  - `加入广东和江西` 修正为 `runtime_intent_hard_cut` + pending card `偏好地域：广东、江西`，不再走 full-agent/add_units，也没有丢实体。
  - median `20764ms`，p95/max `37912ms`。长尾仍集中在 full-agent candidate/query 链路，以及 direct intent 的多模型串行。
- 基于 micro timing 继续收敛 direct intent 性能：当 `TurnDecision=intent_pending/future_reference` 高置信，且 `IntentEntityProfile` 高置信输出单一非专业正向 bucket（career/region/school/budget）时，跳过第三个 `IntentSideEffect` 仲裁；纯 major 单项仍保留仲裁，防止“计算机适合我吗”这类只读咨询误生成 pending。
- 新增 probe `examples/dialog_regression_320_career_region_fastpath_probe.json`，临时 Agent `18317` 输出 `/tmp/dialog_regression_320_career_region_fastpath_18317.metrics.json`：
  - 2/2 successful。
  - career `我想要优先稳定体制内`：从 micro 的 `20577ms` 降到 `13547ms`，eventTimings 中不再有 `intentSideEffectDurationMs`。
  - region `加入广东和江西`：从 micro 的 `20951ms` 降到 `14861ms`，eventTimings 中不再有 `intentSideEffectDurationMs`。
- fast path 后重新验证：
  - `pytest tests/unit/test_chat_service_history_persistence.py -k "runtime_intent_hard_cut or runtime_intent_entity_profile_context or runtime_intent_entity_profile_pending_card" -q`：30 passed。
  - `pytest tests/unit/test_career_slots.py tests/unit/test_intent_entity_profile_tool.py tests/unit/test_turn_decision_tool.py tests/unit/test_model_node_benchmark.py -q`：38 passed。
  - `py_compile app/service.py app/domain/career_slots.py app/tools/intent_entity_profile_tool.py app/tools/turn_decision_tool.py ...`：通过。

当前边界：

- `加入广东和江西`、`我想要优先稳定体制内` 这类高置信非专业 future intent 已经不再需要第三个 `IntentSideEffect` 模型节点；但专业单项仍保守保留仲裁。后续真正的 P0 性能方向仍是合并 `TurnDecision + IntentEntityProfile`，而不是继续逐类扩 fast path。
- 这次只覆盖 career alias 与 bare region add 的框架缺口；候选列表、当前方案条目、active pending 精细引用仍属于后续 `StructuredContextLedger / ContextReferenceResolver`。
