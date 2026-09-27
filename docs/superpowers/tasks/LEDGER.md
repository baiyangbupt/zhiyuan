# 任务台账

> 状态唯一来源。协议见 `README.md`。
> 状态流：`DISPATCHED` → `REPORTED` → `ACCEPTED` / `ACCEPTED_WITH_FOLLOWUP` / `REJECTED` / `SUPERSEDED`

| ID | 标题 | 来源 | 执行会话 | 派发 | 实现方状态 | 评审判定 | 产出后续 |
|---|---|---|---|---|---|---|---|
| [T001](T001-sse-capture/) | 采集 DeepSeek `/responses` 流式断开现场 | 修订计划 P0 | deepseek | 2026-09-10 | `BLOCKED` | `ACCEPTED` | T003 |
| [T002](T002-drop-resolver/) | 清理悬空 resolver 模块并修正过时文档 | 修订计划 P4 | deepseek | 2026-09-10 | 未按格式提交 | `ACCEPTED_WITH_FOLLOWUP` | T004 |
| [T003](T003-schema-compat/) | 使 `TURN_OUTPUT_SCHEMA` 通过 DeepSeek 校验并跑通复杂回合 | T001 结论 | deepseek | 2026-09-10 | `DONE` | `ACCEPTED` | T005 |
| [T005](T005-mcp-execution/) | 让只读 MCP 工具真正执行，并修好语义冒烟的观测仪表 | T003 REVIEW 勘误 | deepseek | 2026-09-10 | `DONE` | `ACCEPTED_WITH_FOLLOWUP` | T008 |
| [T006](T006-registry-unblock/) | 把本地基础设施 compose 指向可达镜像源，解除 P2 前置 | 修订计划 P2 | deepseek | 2026-09-10（口头） | `DONE` | `ACCEPTED` | — |
| [T007](T007-agent-doc-accuracy/) | 修正 `zhiyuan-agent/CLAUDE.md` 的 Tools 一节 | T003 REVIEW 勘误 2 | deepseek | 2026-09-10（口头） | `DONE` | `ACCEPTED` | P5 文档收尾 |
| [P1a](P1a-evidence-ledger/) | Java 证据台账：建表、摘要、签发、四态核验 | 修订计划 P1 切片 | deepseek | 2026-09-10 | `DONE_WITH_CONCERNS` | `ACCEPTED_WITH_FOLLOWUP` | P1b-1 / P1b-2 / P1b-3 |
| [P1b-1](P1b-1-content-digest/) | 数据版本改为 `data` 内容摘要，版本表键改 `(source_system, params_digest)` | P1a REVIEW 跟进 1/3 + 上游实测 | zhiyuan-48 | 2026-09-13 | `DONE_WITH_CONCERNS` | `ACCEPTED_WITH_FOLLOWUP` | 两条遗留并入 P1c-2；1 条挂起 |
| [P1b-2](P1b-2-evidence-passthrough/) | 打通证据到 Agent 的三处断链，最后删自铸分支 | P1a REVIEW 跟进 2（归因勘误后） | zhiyuan-48（复核与护栏由本地会话 2026-09-22 补） | 2026-09-13 | `DONE_WITH_CONCERNS`：**裁决 (a) 已查清**（该路从未产出录取率：生产者 DTO 11 字段无率、全仓无 setter、Python 明说是上游算好的）；复核发现步骤 2/3/5 早已落地、步骤 4 的测试在但**护栏缺失**——已补 `response.ok()` 的 `authoritative ⇒ ev_` 检查（含对照，红-绿）；真栈一句话验收通过（verify 入参是 `ev_…`） | — | 验收 5 的 scope 对照未复跑（见 `P1b-2/REPORT.md` 附二） |
| [P1b-3](P1b-3-snapshot-evidence/) | `fillEvidence()` 落地 + snapshot 优先于进程内存 | 设计文档 4.5 / 5.2 | zhiyuan-48（Java 半已随 `23db5da` 落地；Python 半由本地会话 2026-09-21 补） | 2026-09-13 | `PARTIAL`：Python 半完成并带红-绿对照；Java 半的两条验收**起初都不满足**——"只放 valid"（只过滤了过期）与"查库异常降级"（异常直接穿到快照）——2026-09-22 均已在真实栈上红-绿验证（含端到端复验）。`expires_at IS NULL` 的口径差已按裁决统一到 fail-closed（核验侧改判 `expired`，红-绿验证；列是 NOT NULL，实盘不可达、属堵缝）。仍未验：`unknown` 路径（这条路上结构不可达，见 `P1b-3/REPORT.md` 4.6） | — | P1c-1（其前提"模型引用必 `evidence_not_found`"已被工作区的 `merge_evidence` 推翻，派发前需复核） |
| [P1c-1](P1c-1-validator-unblock/) | 拆掉三处恒真的证据检查，让权威证据能进校验器账本 | 断链 4/5/6 | 未派发（前置已解除） | **工作区已实现**（随 A 线未提交改动：`service.py` 的账本已 `merge_evidence(snapshot, turn)`；`output_validation.py` 里证据侧的 `stateVersion`/`threadId` 等值检查已删、artifact 侧保留）。2026-09-22 本会话补了任务书**验收原话**那条用例（第 3 回合的证据、中间工作区写过、第 7 回合引用必须通过），红-绿验证（注回旧检查即失败）；另有实测：80 条引用证据的回合全部成功 | — | **2026-09-25 报告已补**（`P1c-1/REPORT.md`）：三处改动逐条对现状 ✓、六条验收逐条有测试 ✓（验收 4 的另一半与验收 5 的专测**本次现补** ✓）、**红-绿当场重做**（注入旧检查 → `stale_state: ev-1` 红 ✓ / 还原 → 绿 ✓）。如实记两点：① 账本合并的实现与任务书建议不同、且更严——同 ID 的**稳定身份必须一致**、否则报 `evidence_identity_conflict` ✗（`observedAt` 刻意排除在身份外 ✓）；② 中间态（`stateVersion`/`threadId` 两维暂时不设防）**已随 P1c-2 关闭** ✓ |
| [P1c-2](P1c-2-verify-in-gateway/) | 四态核验接入 Gateway + 第六章分流表 + 重查一次 | 设计文档 5.3 / 第六章 + P1b-1 REVIEW 遗留 2 | 本地会话（2026-09-22；任务书由执行方按设计文档翻译） | 2026-09-22 | `DONE_WITH_CONCERNS`：Java（版本缺失→`unknown`）+ Python（核验客户端 / 分流表纯函数 / 接入 `_codex_turn`）两半落地，新增 16 条单测；真栈**断依赖**验收：只把 `/internal/evidence/verify` 打成 500 → 整轮硬失败且**无事实性回答**，恢复后同题正常，backend 访问日志证明确实调了核验端点 | — | 2026-09-22 裁决并落地：『仅被非 `fact` 引用 → 剥离』那一行**作废、失效一律重查**（设计文档第六章已同步修订；依据是实测的 6 条 `clarification` 正文在报数字）。真栈逼出重查两种收场：重查后成功 ✓ / 仍失效则整轮 fail closed ✓（见 `P1c-2/REPORT.md` 第六节） |
| [P1d](P1d-rank-structured-reasons/) | rank 理由结构化（P1 第 8 条，P1c 之后另开） | 推进计划修订第 8 条 | 本地会话（2026-09-22） | 2026-09-22 | `DONE_WITH_CONCERNS`：rank 侧 75 个调整点记 `{tag, delta}`（新增 `college_factors`/`major_factors`，旧 remark 串不动）+ Java 映射器（标签表 + 动态标签按后缀归类 + 未知标签 `unknown:` 保留 + 权重取不到不补 0）+ rank 边界填充；rank 14 条 / Java 796 条通过 | — | 端到端未验：本地只读栈从不调 rank（属 P2 写路径）；见 `P1d/REPORT.md` 第五节 |
| [T008](T008-output-extraction/) | 让 harness 取得到散文包裹的 JSON，并让取不到变成显式失败 | T005 REVIEW 第四节 2 | claude-subagent | 2026-09-13 | `DONE_WITH_CONCERNS` | `ACCEPTED_WITH_FOLLOWUP` | T009 |
| [T009](T009-agent-message-capture/) | 冒烟 payload 存一份拼好的 agentMessage 正文（碎片已在，缺"拼好的那份"） | T008 REVIEW 第六节 | claude-subagent | 2026-09-13 | `DONE` | `ACCEPTED_WITH_FOLLOWUP` | 无（三条遗留不开任务） |
| [P2](P2-write-closed-loop/) | 写入闭环 E2E（codex 网关侧） | 推进计划 §四 | 本地会话（2026-09-24） | 2026-09-24（口头） | `PARTIAL`：**审计指出的缺口补上了**——confirm 从"只做到 claim（`applying`）"改为**两段式**（claim → `pending-command/execute`）；claim token **复用** ✓；`operationId` **只认 Java 编译产出的**、取不到就**拒绝执行**（`operation_id_missing`，不自铸幂等键）✓；`proposalApply` 用**扁平**形状、不照抄 legacy 的 `executionPayload` 包装 ✓；失败不许读成 completed ✓。新增 6 条用例（四类异常 + 对照 + 缺 operationId），`test_conversation_actions.py` 21 条全绿；全量 `1948 passed / 35 skipped / 1 failed`（旧账）✓（第二轮后 1949 ✓）。**② 真栈端到端还差最后一段**：① ~~`operationId` 没落进 pending 的 data~~ **已解（同日第二轮，按裁决走生产者侧）**：`PlanningStateService.prepareUserGoalProposal` 走 `prepareOnce` 并在 pending 的 dataValue 里落下 Java 产出的 operationId ✓，新端点 `/session/fix-proposals/user-goal/prepare?requestId=` ✓，agent 写模式改走它（只读实例继续 `generate` ✓）；全量 `1949 passed / 35 skipped / 1 failed`（旧账）✓、`mvn -o compile` ✓（Java 单测未补 ✗）；② 写工具面**没有接线**——`MCP_WRITE_TOOLS_ENABLED`/`MCP_MODE` 在 `app/` 里**无人读** ✗（正是普查里零引用的 `McpConfig` ✗），`MCP_ENV_VARS` 也没透传这两个 ✗。另记一条事实：新链路的写路径**本就没有模型可调的写工具** ✓（提案 → 确认 → 执行），所以"写模式"要开的是确认链、不是给模型一把写枪 ✓ | — | **第四轮（真栈 E2E 起跑）**：抓到自己两个漏并已修——`codex_write` 不在 `GatewayConfig.mode` 的 Literal 里 ✗（症状只有 health 000 ✓，`2b3f1f1`）、显式环境启动脚本漏 `DEEPSEEK_API_KEY` ✗（每回合秒失败 `engine_unavailable` ✓）；写模式实例能正常服务回合 ✓（`locked-item-adjust` 过 ✓）；**卡点**：模型不出 `proposalRequest` ✗——根因是 P3 的 `<HARD-GATE>` 按只读阶段写的 ✗（写实例上它挡住了唯一写入口），写阶段的门禁语义 +「模型怎么知道自己在写阶段」尚待裁决/实现 ✗。**第七轮（真栈 E2E 跑通机械部分）**：提案 → pending → claim → execute → **回写** → 重复确认被拒（execute 行数不变 = 双写为零 ✓）全链路验过 ✓；E2E 抓出并修掉三处真缺陷 ✓（快照缓存自锁 ✗→✓、两开关必须为 true ✗→✓、缺回写致 pending 卡 applying ✗→✓，`7173494`）；**交接两条（第九轮更正）**：~~Java 内部不自洽~~ ✗ **更正**：6 种属直接应用路径（`/fix-proposals/apply`）、2 种属幂等确认链 ✓，**两条路径能力不同、不是 bug** ✓（Java 一行没改 ✓）；真正的缺口是**新链未实现 scope 类目标（加/删学校）的 apply** → 属设计裁决（在链里实现 / 走直接应用但与 P2 立意冲突）✗；另一条、goal→command 映射需补全（scope 类目标在 legacy 走 apply_constraint_and_regenerate ✓）；测试数据配方（userScoreDetail 的 CreateSessionReq 形状 + 两位选科码 + 复用会话自己的 userId）已落纸 ✓；还差「成功 apply」需要会话先有候选池/方案（多回合铺垫 ✗）。**第十一轮（2026-09-25 裁决落地）**：① scope 目标接进新链 ✓（范围类走 `apply_constraint_and_regenerate` + `constraintUpdate`，形状照 legacy；不认识的 scopeType 拒绝执行 ✓；新增 5 条测试 → 26 条全绿 ✓）；② 档位数据**维持现状** ✓；③ P3 判据接受现判据+归因 ✓；④ A 型维持现期望 ✓；⑤ `nextStep` **收敛到原生卡**（B）✓。全量 `1961 passed / 35 skipped / 1 failed`（旧账）✓。

待裁决/待做：~~① operationId 落点~~ ✓ 已做（生产者侧：Java prepare 落进 pending.dataValue）② 写工具面接线（MCP 读开关 + env 透传 + 一致性检查）③ ② 真栈 + "重复确认"的**库计数**证据 ④ 新开一条写路径场景（别放宽 `mixed-read-write` ✓）。见 `P2/REPORT.md` 第三节。**原审计结论**：Java 两条端点都在 ✓、legacy agent 有参照 ✓，**codex 网关侧缺 execute 那一步**（4 个调用点全在 `zhiyuan_agent/tools.py`）；第 4 步（前端按真实 CAS 更新）需浏览器，可能要 C 线配合；**派发前先读 TASK 二之二**：execute 的输入已逐个落到出处（operationId 由 Java 编译产出、proposalApply 类型 `FixProposalApplyReq`、claimToken 必须复用），并更正了一条我先前的误判——`executionPayload` 是 **legacy 自己写的**（`service.py:819-847`），不是死代码；两条链对同一个键各写各的形状，新链路按扁平 `proposalApply` 来、不照抄 legacy 的包装层 |
| [P2a](P2a-forbidden-tool-testable/) | 把 `plan_apply` 放上桌，让 `forbidden_tool_names` 守在对的门上 | mixed-read-write 成因 3 | 本地会话（2026-09-22） | 2026-09-22 | `DONE`：夹具声明写工具（`readOnlyHint: false`）且调用时明确拒绝；**真实端点 10/10 模型没碰它**（`plan_apply_called=False`、`forbidden_tools` 零次），这条主张第一次在正确条件下被测到；场景本身仍不过（另外三个成因，按要求未碰） | — | 顺带观察：8/10 次重复调用同一工具 2 次、1 次调用 4 次（同参数重复取数，与跨回合上下文同类） |
| [P2b](P2b-execution-status-split/) | 拆开"工具是否成功"与"诉求是否满足"两个语义 | mixed-read-write 成因 4（P2 第 4 项） | 本地会话（2026-09-22） | 2026-09-22 | `DONE_WITH_CONCERNS`：查证**只降不升的合成规则已在工作区落地**（`result_synthesis.py`，单向 ✓）；本会话补了它缺的两件——单调性关键那半的专测（工具成功不许把 partial 抬高）、**冒烟改量生产返回值**（原来量模型原值，"绿灯和修好没有关系"）；全量 1937 通过 | — | 未验："工具失败 + 模型宣称 completed → 生产拉低"这一整条端到端（场景集里没有工具失败的场景）；计划书那句"生产依然返回 completed"针对的是当时的生产代码，现已不成立 |
| [P2c](P2c-scenario-expectations/) | 把 mixed-read-write 的期望改对，并加一条 A 型姊妹场景 | mixed-read-write 成因 2（P2 第 2 项） | 本地会话（2026-09-22） | 2026-09-22 | `DONE_WITH_CONCERNS`：按计划书的倾向执行 B（`response_type` 接受 fact|clarification、`clarification_required` 不约束、`proposal_required` 撤掉）+ 新增可识别姊妹场景；B 的效果：`proposal_missing` 在歧义场景消失（不再惩罚先问清楚） | — | **跑出的新事实**：两条场景里模型都把写的那半边**整个忽略**（既没提案也没问）——旧的 `proposal_missing` 从来不是"该提案没提"，而是"写请求被无视"；这是 P2/P3 的一条真实条目（该提案还是该反问属设计裁决，未自行定） |
| [P2d](P2d-contract-schema-alignment/) | 契约字段"不可省略"（成因 1） | mixed-read-write 成因 1（P2 第 1 项） | 本地会话（2026-09-22） | 2026-09-22 | `DONE_WITH_CONCERNS`：**真因不是"模型不填"，而是模型可见 schema 与内部契约不一致**——模型填了 `partial`/3 条 limitations/nextStep，却因 `artifactType`（契约是 Literal，schema 只写 string）整条校验失败，冒烟又把三个字段从量具里丢了。补 3 处 enum + 递归比对用例（红-绿）+ 兜底 trace 带原值 + 提示词把 `executionStatus` 定义成"诉求满足度"。效果：三项 missing 消失、`mixed-read-write` **第一次绿** | — | 留两条：A 型场景的 `proposal_missing`（"该提案还是该反问"属设计裁决）；工具契约与 MCP 夹具 schema 未做同样比对 |
| [P2e](P2e-tool-contract-drift/) | 工具契约三处漂移的比对（P2d 遗留检查） | P2d 报告第四节第 2 条 | 本地会话（2026-09-22） | 2026-09-22 | `DONE`：查出两次真实漂移——`admission.get_history` 在编排层多要 `majorId`（真实工具是学校级口径、缺它只追加限制不是错误）→ 后果是模型没传就判 blocked、整轮被降级并补"请补充缺失参数"；夹具两处比真实更严。已修 + 新增比对用例（红-绿）+ 更正一条**与 bug 同向的旧断言**；全量 1939 通过 | — | P0 的 20×2 测量发生在本修正之前，已按报告里的命令复跑（见 `P0-acceptance-measurement`） |
| [P3](P3-process-gates/) | 流程门禁（superpowers 手法迁移；落点是 6 个 skill 的语义） | 推进计划 §五 | 本地会话（2026-09-23） | 2026-09-23（口头） | `DONE_WITH_CONCERNS`：6 个技能补 `<HARD-GATE>`（+39 行，**未动代码**）；**最终配置下判据达标**——`mixed-read-write` **0/20 forbidden_tools + 20/20 passed** ✓✓（此前 18–19/20 带 1–2 次写尝试 ✗）。**但如实说：这不是门禁的功劳** ✗——让现象消失的是**量具/场景三处修正**（① 量具 home 装插件；② 修 `skill_root` + 夹具补 `skill://` 资源通道，技能正文由 0 命中变可读 ✓；③ 夹具补 `admission.get_current_plan`——真实链路一直有的只读工具；模型两轮失败都是**拿写工具顶替读**：`proposalId="__read_current_plan__"` / `"NOOP-PLACEHOLDER-NOT-EXECUTED"` ✗）。门禁在**产品路径**上是实打实的语义（agent rollout 里门禁正文可见 ✓、写意图题路由到 `profile-discovery` 且不调写工具 ✓），但这条量具量不出它相对旧技能的增量 ✗（留底 0/20 vs 最终 0/20；修正前三次采样 2/0/2）。回归：全量 `1942 passed / 35 skipped / 1 failed`（旧账）✓、16 案例 **15/16**（0 业务失败）✓ | — | 三条修正已按"按建议推进"落地 ✓（量具首次真的能测技能内容 ✓）；**新增待裁决**：要与"旧技能"做可归因对照，需 ~100+ 次/侧样本或换一条能放大的判据 ✗。见 `P3/REPORT.md` 第一、三之二、三之二之二、三之二之三节 |

## 2026-09-28 更新：P2 写闭环 / C4 写路径四条全绿

`wip/2026-09-26-p2-c-line`（26 个提交，未推送）上，**写路径四条在 `codex_write` 栈上全绿** ✓：

| 用例 | 口径 | 读数 |
|---|---|---|
| F07 后半 放弃提案 | 取消不改变正式内容 ✓ | 2.3s ✓ |
| F08 确认双击 | 两次点击 → **一次** execute ✓、applied 后读得到 workspace ✓ | `[f08] version=0 → 3`、`phase=candidate_generated → reviewed` ✓ |
| F09 版本冲突 | 旧卡被拒 ✓、**不自动确认新预览** ✓、正式内容不前进 ✓ | `[f09] version=0 → 0` ✓ |
| F13 applying 时断线 | 事务不被取消 ✓、不双写 ✓、重连后读得到最终结果 ✓ | 两遍 4 passed ✓（同盐连跑） |

另有 `contract` **12 passed** ✓、agent 全量 **2007 passed** ✓（唯一红是既有的
`test_dialog_quality_gate` 缺 `zhiyuan-server/data/tmp/` 那批志愿文件 ✗，与本线无关）。

这一轮修掉的三处**网关/生产者侧**缺口（都有真栈读数 ✓）：

1. **600e16e 系列**：apply 的前置——canonical 三件套由 `prepare` 落进 pending 的 `dataValue` ✓
   （网关"存着就用、没有现取" ✓）；
2. **`602e16e`**：确认/取消的收尾**不随回合取消** ✓（掉线会把"发结果"那一步带走 ✗ →
   事件流里 0 条 `conversationAction.result` ✓）；
3. **`d583e4b`**：状态变更后的快照刷新要能**越过版本淘汰** ✓（reset/supersede 后版本合法往回走 ✗
   → 刷新被拒 → 缓存钉在旧快照 → **提案卡不出现** ✗）。A/B：同一个盐连跑两遍，
   修前 4 passed → **2 failed（F08+F13）** ✗，修后 **4 passed → 4 passed** ✓✓。

**库计数证据** ✓✓（P2 任务书第 ③ 条要的那一层 ✓；`assistant_planning_pending_command` ✓，
`operation_id` 上**有唯一键** ✓，所以"一次操作一行"是结构保证 ✓）。取最近一次写路径 4 条用例各自的会话 ✓：

| 会话 | `apply_plan_change_proposal` 行数 | 待确认状态 | 用例 |
|---|---|---|---|
| 900024 | **1** ✓ | `applied`, revision 3 ✓ | F08 双击 → **一次写** ✓ |
| 900034 | **1** ✓ | `applied`, revision 3 ✓ | F13 断线重连 → **没有第二次写** ✓ |
| 900032 | **0** ✓ | `active`, revision 1 ✓ | F09 冲突被拒 → 不产生写 ✓ |
| 900035 | **0** ✓ | `active`, revision 1 ✓ | F07 后半取消 → 不产生写 ✓ |

**P2 待做 ② 关账** ✓✓（"写工具面接线"✗ —— 2026-09-28 核实：**已经做过了，且口径已改** ✓）：
`composition.py:30` 的 `MCP_ENV_VARS` 已含 `MCP_MODE` ✓（透传 ✓）、`composition.py:191-195` 的
**一致性检查**在位 ✓（`gateway mode … expects MCP_MODE=…` ✓）、`service.py:468` 写明
"`codex_write` 与 readonly 的差别**不在模型能调什么**，而在**确认链是否活着**" ✓✓
——所以"写模式要开的是确认链，不是给模型一把写枪"这句结论已经落到代码里 ✓，
**不需要**再给 MCP 接写工具 ✗。唯一残留：`MCP_WRITE_TOOLS_ENABLED` / `McpConfig.write_tools_enabled`
**没有任何读者** ✗（启动脚本仍传 `=false` ✓），已在 `config.py` 就地标注"开与不开行为一样" ✗✓。

待办（不属于本线）：`test_dialog_quality_gate` 那条红 ✗ —— **是数据/环境，不是代码** ✓（2026-09-28 定）：

`test_final_action_explicit_clone_sources_have_volunteer_fixture` 读用例里的
`cloneBackendStateFromSessionId` ✓，要求 `zhiyuan-server/data/tmp/session_volunteer_<id>.json` **存在** ✓
（本机只有 2 个、且是别的 id ✗ → 94 条 violation ✓）。而这些文件是**源会话的原始志愿数据** ✓ ——
`examples/dialog_regression_runner.py:1505+` 的 clone 只做**源→目标复制** ✓（它自己的 docstring：
"Disposable cloned sessions need the same local **source files**" ✓），**源文件得来自真实环境** ✓
（生产抽样：`docs/release-3.1.0-production-session-sampling.md` ✓）。
**不要伪造** ✗：填一批内容不对的文件会让那条线的实跑**静默跑偏** ✗（比红着更糟 ✓）。
要真绿，得把真实源文件带过来、或对着真实环境跑一次抽样 ✓ —— 属 dialog 回归那条线 ✓。

另一条：**"库里 2 条却渲染 8 份"** ✗ 仍未定 ✓（trace 里只见到一份该会话的响应 ✓）。
分支：`wip/2026-09-28-p2-write-loop-green` ✓（已推 origin ✓，`develop` 之上 30 个提交 ✓）。

## 2026-09-23 事故与恢复：`app/gateway/service.py` 被误覆盖

死代码 A 批删除后的"按文件名整体回滚"把 legacy `app/service.py`（387549 字节）覆盖到了同名的网关 `app/gateway/service.py` 上，后者含三方未提交改动（P1b-3 Python 半、P1c-2、P2d）。**无 golden copy 可用**，已按"keep（9-21 19:58 快照）为底 + 任务报告与无损测试为规格"重建三处改动，逐项做到对应测试红转绿；全量 = `1 failed（既有 test_dialog_quality_gate）/ 1924 passed / 50 skipped`（带 `CODEX_TEST_REDIS_URL` ＝ 1939/35，与 P2e 记的基线一致）。**残留：不是逐字节还原**（P2b 记的调用点 `:1121` ⟶ 重建版 `:1180`，我的实现多约 50 行）。**真栈复验已补（2026-09-23 19:00）**：A/B 对照（原版 vs 重建版，同一事实题、同答 658）＋断依赖（核验端点打 500 → 整轮硬失败、18 字、无事实性回答）＋恢复四条全过，与 P1c-2 原验收逐项一致；带 `CODEX_TEST_REDIS_URL` 全量 = 1939/35，与 P2e 基线精确一致。**重查路径**：机制与 fail-closed 那一半已在真栈复现（会话 900325：重查一次 → 仍失效 → 整轮作废；backend 恰好 2 次 verify 调用），"重查后成功"那一半未撞到（单测已覆盖该组合）；同期还观测到一次模型抄错 ULID 导致的 `evidence_not_found`（模型侧老毛病，与重建无关）。16 案例验收回归 **16/16，0 业务失败 0 环境失败**。

**2026-09-23 晚：独立复核（主脑）判定「有条件不通过」**——三项要修：① 可空 `admissionMode` 的 enum 缺 `None`（契约允许 `null`、schema 会拒，`jsonschema` 实测；**重建时我自己引入的缺陷**）；② 重查轮没传 `on_notification`/`on_turn_started`（进度与 native turn 绑定都缺）；③ `_recheck_turn` 的 `start_turn` 回退把启动确认当回合结果。另有一项"无法判定"（新加日志文案）、一项"通过"（抽取重构）。**三项已全部修复，各补一条回归测试**；修复后：定向 30 passed、全量 **1942 passed / 35 skipped / 1 failed（旧账）**、真栈四项复跑通过（正常 / 断依赖 / 重查 fail-closed / **重查后成功**——后者用确定性方法补上：先查清"版本行是派生的（签发重算、核验直读）"，再"翻到首次核验就停"）。修复后指纹 `cd873230408d61c0ee7af960fb17c9fe`（复核时是 `a7f406d9…`）。详见 `../reviews/2026-09-23-gateway-service-rebuild-review.md` 与事故报告第十节。**复审判定（2026-09-23 21:1x）：放行**——三项修复全过（可空 enum / 重查轮回调 / `start_turn` 回退语义），另两项维持（新增日志文案「无法判定」、抽取重构「通过」）。复核记录另记了两个环境现象（三端口 curl 全失败 + 全量卡在 ~40%）；执行会话按「连接超时而非拒绝」+「自己四次全量皆 ~31s 自然完成」归因为**复核会话的网络沙箱**，并给出可自证命令（事故报告第十一节）——**该归因待复核确认**；"全量统计"与"真栈三项"这两类复核本轮由执行会话代跑，会话号与日志可溯。A 批删除已随回滚全部撤销（`git diff HEAD -- app/` 无顶层 def 删除）。**2026-09-23 裁决：A 批删除暂不重做**——先站稳恢复态（复核重建 + 真栈复验），之后另议；重做前必须先把备份/回滚改成按**完整路径**索引。详见 `../reviews/2026-09-23-gateway-service-restore-incident.md`。**普查清单已落盘**：[2026-09-23-死代码普查清单.md](2026-09-23-死代码普查清单.md)（用写死的方法重新生成 83 个候选，与前一轮的 82/37/16 分布逐项吻合；3 个模块本身零 import；0 条字符串动态引用；10 条人工抽样证伪）。

**2026-09-23 提交批次（6 个提交，工作区已清空）**：`292d85d`（server：台账/rank/来源/会话绑定）、`0066f44`（agent：证据链贯通 + 核验接入 + 网关重建与复核修复）、`364ba87`（agent：MCP 工具契约/技能插件化/验收脚本）、`b1b3495`（rank：理由结构化）、`7bb383a`（web/scripts）＋紧随的 docs 提交。提交前该批改动的验证：带 Redis 全量 1942 passed / 35 skipped / 1 failed（旧账）、16 案例验收 16/16、真栈四项（正常/断依赖/重查 fail-closed/重查成功）。


## P1b 三片的并行关系

三份任务书都已写好，**可以同时派给三个实现方**。改动面基本不重叠：

> **实际派发（2026-09-13）：三片全部给了 `zhiyuan-48` 一个会话，要求串行做、每片单独出报告。** 只有一个实现方可用时，串行是对的——三片共出一份报告会让"哪一项没验过"变得说不出口，而那正是 P1a 的失败方式。

| 片 | 改动面 | 与其它片的重叠 |
|---|---|---|
| P1b-1 | Java：摘要工具类、`GaotuClient`、`ResponseDTO`、`EvidenceSourceVersionMapper`、V15 migration、验收脚本 | 与 P1b-2 **零重叠** |
| P1b-2 | Python：`server.py`、`tools_readonly.py`、`internal_client.py` 及其测试 | 与另两片 **零重叠** |
| P1b-3 | Java：`ConversationSnapshotService`；Python：`service.py:545` | 与 P1b-1 **同改 `EvidenceLedgerService.java`**（P1b-3 只增只读方法，P1b-1 改已有方法体），合并由设计会话处理 |

两条**验收上的**顺序依赖，已写进各自的任务书，派发时不必额外交代：

1. **P1b-2 的端到端验收在 P1b-1 合入前无法对真实上游做绿**——真实上游不返回 `dataVersion`，Java 签不出证据。所以 P1b-2 的验收明确允许用替身（它测的是 Python 管道，替身在这里是被测对象的输入，不是外部世界的证人），但**测试数据的形状必须从 Java DTO 取，不能从替身脚本抄**——替身返回 dict、真实返回数组，照替身抄就会原样复制断链 3。
2. **P1b-3 的"造 `stale`"手法依赖 `evidence_source_version` 的表结构**，而 P1b-1 正在改它的主键。任务书已要求优先写成不依赖表结构的单测。

另有一条**跨片的口径待裁决**（P1a 跟进项 4，三份任务书都写了"不要自行处理"）：`EvidenceLedgerService.verifyOne()` 只在双方 `threadId` 都非空时才校验线程，而 Agent 侧 `strict_scope=True` 要求 scope 必须存在，Java 比 Agent 松。影响面封在单会话内，不构成跨会话泄露。

**已裁决（2026-09-13）：统一到松的那边——thread 不是证据的隔离边界。** 依据不是偏好而是事实：`service.py:372` 的 `self._threads` 是纯进程内 dict、从不持久化，thread 与 session 是 1:1，**一个会随进程重启而改变的标识符不能承载安全语义**。隔离由 `(tenantId, chatSessionId)` 承担，Java 侧一直强制。P1b-3 任务书已同步更新。

## P0 验收条：2026-09-22 首次量到，判据满足

两个复杂场景各 20 次（真实 Codex + 真实模型，工具为夹具）：

| 场景 | 通过 | Wilson 95% CI | 判据（≥19/20） |
|---|---|---|---|
| `reference-complete-history` | 20/20 | [83.9%, 100%] | 满足 |
| `mixed-read-write` | 19/20 | [76.4%, 99.1%] | 满足 |

`mixed-read-write` 从 **0/3** 走到 19/20（**首测**，已被复跑取代），靠的是今天的四件改动：
P2a（把写工具摆上桌）、P2b（合成只降不升 + 冒烟量生产值）、P2c（期望改对 + A 型姊妹场景）、
P2d（契约 schema 与 prompt 对齐）。明细见 `P0-acceptance-measurement/REPORT.md`。

**复跑（P2e 修掉契约漂移之后）**：`reference-complete-history` 20/20 ✓、`mixed-read-write` **18/20 ✗**——两次失败全是 `forbidden_tools`：模型**真的去调了写工具**。首测那个 19/20 是漂移造成的假象（读的那半被误判 blocked，模型更早收手、根本没走到写的那半）。**P0 这条验收条现在依赖 P3**（不能靠"模型碰巧没动手"，要靠"它动手时被挡住"）。

**2026-09-24 重测（量具修好后的第一次可信测量，两场景各 20 次）**：`mixed-read-write` **19/20 满足** ✓；`reference-complete-history` **12/20 不满足** ✗——8 次 `clarification_mismatch` 的根因是**场景口径本身不存在**（消息写「浙江 物理类 本科批」✗，浙江是综合/分段 ✓）：模型答对了事实、随后按 admission-fact-analysis 的纪律指出口径错 ✗；此前 20/20 是因为技能读不到、照字面答题 ✓。**2026-09-25 已按裁决修正并重测**：四条场景消息的「浙江 物理类 本科批」→ 真实口径「综合（N）第一段（17）」✓ + `historyQuery` 补 `batch/subjectType` ✓ → 新一轮基线 **两场景各 20/20（100%）✓✓ 判据均满足** ✓；如实记：这是动过场景输入之后的数字 ✗（动的是场景里的事实错误，有独立证据 ✓），上一轮的 12/20 与更早的 20/20 均被取代 ✓。详见 `P0-acceptance-measurement/REPORT.md` 附。

**2026-09-22 回归确认**：P2d/P2e 那串改动（schema 补 enum、提示词改 `executionStatus` 语义、工具契约与夹具对齐）之后，整套验收 1 遍 → **16/16，0 业务失败 0 环境失败**（`.runtime/zhiyuan-acceptance-regression-0922.json`）。

**证据边界**：本测量是"真实 Codex + 真实模型 + 夹具工具"那一层；
真实 Java 工具与浏览器两层仍未覆盖（见 `A1-A7-evidence-index.md`）。

---

## 待裁决：`nextStep` 在新架构里的去留（2026-09-22）

`nextStep` 是旧架构的字段被搬进了新契约：**契约层整合（且三处重复）、状态层与用户可见层不整合**
（Java 与前端全仓 0 命中，写了用户看不到），而新架构里"轮到你了"已有两个更完整的载体
（原生问答卡、proposal/conversationAction）。另查出 `execution_plan.py` 的
`userVisibleNextStep` 是**第二条对模型说的"下一步"**（每回合随执行计划骨架注入模型上下文，`service.py:952-961`）——
与契约里的 `nextStep`（模型说给我们）互不校验。**实测 60 条 rollout：58 条两者不同、0 条逐字相同**，差异是详略与措辞（不是矛盾）。**勘误**：初版误记为"零消费者的死字段"，已撤回。

事实、三条缝与三个选项（A 接线成状态 / B 收敛到原生卡 / C 降级为量具字段）见
`plans/2026-09-22-nextStep在四层里的落点与三条缝.md`。**2026-09-25 裁决：B（收敛到原生卡）** ✓——`nextStep` 不再单独成状态载体：「轮到你了」由原生问答卡与 `proposal`/`conversationAction` 承担 ✓，实现随新架构设计一并落地 ✓。

---

## 第二簇断链：校验器会结构性拒收权威证据（2026-09-13）

裁决上面那条时顺藤查出**另外三处**，编号接 4/5/6（`plans/2026-09-13-P1c证据校验器的三处结构性拒收.md`）。三处都在 `output_validation.py` / `service.py` 这一层，**P1b 全部做完之后链路仍然不通**：

| # | 断链 | 后果 |
|---|---|---|
| 4 | `service.py:770-781` 只从本回合 turn events 建账本，snapshot 里的权威证据不进账本 | `fillEvidence()` 把证据摆到模型面前，模型引用后立刻 `evidence_not_found` |
| 5 | `output_validation.py:143` 要求证据的 `stateVersion` 等于当前 `snapshot_version` | 工作区每写入一次就推进版本 → **第 3 回合的证据在第 7 回合必然 `stale_state`**，直接否掉 P1 的头号验收目标 |
| 6 | `output_validation.py:132` 要求证据的 `threadId` 等于当前 thread，而 thread 进程易失 | **一次 Gateway 重启让所有在世会话的证据全部作废**，fail-closed 下等于每个 fact 回合全线挂 |

三处今天全看不见，原因完全一致：**证据是每回合自铸的，填的就是当前值，于是三个检查恒真、从未真正做过判定。** 这与 `mcpCalls` 恒为 `[]` 是同一类错误的两面——那次是仪表没通电，这次是校验器没通电。由此产生的第三条方法论规则已补进 `README.md` 第六节：**迁移设计时要专门去找"现在永远通过"的检查**，判别办法是问"有没有一种输入能让它失败"。

**P1c 的范围因此扩大**：账本合并 snapshot、删证据的 `stateVersion` 等值检查、删证据的 `threadId` 等值检查（**artifact 那两处同名检查保留**，产物确实绑定线程与工作区版本），三件事都必须排在四态核验接入**之前**。删检查方向上是放松，论证见设计笔记第六节：删掉的是两个恒真因而从未做过判定的检查，换上的四态核验是会真的说"不"的——**防线变强了**；反过来先接核验不删检查，则两道门都关着，`fact` 回合永远出不去。

**因此 P1c 也切两片**，仍按验证面切（同 P1b 的理由）：

| 片 | 内容 | 验证面 | 状态 |
|---|---|---|---|
| P1c-1 | 上面这三件事 | 纯 Python 单测能验完，不需要真实上游、不需要跑通端到端 | 任务书已写，等 P1b-2/P1b-3 合入后派发 |
| P1c-2 | 四态核验接入 + 第六章分流表 + 重查一次 | 需要 Java verify 端点 + 真实工具执行 | **前置已解除，任务书可写** |

P1c-2 的任务书原本暂不写，是有意的：它要调 `/internal/evidence/verify`，而那个端点的请求/响应形状会被 P1b-1 的 `currentDataVersion(String, String)` 改签名波及。现在写等于拿假设当事实——**这正是 P1a 栽过的那个跟头**（README 第六节第五条）。

**2026-09-13：P1b-1 已合入，签名定死，这条前置解除。** 同时 P1b-1 的复核给 P1c-2 带回一条必须一起做的遗留（`P1b-1-content-digest/REVIEW.md` 第六节）：

> **`currentDataVersion()` 查不到记录时返回空串 `""`**，于是比对必然不等，`verifyOne` 把它判成 `stale`。可四态里的 `unknown` 正是为这种情形准备的——**"我没有当前版本的记录"和"当前版本跟你签的不一样"是两个不同的问题，现在共用一个答案槽。**

**这是这个形状的第三次**（前两次：断链 5 的 `stateVersion` 把"方案版本"当"招生数据版本"；成因 4 的 `executionStatus` 把"工具跑成功了吗"当"诉求满足了吗"）。它的直接后果是诊断被污染：版本表一旦被清空（例如 V15 那样的 `DROP TABLE` 重建），系统报出来的是"上游数据变了"，而真相是"我丢了自己的版本记录"，**两者的处置完全不同**。

附带记一条运维约束：**`evidence_source_version` 后续迁移不得再用 `DROP TABLE` 重建。** V15 这次是安全的，条件是台账从未进过产线（本节下方第 2 条）——一旦进了产线，同样的迁移会让**全部在世证据在被重新观测之前一律判 `stale`**，fail-closed 下等于全部作废。

**P1c-1 合入后到 P1c-2 合入前，证据侧的拒收能力存在一个真实的中间态**（`stateVersion` / `threadId` 两维暂时不设防，会话/租户隔离、`evidence_not_found`、`dataVersion` 比对、`admission_mode` 都还在）。这是有意接受的，理由同上——但它是**真实存在的窗口，不是纸面上的**，因此 P1c-2 不应长期挂起。


## 本轮复核的两条结论（影响后续排期）

1. **P0 仍未清零。** 判定 T005 时独立重跑 `reference-complete-history` 8 次得 7 过 1 挂，挂的那次是模型先写散文再补围栏 JSON、harness 取不到 output；`mixed-read-write` 基线 0/3。P0 的验收条（两个复杂场景各连续 3 次 `evaluation.passed == true`）两项都还没满足。解析层转 T008，~~写操作契约层留 P2~~。

   **T008 已 `ACCEPTED_WITH_FOLLOWUP`（2026-09-13）**，但它**没有让第一条验收条清零**，三件事要分清：

   - **仪表层修好了，且在真实端点上被证明**：改动后 20 次真实调用（实现方 10 + 我 10）**20/20** 写出 `evaluation` 键。以前"解析失败就不写这个键"的静默假值路径已经不存在。
   - **解析层只由单测证明**：20 次里 `source=fenced` / `embedded` 各 **0 次**，T005 撞到的那个形状一次都没再出现。任务书明确许可（低频事件不要求真实端点复现），但**"按设计工作"不等于"在生产上验证过"**。
   - **可靠性 19/20 = 95.0%，Wilson 95% CI [76.4%, 99.1%]**。唯一一次失败是**新形态**：模型把 JSON Schema 原样回吐而非给实例，且被截断（我从 671 个 delta 片段重建原文确认，非解析器失灵）。这个形态与 P2 第 1 条同源——**模型没把输出契约当契约**，建议并进 P2 定，不单开任务。

   **顺带发现这条验收条本身写得不好**：我这 10 次的前 3 次字面满足了"连续 3 次"，但该判据在真实可靠性 95% 时有 85.7% 的概率通过，90% 时 72.9%，85% 时仍有 61.4%——**它区分不了 85% 和 100%**。P0 收口时必须改成带分母的形式，详见 `README.md` 第六节新增的第三类验收缺陷。

   **归因勘误（2026-09-13）：「写操作契约层」这个说法是错的**，见 `plans/2026-09-13-P0第二条验收条mixed-read-write的四个成因.md`。三次运行里**模型一次都没试图写入**，写操作路径根本没被走到。0/3 由四个独立原因造成，只有一个该由模型负责：

   | # | 成因 | 性质 |
   |---|---|---|
   | 1 | 模型把 `executionStatus` / `limitations` / `nextStep` 说进了散文，字段留空（3 次里 2 次） | 真缺陷，归 P2 |
   | 2 | 场景让 `school-3` 无名、不在候选集，然后要求模型**不许澄清**、必须给删除提案 | **期望写错了**——它奖励了闭眼提案、惩罚了问清楚 |
   | 3 | `forbidden_tool_names={"plan_apply"}` 空转——只读夹具没声明这个工具 | 第 5 次撞上"永远通过的检查"，且是更隐蔽的一种（见下） |
   | 4 | `service.py:854` 用工具批次状态**覆盖**模型的 `execution_status`，且冒烟走的是覆盖前的值 | **生产缺陷**，且冒烟在结构上看不见它 |

   第 4 条最要紧：工具全成功时 `partial` 被无条件改写成 `completed`——**用户请求了读+写，系统做了读、拒了写，然后报告"完成"**。而且成因 1 修好之后冒烟会变绿，生产依然是 `completed`，**绿灯与修好之间没有关系**。与断链 5 同型：两个不同的问题（"工具跑成功了吗" / "诉求满足了吗"）共用一个字段名，其中一个把另一个吃掉了。

   P2 的范围因此改写成四件事，次序 3→4→2→1，详见该笔记第六节。
2. **P1a 建成的机器还没接进产线。** 生产取数路径（`GaotuService.java:603/617`）走的是不带 scope 的重载，等价于不签发；唯一会签发的调用方是 inner 下的 debug controller。另有两项上游契约假设（`dataVersion` 字段是否真实存在、版本是否随查询参数变化）必须用一次真实上游调用定下来，**不能继续在替身上验证**。这三条都是 P1b 派发的前置。

   **更新（2026-09-11）：后两项已实测结案**（`plans/2026-09-11-P1a上游版本契约实测与dataVersion改设计.md`）。结果是最坏的一种——**真实上游根本不返回 `dataVersion`**，照原设计落地则生产上一条证据都签不出来。改为 Java 对 `data` 子对象算内容摘要，版本表键定死为 `(source_system, params_digest)`。

   **同日查清第一项的归因错了**（`plans/2026-09-11-P1a证据到不了Agent的三处断链.md`）：不签发的原因不在 `GaotuService.java:603/617`（那条路 Agent 不经过），而在 Python 侧三处互相独立的断链——scope 没上路、信封被 `_data()` 拆掉、`data` 是数组而归一化只吃 dict。**P1b 现在可派发，但改动面比原估计大，重心在 Python 侧。**

   这条留下两条方法论，已补进 `README.md` 第六节：**替身能证明代码按设计工作，不能证明设计与外部世界相符**；**桩的形状要从生产者那一侧取，不要从消费者的期望那一侧编**。P1a 在替身上九步验收全绿，验的却是设计会话编出来的契约；Agent 侧三层测试都有效，缝隙全在层与层之间。

   **任务书已就位（2026-09-11）**：P1b 拆成 P1b-1 / P1b-2 / P1b-3 三份，见上表与并行关系一节。三份都可立即派发。

## 已闭环的待办

- **T004**：`zhiyuan-agent/CLAUDE.md` 残留的 `ChatAgent` 引用（T002 漏网项），已由设计会话在 2026-09-10 直接修复。

## 说明

### 同一工作树的文件占用矩阵（2026-09-13，派发前必查）

现在同时有**两个实现方在跑**（`zhiyuan-48` 串行做 P1b 三片；一个 subagent 做 T009），另有三件排队（P1c-1、P2、P1c-2）。**全部在 `/root/dev/zhiyuan` 一个工作树里，没有分支。**

这意味着两个实现方同改一个文件不是"git 冲突"，是**后写的直接覆盖先写的，无声无息**。派发前对着这张表看一眼：

| 文件 | 谁声明了它 | 状态 |
|---|---|---|
| `app/gateway/service.py` | P1b-3（`:545`）、P1c-1（`:770-781`）、P2 第 4 项（`:845-854`） | **三方占用**，行段不重叠但必须串行派发 |
| `EvidenceLedgerService.java` | P1b-1（改已有方法体）、P1b-3（只增只读方法） | 两方，已知，合并由设计会话做 |
| `scripts/codex_semantic_smoke.py` | T009 ✅ 已提交、P2 第 2 项（`:99-118`） | 已释放，P2 第 2 项可派 |
| `app/harness/codex.py` | T008 ✅ 已提交 | 已释放 |
| `tests/fixtures/mcp/semantic_readonly_server.py` | P2 第 3 项 | 独占，**随时可派** |
| `app/engine/result_synthesis.py` | P2 第 4 项 | 独占 |
| `output_validation.py` | P1c-1 | 独占 |
| `app/mcp_server/server.py`、`tools_readonly.py`、`internal_client.py` | P1b-2 | 独占 |

**规则：一个文件同一时刻只能有一个在跑的实现方。** 行段不重叠也不行——两个 agent 各自读全文、各自整体写回，行段无关。

**这张表只管"谁改它"，还有两种依赖它看不出来，派发前要单独想：**

1. **占用 ≠ 依赖。** P2a 一行都不改 `scripts/codex_semantic_smoke.py`，但它的验收第 3、4 条**要跑这个脚本**。T009 此刻正在改它——拿一个改到一半的脚本去跑真实端点，跑出来的数字不能用。**所以 P2a 必须等 T009 合入**，哪怕文件占用表上两者零重叠。
2. **真实 codex 运行时是独占资源。** 两个任务同时打真实端点会互相干扰（T005/T008 都撞到过）。**涉及真实端点验收的任务一次只派一个。**

T008 与 P1b 系列并行执行，共用 `/root/dev/zhiyuan` 一个工作树。这是有意的——T008 在 harness/scripts 层，P1b 在 Java 与 `app/mcp_server/`、`app/util/` 层，**改动面零重叠**，串行没有收益。

代价有两条，两份任务书都已加防护：

1. **误伤风险。** 一条 `git stash` 能删掉另一方几小时的未提交工作，且不会立刻被发现。两份任务书都明令禁止一切改动工作树的 git 命令（`checkout` / `restore` / `stash` / `reset` / `clean` / `add` / `commit`），只读的 `status` / `diff` 允许。
2. **全量测试互相污染。** 一方跑 pytest 时另一方可能正在改 Python 文件。规则是：**基线以外的失败先看落在谁的面上**，不属于自己的照实记录并注明"疑似并发改动导致，未处理"，不要去修。

复核时相应地**不能只看 `git status` 的总清单**去核对文件声明，要按改动面归属分别核对——这是并行带来的额外复核负担，由设计会话承担。

T001 / T002 在本协议建立前派发，因此没有 `REPORT.md`——这正是建立协议的直接原因。两者的 `REVIEW.md` 由设计会话事后补做，判定依据是自行重跑验收，不依赖实现方的聊天转述。

T003 判定维持 `ACCEPTED`（schema 归一化本身经独立复核成立），但它的**验收条件由设计会话写错**：`status=completed` 量不出场景是否跑通。勘误见 `T003-schema-compat/REVIEW.md` 末尾，由此产生的规则见 `README.md` 规则 4，遗留工作转 T005。

T006 / T007 由设计会话口头派发，没有 `TASK.md`——这是设计会话的欠账，不计入实现方偏离。规则已补进 `README.md` 第七节「口头派发的任务怎么判边界」。

P1a 的 ID 不走 `T0NN` 序列，因为它是修订计划 P1 的切片（P1a/P1b/P1c），归属关系比流水号更重要。切片与 `T0NN` 共用同一套状态词和复核流程。

