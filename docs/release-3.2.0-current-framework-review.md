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
