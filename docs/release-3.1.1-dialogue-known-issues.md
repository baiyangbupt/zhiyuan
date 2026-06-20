# Release 3.1.1 Dialogue Known Issues

本文记录 `prod-3.1.0` 上线后继续进入 `3.1.1` 的对话侧待处理问题。`3.1.0` 生产标签为 `prod-3.1.0`，当前基线提交为 `55a786a chore: add 3.1.0 release smoke and docs`。

## 1. 记录口径

- 只记录当前回归或人工走查中仍可复现的问题，不把 `3.1.0` 已完成修复重新列为缺陷。
- 对极端玩笑、攻击性或明显无业务含义输入，优先级低于典型志愿填报场景；除非会触发误改方案、误写偏好或严重拒答。
- 修复原则仍保持 `Explore / Policy / Intent / Plan` 分层一致：不要用用户话术字符串枚举兜底，不新增多条兼容旁路；典型问题先从语义边界、工具事实、pending 确认和统一 proposal/apply 链路上解决。

## 2. 当前确定待处理

### P0-0 人工走查发现的确认卡和方案预览问题

来源：

- `prod-3.1.0` 上线后本地/测试环境前端人工走查。
- 覆盖确认采纳卡、方案替换预览、补充志愿选择和整体对话体验。

现象：

1. 确认采纳卡点击确认后，卡片标题仍显示“待确认”，状态没有按用户操作变成已采纳/处理中/已生效等用户可理解状态。
2. 方案替换类预览只说明“要替换哪个志愿”，没有预览“用哪个志愿替换进去”。用户无法判断替换后质量、地域、专业、院校层次和风险变化。
3. 补充志愿的候选选择仍欠缺用户 intent 相关排序：没有稳定按用户已采纳/当前表达的专业、地域、院校、预算、风险偏好做有次序的填充。
4. 对话质量还需要继续优化，尤其是多轮真实对话、模拟用户分叉、拒绝引导、只读分析和方案动作之间的边界。

期望：

- 卡片状态与后端 pending/apply 结果一致，点击后标题和按钮状态都能明确表达“处理中/已采纳/已执行/已失效”。
- 替换预览必须同时披露 `from -> to`，包括被替换项、补入项、关键差异和影响摘要；缺少补入项时不能生成可确认替换卡。
- 补充/替换候选选择应进入统一策略：先满足硬要求，再按软偏好和推荐系数/录取风险/院校层次/专业相似度排序，不能只按任意候选填空。
- 建立可持续 benchmark，用真实对话抽样、autoexplorer 模拟和固定回归 case 共同评估质量、正确性、耗时和状态一致性。

后续处理方向：

- 前端确认卡状态映射和后端 pending 状态统一检查。
- Java proposal 的替换/补充结果必须返回可展示的目标志愿详情；Agent 和前端不能只展示 ID 或只展示被移出项。
- `RepairCandidateSelector` / user-goal proposal 选择策略补充 intent-aware 排序和可解释字段。
- 将 `assets/` 下 autoexplorer 原始数据和运行报告纳入 3.1.1 benchmark 资产索引。

当前进展：

- 已修复前端确认卡 badge 文案硬编码问题：`active` 显示“待确认”，`applied/cancelled/replaced/expired` 会显示对应状态。
- 已修复 pending 确认卡只展示 `summary`、吞掉 `content` 明细的问题：前端现在会同时展示概览和卡片内容，避免替换预览被覆盖。
- 已补齐 user-goal proposal 替换预览链路：Java `replaceAction` 会生成可读 `from -> to` 明细和关键变化；Agent facts/card formatter 保留并展示 action `detail`，不再只展示 action summary 或内部 ID。
- 已调整 user-goal 补入/替换 preview 候选排序：在硬约束、scope 命中、安全候选过滤之后，优先按 intent/match 分，再看录取率、推荐分、院校排名；避免高推荐分但低用户匹配候选抢占补入/替换预览。
- 已补单测覆盖：`UserGoalProposalBuilderTest` 的可读替换明细、补入 intent-aware 排序、满额替换 intent-aware 排序；`test_fix_proposal_card_content_includes_readable_replacement_preview_detail`；`test_generate_planning_fix_proposals_formats_status_and_warnings` 保留 action detail/replacementPairs。
- 2026-06-19 已跑 3.1.1 review/repair 关键 e2e：`examples/dialog_regression_310_review_repair_cases.json` 共 9 step，`failedSteps=0`，结果写入 `/private/tmp/zhiyuan_311_review_repair_closure.json`。剩余问题主要是耗时 warning：median `26185ms`，max `45929ms`，4 条超过 30s。
- review/repair e2e 中仍观察到一个模型能力边界：`方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动` 被路由为 `analyze_adjustment`，没有生成可确认预览；当前 case 未判失败，但它说明“先看看能怎么处理”在费用/合作类风险下仍可能被模型理解为只读分析，而不是 preview。此项不在 3.1.1 继续加 runtime bridge，纳入 3.2.0 profile。

### P0-1 压线风险咨询被误回成确认边界话术

来源：

- 最新 88 条真实对话衍生回归：`/private/tmp/zhiyuan_303_dialogue_derived_after_arealevel_fix.json`
- Case：`303-dialogue-near-batch-line-no-overpromise`
- Prompt：`分数刚压本科线，别给我画大饼`

现象：

- 回归记录 `failures` 中仍有 1 条内容门禁失败，虽然 summary 显示 `failedSteps=0`。
- 实际回复变成“这轮不会改动当前方案，也不会写入后续报考参考”的确认边界话术。
- 没有回答用户真正关心的本科线/压线、保底/兜底、民办/专科和风险建议。
- 耗时约 `76s`，同时触发慢请求 warning。

期望：

- 这是只读 Policy/风险解释场景，不应进入 Intent/Plan 确认话术。
- 回复应直接给出压线考生的风险边界：本科批机会、保本科策略、民办/中外合作/专科兜底、冲稳保安全垫、下一步需要看位次和批次线。
- 如果没有当前方案，也不能用“不会改动方案”作为主体答复。

后续处理方向：

- 建立高置信只读 Policy 语义入口或强化 full agent 调度规则，让分数/批次线/压线类问题优先走 `answer_admission_policy_question` 或等价只读政策框架。
- 对 `score_batch` 类工具输出补充压线风险结构化 focus，最终仍由模型按用户语言组织，不靠用户原话字符串枚举。
- 修复回归 runner summary 与 failures 口径不一致，避免发布前误判为全通过。

当前进展：

- 已修复回归 runner summary 口径：`failedSteps` 现在会统计请求/WS 错误、样式断言、内容断言、工具路径断言和性能硬失败，并输出 `failedByReason`。
- 已补 3.1.1 定向修复：`分数刚压本科线，别给我画大饼` 这类高置信压线风险问题在模型只返回确认边界/无有效政策事实时，会恢复成只读 Policy 风险说明，覆盖本科线、压线、保本科/保底/兜底、民办/专科和下一步核验信息；不会生成 pending 卡。
- 已补单测：`test_chat_service_recovers_batch_line_risk_policy_reply_from_boundary_only_misroute`。

### P0-2 专业组内“只保留最稳专业”被误解为长期稳定就业意向

来源：

- 最新 88 条真实对话衍生回归：`/private/tmp/zhiyuan_303_dialogue_derived_after_arealevel_fix.json`
- Case：`303-dialogue-operation-major-group-keep-safest-major`
- Prompt：`专业组里只保留最稳的专业行不行`

现象：

- 实际回复生成了“只保留发展方向：稳定就业导向”的意向预览。
- 用户问的是当前方案/专业组内的局部操作可行性或规则解释，不是长期职业方向、就业导向或后续偏好。
- 耗时约 `53s`，触发慢请求 warning。

期望：

- 该场景属于 Plan/Policy：解释专业组内专业选择、组内安全垫、保底专业、是否能删专业行，以及需要确认专业组模式和当前方案具体条目。
- 不能生成职业/发展方向 Intent pending，也不能写入后续报考参考。

后续处理方向：

- 收紧 Intent 恢复边界：当前方案、专业组、组内专业、只保留最稳/删掉风险专业这类局部对象，不能被恢复成 career/major long-term intent。
- 让 `PlanGoal`/Plan action 链路承接组内局部操作和只读解释；如果无法安全执行，返回具体需要查看的专业组/专业行和确认边界。
- 增加单测和对话回归，断言不能出现“稳定就业导向”意向卡。

当前进展：

- 已补 3.1.1 定向修复：`专业组里只保留最稳的专业行不行` 被判为专业组内局部策略/只读解释时，即使 full agent 误调用 career intent preview，也会降级为专业组规则和风险说明，并清空 intent pending/followup。
- 修复范围仅覆盖“专业组/组内 + 只保留最稳/安全垫 + 可行性提问”这种局部对象，不拦截用户明确表达的长期稳定就业或职业方向偏好。
- 已补单测：`test_chat_service_downgrades_major_group_keep_safest_from_career_intent_preview`。

### P0-3 排除当前方案专业时，已有可执行预览但未落 pending 确认卡

来源：

- 2026-06-19 3.1.1 constraint/plan action e2e。
- 命令输入：`zhiyuan-agent/examples/dialog_regression_310_constraint_plan_action_cases.json`
- 结果文件：`/private/tmp/zhiyuan_311_constraint_plan_action_closure.json`
- Case：`310-constraint-exclude-major-preview-and-apply`
- Session：`9903103`
- Prompt：`不要英语相关专业，当前方案里有的话也删掉`

现象：

- 第一步回复已经定位到当前方案中英语相关 3 条志愿：
  - 青岛城市学院 · 商务英语
  - 青岛恒星科技学院 · 英语（外语语种为英语）
  - 海口经济学院 · 英语（教育、翻译、商务方向）
- 回复文案明确表达“如果后续采纳，会把这 3 条移出当前方案”，并追问“需要我现在确认移除吗？”
- 但 WebSocket followup 中没有 `pendingConfirmationCard`，`followupMessages=0`。
- 第二步用户发 `确认执行` 后，系统回复“没有上一轮正在等待采纳或执行的内容”，说明后端 pending 状态确实没有落下。
- 本轮 constraint/action e2e 汇总为 9 step、8 step 通过、1 step 内容失败；失败原因是 `assertFollowupType=pendingConfirmationCard` 和 `assertFollowupCount=1` 不满足。

已确认事实：

- 这不是后端执行层没有生成预览。失败回合的工具链路是：
  - `preview_current_major_intent_confirmation` 返回 `status=empty`，提示没有稳定识别“要保留”的正向范围。
  - 随后 `plan_next_action` 返回 `remove_units` preview，`requires_confirmation=true`。
  - `execute_plan_action` 返回 `action_family=remove_units`、`stage=preview`、`result_kind=preview_only`、`reply_focus=["preview_only","confirmation_required","constraint_plan_removal"]`。
  - `execute_plan_action.facts.resolved_apply_payload.atomic_actions[0].volunteer_ids` 已包含 3 个可执行志愿 ID。
  - `execute_plan_action.facts.intent_update.selected` 已包含后续报考参考更新：`negative_level3=["英语","商务英语","翻译","英语语言文学"]`。
- 用已保存的 `9903103` history 直接调用 `_extract_plan_confirmation_candidate(...)` 可以抽出完整 `remove_units` plan pending candidate，包含 `stage=apply` payload、3 个 volunteer id 和 intent update。
- 因此问题不在 Java proposal、不在 `execute_plan_action` 预览结果本身，也不在基础 candidate 构造能力；问题落在当轮 ChatService 最终组装/保存 followup 阶段：可确认 Plan preview 在 Intent+Plan 混合回合中没有被保存为 pending 卡。

初步定性：

- 这是 3.1.1 P0：用户已经看到“可确认/可采纳后执行”的高副作用方案动作，但系统没有对应 pending 状态，下一轮短确认无法执行。
- 修复应复用现有 `plan preview -> pendingConfirmationCard -> confirm -> apply` 主协议，把已经存在的 `remove_units preview_only + resolved_apply_payload + intent_update` 正常落成 plan pending。
- 不应新增“上一轮文案里出现确认就执行”的文本桥接，也不应新增另一套确认兼容路径。

与 3.2.0 的关系：

- 该 case 暴露的是模型/编排混合路径问题：同一回合先走了 Intent preview 工具（且 empty），又走了 Plan preview 工具；最终应该以可执行 Plan preview 为准。
- 3.2.0 需要在 `TurnDecision -> ToolPlan -> Proposal/Pending` 中明确同一回合只能产生一个用户可确认对象，且优先级由结构化 side effect 决定，不由模型最终文案决定。
- 该 case 应进入 3.2.0 profile 的 golden 集，用来测 `sideEffect=plan_preview`、`expectedPending=plan_mutation`、`mixed intent+plan turn consistency`。

当前处理建议：

- 3.1.1 做窄修：当同一当前回合存在可执行 `remove_units/add_units/replace_units` preview，且 `resolved_apply_payload` 已给出执行 scope，即使同回合出现 empty/non-pending intent preview，也必须落 plan pending card；若 intent update 存在，作为 plan pending 的附带 `intentPayload`，确认后先采纳报考参考再执行方案动作。
- 修复后只复跑：
  - `tests/unit/test_chat_service_history_persistence.py` 相关 plan pending/constraint 单测。
  - `examples/dialog_regression_310_constraint_plan_action_cases.json`。
- `examples/dialog_regression_310_review_repair_cases.json` 做回归防串扰。

2026-06-20 3.1.1 修复进展：

- 已按主协议做窄修，没有新增文本确认 bridge 或 shadow 路径：
  - `execute_plan_action` 的直接 JSON payload 字符串现在可被统一解析。
  - plan pending candidate 复用同一 payload 解析入口，避免工具调用形态差异导致可执行 preview 丢失。
  - `remove_units` 的 `source_major_names` 被视为有效执行 scope，保证“当前方案里有的话删掉”这类按专业名解析出的动作能落 pending。
  - 同回合错误/空的 intent preview 不再覆盖已存在的可执行 plan preview；真正 active 的历史 `only_keep` pending 仍会拦截不安全的负向方案动作。
- 定向单测已覆盖：
  - 直接 payload string 提取。
  - 同回合错误 `only_keep` intent preview + 正确 `remove_units` plan preview 时优先落 plan pending。
  - active `only_keep` pending 仍能阻断普通负向 remove preview。
- 定向 e2e 已通过：`examples/dialog_regression_310_constraint_plan_action_cases.json` 写入 `/private/tmp/zhiyuan_311_fix_310_constraint_plan_action_r2.json`，`steps=9`、`successfulSteps=9`、`failedSteps=0`，median `16278ms`，max `40199ms`。
- 小范围回归已通过：`/private/tmp/zhiyuan_311_small_regression_p03_constraint_plan_action.json`，`steps=9`、`successfulSteps=9`、`failedSteps=0`，median `16855ms`，max `44115ms`。本轮 `不要英语相关专业...` 实际走 `apply_fix_proposal` 预览/确认链路，仍满足 `preview -> pendingConfirmationCard -> confirm -> apply` 主协议，不新增 action family 兼容要求。

### P0-4 Career intent 确认卡内容被通用 title 覆盖

来源：

- 2026-06-19 full journey 扩展回归。
- 结果文件：`/private/tmp/zhiyuan_311_full_journey_round1.json`
- Case：`full-journey-career-stable-region-fix-boundary`
- Session：`5745`
- Prompt：`先把体制内稳定就业当成优先参考`

现象：

- 工具层 `preview_current_career_intent_confirmation` 已正确识别出两个 selected item：
  - `体制内`
  - `稳定就业`
- 但用户可见回复变成：
  - `已列出这次报考想法预览：好的，我先把这次你提到的想法整理一下...`
- `pendingConfirmationCard.summary/content` 同样是通用 title 文案，没有展示“体制内/稳定就业”。
- 用户点击/回复确认后，回复只有“已采纳。后续推荐和专家优选会更贴近这个方向...”，仍没有回显本次采纳的具体内容。

初步定性：

- 这不是模型没有理解意图；结构化 payload 里已有正确 items。
- 问题在 career intent card/reply formatter：summary/content 取了 payload title 或 message，而不是从 selected items 生成用户可读摘要。
- 这属于 3.1.1 可以窄修的展示/协议落点问题，不需要新增 route、shadow 或确认文本桥接。

期望：

- 预览回复和卡片必须展示：`发展方向：体制内/考公导向、稳定就业导向` 或等价用户语言。
- 确认后必须回显本次采纳内容。
- 如果 items 存在，title 只能作为卡片标题/引导，不应覆盖 summary/content。

建议验证：

- 增加 career intent pending card 单测：结构化 items 存在时，card summary/content 和 confirm ack 均包含具体方向。
- 复跑相关 full journey 单 case；不要求修复 full journey fixture 后才验证此展示问题。

2026-06-20 3.1.1 修复进展：

- 已按 formatter/protocol 落点做窄修，没有改动 intent 合并业务逻辑：
  - career slots 无法映射到标准 label 时，保留原始用户语言，例如 `体制内`、`稳定就业`。
  - intent preview 的 primary reply、pending card summary/content 优先由 selected item values 生成，不再被通用 title 覆盖。
  - pending intent 确认后，如果 `preference_applied/constraint_applied` 只返回泛化采纳文案，且回复没有包含 pending summary 的具体内容，则补充 `本次内容：...`。
- 定向单测已覆盖：
  - literal career values 摘要保留。
  - career item values 优先于通用 title。
  - career pending 确认后回显 `体制内/稳定就业`。
- 定向 e2e 已通过：`302-explore-career-to-soft-intent` 写入 `/private/tmp/zhiyuan_311_fix_302_career_single_after_confirm_summary.json`，`steps=4`、`successfulSteps=4`、`failedSteps=0`，median `11065ms`，max `22017ms`。确认回复包含 `本次内容：发展方向：“体制内”、“稳定就业”`。
- 同时复跑完整 `examples/dialog_regression_302_explore_intent_cases.json` 时仍有 1 个失败：`302-soft-hard-intent-mix-with-plan-impact` 第二轮旧断言期待“确认时无 pending”，但第一轮实际已生成 intent pending。该项按陈旧 fixture/软硬意向契约重定义处理，不用业务兼容逻辑去满足旧断言。
- 小范围回归已通过：`/private/tmp/zhiyuan_311_small_regression_p04_career.json`，`steps=4`、`successfulSteps=4`、`failedSteps=0`，median `11669ms`，max `16227ms`。预览和确认回复均保留 `体制内/稳定就业` 的具体内容。

### P0-5 单独负向地域排除未生成 pending 卡

来源：

- 2026-06-19 full journey 扩展回归。
- 结果文件：`/private/tmp/zhiyuan_311_full_journey_round1.json`
- Case：`full-journey-soft-hard-mix-major-group-remove-add`
- Session：`5749`
- Prompt：`东北西北都不要，必须避开`

现象：

- `intentSideEffectDecision` 判定为 `intent_preview`，confidence `0.95`。
- 理由也明确识别为“不要/必须避开”的强排除要求。
- 但最终回复是“没有稳定识别出具体要保留的专业、院校或地域”，没有 `pendingConfirmationCard`。
- 下一轮 `确认` 进入 no-pending guard。

初步定性：

- 这不是用户表达不清；“东北/西北都不要，必须避开”足以形成负向地域 intent pending。
- 问题可能在 `preview_current_region_intent_confirmation` 对 negative-only region constraint 的处理：把负向排除错误套进 only_keep/必须存在正向保留范围的逻辑。
- 3.1.1 可做窄修：负向地域排除应独立生成 `排除地域：东北、西北` pending，不要求用户补“要保留哪里”。

期望：

- 该 prompt 应生成 `intent_change` pending card，summary/content 明确展示 `排除地域：东北、西北`。
- 确认后写入后续报考参考，并刷新候选/必要工作区。
- 不新增“用户说确认就强行写入”的文本桥接。

2026-06-20 3.1.1 修复进展：

- 已按 intent normalization 窄修：当 semantic side-effect 把纯负向地域排除误标成 `only_keep/must_have` 时，系统先只在用户话里存在明确正向范围信号时尝试恢复正向范围；恢复后仍是纯负向 payload，则降级为 `default` 强排除条件，直接生成 `排除地域：...` pending。
- 保留原有保护：`孩子就想去南方，北方先别考虑` 这类真实 only_keep 若模型只传了负向北方，仍会尝试恢复正向南方；不会退化成单独排除北方卡。
- 已补单测：
  - `test_semantic_only_keep_region_recovers_missing_positive_area`
  - `test_negative_only_region_constraint_not_blocked_by_semantic_only_keep_label`
  - `test_chat_service_negative_only_region_constraint_creates_intent_pending_card`
  - `test_chat_service_only_keep_region_preview_without_positive_scope_does_not_become_exclude_card`
- e2e 验证：`full-journey-soft-hard-mix-major-group-remove-add` 中目标步骤 `东北西北都不要，必须避开` 已生成 `pendingConfirmationCard`，summary/content 为 `排除地域：东北、西北`；下一轮确认回复包含 `本次内容：排除地域：东北、西北` 并刷新 ordered/candidate。结果写入 `/private/tmp/zhiyuan_311_fix_p05_negative_region_single_full_journey.json`。
- 该 full journey 整 case 仍为 6/9，剩余失败来自前置方案/候选为空和旧断言期待后续删除/补入 apply，不属于 P0-5 回退。
- 小范围回归已通过：`/private/tmp/zhiyuan_311_small_regression_p05_negative_region.json`，`steps=2`、`successfulSteps=2`、`failedSteps=0`，median `5573ms`，max `8971ms`。确认后 followup 同时刷新 ordered/candidate。

### P1-1 Full agent 长尾仍需继续压缩，但不能牺牲回复质量

来源：

- 同一轮 88 条回归 summary：
  - median `17.7s`
  - p95 `36.4s`
  - max `76.1s`
  - 超过 45s warning：2 条

现象：

- 专项资格问题已恢复质量，耗时约 `10.4s`，暂不列为质量缺陷。
- 慢点集中在压线政策咨询和专业组局部操作误路由。

期望：

- 高置信只读政策和明确 Plan 局部操作应减少 full agent 长尾。
- 对不能安全快路由的复杂问题，继续优先保证回复质量；前端 thinking hint 可以承接等待感知，但不能用低质量模板换延迟。

后续处理方向：

- 只对高置信、低副作用、语义边界清晰的场景做语义快捷入口。
- 继续用回归记录里的 `turnObservability` 区分模型长尾、工具长尾、重复工具和误路由。

### P1-2 Benchmark 和真实对话模拟体系需要沉淀

来源：

- 新增 `assets/` 原始数据和 autoexplorer 运行结果。
- 生产样本分析、生产风格模拟、长 prompt replay、转写对话和人工标注。

现象：

- 当前已有大量真实/模拟对话资料，但还没有统一 benchmark 分层和版本验收入口。
- 自动探索报告中存在 judge 失败、上下文 mismatch、场景 session 绑定等噪声，需要区分“产品问题”和“评估噪声”。

期望：

- 将 benchmark 分为固定回归、生产抽象模拟、真实样本抽取、长对话 replay、前端人工走查五层。
- 每层明确输入文件、运行命令、评价维度、噪声处理和晋级规则。
- 新发现的问题先进入 known issues，修复后沉淀为稳定回归 case。

后续处理方向：

- 新增 benchmark 文档索引 `release-3.1.1-dialogue-benchmark.md`。
- 从 autoexplorer 报告中提炼可稳定复现的高价值 case，而不是直接把所有 judge issue 当缺陷。
- 建立按版本持续累积的场景集，不再按旧版本号割裂维护。

### P1-3 Full journey 回归资产依赖隐含前置状态，当前不能作为稳定发布门禁

来源：

- 2026-06-19 full journey 扩展回归。
- 命令输入：`zhiyuan-agent/examples/dialog_regression_full_journey_cases.json`
- 结果文件：`/private/tmp/zhiyuan_311_full_journey_round1.json`

结果：

- `steps=69`
- `successfulSteps=53`
- `failedSteps=16`
- `failedByReason={"content": 16}`
- median `16786ms`
- p95 `31589ms`
- max `44938ms`

主要失败形态：

- 多个 case 清理历史和 backend pending/planning intent 后，当前方案/候选为空。
- 用户后续要求“移动第 3 个专业组”“删除第 5 个专业组”“把会计审计相关换掉”“补一个候选专业组”等动作时，系统正确返回无可操作对象或信息不足，没有生成 pending。
- case 断言仍期待 `ordered` refresh 或“已移动/已删除/已加入”等 apply 结果，导致内容失败。

初步定性：

- 这类失败大部分不是业务回退，而是回归 case 的 fixture 契约失效：case 假设会话已有方案/候选/基础报考信息，但 runner 的清理策略和当前会话数据使其实际为空。
- 不应通过业务代码去“空方案也移动/删除/补入”来满足旧断言。
- `dialog_regression_full_journey_cases.json` 当前应降级为“探索/发现集”，不能直接作为 3.1.1 稳定发布门禁。

处理方向：

- 将 full journey 拆成明确 fixture 类型：
  - `empty_state_journey`：验证空方案下的安全拒绝和引导。
  - `plan_present_mutation_journey`：必须预置 ordered plan。
  - `candidate_present_add_journey`：必须预置 candidate pool。
  - `generated_plan_journey`：必须先生成方案并确认，再进入审查/修复。
- 对依赖真实会话状态的 case 使用 `cloneBackendStateFromSessionId` 或稳定 fixture，不要靠 session id 隐含数据。
- 修改断言：当工具返回 error/no scope/no candidate 时，应断言“不改动方案 + 无 pending”，而不是期待 ordered refresh。

### P1-4 费用/中外合作只读风险询问被泛化成通用方案审查

来源：

- 2026-06-19 open quality 回归。
- 结果文件：`/private/tmp/zhiyuan_311_open_quality_round1.json`
- Case：`303-open-quality-budget-risk-colloquial-readonly`
- Prompt：`方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动`

现象：

- 断言层面通过，且没有生成可执行 pending。
- 但最终回复主要是通用审查结论：冲区占比过高、本省保底不足、概率倒挂等。
- 回复没有正面回答用户关注的“中外合作是不是多”“预算一般的风险”“高收费如何影响保底/家庭承受力”。

初步定性：

- 这是 focused readonly 问题被 `review_plan` 泛化覆盖。
- 当前 `review_plan` 能提供整体风险，但缺少“按用户指定 issue refocus 后生成回答”的稳定约束。
- 不建议 3.1.1 为该口语化 prompt 增加字符串分支；应进入 3.2.0 profile，要求 `ToolPlan` 携带 target issue/focus，并要求 reply generator 优先回答用户焦点。

补充观察：

- 2026-06-19 303 累积补跑再次复现同类问题。`dialog_regression_303_open_quality_cases.json` 中 `303-open-quality-budget-risk-colloquial-readonly` 断言通过，但回复仍主要围绕冲稳保、本省保底、概率倒挂，没有回答预算/中外合作。
- `dialog_regression_303_dialogue_derived_cases.json` 中类似问题还包括：
  - `预算一般，是不是要少放中外合作`
  - `高收费会不会影响保底安全`
  - `优先专业还是学校，这版偏哪边`
  - `能不能用大白话说下这版值不值得`
- 这些 case 说明当前问题不是某一句话术，而是 `review_plan` evidence 与最终 reply focus 没有绑定。3.1.1 不应继续添加口语化 prompt 分支。

### P1-5 偏好采纳与当前方案替换预览边界过强绑定

来源：

- 2026-06-19 303 累积补跑。
- 结果文件：
  - `/private/tmp/zhiyuan_311_303_open_quality_round1.json`
  - `/private/tmp/zhiyuan_311_303_effect_perf_round1.json`
- 代表 prompt：
  - `我倾向会计学和审计学，但土木工程不要`
  - `我倾向法学和财政学，但护理不要`

现象：

- 用户表达的是“专业偏好 + 排除方向”，自然语义上更像后续报考参考的 `intent_change`，当前方案影响应作为附带说明或后续可选动作。
- 实际在部分 session 中，系统直接生成 `plan_mutation/apply_fix_proposal` pending card，把“采纳偏好”和“替换当前方案命中项”合并为一张高副作用卡。
- 旧回归 case 有些接受该结果，因此断言层面不失败，但产品边界并不清晰：用户可能只想先记偏好或看影响，却被推到当前方案替换执行卡。
- 另一类 case `医学护理这些别碰，财会还能接受，先看看影响` 中，`intentSideEffectDecision` 判为 `mixed_answer_then_ask` 且 `honored=true`，最终没有出卡，说明系统已经需要在“先看影响”和“直接采纳/替换”之间做细粒度裁决。

初步定性：

- 这是 sideEffect 唯一裁决层缺失问题，不是单一工具 bug。
- 当前模型侧 `intentSideEffectDecision`、intent preview 工具、plan mutation formatter、directToolReturn 后处理之间没有统一仲裁：
  - 有时模型判断应先分析，最终仍可能出卡。
  - 有时工具返回 plan mutation，用户原始表达仍更适合作为 intent pending。
  - 有时确认卡把 intent update 和 plan action 混成一个不可拆的动作。

3.1.1 处理边界：

- 不为这类表达新增 shadow 或桥接。
- 不在 3.1.1 大改 intent/plan 复合协议。
- 如出现“明确只看影响/先别记/先不要改方案”却生成高副作用卡，可作为窄 bug 单独修。

3.2.0 方向：

- `TurnDecision` 必须先给出唯一 `sideEffect`：`readonly / intent_pending / plan_preview / composite_pending / clarification`。
- `CompositeProposal` 需要把 `intentUpdates` 和 `planActions` 分层展示：用户可清楚看到“采纳偏好”和“调整当前方案”是否都将执行。
- 对“偏好 + 当前方案已有冲突”场景，应支持两阶段：
  - 先采纳偏好并说明当前命中影响。
  - 用户再选择是否生成替换/移出预览。
  - 或在用户明确要求“当前方案有的话也删掉/替换”时生成 composite plan pending。

## 3. 继续观察项

### W1 审查/修复回复仍可能出现偏系统化表达

背景：

- `3.1.0` 已对审查修复文案和 proposal 展示做了多轮收口。
- 仍需在 3.1.1 回归中继续观察“不能直接处理/候选不足/预览不可用”等场景是否出现内部状态词或过度系统化表达。

观察重点：

- 不向用户暴露 `blocked`、`cannot_satisfy`、`preview_only`、`fix_proposal`、`候选池不足` 等内部表达。
- 不能处理时用用户能理解的原因：可替换项不够、会明显降低院校层次、会改变专业组数量、需要先放宽地域/专业/预算条件。
- 不把“移出 0 条、补入 0 条”这类无意义动作写进用户回复。

### W2 约束意向与方案联动需要继续做端到端验收

背景：

- `3.1.0` 已将 `only_keep / must_have / exclude` 收口到 Java `user_goal` proposal/apply 主链路。
- 3.1.1 仍需持续验证：排除、仅保留、必须有、中外合作/高收费预算等约束采纳后，是否能正确生成方案预览、确认后执行、刷新方案和审查状态。

观察重点：

- 不能只写入报考参考而不处理当前方案，除非执行层明确说明当前不能安全调整。
- 不能把“仅保留 X”误转为“排除 X”。
- 专业、专业类、招生计划自定义专业类之间存在歧义时，要在预览里披露或要求用户确认。
- 2026-06-19 e2e 当前状态：`only_keep`、`must_have`、`exclude cooperative program`、`tuition budget` 主路径基本可用；但 `exclude major + 当前方案移出` 发现 P0-3，属于发布前阻塞项。

### W3 典型场景回归仍需完整跑完

需要继续覆盖：

- 3.0.3 真实对话衍生 case。
- 3.1.0 constraint / plan action / review repair case。
- open quality、career direction、full journey 和累积生产抽象场景。
- autoexplorer 生产风格 follow/diverge 场景。
- `assets/dialogues` 中可抽取的真实转写/意图标注场景。
- 前端人工路径：对话输入、确认卡、工作区刷新、审查详情、修复预览、方案/候选筛选联动。

### W4 pending 存在时，只读方案查询可能被 pending 边界话术覆盖

来源：

- 2026-06-19 full journey 扩展回归。
- Case：`full-journey-ambiguous-intent-confirmation-boundary`
- Prompt：`先不确认，当前方案里有没有护理或者中医学`

观察：

- 上一轮存在 `偏好金融学类；排除护理学、中医学` 的待采纳 intent pending。
- 用户明确说“先不确认”，并询问当前方案是否有护理/中医学。
- 系统只回复 pending 的影响边界，没有实际查询/回答当前方案命中情况。

定性：

- 这是 pending 状态下的 readonly plan query 被 pending guard/影响说明抢占。
- 3.2.0 需要把 `pending_context + readonly_query_current_plan` 定义为合法场景：保留 pending，不应用，但仍可读取当前方案回答问题。

### W5 备选偏好和弱偏好容易被压扁

来源：

- 2026-06-19 full journey 扩展回归。
- Case：`full-journey-major-soft-hard-adjust-review`
- Prompt：`那把网络与新媒体作为优先方向，跨境电商也可以考虑`

观察：

- 系统生成 pending：`至少保留专业：网络与新媒体`。
- “跨境电商也可以考虑”没有进入 pending card，也没有作为 secondary/acceptable preference 展示。

定性：

- 模型/intent schema 对“优先 A，B 也可接受”的强弱偏好表达不够完整。
- 3.2.0 profile 需要覆盖 primary preference、secondary acceptable preference、hard constraint 三类权重，而不是全部压成 only/must/default。

### W6 候选查询缺少分数/位次时，容易把“缺前置条件”说成“无命中”

来源：

- 2026-06-19 full journey 扩展回归。
- Case：`full-journey-candidate-refresh-results-add-apply`
- Prompt：`我是湖北物化生，想看看候选里计算机和数据科学方向多不多`

观察：

- 用户只给了省份和选科，没有给分数/位次。
- 系统查询候选后回复“当前候选没有命中”“按你目前的分数和筛选条件暂时没匹配到”，容易让用户误以为已有分数条件参与判断。

定性：

- Plan query 缺少前置条件校验和 `missingInfo` 暴露。
- 3.2.0 需要明确：缺分数/位次时，应先说明当前只能看已有候选或要求补信息，不能把缺信息造成的空结果解释成分数不够。

### W7 303 realistic_user 两个失败主要是断言契约噪声

来源：

- 2026-06-19 303 累积补跑。
- 结果文件：`/private/tmp/zhiyuan_311_303_realistic_user_round1.json`
- 结果：`steps=9`，`successfulSteps=7`，`failedSteps=2`。

失败项：

- `303-real-user-lazy-plan-risk`：业务回复可用，失败集中在 `assertThinkingContainsAny` 的 thinking 文案白名单不匹配。
- `303-real-user-vague-confirm-guard`：实际无 pending guard 生效，失败是断言词与当前 no-pending 文案不完全匹配。

定性：

- 当前不应把这 2 条直接列为产品 P0/P1 缺陷。
- 它们说明旧 case 对 thinking 文案和 guard 文案的断言过窄，容易把可接受表达误报为内容失败。

处理方向：

- 对 thinking 文案只保留关键语义断言，减少固定文案白名单。
- no-pending guard 应断言语义：无待确认、不会执行、可继续说明下一步，而不是固定句式。
- 修完断言契约后再把 realistic_user 纳入稳定门禁。

### W8 Provider benchmark 缺少前置可用性门禁，容易把错误兜底误判为模型效果

来源：

- 2026-06-19 model provider 303 补查。
- 结果文件：
  - `/private/tmp/zhiyuan_311_model_provider_303_quality_readonly_agent_existing.json`
  - `/private/tmp/zhiyuan_311_model_provider_303_quality_readonly_glm52_validid.json`

观察：

- `model_provider_benchmark.py --agent-only --agent-url ...` 不会真正切换 provider；provider 配置只作为结果标签。若复用当前 8000 agent，结果只能代表当前 agent runtime env。
- GLM 5.2 的真实 SiliconFlow 模型 ID 是 `zai-org/GLM-5.2`；`Pro/zai-org/GLM-5.2` 返回 400 `Model does not exist`。
- 当前 SiliconFlow key 调用 `zai-org/GLM-5.2` 返回 403 `insufficient balance`。
- Agent 捕获 provider 异常后会快速返回安全兜底文案，导致耗时看起来非常低，但这不是模型质量通过。

定性：

- 这不是 GLM 5.2 的效果结论，而是 provider 接入前置失败。
- benchmark 工具如果不先做 provider 可用性校验，会把“模型不可用 + 系统错误兜底”混入质量评分。

处理方向：

- provider benchmark 进入质量评分前必须检查：
  - 模型 ID 存在。
  - API key 鉴权通过。
  - 账户余额/额度可用。
  - direct smoke 成功。
  - `--start-agent` 独立 agent 启动成功，且 `LLM_MODEL_NAME` 与结果 provider 一致。
- 错误兜底结果应标记为 `provider_unavailable`，不参与模型效果 median/p95 或 quality gate pass rate。

### W9 历史偏好被后续约束过强合并，导致 only_keep 范围收窄

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 文件：`dialog_regression_robust_cases.json`
- Case：`robust-typo-and-abbrev-580`
- Session：`933209010`

现象：

- 用户先说 `加合工大和南邮到意项里`，系统生成 `至少保留院校：合肥工业大学、南京邮电大学`。
- 下一轮用户说 `保底要公办不要民辨`，语义重点是“保底区要公办、不要民办”。
- 实际输出变成 `只保留院校：合肥工业大学、南京邮电大学；排除院校：民办院校`。

初步定性：

- 后一轮的 negative/hard constraint 把上一轮的 school preference 一并升级成 only_keep positive scope，造成候选范围过度收窄。
- 这不是断言失败，`robust_r1` 全过；但它会导致真实用户后续方案被不必要地限制到两所学校。
- 根因是 intent state merge 缺少 preference strength 和 scope binding：历史偏好、当前硬约束、保底局部约束被合并成同一种 only_keep。

3.1.1 边界：

- 不建议用字符串分支修 `民辨/民办` 这类话术。
- 若后续复现为高频产品问题，可做窄修：负向院校类型约束不能把已存在 school preference 升级为 only_keep。

3.2.0 方向：

- intent schema 需要区分 `preferred_colleges`、`must_include_colleges`、`only_keep_colleges`、`negative_college_type`。
- 合并新旧 intent 时必须保留来源和强度，不能用本轮 hard negative 覆盖历史 positive preference。

### W10 pending 采纳吞掉同轮新动作诉求

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 文件：`dialog_regression_robust_cases.json`
- Case：`robust-resume-mid-conversation`
- Session：`933209008`

现象：

- 用户先说 `把计算机类加进意向`，系统生成 `intent_change` pending。
- 用户下一轮说 `现在基于这些出方案`。
- 系统只执行上一轮 pending 采纳，回复“已采纳...下一步可以继续查看当前方案，或让我按这个方向整理补入预览”，没有继续处理“出方案”。

初步定性：

- 当前 pending apply 优先级过高，会把同轮额外动作诉求当成确认文本尾巴吞掉。
- 用户自然语言中“基于这些出方案”既包含确认上一轮意向，也包含新的 plan generation 目标。
- 这是复合 turn：`apply_existing_pending + plan_preview request`。当前状态机只能处理前者。

3.1.1 边界：

- 不新增“确认后继续自动出方案”的桥接逻辑。
- 不建议在当前多路径里补一条 service recovery，否则会扩大 pending/apply 与 plan generation 的耦合。

3.2.0 方向：

- `TurnDecision` 需要支持复合输入：
  - `apply_existing_pending_only`
  - `apply_existing_pending_then_new_plan_request`
  - `new_request_conflicts_with_pending`
- compiler 应能明确选择：先 apply pending 后生成新的 pending/preview，或要求用户确认是否继续生成方案。

### W11 “加到意向”默认升级为 must_have/至少保留，偏好强度过硬

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 代表 case：
  - `fuzzy-creative-unconventional-610-zj`
  - `robust-session-isolation-a`
  - `robust-resume-mid-conversation`
  - `robust-typo-and-abbrev-580`

现象：

- `把计算机类加到意向`、`把计算机类加进意向`、`还有数据科学和生物信息也加上`、`加合工大和南邮到意项里` 等表达，多次生成 `must_have/至少保留`。
- 用户字面表达是“加入意向/偏好/也可以考虑”的纳入动作，未必等价于方案中必须保留或硬性满足。

初步定性：

- 当前 schema/formatter 对“加入意向”缺少明确的 soft preference 表达，容易把它映射成 `must_have`。
- 这会影响后续候选排序、方案生成和修复补入，特别是在候选不足时过早阻断或过度收紧。

3.1.1 边界：

- 不建议逐条话术降级，避免又形成“加/加入/加进/意项”字符串兼容表。
- 3.1.1 可先记录并在 profile 中量化，不作为当前小修主线。

3.2.0 方向：

- profile 必须测 `soft preference`、`primary preference`、`acceptable fallback`、`must_have`、`only_keep` 的混淆矩阵。
- schema 需要支持偏好强度，formatter 也要把“偏好/优先参考”和“至少保留/硬要求”明确区分。

### W12 mixed/analysis 场景缺少可确认 transition，用户短确认体验差

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 文件：`dialog_regression_science_cases.json`
- Case：`science-software-engineering-intent-candidate`
- Session：`933210002`

现象：

- 用户说 `想学软件工程`。
- 系统判定为 `mixed_answer_then_ask`，先做适配分析，并提示“如果后续希望以软件工程作为优先方向，我可以把它作为推荐参考”。
- 用户下一轮 `确认`，系统进入 no-pending guard。

初步定性：

- 模型侧的判断并非完全错误：`想学软件工程` 可以先分析，不一定直接写入。
- 但回复中自然提出“可作为推荐参考”后，用户的 `确认` 在交互上很像确认这个 transition；系统没有结构化 selectable option/pending，所以只能 no-pending。

3.1.1 边界：

- 不建议把所有 analysis 后的“确认”都恢复成写入 intent，风险过大。
- 如果要小修，只能在回复中避免制造“可确认但无 pending”的暗示，或把明确 selectable option 结构化。

3.2.0 方向：

- 除 `pendingConfirmation` 外，需要定义轻量 `selectableProposal` 或 `suggestedIntentTransition`。
- 短确认只能作用于真实 pending 或结构化 selectable option，不能从自然语言暗示中恢复执行。

### W13 Plan action 动词缺失或语义错配：锁定被误路由为移动/no-change

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 文件：`dialog_regression_enriched_cases.json`
- Case：`specific-multi-pin-and-fill-26`
- Session：`933208012`

现象：

- 用户说 `帮我把方案里第1个和第2个冲档锁定 位置不要动`。
- 工具链路生成 `move_ordered_unit`，结果为 `no_change`，回复“烟台大学已经在第1位，本次不需要移动”。
- 后续 `确认锁定` 进入 no-pending；再问 `现在锁定了几个` 也没有读取锁定状态。

初步定性：

- 当前 action family 没有稳定表达“锁定/固定位置/不要动”这一类 plan state mutation。
- 模型把“位置不要动”中的位置语义映射到了移动排序，丢掉“锁定”主动作。

3.1.1 边界：

- 如果现有业务没有锁定能力，不应伪造锁定成功。
- 应至少回复“当前不支持锁定/只能记录保留位置要求/需要先生成可执行预览”，不能把它说成 no-change 移动。

3.2.0 方向：

- DSL/action schema 需要区分 `pin_or_lock_unit`、`move_ordered_unit`、`preserve_position_constraint`。
- compiler 发现 unsupported action 时返回 clarification/unsupported explanation，而不是改道成近似 action。

### W14 保底区内排序被理解成全方案排序

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 文件：`dialog_regression_enriched_cases.json`
- Case：`specific-conditional-reorder-26`

现象：

- 用户说 `保底区里录取率最高的调到保底第一位`。
- 预期 scope 是 `tier=保底` 内部第一位。
- 观察到系统倾向生成全方案位置 1 的移动语义。

初步定性：

- tier/local scope anchor 没有被稳定带入 plan action。
- “第一位”缺少局部范围限定时被默认解释为 whole-plan rank。

3.2.0 方向：

- PlanGoal 必须携带 `scopeAnchor=tier_segment` 和 `targetTier=保底`。
- compiler 必须把局部 ordinal 编译为 tier 内排序，而不是全局 ordinal。

### W15 工具调用预算缺失，score/candidate 查询容易重复放大长尾

来源：

- 2026-06-20 历史积累场景三轮回归阶段记录。
- 代表样本：
  - `comprehensive-art-student-combined-score-530-sd#5`：`112704ms`。
  - `full-journey-school-region-major-group-unit-adjust#1`：24 次工具调用。
  - `comprehensive-cross-batch-police-615-sd#5`：19 次工具调用。
  - `convergence-score-borderline-negotiation-530-ah#3/#5`：各 10 次 `query_score_line`。

现象：

- 对“哪些学校能冲”“会不会断档”“多批次怎么搭配”等问题，模型会连续发起多次同类查询。
- 工具结果能支撑回答，但延迟和请求数显著放大，部分 case 接近 request limit。

初步定性：

- 当前 ToolPlan 缺少批查询、预算上限和同类查询去重。
- 模型将多个学校/专业组逐个查，而不是编译成 batch evidence step。

3.2.0 方向：

- ToolPlan 编译阶段增加 tool budget、batch query 和 repeated tool guard。
- profile 指标必须同时记录 `toolCallCount`、同名工具重复数、tool internal timing、final latency。

### W16 用户引用“当前/刚才方案”时缺少真实方案状态校验

来源：

- 2026-06-20 历史积累场景三轮回归 round1。
- 文件：`dialog_regression_score_tier_cases.json`
- Case：`tier-mid-520-just-want-bachelor`
- Session：`933211007`

现象：

- 用户先说 `我520咋稳上个本科就行`，系统提示需要省份/选科/方向等信息。
- 用户再说 `那帮我直接弄一版稳的方案`，系统仍然追问关键信息，没有生成正式方案。
- 用户第三轮说 `刚那个方案民办能少点不`，系统没有指出“刚才并未生成方案”，而是生成 `排除院校：民办` 的 pending。

初步定性：

- 用户的“刚那个方案”是对上下文对象的引用，但当前状态中并不存在正式方案或候选方案。
- 系统将引用型修改请求直接当作长期意向变更，缺少 `referenced_plan_exists` / `current_plan_available` 这类前置校验。
- 这会让用户误以为系统已经生成过方案，也会把不存在的方案编辑转成未来偏好约束。

3.1.1 边界：

- 不要为“刚那个方案”这类话术增加局部字符串兼容。
- 可接受的小修是：任何基于“当前/刚才/这版方案”的修改请求，在没有方案对象时必须先给状态诚实回复，不创建 plan/intent pending。

3.2.0 方向：

- TurnDecision 增加 `referenceResolution`：`current_plan`、`candidate_preview`、`no_referent`。
- `no_referent` 时只能进入澄清/状态说明，不能进入 mutation 或长期 intent 写入。

### W17 领域计算/政策类回答缺少结构化校验，艺术综合分出现公式和尺度不一致

来源：

- 2026-06-20 历史积累场景三轮回归 round1。
- 文件：`dialog_regression_special_cases.json`
- Case：`special-art-580`
- Session：`933212002`

现象：

- 用户问 `我美术生文化课580联考250综合多少能上啥`。
- 系统回复中写出 `250 × 7.5 × 50% = 937.5`，随后又给出 `综合分 ≈ 580分左右`。
- 同一回复里公式中间值和最终综合分尺度不一致，且未明确省份公式差异导致无法精确计算。

初步定性：

- 这是模型自由生成计算过程导致的领域推理质量问题，不是简单协议/formatter 问题。
- 艺术类综合分、强基/专项政策、批次规则这类高风险信息不能只靠模型口算和泛化解释。

3.1.1 边界：

- 不建议在 3.1.1 引入艺术类完整政策公式引擎。
- 若无法确认省份公式，应避免给出看似精确的中间计算，改为说明需要省份和当年公式。

3.2.0 方向：

- profile 增加 `domain_calculation` 类 golden，记录公式抽取、变量缺失、是否给出无依据精确值。
- 对政策/计算型回答增加 evidence requirement：无可靠公式来源时只能给边界说明和所需信息。

### W18 只读审查/合理性问题被误升级为生成方案 pending

来源：

- 2026-06-20 历史积累场景三轮回归 round1。
- 文件：`dialog_regression_special_cases.json`
- Case：`special-strongbase-655`
- Session：`933212005`

现象：

- 用户说 `现在这版强基+普通批方案合理不`。
- 系统先执行 `query_state`，又执行 `generate_plan` preview 和 `review_plan`。
- 最终回复“已完成方案审查”，但同时挂出 `确认生成方案` pending，要求基于强基意向生成完整方案。

初步定性：

- 用户目标是 review/explain 当前方案合理性，不是生成一版新方案。
- 当前 plan 编排把“没有正式方案/需要补齐方案”作为隐式生成目标，导致只读合理性问题升级为高副作用 pending。
- 这与既有 review repair 问题同根：`review_plan` 是 evidence step，但不能自动推出 `generate_plan` mutation。

3.1.1 边界：

- 不新增“审查后自动生成方案”的桥接。
- 可做窄修：readonly review 场景即使发现没有方案，也应回答“当前无正式方案，无法审查；是否需要生成方案”，而不是直接挂生成 pending。

3.2.0 方向：

- `requiresPlanMutation` 必须是硬门禁。
- `review_current_plan`、`generate_new_plan`、`repair_existing_plan` 三类 scenario 必须互斥，不能在一个自然语言只读问题里自动串联为 mutation。

### W19 pending 状态抢占只读事实查询，导致基础信息状态未回答

来源：

- 2026-06-20 历史积累场景三轮回归 round1。
- 文件：`dialog_regression_special_cases.json`
- Case：`special-correction-630`
- Session：`933212006`

现象：

- 用户先纠正 `湖北`、`620`，然后说 `把华中科技大学加到意向`，系统生成华科 pending。
- 下一轮用户问 `现在方案是按620湖北算的吧`。
- 系统只解释“当前有一项待采纳的想法”，没有回答方案/基础信息是否按 `620 湖北 物化生`。

初步定性：

- pending guard 的优先级过高，把只读事实查询当成 pending 上下文说明处理。
- 用户问的是基础信息状态，不是是否采纳华科意向；二者应可并存。

3.1.1 边界：

- 不建议绕过 pending 直接执行新副作用。
- 但只读事实查询应允许在 pending 存在时读取状态并回答，同时提醒 pending 未采纳。

3.2.0 方向：

- TurnDecision 需要区分 `pending_confirm_or_cancel`、`readonly_query_while_pending`、`new_mutation_while_pending`。
- pending 不是全局拦截器；只应拦截确认/取消和冲突性新 mutation。

### W20 长链路中实体误抽、pending 栈残留和多 pending 并存

来源：

- 2026-06-20 历史积累场景三轮回归 round1。
- 文件：`dialog_regression_special_cases.json`
- Case：`special-long-chain-12-turn`
- Session：`933212007`

现象：

- 用户说 `城市优先长三角`。
- 系统输出 `只保留专业：城市（城市管理）；只保留地域：江苏、浙江、安徽、上海`，把“城市优先”误抽成“城市管理”专业，并把“优先”升级为 `only_keep`。
- 用户后续 `出一版方案` 生成 plan pending，但未确认。
- 再说 `冲档太冒险了删掉一个` 时，系统仍返回“生成一版方案”的 pending，没有承接删除冲档。
- `稳档想换成省内的` 同轮返回旧 `generate_plan` pending 和新 `intent_change` pending，出现多 pending 并存。

初步定性：

- 存在三类问题叠加：
  - NER/slot 抽取把“城市优先”误当专业实体。
  - 偏好强度把 `优先长三角` 解释成 `only_keep`。
  - pending 生命周期缺少单一活跃业务目标和冲突处理，旧 plan pending 残留后继续污染后续 mutation。

3.1.1 边界：

- 不建议为“城市优先”单独加字符串修补。
- 可做最小防护：同轮不能返回两个可点击 pending；新 mutation 与旧 pending 冲突时必须先让用户处理旧 pending 或明确替换。

3.2.0 方向：

- slot extraction 需要实体类型置信度和冲突校验，`城市` 作为普通名词/维度词不能默认映射为专业。
- pending model 需要 `activeProposal` 单一源，支持 `replace_pending` / `cancel_then_new` / `readonly_while_pending` 的显式决策。

### W21 同一句里正向“加意向”和负向“排除/去掉”发生极性串扰

来源：

- 2026-06-20 历史积累场景三轮回归 round2。
- 文件：`dialog_regression_comprehensive_cases.json`
- 代表 case：
  - `comprehensive-parent-doctor-conflict-620-gd`
  - `comprehensive-finance-to-cs-switch-605-js`

现象：

- 用户说 `把生物医学工程和智能医学工程加意向 排除临床医学和口腔`。
  - 期望：生物医学工程、智能医学工程为正向偏好；临床医学、口腔医学为负向排除。
  - 实际：四个专业全部进入 `negative_level3`，卡片 summary 为“排除专业：临床医学、口腔医学、生物医学工程、智能医学工程”。
- 用户说 `把金融去掉 加计算机类和人工智能 地域不限`。
  - 期望：金融为负向，计算机类/人工智能为正向偏好，地域约束放宽。
  - 实际：计算机类、人工智能被落成排除项。

初步定性：

- 这是结构化 intent extraction/compile 的 polarity scope 错误，不是单个词表问题。
- 同一个 turn 里出现多个动词短语时，后处理把负向极性扩散到了后续正向短语，或缺少按 clause 分段绑定极性。
- 风险很高：用户明确要“加入”的专业被排除，会直接反向影响候选、方案生成和后续审查。

3.1.1 边界：

- 不建议加“加 A 排除 B”字符串模板桥接。
- 若要在 3.1.1 小修，只能做低风险校验：同一 payload 中，如果原文存在明确 `加/加入/加到意向/作为备选` 与某实体近邻绑定，该实体不得被编译成 negative，冲突时应阻断并澄清。

3.2.0 方向：

- intent parser 必须输出 clause-level operations：`add_preference(A)`、`remove_or_exclude(B)`、`relax_constraint(C)`。
- compiler 只按 clause scope 绑定 polarity，禁止全句级负向传播。
- profile 增加 mixed positive/negative intent polarity golden。

### W22 plan 查询明细 projection 不足，读取到方案后仍无法回答“最后几个/录取率”

来源：

- 2026-06-20 历史积累场景三轮回归 round2。
- 文件：`dialog_regression_comprehensive_cases.json`
- Case：`comprehensive-existing-plan-deep-query-26`

现象：

- 用户问 `保底最后几个是什么学校 录取率多少`。
- 系统执行了 `query_volunteer_plan` 和 `query_state`，但最终只回答“保底 30 个没有单独列出明细”，并反问用户是想看末尾还是查具体学校。
- 当前方案实际存在，且用户的问题已经给出明确 projection：`tier=保底`、`position=最后几个`、字段为学校和录取率。

初步定性：

- 这是只读 plan query 的 projection/sort/slice 能力不足。
- 问题不在 pending，也不是 fixture 缺失；系统读取方案后没有把用户的局部范围映射成结构化查询输出。

3.1.1 边界：

- 不建议针对“保底最后几个”单独加文本分支。
- 可接受的小修是 query formatter 支持已有 plan data 的基础 slice：按 tier、排序位置、学校/专业/录取率字段输出。

3.2.0 方向：

- PlanQuery DSL 增加 `scope=tier_segment`、`slice=tail(N)`、`fields=[school, major, admissionProbability]`。
- profile 增加 readonly plan projection golden，避免模型读取到 evidence 后仍退回澄清。

### W23 pending apply 吞掉同轮后续只读查询，apply 后没有继续回答“剩多少/梯度”

来源：

- 2026-06-20 历史积累场景三轮回归 round2。
- 文件：`dialog_regression_comprehensive_cases.json`
- Case：`comprehensive-existing-plan-mutation-chain-35`

现象：

- 用户先要求 `帮我把那些超过两万学费的非意向志愿删掉`，系统生成 plan mutation pending。
- 下一轮用户说 `删完了再帮我看看还剩多少个 梯度有没有问题`。
- 系统只执行 pending apply 并刷新 ordered/candidate/review，没有继续回答“还剩多少个”和“梯度有没有问题”。

初步定性：

- 这是 W10 的同类扩展：`apply_existing_pending + readonly_query_after_apply` 复合 turn 未被拆解。
- 当前 pending apply 是终止态，一旦命中确认/执行语义，同轮后续意图被丢弃。

3.1.1 边界：

- 不新增桥接式“执行后自动分析所有尾句”的自由恢复。
- 可以记录为 3.2.0 TurnDecision 必测；若 3.1.1 要小修，应限制在结构化识别到明确 `再/然后/看下/还有没有` 的只读查询，且 apply 成功后只做只读查询，不产生新 mutation。

3.2.0 方向：

- TurnDecision 支持 `apply_pending_then_readonly_query`。
- apply result 应作为新 evidence 输入后续 query/review，而不是直接结束本轮。

### W24 runner/WS finalMessage 与 agent 内部耗时偏离，性能指标需要拆层

来源：

- 2026-06-20 历史积累场景三轮回归 round2。
- 文件：`dialog_regression_comprehensive_cases.json`
- 代表样本：
  - `comprehensive-major-group-beijing-465-bj#2/#3`
  - `comprehensive-full-plan-review-adjust-26#4`

现象：

- 多个样本 `elapsedMs/finalMessageMs` 达到 75s-122s，但 `turnObservability.agentRun.totalDurationMs` 只有 20s-30s 左右。
- 同时也存在真实模型/工具长尾，例如 `query_score_line` 46 次触发 request limit、`query_admission_score` 20 次。

初步定性：

- 当前性能问题有两层：
  - 模型/工具规划层真实长尾：重复工具查询、request limit、最终生成过长。
  - 测试 runner / websocket 流式收尾层长尾：finalMessage 统计明显大于 agent 内部总耗时。
- 如果只看 dialogue runner 的 elapsed，会混淆用户可感知流式等待、agent 编排耗时和测试框架等待策略。

3.2.0 方向：

- profile 指标必须拆成 `firstMessageMs`、`agentRun.totalDurationMs`、`toolInternalDuration`、`finalMessageMs`、`runnerOverheadMs`。
- 性能 gate 应同时看用户首响、业务完成耗时、最终收尾耗时，避免把 provider/model 问题和 runner 统计问题混为一谈。

### W25 历史三轮回归最终定性：问题不是单一框架失效，而是协议裁决、fixture 契约和模型能力边界叠加

来源：

- 2026-06-20 历史积累场景三轮回归。
- runner：
  - `/private/tmp/zhiyuan_311_three_round_runner.py --phase historical --rounds 3 --run-id v2hist --session-base 933100000`
- 聚合输出：
  - `/private/tmp/zhiyuan_311_3round_v2hist_stage_aggregate.json`

结果：

- 总计 `2283` step，`2209` pass，`74` fail，整体 pass rate `96.76%`。
- 三轮全过集合：
  - `mainline`：369/369。
  - `lifecycle`：108/108。
  - `robust`：138/138。
  - `science`：366/366。
  - `score_tier`：108/108。
  - `special`：204/204。
  - `plan`：18/18。
- 主要失败集合：
  - `full_journey`：160/207，47 fail。
  - `enriched`：181/201，20 fail。
  - `plan_correctness`：87/90，3 fail，均为同一旧措辞断言。
  - `comprehensive`：303/306，失败集中在 round1，round2/round3 断言全过。

定性：

- 不能继续用“整个框架不可用”这种过粗结论。大量稳定集合三轮全过，说明主线对话、只读探索、生命周期、特殊政策基础问答和部分 mutation protocol 可以工作。
- 也不能只看 pass rate 判断已经收敛。断言全过的集合仍暴露偏好强度、pending 抢焦点、特殊批次结构弱和性能长尾；现有断言覆盖不到这些产品关键问题。
- 问题根因是三类叠加：
  - 回归资产层：部分历史 case 依赖隐含 session state，clone/clear 后当前方案、候选或基础信息为空，旧断言仍期待执行结果。
  - 协议编排层：同一轮 sideEffect 没有单一裁决，pending、intent preview、plan preview、directToolReturn 和后处理恢复会互相覆盖。
  - 模型/生成能力层：偏好强度、正负极性、批次类型、review focus、plan query projection 和复合 turn 拆解不稳定。

3.1.1 边界：

- 不用业务代码去兼容 fixture 契约错误，例如空方案下移动/删除/替换仍强行返回 ordered refresh。
- 不新增 runtime shadow、文本确认桥接或新旧并行确认路径。
- 仅处理明确窄修：
  - 已有可执行 plan preview 必须落 pending。
  - career/intent 卡片有结构化 items 时不能被通用 title 覆盖。
  - negative-only 地域/约束能够独立生成 intent pending。
  - 明显反向极性 payload 至少要阻断或澄清，不能把“加意向”的实体写成排除。

3.2.0 方向：

- 建立 `TurnDecision -> ToolPlan -> Proposal/Pending` 唯一主路径。
- 每轮只有一个 active sideEffect；多个候选必须由 compiler 决策或澄清。
- Intent schema 支持 `primary / acceptable / avoid_soft / exclude_hard`，并按 clause 绑定 polarity。
- PlanQuery 成为一等 DSL，支持 tier/slice/field projection。
- pending 状态支持 `readonly_while_pending`、`apply_pending_then_readonly_query` 和 `new_request_conflicts_with_pending`。
- 特殊批次/政策路径需要 batch/type/path 结构，不能只压成学校/专业偏好。
- 性能 profile 拆 agent、tool、provider、WS runner 四段，不再只用单个 elapsed 判断。

### W26 soft preference 被硬化为 must_have/only_keep

来源：

- 2026-06-20 历史三轮回归中的 `robust/science/special/full_journey` 多个集合。

现象：

- 用户说 `加进意向`、`作为参考`、`优先`、`可以重点关注`，系统经常生成：
  - `至少保留院校/专业`
  - `must_have`
  - `only_keep`
- 代表样本：
  - `special-art-580`：`江南大学和苏州大学加进意向` 落成 `至少保留院校`。
  - `special-batch-cross-485`：`山西大学的本科和山西职业技术加进意向` 落成学校 must_have，且丢失本专批次差异。
  - `science-energy-power`：`新能源动力方向作为参考` 落成 `must_have/至少保留`。
  - `robust-typo-and-abbrev-580`：上一轮学校偏好和本轮 `保底要公办不要民辨` 合并升级成 `只保留院校 + 排除民办`。

初步定性：

- 这是 intent schema 与 compiler 表达能力不足，不只是模型偶发理解错误。
- 当前结构更容易表达 `positive/negative/only_keep/must_have`，不擅长表达“优先参考、可接受备选、软偏好、硬排除”的强弱层级。
- 强度被硬化会直接影响候选排序和方案生成，风险高于普通回复措辞问题。

3.1.1 边界：

- 不用字符串枚举修每个“加进意向/优先/作为参考”。
- 若结构化 payload 已明显把软表达编译成硬约束，应优先在卡片文案和 apply 前阻断高风险过强约束，而不是默默写入。

3.2.0 方向：

- Intent schema 支持 preference strength。
- compiler 区分：
  - `primary_preference`
  - `acceptable_fallback`
  - `soft_avoid`
  - `hard_exclude`
  - `must_have`
  - `only_keep`
- 候选排序和卡片摘要必须保留强弱差异。

### W27 特殊批次/路径被压扁为普通学校或专业意向

来源：

- `dialog_regression_special_cases.json` 三轮全过，但人工 review 暴露特殊批次结构不足。

现象：

- 强基、提前批、艺术生、本专兼报、专项计划等场景常被压成普通学校/专业意向。
- 代表样本：
  - `special-strongbase-655`：`清华北大复旦的强基都加进意向` 最终只保留 `数学类/物理学类`，学校和强基路径丢失。
  - `special-batch-cross-485`：本科和专科意向混在普通院校偏好里，缺少 batch distinction。
  - `special-art-580`：艺术综合分公式/尺度表达有不一致，院校偏好又被硬化。

初步定性：

- 当前意向结构以学校/专业/地域为中心，缺少 `batchType / admissionPath / planType / qualification`。
- 模型即使识别到“强基/专科/艺术/专项”，后续 schema 和 formatter 也容易丢信息。

3.1.1 边界：

- 不在 3.1.1 为每个特殊路径增加并行 route。
- 对明显无法表达的特殊批次意向，应优先澄清或只读说明，不要生成失真的普通 must_have 卡。

3.2.0 方向：

- Profile 增加特殊批次 golden。
- Intent/PlanGoal schema 增加批次、路径、资格和适用范围字段。
- proposal/apply 必须知道这些字段是否只影响后续推荐，还是影响当前方案生成/筛选。

### W28 当前方案只读 projection 能力不足

来源：

- 2026-06-20 历史三轮回归 `comprehensive/enriched/special/score_tier`。

现象：

- 已经读取当前方案后，仍不能稳定回答局部明细查询。
- 代表样本：
  - `保底最后几个是什么学校 录取率多少`：已读取方案，但没有列出保底尾部学校和录取率。
  - `方案里的学校分布在哪些城市`：读取方案后回答“没有命中城市分布地域分布”。
  - `高收费的志愿占比多少`：有时转成通用审查或调整建议，没有输出占比/命中项。
  - `现在方案是按620湖北算的吧`：pending 存在时没有回答基础信息状态。

初步定性：

- 当前 Plan 只读查询缺少 projection/slice/focus 结构。
- `query_volunteer_plan` 或 `query_state` 只是 evidence，最终回复仍依赖模型泛化，没有稳定把用户 query 编译成字段、排序和切片。

3.1.1 边界：

- 不为每类问法加字符串分支。
- 可以对现有方案数据增加基础 formatter 能力，但不扩大副作用路径。

3.2.0 方向：

- PlanQuery DSL 支持：
  - `scope=tier_segment/full_plan/current_major_group`
  - `slice=head/tail/top_by(field)`
  - `fields=[school, major, admissionProbability, tuition, city, tier]`
  - `focus=tuition/cooperative/safety/city_distribution`
- 只读 query 与 mutation preview 严格互斥。

### W29 三轮回归后的 3.1.1 剩余 P0/P1 划分

已完成 3.1.1 小修并通过小范围回归：

- P0-3：已有可执行 plan preview 未落 pending card。已通过 `/private/tmp/zhiyuan_311_small_regression_p03_constraint_plan_action.json`，9/9。
- P0-4：career intent 卡片和确认回显被通用 title 覆盖。已通过 `/private/tmp/zhiyuan_311_small_regression_p04_career.json`，4/4。
- P0-5：negative-only 地域排除未落 pending card。已通过 `/private/tmp/zhiyuan_311_small_regression_p05_negative_region.json`，2/2。
- 防串扰：`/private/tmp/zhiyuan_311_small_regression_review_repair.json`，9/9；但仍有 2 条 30s+ latency warning。
- 封版单元验证：`zhiyuan-agent` 定向单测 `662 passed`，`zhiyuan-server` `UserGoalProposalBuilderTest` 通过。

3.1.1 当前不建议继续扩修：

- mixed positive/negative polarity 反向编译仍需进入 3.2.0 profile；若 3.1.1 后续发现高频严重误写，再优先做阻断/澄清，不做文本桥接。
- 已补负向专业护栏：模型误把 `不要英语相关专业...` 这类负向专业排除标成 `only_keep/must_have`，且没有明确正向范围时，intent tool 继续阻断，不生成普通排除 pending；P0-5 的纯负向地域排除仍允许生成 `排除地域` pending。

暂不建议 3.1.1 修：

- full journey fixture 隐含状态问题。
- 历史 keyword 断言过窄问题。
- review focus 全量重构。
- PlanQuery DSL 全量实现。
- 特殊批次 schema 重构。
- pending 复合 turn 全量拆解。
- provider 横评模型选择。

这些应进入 3.2.0 profile 和主路径设计，不在 3.1.1 通过兼容桥接解决。

### W30 current gate 三轮回归最终定性

来源：

- 2026-06-20 current gate 三轮回归。
- runner：
  - `/private/tmp/zhiyuan_311_three_round_runner.py --phase current --rounds 3 --run-id v2current --session-base 934100000`
- 聚合输出：
  - `/private/tmp/zhiyuan_311_3round_v2current_stage_aggregate.json`

结果：

- 总计 `681` step，`664` pass，`17` fail，整体 pass rate `97.50%`。
- 三轮全过集合：
  - `301_agent_smoke`：18/18。
  - `302_agent`：24/24。
  - `302_readonly_real_session`：6/6。
  - `303_career_direction`：12/12。
  - `303_effect_perf`：42/42。
  - `303_open_quality`：69/69。
  - `310_production_abstracted`：66/66。
  - `310_review_repair`：27/27。
- 主要失败集合：
  - `310_constraint_plan_action`：23/27，稳定暴露 P0-3。
  - `302_explore_intent`：61/66，暴露 P0-4 和软硬 pending 边界。
  - `303_realistic_user`：23/27，主要是旧断言白名单/思考文案噪声。
  - `303_dialogue_derived`：261/264，主要是性能硬阈值和只读边界文案。

稳定业务缺陷：

- P0-3 三轮稳定复现：
  - `310-constraint-exclude-major-preview-and-apply`
  - prompt：`不要英语相关专业，当前方案里有的话也删掉`
  - 三轮均已有 `remove_units preview_only` 工具事实，但未生成 `pendingConfirmationCard`。
  - 这是 current gate 最明确的 3.1.1 阻塞项。

低风险小修候选：

- P0-4 在 current gate r2/r3 复现：
  - `先把体制内稳定就业作为参考方向`
  - 结构化 items 应包含 `体制内/稳定就业`，但用户可见回复或 card 未稳定回显。
  - 属于 formatter/protocol 展示问题，适合 3.1.1 小修。

波动或结构性问题：

- `太贵的学校别放了，学费最好控制在两万以内` 在 r2 未生成 pending，只做 review/refocus；r1/r3 通过。
  - 说明费用类明确调整诉求在 `review_plan` 与 `preview_fix_proposal` 之间不稳定。
  - 若 3.1.1 要让 current gate 全绿，需要窄修现有预览落点；更完整方案仍属 3.2.0。
- `先不确认，看看这个偏好会影响方案吗` r1 失败、r2/r3 通过。
  - 属于 pending 上下文只读 query 波动。
  - 不建议新增文本桥接；进入 3.2.0 `readonly_while_pending`。
- `302-soft-hard-intent-mix-with-plan-impact` 三轮失败/波动与 case 预期有关。
  - case 期待第二轮 `确认` 无 pending，但第一轮实际生成了 intent pending。
  - 应先重新定义“财经类可以优先，但是护理和中西医结合不要”是否应出 pending，以及软偏好/硬排除如何表达。

测试断言噪声：

- `303-real-user-vague-confirm-guard` 三轮失败，但实际是 no-pending guard 回复未命中旧白名单。
- `303-real-user-sort-good-school-preview` r3 失败是 thinking 文案断言。
- 这些不应驱动业务兼容逻辑，应调整 case 断言口径。

性能问题：

- `303-dialogue-budget-less-sino-foreign` r3：`169466ms`。
- `303-dialogue-plan-too-risky` r3：`172051ms`。
- `310_review_repair` 三轮全过但 median 约 `25s-27s`。
- 这些说明 current gate 的功能正确性和性能稳定性要分开看；性能 profile 应进入 3.2.0 前置评估。

3.1.1 收口判断：

- P0-3/P0-4/P0-5 已完成窄修并通过小范围回归；后续只接受明确回退修复。
- review/repair 防串扰小回归 9/9，但仍有 `310-review-shortage-honesty` `42928ms`、`310-review-fix-explain-hierarchy` `31328ms` 两条耗时告警，应进入 3.2.0 profile。
- 封版补充验证通过：Agent 定向单测 662/662，Server proposal 单测通过。
- 不为 `303_realistic_user` 的 thinking/白名单断言加业务兼容。
- 学费 preview 波动、pending+readonly 复合 turn、软硬偏好强度和 PlanQuery projection 均按结构问题进入 3.2.0。

## 4. 下一步建议

1. 3.1.1 停止新增兼容桥接：P0-3/P0-4/P0-5 已用窄协议/formatter/intent normalization 修复，并通过小范围回归；后续只接受明显回退修复。
2. 进入 3.2.0 前置模型能力 profile：重点量化 side-effect 判定、软硬偏好强度、正负极性绑定、pending+readonly 复合 turn、review evidence -> proposal 和 PlanQuery projection。
3. 对 full journey 先修 fixture/断言契约，再决定哪些 case 晋级稳定门禁；当前不要用空方案下的 ordered refresh 失败倒逼业务逻辑。
4. 保留 88 条真实对话衍生 case 和 current gate 作为下一轮完整回归，但区分业务缺陷、旧断言噪声和性能硬阈值。
5. review/repair、费用类 preview 和长尾耗时不要在 3.1.1 继续靠 shadow/bridge 收敛，应作为 3.2.0 主路径设计输入。
