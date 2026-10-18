# J1 旅程块设计复审

日期：2026-10-18。性质：设计与源码静态核对；不是实施批准或部署验收。

## 1. 范围与结论

- 设计：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md`，最终读取快照 577 行，
  SHA-256：`2a7d4520c34b4f12c2d33861e989e0de13f7fae36721f4bfb57e9cf436cbb828`。
- 审查过程中原稿持续更新；以下以该读取快照为准，已修正项不再作为当前阻断。
- 随后增量核对到 SHA-256 前缀 `f8bb02109f64`：新增 blocked 任务清账、按最终
  operations 判定 planned、细化 constrain/remove 测试；这些不改变下面五个未闭合项。
- 代码基线：`616464c` 加当前工作区已有未提交实现。本文不把之前审查的旧缺陷
  自动视为当前缺陷；确认冲突、非原子变更集等守卫已有后续修改。
- 本次只新增本审查记录，未修改设计稿或业务代码，未运行应用测试、重启、提交或部署。
- **结论：方向成立，建议修订后再实施。** 下列问题主要是尚未实施的 J1 设计缺口，
  不代表已在运行环境复现。另有已由源码确认的现有入口保护差异。

应保留：Java 生产事实、Agent 派生对话位置；不持久化第二套业务阶段；不重造确认引擎；
动作目录只作提示、业务可执行性由 Java 判断；planned 动作不承诺执行；兼容旧快照。

## 2. 已修正项与主要发现

### J1-R1 · 已在新设计中修正：fill 与 add 的前置条件

新稿 `docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:225`
已改为有候选即可提供 fill，并从 no_plan/tier_quota 阻断中移除 fill。
无方案时推荐首版 fill，不再与动作目录冲突。

源码依据：
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/UserGoalProposalBuilder.java:816`
  的 fill 路径没有 add 的“必须已有方案”前置条件，并接受 `tierQuotaGoal`。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningObjectiveCompiler.java:56`
  会编译请求或已确认的配额。
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/UserGoalProposalBuilderTest.java:1476`
  已有通过 fill 调整冲稳保配额的用例。

该修订与当前 Java 能力一致；这里只确认设计修正，不声称 J1 实现或回归已完成。

### J1-R2 · P1：快照检查不足以保证 applying 期间不能创建新 pending

设计位置：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:392`、
`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:405`。

J1c 只在模型输出后检查回合快照。另一请求可以在取快照后才把 pending claim 成
applying；跨进程时不能依赖 Agent 进程内会话锁阻止此类交错。

当前普通方案和成绩 prepare 已有 applying 前置检查，并非所有入口都没有保护。
但发展方向路径存在一个具体例外：

1. 回合开始时快照尚非 applying。
2. 另一请求 claim 当前 pending。
3. `_prepare_career_update` 调 `save_pending_confirmation`，后者重新读取最新 revision。
4. Java 通用 upsert 只检查 revision/CAS，没有拒绝当前状态为 applying。
   因为本次拿到的就是最新 revision，CAS 本身不能阻止把 applying 行替换为新 active。

源码依据：
- `zhiyuan-agent/app/gateway/service.py:1566`：发展方向直接保存 pending。
- `zhiyuan-agent/app/util/internal_client.py:1467`：保存时可重新获取最新 revision。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingConfirmationBizService.java:54`：
  upsert 校验 revision 后构建新 active，缺少 applying 状态拒绝。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationProposalRequestService.java:88`：
  普通 prepare 已有独立 applying 检查。

建议：明确 Java pending 写入口是该硬不变量的最终 owner；禁止普通 upsert 覆盖
applying，并保留 CAS 抵御读取之后的状态变化。Agent 检查只作为提早反馈。
增加“取快照后发生 claim，再提交发展方向”的交错测试，不能只测静态 applying 快照。

### J1-R3 · P1：applying 只有等待口径，没有结果未知时的恢复出口

设计位置：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:108`、
`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:267`、
`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:403`。

`pendingStatus` 只输出 applying，动作表阻止新写和确认/取消，推荐永远是 wait。
这能覆盖正常执行窗口，但未说明以下状态由谁结束：

- claim 成功后 Agent 重启，执行请求尚未送出；
- 执行成功，但 complete 回写失败；
- 请求超时，实际提交结果未知；
- claim 租约已过期，但数据库状态仍是 applying。

源码依据：
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingConfirmationBizService.java:101`
  在 confirm 路径处理 applying 的租约重认领；租约到期本身不会自动把状态改成 expired。
- `zhiyuan-agent/app/gateway/conversation_actions.py:1025`
  对结果回写失败只记日志；执行结果不会因此改判。

建议：保留“不向用户提供取消”的安全边界，同时指定服务端恢复 owner 及现有
operation 台账的查询/对账入口。可由受信恢复流程读取 pendingId、operationId、
revision、租约信息；这些不必全量注入模型。先查台账再决定补回执、继续等待或
进入受控恢复，不因超时擅自视为未执行，也不自动创建第二个 operation。
如果恢复属于另一切片，必须写明依赖及可用前提，而不是把无限等待当成完整闭环。

### J1-R4 · P2：hasPlan 的兜底语义大于解读接口实际支持的方案形状

设计位置：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:97`、
`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:224`。

J1 把 working/ordered 的 items/units 任一非空都视为有方案，随后只要 hasPlan
就提供解读。可是当前解读只读取 ordered，而且按 admissionMode 严格取对应形状：
仅有 working 条目，或 major_group 下只有 ordered items 时，J1 会报“方案存在、
可以解读”，解读却返回 no_plan。

新稿已给 working digest 增加前缀并要求 ordered parity 测试，解决了指纹域的歧义；
但这不等于解读接口已经支持 working 或异形 ordered。

源码依据：
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanAdmissionInterpretationFacade.java:65`：
  条目只来自 ordered；major_group 用 units，major 用 items。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanAdmissionInterpretationService.java:70`：
  输入为空返回 no_plan。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/EvaluationContextBuilder.java:55`：
  digest 当前固定取 ordered。

建议：保留 hasPlan 表达“有历史/草稿内容”，但增加明确的可解读事实或正式方案形状
判据。或者让解读、评价、journey 复用同一个方案选择器；不能只在 J1 单方面兜底。
digest 应注明作用对象，并通过共享 helper 或对照测试保证同一对象的算法一致。

### J1-R5 · P1：推荐逻辑没有消费候选、方案的新鲜度

设计位置：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:106`、
`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:261`。

Java 提供 stale 是合理的，但后续 available/blocked/recommended 表实际只读取
“是否存在”和 reviewStale，不处理候选或方案本身是否需要刷新。
典型反例是补录成绩后：画像齐、旧候选和旧方案均保留，因此系统可能仍推荐加入，
或直接推荐审查/解读旧方案，没有表达应先核对新成绩下的候选与方案。

另一方面，stale 是六个 flag 的并集，不能简单改成“只要 stale 就全部阻断”：
只有审查过期、推荐视图过期时，不等于候选或方案都不能用。

建议：由 Java 给出有界的组件新鲜度或 `refreshRequirement` 枚举，Agent 仅消费结果；
将其放入推荐优先级，并解释“查看旧方案”与“基于当前条件执行新变化”的区别。
无需计算 stalePlanItemCount，也不要靠 Agent 解析 reason/message 重新实现业务规则。

### J1-R6 · P2：人工审查动作与后端审查 freshness 尚未形成同一生命周期

设计位置：`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:206`、
`docs/superpowers/specs/2026-10-18-j1-journey-block-design.md:272`。

- review_plan 被定义为只读的人工审查；它不会更新 Java reviewState/sourceVersion
  或清除 reviewStale。因此完成一次人工审查后，下一轮依旧推荐同一个动作。
- 初稿“加入成功后必有 reviewStale=true”已经在新稿 :275、:489 修正，
  不再判为当前缺陷。当前剩余问题是人工审查与后端规则审查不能互相代替。

源码依据：
- `zhiyuan-agent/skills/codex-marketplace/plugins/zhiyuan-codex-planner/skills/plan-final-review/SKILL.md:28`：
  人工审查只允许只读工具。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java:953`：
  加入冻结命令带 rerunReview=true。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizService.java:453`：
  执行后调用 runReview。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java:2914`：
  规则审查清除 review stale。

建议：区分“后端规则审查是否新鲜”和“用户是否刚读过本版的人工审查说明”。
不要让模型清除业务 stale，也不要为满足 J1 测试人为把已新鲜的审查标旧。
验收应按真实执行回执判定：已 rerunReview 则检查审查来源和结果；未重跑才检查
审查待更新。推荐逻辑不能假定两种审查动作互相代替。

## 3. 非阻塞的一致性补充

1. **已修正：可用与阻断互斥。** 新稿 :229 先算候选动作，再扣除 blocked；
   applying 的写动作不再同时出现在可用列表。建议再约束 `recommended_next`
   必须是有效建议动作或 wait/clarify 等明确元动作。
2. **默认推荐不能覆盖未完成任务。** :261 的表没有与已有 `workingSet.taskDraft`
   定义优先级。应明确安全状态优先，其次当前明确请求和剩余任务，最后才是默认
   review/interpret 建议；否则用户说“继续”时会收到两套相反引导。
3. **优先级能力说明需对齐。** 动作表与开放问题仍写“优先级未接”，但已有
   `prioritize_within_tier` 与 `priorityRules`。应区分已支持的同档优先排序和未支持的
   风险姿态/通用优化策略；技能切片的“仅本次”也应按具体字段真实生命周期表述。
   新稿 D13 已明确把 prioritize 与 planned reorder 分开，说明文字也应同步收口。
4. pending 查询不用改变 getCurrent，但 activeProposal 与 pendingStatus 最好来自
   同一次只读记录，避免同一快照一边展示 active 卡、一边声称 applying。
5. **增量版本已修正：** §6.2b 的 constrain/remove 用例已注明 targets 和主操作，
   planned 判定改按最终 operations，blocked 也明确清理进程内及 Redis 任务页。
   不再把初稿的测试歧义列为当前缺陷。

此外，新稿已修正真实工具事件的提取来源、applying 校验顺序与不 repair 口径，
并补充 planned 动作、归一化别名、业务计数 helper 的契约要求；不重复报作未修项。

## 4. 建议补入的验收场景

- 有画像、有候选、无方案：可推荐首版 fill，且不能同时标为 no_plan 阻断。
- 已确认配额：add 提示受限，但 fill 配额调整继续交 Java 判断，不一刀切禁止。
- working-only、unit-only、mode 与存储形状不一致：journey 与解读结果口径一致。
- 取快照之后发生 claim：发展方向等新 pending 不能覆盖 applying 行。
- claim 后进程退出、执行后回写失败、租约过期：能找到受信恢复入口，且不重复执行。
- 补录成绩保留旧候选/旧方案：推荐明确的新鲜度处置，不直接当成当前条件下的新方案。
- 加入已自动重审与未重审两种回执：不硬编码 reviewStale 必须为 true。
- 人工审查后用户说“继续”：不会仅因 Java reviewStale 未变而无限重复人工审查。
- applying 时可用/阻断不矛盾；剩余复合任务优先于无任务时的默认推荐。

目录契约单测仍只证明目录自洽，不能替代上述跨状态与异常路径验收。
