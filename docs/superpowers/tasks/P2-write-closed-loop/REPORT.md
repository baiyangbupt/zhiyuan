---
task: P2
status: PARTIAL（代码两半 + 写模式接线 + 写实例规则层都已落地并各自验证；② 真栈 E2E 只差「标准选科编码」这一个测试数据值 + 跑一遍驱动）
executor: 本地会话（2026-09-24）
source: docs/superpowers/tasks/P2-write-closed-loop/TASK.md
---

# P2 报告：写入闭环 E2E（codex 网关侧）

## 一、结论

**审计指出的那个缺口补上了**：`confirm` 从"只做到 claim（`applying`）"改成**两段式**
（claim → execute），四类异常各一条用例 + 对照；全量回归过。但 **② 真栈端到端还跑不了**——
它被两处**跨侧**堵点挡住（详见第三节），需要裁决/另一侧改动才能打通。

| 任务书验收 | 状态 |
|---|---|
| ① 四类异常各一条用例 + 对照 | ✓ 已做（新增 6 条，`test_conversation_actions.py` 21 条全绿）。**说明**：任务书要求"重复确认"给**双写为零**的证据（回读数据库计数）——替身层面给的是"execute 只被调一次"；真栈的落库计数随 ② 一起做 ✗ |
| ② 真栈 confirm → 落库 → 回读 | ✗ **就差最后一段**：operationId 的落点已按裁决做完（第三节堵点 1 ✓，Java 编译 + agent 全量都过 ✓），剩下的只有"写工具面接线 + 真栈跑一遍" |
| ③ 不回归 | ✓ `1 failed / 1949 passed / 35 skipped`（那 1 = 旧账 `test_dialog_quality_gate`） |

## 二、改了什么

**`app/gateway/conversation_actions.py`（核心）**：
- confirm 成功（claim 返回 `applying`）后**继续走 execute**：`pending-command/execute`，
  `command_type=apply_plan_change_proposal`；
- **claim token 复用**：claim 时生成、execute 原样带上（任务书点名"最容易错的一点"）；
- `operationId` **只认 Java 编出来的那个**（pending data / activeProposal 里取），**取不到就拒绝执行**
  （`operation_id_missing`）——自铸会让 Java 的幂等键认不出同一次操作，"重复确认不双写"就失去依据；
- `proposalApply` 用**扁平**形状（`FixProposalApplyReq` 那层），**不照抄 legacy 的 `executionPayload` 包装**
  （任务书二之二的更正：那个键是 legacy 自己写的，Java 全仓 0 命中）；
- 失败不许读成成功：沿用既有的 `_status`（"HTTP 成功不等于执行成功"），拿不准一律 `failed`。

**`app/gateway/service.py` / `composition.py`（写模式，最小接线）**：新增模式名 `codex_write`
（与 `codex_readonly` 并列；代码注释写明它**不是**"给模型开写工具"，而是表示确认链在这台实例上是活的）。

**测试**（`tests/unit/test_conversation_actions.py`，新增 6 条）：
对照（同 token + 扁平形状）／陈旧 revision（不执行）／重复确认（execute 只一次）／
过期 Proposal（拒绝 + "要重新生成"如实回传）／执行失败（落 `failed`，不是 `completed`）／
缺 operationId（拒绝执行）。另更新一条旧用例：它记录的正是"claim 只报 applying"的旧行为 ✓（P2 要改的）。

**Java 侧（operationId 落点，2026-09-24 第二轮）**：
`PlanningStateService.prepareUserGoalProposal(...)`（prepareOnce + 把 operationId 写进 pending 的 dataValue ✓）、
新端点 `POST /session/fix-proposals/user-goal/prepare?...&requestId=` ✓、`internal_client.prepare_user_goal_planning_fix_proposals` ✓、
`service.py` 写模式改走 prepare（并同时认 `PrepareResultDTO` 的嵌套 `result` 形状 ✓）。
测试：`tests/integration/test_shadow_gateway.py` 新增写模式用例（含"generate 不许被调"的对照 ✓）→ 该文件 15 条全绿 ✓。
`mvn -o compile` 通过 ✓（Java 单测未补 ✗，见第五节第 5 条）。

## 三、跨侧堵点（② 为什么还跑不了）

1. **~~`operationId` 没有人写进 pending 的 data~~ —— 已解（2026-09-24，按裁决走"生产者侧落地"）。**
   生产者侧确认过：operationId 是 Java 编译时产出的 ✓（`ConversationProposalRequestService.PrepareOutcome`），
   但它原来只存在**自己的实体**里（`ConversationProposalRequestEntity`）✗，没有落进 pending 的 dataValue ✗，
   而快照暴露给网关的只有 `activeProposal.data` ✗ → 网关 confirm 时拿不到 ✗（当时按 fail-closed 拒绝执行 ✓
   所以不会错写，但链路是断的）。
   **落地方案（Java 侧，生产者权威）**：
   - `PlanningStateService.prepareUserGoalProposal(...)`：走 `prepareOnce`（幂等/supersede/并发防线都由它承担 ✓），
     work 里**编译预览 → 生成 operationId → upsert 一个 pending（dataValue 带上 `operationId` /
     `proposalSource` / `sourceVersion` / `proposalId`）→ 返回 (pendingId, operationId, 预览)** ✓；
   - 新端点 `POST /session/fix-proposals/user-goal/prepare?chatSessionId=&requestId=` ✓
     （**只读实例继续走 `generate`** ✓——那条路只出预览、不产生待确认，是刻意的 ✓）；
   - agent 侧：`codex_write` 模式下改走 `prepare`（`requestId = 租户:会话:回合`，同回合重试即重放 ✓）；
     `generate` 在写模式下**不许被调**（测试里用"被调到就炸"的替身守着 ✓）。
   → 闭环因此**不再需要网关自己记录 operationId**：它由 Java 落进 pending、由快照带出来，
     和 execute 段的读取（`activeProposal.data.operationId` ✓）正好接上 ✓✓。
   **留一条**：Java 侧这次没有补单测（时间），由 ② 的真栈端到端覆盖 ✓。
2. **写工具面没有真正接线（step 1 比任务书预估的大）。**
   实测：`MCP_WRITE_TOOLS_ENABLED` / `MCP_MODE` 这两个名字在 `app/` 里**没有任何代码读** ✗
   （启动脚本一直在传 ✓；唯一相关的是 `app/config.py` 的 `McpConfig.write_tools_enabled` ✓——
   正是 2026-09-23 死代码普查里 **零引用** 的那个类 ✗）；`composition.MCP_ENV_VARS` 也只透传
   `INTERNAL_SERVICE_URL` / `INTERNAL_SERVICE_TIMEOUT_SECONDS` ✓，MCP 子进程根本收不到这两个开关 ✗。
   → "让写工具在该阶段可见"不是加个 flag，而是要**真的接线**（MCP 侧读开关并据此暴露写工具 ✓
   + 透传 env ✓ + 与模式的一致性检查 ✓）。
   **补一条事实**：新链路的写路径**本来就没有模型可调的写工具** ✓——它由
   "模型出 `proposalRequest` → Java 编译出 pending → 用户确认 → 网关执行"承担 ✓✓
   （P2 任务书二之二的形状），所以"写模式"要开的是**确认链**，不是给模型一把写枪 ✓。

## 四、边界遵守

- 没改 P1 证据链 ✓；没在 Gateway 加关键词规则 ✓；没碰前端乐观更新 ✓；
- `mixed-read-write` 场景期望一个字没动 ✓（写路径要另开场景量 ✓，见任务书 §五）。

## 四之二、第三轮（2026-09-24）：写工具面接线 + 重部署 + operationId 落点的真栈验证

1. **写工具面接线**（`476e3b1`）：MCP 读 `MCP_MODE`（默认只读）✓；写工具仍不可调，但拒绝话术按模式变
   （写实例指向合法出口"用 proposalRequest 出提案、用户确认后由确认链执行" ✓）；`MCP_ENV_VARS` 补上
   `MCP_MODE` ✓（MCP 子进程不继承环境，不声明就永远拿不到 ✓）；网关侧一致性告警 ✓。
2. **重打包重部署 Java** ✓（此前跑的是 9-22 06:29 的 jar ✗）：`mvn -o package -DskipTests` ✓ +
   `/tmp/restart_backend.py`（继承旧进程环境→停旧→起新→等健康 ✓，日志轮转以便真栈证据干净）。
3. **operationId 落点的真栈验证** ✓✓：部署后探针**抓到一个编译期发现不了的 bug** ✗——
   `upsert` 的 `validateUpsert` 要求调用方给 `pendingId`（服务不生成）→ 已修（生成 uuid，与 legacy
   同一约定 ✓）。复探（真实会话 900357）：
   - `prepare` 返回 `{status:prepared, pendingId:88db3aaa-…, operationId:9cd0705f…, result:{…}}` ✓
   - 库里 `assistant_chat_session_pending_confirmation` 的 `data_value` =
     `{"operationId":"9cd0705f…","proposalId":"ugp_02e9c864…","proposalSource":"user_goal","sourceVersion":0,…}` ✓✓
     ——**operationId 确实落进了 pending 的 dataValue**，正是 execute 段要读的那个位置 ✓。

## 四之三、第四轮（2026-09-24）：真栈 E2E 起跑——又抓到自己两个漏，卡在"写阶段的门禁语义"

**抓到的两个漏（都已修，`2b3f1f1` + 启动脚本）**：
1. `codex_write` **不在 `GatewayConfig.mode` 的 Literal 里** ✗ → `GATEWAY_MODE=codex_write` 起 agent 时
   pydantic 直接拒收，`Application startup failed`，而症状只有 **health 000**（排查起点完全不指向配置 ✓）。
   已修 + allowlist 用例加一条；
2. 我那份"显式环境"启动脚本（`/tmp/start_agent_write.py`）**漏了 `DEEPSEEK_API_KEY`** ✗ →
   codex 每个回合秒失败 `engine_unavailable`，日志原文 `Missing environment variable: DEEPSEEK_API_KEY` ✓。
   已修（从启动者环境读，不写死 ✓）。

**已验到的**：
- 写模式实例**能正常服务回合** ✓：验收用例 `locked-item-adjust` 在 `GATEWAY_MODE=codex_write` +
  `MCP_MODE=write` 下**通过** ✓（10.7s ✓）；两个开关一致、日志无 mismatch 告警 ✓；
- `prepare` 端点的真栈行为 ✓✓（第三节第三轮已验：pending 的 dataValue 里带着 Java 产出的 operationId ✓）。

**卡在哪**：两轮 plan 类用例跑下来**没有 pending 产生** ✗ ——模型在这两轮里**没有出 `proposalRequest`** ✗。
根因是结构性的：**P3 的 `<HARD-GATE>` 是按只读阶段写的** ✗（"本技能不创建 Proposal / 不执行，
写请求只说明需用户确认" ✓）——那套话在只读实例上完全正确 ✓，但写实例上它**阻止了唯一的写入口** ✗。
→ 这正是 P2 步骤 1 的后半（"门禁语义按 P3 的写法进技能" ✓）**还没做** ✗：
   写阶段要有对应的语义（"用户要写 → 出 `proposalRequest`；是否执行由确认链决定" ✓），
   且模型要**知道自己在哪个阶段** ✓ ——这一条要裁决：靠快照的 `allowedCapabilities`（Java 侧 ✓）
   还是靠模式相关的 developer_instructions（网关侧 ✓）。

**另外记一条不属于 P2 的观察**：`plan-generate-readonly` 这轮失败在
`evidence_scope_violation: planner-tier-mapping-v1` ✓ ——那是 P1 证据校验的 fail-closed 生效 ✓
（模型引用了不在范围内的证据 ✓），与写闭环无关 ✓。

**驱动已就绪**：`/tmp/write_turn.py`（建会话 → 写意图 → 读 pending → 用 WS 的 compat 形状发确认 ✓；
还差一个"用既有会话"的开关，给"确认半段"复用 ✓）。

## 四之四、第五轮（2026-09-24）：写实例的规则层就位；E2E 前半段就差"给会话铺画像"

**改了什么（`3d6e6b5`）**：新增 `skills/codex/developer_instructions.write.md`（写实例附加规则：
写请求 → 出 `proposalRequest` 说清对象/变更/影响；不自执行、不调写工具；提案里不编数字；
只读的那半——证据绑定、四态、缺硬事实先澄清——一条不放松），由 `composition` 在 `codex_write`
时拼进 developer instructions（只读实例不带 ✓，测试两条：写实例带上 / 只读实例不许带 ✓）。

**为什么走指令层而不是快照**（核实过再定 ✓）：Java 的 `fillCapabilities` 恒为只读
（只加 `catalog_read` / `admission_read` / `review_read` ✗）→ 快照里**没有写能力**可判 ✗；
而技能文本两边共用 ✗ → 实例级规则只能由"知道自己是哪个模式"的那一层（网关）来加 ✓。

**这轮验证到的**：
- 写实例上两个 plan 用例**都通过** ✓（`plan-generate-readonly` 17.6s、`locked-item-adjust` 18.5s，
  2/2、0 失败 ✓）——写模式下只读行为**没有回归** ✓；
- 但**仍没有提案产生** ✗ ——查明原因：这两个用例本来就是**只读期望** ✓
  （`plan-generate-readonly` 要的正是只读草案 ✓），不是写意图场景 ✗；
  按任务书 §五，写路径要**另开场景/另发指令** ✓。

**E2E 前半段的最后一块（已定位）**：写意图要出提案，会话得有**已确认的画像** ✓
（缺硬事实时模型的正确行为是先澄清 ✗✓，我实测那句"把浙江大学加进我的方案"就是这样 ✓）；
而本地库里**没有现成画像**（`assistant_chat_session_extra_data` 全是 25 字节的批数据 ✗）。
→ 下一步：驱动里加"铺画像"一步（走 `internal_client.save_chat_profile` / 成绩详情那类 inner 接口 ✓，
harness 自己不带铺状态 ✓），然后：写意图回合 → 期望 `proposalRequest` → prepare → **pending** ✓ →
再用 WS compat 形状发确认（驱动 `/tmp/write_turn.py` 已就绪，补一个"用既有会话"的开关 ✓）→
回读 + 重复确认的库计数 ✓。

## 四之五、第六轮（2026-09-24）：E2E 前半段收窄到**一个**未知量——标准选科编码

要跑"写意图 → 提案 → pending"，会话得先有确认画像 ✓。本地栈没有现成画像（`extra_data` 全是
25 字节批数据 ✗），于是按生产者侧迭代探了"建会话时带成绩"这条正路 ✓，把接口的真实要求逐条钉出来：

| 顺序 | 要求 | 证据（原话） |
|---|---|---|
| 1 | `province.code` | `请选择高考省份后再创建会话` → 补 `{"name":"浙江","code":"330000"}` ✓ |
| 2 | `subjectType.code` | `请选择选科类型后再创建会话` → 补 `{"code":"N"}`（浙江综合 ✓） |
| 3 | `subjectScoreList` 非空且**字段名要对** | `请填写各科成绩后再创建会话` → 我最初用 `{"name":…}` 得到 **`系统错误`** ✗；真形状是 `{"subject":…,"subjectName":…,"score":…}`（`CreateSessionReq.SubjectScore` ✓）→ 之后报错前进到第 4 条 ✓ |
| 4 | `subjectList[].value`/`subject` 必须是**标准选科编码** ✗ | `非标准选科编码` ——试过 `"1"/"2"/"3"` ✗、科目名（→`空指针异常` ✗）、`"PHY"/"CHE"/"BIO"` ✗；**这条报错不在 Java 源码里**（全仓 grep 0 命中）→ 来自依赖 jar ✗ |

**第 4 条就是唯一的未知量**（一个词汇表值 ✓）。去哪儿找：前端的选科选项接口
（`zhiyuan-web/src/interface/api/updateBaseInfo.ts` / `customerDetail.ts` 会取这份字典 ✓）
或 gaotu SDK 里的编码枚举 ✓。

**除它以外，E2E 的全部零件都已就位** ✓✓：
- 写模式实例 ✓（`GATEWAY_MODE=codex_write` + `MCP_MODE=write`，health 200 ✓，两个开关一致无告警 ✓）；
- 写实例规则层 ✓（`3d6e6b5`，测试守住 ✓）；
- `prepare` 的真栈行为已验 ✓✓（pending 的 dataValue 里带着 Java 产出的 operationId ✓，第三节第三轮）；
- 驱动 `/tmp/write_turn.py` 已就绪 ✓（建会话 → 写回合 → 读 pending → WS compat 形状发确认 ✓；
  补一个"用既有会话"的开关即可复用 ✓）；本节的铺画像配方也已落纸 ✓
  （拿到编码后填进 payload 即可 ✓）。

**注意**：这一段是**测试数据**的事，不是 P2 的代码 ✗——P2 的 agent/Java 两半都已落地并各自验证 ✓；
E2E 离收口只差"查到那个编码 + 跑一遍驱动 + 确认半段" ✓。

## 四之六、第七轮（2026-09-24）：**写闭环的机械部分全部验通**——三处真缺陷被 E2E 抓出并修掉

### 验到了什么（每一步都有原始输出）

| 步 | 结果 |
|---|---|
| 写意图回合 | 模型出提案 ✓（正文自述「写操作在你确认之前一律不执行…只生成一条待你确认的提案」✓ = 写实例规则层生效 ✓） |
| prepare | 库里出现 pending ✓（`operationId=6fec912d…` / `cc5af919…` ✓ 由 Java 产出 ✓） |
| 确认（claim） | `pending/resolve(confirm)` 通过 ✓，pending → `applying` ✓ |
| 执行（execute） | **真的打到 Java 的业务校验** ✓（见下「交接 2」） |
| **回写** | pending `applying` → `expired` ✓✓（fail 分支 ✓，不再卡住 ✓） |
| 重复确认 | 被 Java 拒（`40902 pending transition mismatch` ✓）→ **execute 行数不变 = 双写为零** ✓✓ |

### E2E 抓出并修掉的三处真缺陷（`7173494`）

1. **快照缓存自锁** ✗→✓：提案改了服务端状态（pending 落库），而网关缓存的快照是提案**之前**的
   → 确认时拿旧快照核对 `proposalRef`，必然 `proposal_reference_mismatch` ✗（确认永远被自己的缓存挡住）。
   修：提案成功后重读权威快照并写缓存 ✓。
2. **`proposalApply` 两开关必须为 true** ✗→✓：Java 明说 "requires regenerateOrderedPlan and
   rerunReview"，legacy 客户端默认也一直是 true；我按「保守取 false」写 → 真栈 40001 直接拒 ✗。
   教训写进注释：**没有依据的"保守"就是猜**，依据在生产者侧 ✓。另补 `userGoalRequest` 透传 ✓。
3. **execute 之后没有回写** ✗→✓：不回写则 pending 停在 `applying` ✗——而它正是「重复确认」的判定依据
   （第二次确认会走「applying 且未过期 → 同状态」分支，看起来像没事、实际什么都没落地 ✗）。
   回写复用**同一个 claim token** ✓（Java 校验归属 ✓）。

### 交接给设计侧的两条发现 ✗（不是 agent 改得动的）

1. **Java 内部不自洽**：`RepairProposalTaxonomy.USER_GOAL_APPLYABLE_STRATEGIES` 列了 6 种可 apply 的
   user-goal 策略（含 `only_keep_scope` / `must_include_scope` / `exclude_scope` / `tuition_budget_scope` ✓），
   而 `PendingPlanningCommandBizService` 的 user-goal 分支只认 `FILL_MISSING_COUNT` / `PRIORITIZE_WITHIN_TIER`
   两种 ✗ → 「把浙大加进方案」这类**最自然的写**被判 `unsupported plan change goalType` ✗（实测原话 ✓）。
2. **goal → command 的映射**：agent 现在恒发 `apply_plan_change_proposal` ✗，而 legacy 链对
   **scope 类目标**（加/删学校）走的是 `apply_constraint_and_regenerate` + `constraintUpdate` ✓
   （见 `app/zhiyuan_agent/tools.py` 的参照调用 ✓）。P2 任务书二之二只记了前者 ✗ → 映射表要补全或裁决。

### 测试数据配方（已落纸，可复用）

建 draft 会话 ✓ → `add-extra-data` 写 `userScoreDetail`，值按 **`CreateSessionReq` 的驼峰+嵌套形状** ✓
（`province:{name,code}` / `totalScore` / `totalScorePos` / `subjectList:[{name,value,isFirst}]` /
`batch:{name,code,score}` …）→ 选科 `value` 用**标准两位码**（01 物理 / 05 化学 / 06 生物 ✓，
取自前端字典 `gaokao_volunteer_flow_config.json` ✓）→ 之后快照 `missingFacts=[]`、`stage=profile_ready` ✓。
**两个坑**：① 会话创建返回的 `userId` 必须被复用（画像按用户读 ✗，写错用户＝模型看到空画像 ✓）；
② 井号/引号别当 shell 元字符（本会话踩过两次 ✓）。

### 还差最后一寸（绿）

要跑出**成功的 apply**（真落库），会话得有**候选池/方案**（模型实测会说
`planning.get_working_plan: insufficient_data` ✗——空方案里没有可填的东西 ✓），
而 `fill_to_count` / `prioritize_within_tier` 正是 execute 认的两种目标 ✓ → 需要先跑一轮
「画像 → 候选推荐 → 生成方案」的铺垫 ✓（多回合 ✓）。这是**场景状态**的事，不是链路的事 ✓。

**③ 复跑与一条偶发**（2026-09-24 收尾）：全量两跑——第一跑 `2 failed / 1951 passed / 35 skipped`
（多出的一条是 `test_codex_harness_client.py::test_client_times_out_without_leaking_pending_request` ✗），
**第二跑恢复 `1 failed / 1952 passed / 35 skipped`** ✓；那条单跑连过 4 次（每次 2.06s ✓）。
它量的是 harness 客户端超时行为 ✓、与 P2 改动无关 ✗ → 记为**满载下的偶发时序抖动** ✓
（排查时别被它带偏：先单跑它 ✓）。

## 四之七、第八轮（2026-09-24）：又抓到一个真 bug（5 个工具全挂）；"绿"的门槛不在链路、在**数据**

### 抓到的 bug（`5f364f2`）

追模型那句 "需要录取率的调用全部返回 `backend_unavailable`" 时，先复现（进程内扫全部
工具 ✓），拿到原话：`'InternalClientBackend' object has no attribute 'current_state_version'` ✗——
该属性**只挂在另一个类**（`ReadonlyDomainTools`）上，而**适配器自己的 5 个方法**用它给信封盖版本戳 ✗：

| 修复前挂掉的 5 个工具 |
|---|
| `admission.check_eligibility` ✗ `admission.compare` ✗ `admission.get_charter` ✗ |
| `admission.get_enrollment_plan` ✗ `catalog.list_admission_units` ✗ |

**推荐路径的入口正好在其中** ✓（模型说的"录取率调用全失败" ✓）。修：适配器接住
`current_state_version`（server 构造时把权威快照版本同时给它 ✓）+ 回归断言 ✓；
工具全扫一遍后 `backend_unavailable` **归零** ✓（修复前 5 个）。

### 复现时的一个坑（记下来）

进程内探针**必须显式设 `INTERNAL_SERVICE_URL`** ✗——不设的话 `internal_client` 会落到它的
**默认地址＝生产** ✓（就是 composition 注释里警告过的那件事 ✓），于是所有调用都返回生产的 404，
看起来像"端点不存在" ✗（我一度以为 `/session/compare` 没实现 ✓，其实 Java 有、本地也有 ✓）。

### "绿"的门槛在数据不在链路 ✗

工具修好后，模型拿到了**真实后端数据** ✓（原话："浙江考区 330000、综合 `N`、第一段参考线
494 分 / 位次 184816" ✓），但它在候选推荐与方案构建两轮都**如实拒绝** ✓✓：

> "冲稳保我现在仍然给不出来…**是档位数据源不存在**…编一份出来只需要三十秒，但那是假的，我不做"
> "按 `prioritize_within_tier` 生成提案需要一个真实的候选…当前 `candidateSet.items = []`"

→ 风险档位（冲/稳/保）依赖 **系统计算的招生单元录取率** ✓，而**本地 test 数据源没有它** ✓
——这正是 P1b-2 那条结论（"该路从未产出录取率…上游算好的" ✓）从**模型侧**再现 ✓。
所以：**成功 apply 的门槛不在写闭环，在数据面** ✗；链路本身（提案→pending→claim→execute→
回写→重复确认被拒 ✓✓）第七轮已全验 ✓。模型的拒绝行为（不编数字、不拿空集包装成提案 ✓）
本身就是 P3/P2 想要的那种克制 ✓✓。

## 四之八、第九轮（2026-09-24）：**更正我自己的一条误判**——6 vs 2 不是 bug，是两条路径

第七轮我把「taxonomy 列 6 种可 apply 的 user-goal 策略、而 pending-command 链只认 2 种」
记成「Java 内部不自洽」✗。读了 `RepairProposalApplyPolicy` 之后更正：

| 路径 | 入口 | user-goal 支持的策略 |
|---|---|---|
| 直接应用（同步） | `POST /session/fix-proposals/apply` → `RepairProposalApplyPolicy.validateUserGoalProposalForApply` | **6 种**（含 `only_keep_scope` / `must_include_scope` / `exclude_scope` / `tuition_budget_scope` ✓） |
| 幂等确认链（本任务接的） | `pending-command/execute` → `PendingPlanningCommandBizService.validatePlanChangeProposal` | **2 种**（`fill_to_count` / `prioritize_within_tier` ✓，且校验规则全是这两种自己的字段 ✓） |

→ **两条路径能力不同，不是同一处代码打架** ✗✓。因此：**Java 一行没改** ✓
（没有缺陷可修；把 6 塞进链的检查反而会放行未实现的策略 ✗）。
真正剩下的是**能力缺口**（不是 bug）：新链还没实现 scope 类目标（加/删学校）的 apply ✗
——要么在链里实现它 ✓，要么这类目标走直接应用那条路 ✓（但那条**绕过确认** ✗，与 P2 的立意冲突 ✗）→ **属设计裁决** ✗。

**顺带更正**：我此前把「agent 恒发 `apply_plan_change_proposal`」记成"映射要补全"✗——
在**链**的语境里那个命令是对的 ✓（链就服务这两种目标 ✓）；要不要让链也接 scope 目标，
才是上面那条裁决 ✓。

## 四之九、第十轮（2026-09-24）：**写路径场景落地**（`8e4e3a2`）

任务书 §五 要求"写模式上来之后应当**换一条场景**去量写路径，而不是放宽 `mixed-read-write`" ✓。
落成三件：

1. **新判据** `proposal_request_goal_type`（`app/engine/semantic_eval.py`）：量的是
   `proposalRequest.goalType`。既有的 `proposal_required` 量的是 `proposalRef`（引用已有提案 ✓）
   ——写路径上新提案走 `proposalRequest`、`proposalRef` **保持空** ✗，只量它会把整条写路径漏掉；
   trace 侧同步补 `proposalGoalType`（`app/engine/turn_trace.py`）。
2. **新场景** `write-path-proposal`（`scripts/codex_semantic_smoke.py`）：快照给一个**没满**的方案
   （3 条 ✓）+ "补足到 80 个"的写意图；期望 `goalType = fill_to_count`（链支持的那两种之一 ✓）
   且 `plan_apply` 仍不许被调 ✓。**为什么给非空方案**：空方案上模型会（正确地）拒绝提案 ✗
   ——那样量到的不是写路径而是门禁 ✓（真栈上踩过这个混淆 ✓）。
3. smoke 在该场景下带上**写实例规则**（镜像 composition 在 `codex_write` 下的行为 ✓），
   否则量到的还是只读实例 ✗。

**实测（一次通过）**：`passed: True`、`failures: []`、`observed.proposalGoalType = fill_to_count` ✓；
模型正文自述"写操作在确认前不执行…提案已就绪，等你确认后由确认链执行；本轮我没有调用任何写工具，
方案状态没有任何变化" ✓。`mixed-read-write` 的期望**一个字没动** ✓。
全量：`1954 passed / 35 skipped / 1 failed`（旧账 ✓）。

## 五、下一步

1. ~~定 operationId 的落点~~ ✓ 已做完（走生产者侧：Java prepare 落进 pending.dataValue + 新端点 + agent 写模式改走它）；
2. 接线写工具面（三节堵点 2：MCP 读开关 + env 透传 + 一致性检查）；
3. ② 真栈端到端 + "重复确认"的**数据库计数**证据（要真 Java ✓）；
4. 新开一条"写路径"场景（别放宽 `mixed-read-write` ✓）；
5. 补 Java 侧 `prepareUserGoalProposal` 的单测（本轮只到"编译过 + 由 ② 覆盖"✗）；
6. ② 开跑前先**重打包重部署 Java**：本地跑的还是 2026-09-22 06:29 的 jar ✗，不含新端点 ✓
   （agent 侧已重启到新代码 ✓，health 200 ✓）。

## 四之十、第十一轮（2026-09-25）：scope 类目标接进新链（裁决 ① 落地）

**背景（真栈实测的缺口）** ✗→✓：`apply_plan_change_proposal` 的 user-goal 分支只认
`fill_to_count` / `prioritize_within_tier` 两种 ✓，而**范围类目标**（加/删学校、只看省内、
学费上限）确认后会被 40001 `unsupported plan change goalType` 拒 ✗——"最自然的写"走到确认就死。
legacy 链一直用**另一条**命令做这件事 ✓：`apply_constraint_and_regenerate` + 一个
`constraintUpdate`（`app/zhiyuan_agent/tools.py` 的参照调用 ✓）。

**落地**（`conversation_actions.py`，映射按生产者形状 ✓）：
- 目标类型 → 命令：计数/排序类走原路径 ✓（行为不变 ✓）；范围类走 constraint 那条 ✓；
- `constraintUpdate` 形状照 legacy 的 `_intent_constraint_payloads` ✓：
  每个偏好束 = `{"positive": [...], "negative": [...]}` ✓（名字级 ✓）；
  `scopeType` → 束：school/college/university→`schoolPreferences`、major→`majorPreferences`、
  province/city/area/region→`regionPreferences` ✓；`intentMode=constraint` ✓；
- 学费类走同一命令 + `min/maxTuitionPerYear`（从目标的 `context` 取 ✓）；
- **不认识的 `scopeType` → 拒绝执行**（`unmappable_goal_scope` ✓）：静默丢掉一条排除，
  用户看不见地在方案里留着他要去掉的学校——比整轮失败糟得多 ✓；
- 范围目标里什么都没有 → `goal_scope_empty` 拒绝 ✓。

**测试**（`test_conversation_actions.py` 新增 5 条 → 26 条全绿 ✓）：范围路由 ✓、三类范围各进各的束 ✓、
学费上下限 ✓、不认识的种类拒执行 ✓、**计数类行为不变的对照** ✓。全量 `1961 passed / 35 skipped / 1 failed`（旧账）✓。

**同日裁决记录**：② 档位数据**维持现状** ✓（写路径已用 `fill_to_count`＋夹具方案测通 ✓，
"成功 apply"缺的是本地 test 栈的录取率 ✗，不是链路 ✗）；③ P3 判据**接受现判据+归因说明** ✓；
④ A 型"该提案还是该反问"**维持现期望** ✓（可识别时给提案 ✓，与 #5 的收敛方向一致 ✓）。

### 第十一轮·真栈复验（2026-09-25）

拿 write 实例跑一遍 scope 目标（"把浙江大学加进我的方案" ✓ → 模型出
`must_include_scope` 提案 ✓ → 库里 pending 带 `operationId` ✓ → 确认）：

- **映射生效** ✓✓：不再出现 `40001: unsupported plan change goalType` ✗→✓——
  确认直接打到了 `apply_constraint_and_regenerate` 的路径上 ✓；
- 链路自身全程正确 ✓✓：claim ✓ → execute ✓ → 真实业务调用 ✓ → 如实报错 ✓ →
  **回写**（pending `applying` → `expired` ✓✓，不卡住 ✓）；
- **卡在数据前置** ✗：Java 回 `110: 下载志愿数据文件失败`——这条命令要读
  `session_volunteer_<会话>_temp.json`（就是普查里 `PlanConfig.file_addr_format` 指向的 OSS 文件 ✓；
  Java 侧那份配置是**活的** ✓，Python 侧同名类才是死的 ✗），而本地 test 会话没有这个文件 ✗。
  → **"成功 apply"的门槛再次落在数据面** ✓（与档位数据同源：本地 test 栈缺真实会话数据 ✓），
    链路与映射都不欠账 ✓。

模型行为也照旧合规 ✓：第一轮它先要画像、不出提案 ✓；追问一次后按指定目标出提案 ✓，
正文写明"写操作在你确认前不会执行" ✓。
