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

### 第十二轮·"110 到底缺什么"复验（2026-09-25，本地会话）

**起点**：第十一轮把"成功 apply 未跑成"记成数据前置缺口（缺志愿数据文件 ✗）。
本轮把这条**查到根**，结论要改：**那不是数据缺失，是接缝没对准** ✓。

**一、"110"的三种成因被分开（此前混成一件事）**

| 症状 | 真因 | 证据 |
|---|---|---|
| 回放脚本投递成功、后端仍 110 | 投递目录与**后端** `gaotu.temp-data-path` 不是同一个：脚本默认 `data/tmp`（对 `application-local.yml` 的 `./data/tmp` ✓），隔离栈却读 `.local/codex-local/tmp`（`codex-local-infra.sh:125` 生成 ✓） | 八月那份 `local-dialog-flow-replay-hotfix-mobile-targets-current.json` 的记录里，文件投到了 `zhiyuan-server/data/tmp/` ✓ |
| 确认回 `会话不存在` | 会话行没建（当次没传 `--ensure-session-record` ✓）；且脚本把行里的 `user_id` 写成**会话号本身** ✗，而 WS 票的归属校验要的是登录态用户（本地 token → `900001` ✓） | 复跑日志 ✓；`ConversationAccessController` 的 `session_forbidden` ✓ |
| WS 403（**新**） | C1 之后门禁是**强制**的：每次连接一张一次性票（Java 签发、Gateway 原子消费 ✓），而回放脚本写在票据之前 ✗；路径里的 `bot/test` 与票里的 bot 不符也会 4403 ✓ | `ws_chat_compat` 的路径身份校验 ✓ |

**二、志愿数据本身**：不是本地拿不到 ✓——`session_volunteer/<id>_temp.json` 在 test OSS 上**可按 key 公开 GET** ✓（session 17 → 200/772KB，含三档区间与逐条 `enroll_ratio` ✓），列目录才被拒 ✗。Java 取数顺序是**先本地后 OSS** ✓（`VolunteerBizService.java:459`），所以把真实文件按本地命名规则放进 `temp-data-path` 即可，不需要凭据 ✓。

**三、回放脚本已补齐（四处，均为缺口而非猜测）**：票（每连一张 ✓）、`--tenant/--bot/--origin`、
会话行 `user_id` 取 `--user-id` ✓、志愿目录可用 `--volunteer-data-dir`／`ZHIYUAN_VOLUNTEER_DATA_DIR` ✓
＋**投递后当场问后端一次**（看不到即 `volunteer_files_not_visible_to_backend` 停下 ✓，
不再用一轮真实回合去撞已知假失败 ✓）；另认 **`proposal.preview`** 原生卡（卡片 JSON 编在
`type=text` 的 content 里 ✗→✓，ref 取**后端快照**的 `activeProposal.proposalRef` ✓）。

**四、真栈跑完的结果**：志愿文件可见后，候选池**真的生成** ✓✓（`statusCode=ready`、
`items=1422`、档位 `{冲13,稳13,保19}`、工作方案 45 单元 ✓），模型也**真的出了提案** ✓✓
（`proposal.preview` + 库内 `pending_id`/`operation_id` ✓、`assistant_chat_session_pending_confirmation`
`status=active` ✓）。**但提案编译成 `status=blocked` + `actions=[]`** ✗：

- `blockingReasonCode = user_goal_target_not_found`（"方案和候选池里都没有找到'北京'相关选择"）✗；
- 而池子里**明明有 262 条北京** ✓、方案里 56 条非北京 ✓ —— 所以不是没数据，是**匹配不上** ✗；
- 提案请求里的范围是：`{"name":"北京","scopeType":"city","entityType":"city","resolutionStatus":"unresolved"}` ✗
  ——**没有 entityId**，而 Java 按 ID 匹配（与"名字只用于解析"的纪律一致 ✓），于是 matchesAny 全 false ✓。

**五、根因（可复现，一行命令）**：区域实体解析在**本地**模块
（`app/domain/region_entity_resolver.py`），北京是**直辖市**——它在表里是**省级**实体，
市级子项是区（海淀/朝阳/大兴）：

```
resolve_region_entity('北京','province') → 1 个候选(level=province) ✓
resolve_region_entity('北京','city')     → 0 个候选 ✗        ← 模型按"北京的学校"取 city，落空
resolve_region_entity('杭州','city')     → 1 个候选(level=city) ✓   ← 普通地级市正常
resolve_region_entity('上海'/'天津'/'重庆','city') → 0 ✗        ← 四个直辖市同型
```

**这不是数据缺席，也不是链路断裂** ✓：是"最自然的一句写请求"（只看北京的学校）**当前无法表达** ✗——
市级取不到时既不降级到省级命中 ✓、也不反问 ✓，而是带着 `unresolved` 走到 Java 被 fail-closed 挡住 ✓
（挡住是对的 ✓，静默空方案坏得多 ✓）。

**待裁决（两条，未自行选）**：① 直辖市在 `city` 级落空、`province` 级命中时，**降级并如实记层级**
（`resolved_level=province`）✗ 还是**反问用户**确认范围 ✗；② 同一处是否对所有"市级取不到但省级命中"
的输入统一处理（浙江这类省名被当 city 的情况同型 ✓）。两条都属产品语义，记在这里等裁决 ✓。

**证据边界**：链条走到"提案已编译、待确认" ✓✓；**确认→claim→execute 这一步本轮仍没走到** ✗——
它被上面那条挡住（确认一条 `blocked` + 0 action 的提案也不会改到方案 ✓）。
对照组是本轮新增的：同会话在**不放**志愿文件时 110 / **放了**之后 `ready` + 1422 条 ✓。

### 第十三轮·真栈走通 `confirm → execute`，并当场抓出两处假绿（2026-09-25，本地会话）

**结论先行**：写闭环的**机械部分第一次在真栈上完整跑通** ✓✓（确认 → claim → execute → Java 业务 → 回写），
但**本轮用例的判定是"失败"** ✓——而且不是链路失败，是"这条目标没做到" ✓。两处**假绿**是本轮自己抓的 ✗✓。

**一、跑通的三处独立证据**（会话 9741936，用例 `严格只保留临床医学`）

| 证据源 | 读数 |
|---|---|
| Java 日志 | `POST /inner/planning/1/session/pending-command/execute` 被调 ✓ |
| `assistant_planning_pending_command` | `command_type=apply_constraint_and_regenerate`、`status=succeeded`、`completedSteps=[constraint_updated, ordered_plan_regenerated]` ✓ |
| `assistant_chat_session_pending_confirmation` | 回写为 `expired` + `resolved_action=fail` ✓（不卡 `applying` ✓） |

**二、抓出的两处假绿（都是量具，不是产品）**

1. **确认帧必须是对象** ✗：compat 层只在 `isinstance(content, dict)` 时把确认转成 `ConversationAction`
   （`server.py` 的 `content.get("action")` 分支）。回放脚本以前把 content `json.dumps` 成**字符串** ✗
   → `action=None` → 整轮**退化成普通聊天**：后端日志只有 `saveMessage`、`pending` 仍是 `active`、
   **链上一次调用都没有** ✗，而模型正文照样写"本轮我把它作为明确确认提交给确认链执行" ✗。
   修：content 传 dict，并带上后端快照的 `expectedSourceVersion` ✓。
2. **判据不读 `actionResult`，且 `only_keep_*` 在空方案上真空成立** ✗：确认轮回来的是
   `conversationAction.result`，里面 `actionStatus=failed`、`actualChanges=[]`、
   `newStateVersion=null`——而正文写的是"操作已处理。"。旧判据只数"不含关键词的行数"，
   方案被清空时那条恒为 0 → **假绿** ✗（首轮实测：harness 判 `passed`（83→0），
   实际 `actionStatus=failed`、方案 45 单元 → **0 单元** ✗）。
   修：把 `actionResult.actionStatus != applied` 记为失败 ✓、`only_keep_*` 追加"结果非空"一条 ✓。
   **红-绿**：同一用例换新会话重跑 → 如实报 `failed` ✓（`action_not_applied:failed`、26 行、
   其中 53 条不含"临床医学"）——修复前是绿、修复后是红 ✓。

**三、产品侧的真实结论：这条目标**没做到**，而且是同一根源的第二次现身**

- 约束落库成 `mustIncludeMajors: ["临床医学"]`——**名字，没有 ID** ✓（与"实体未解析"一致 ✓）；
- 重生成产物 `total=0 / targetCount=45`、`safetyOk=false`（首轮）✗；重跑那轮 26 行、仍判失败 ✗
  ——**而池子里明明有 58 条含"临床医学"的候选** ✓（`statusCode=ready`、items=6142 ✓）；
- 即：**"实体未解析 → 约束只带名字 → 重生成匹配不上"**，与第十二轮"只看北京"是**同一根源**
  （那次被 `user_goal_target_not_found` 挡在编译期 ✓，这次一路执行到重生成 ✓）。
- 附一条同源观察：**同一用例两次跑出的结果不同** ✗（空方案 / 26 行）——约束由模型逐轮给出，
  非确定部分是模型侧的措辞（如是否附带 `mustExcludeMajors: ["中西医临床医学"]`）✓。

**四、一层新的不一致（值得单列）**：**Java 命令层说 `succeeded`，动作层说 `failed`**
（`actionStatus=failed` + `resolved_action=fail`）✗。命令的 `succeeded` 只代表"步骤跑完了"
（`constraint_updated` + `ordered_plan_regenerated` ✓），不代表"目标达成" ✗——
`total=0` 时它照样 succeeded ✓。**"命令成功"不能当"诉求满足"用** ✓（P2b 拆开的那两件事，
在 Java 侧又长回了同一个词）。

**五、两个根因的最终定位（都不是"没数据"，也不是"名称规则"）**

本地目录（Java inner）**是通的** ✓，问题全在**判读**上：

| 输入 | 目录返回 | 真因 |
|---|---|---|
| `临床医学` | `resultType=**multi**`，**2 个同名候选**：`774`（`100201K`，本科）/ `1406`（`520101K`，专科）✓ | 同名**不同学历层次**，请求里没带层次 → 无法唯一化 ✓ |
| `计算机科学与技术` | `exact` → `majorId=574` ✓ | 对照组：能唯一化的就正常 ✓ |
| `杭州`（city） | `exact` → `cityCode=330100000000` ✓ | 对照组 ✓ |
| `北京`（city） | `resultType=**empty**`，`data=null` ✓ | **直辖市没有 city 级实体** ✓（浙江省→province 命中是同一机制的另一面 ✓） |

即：**该唯一化时全都能唯一化** ✓；不能唯一化的两种（同名不同层次 / 直辖市取错层级）**本来应当反问** ✗，
现状却是"标 unresolved ✓ → 名字进约束 ✓ → 重生成给出空/错方案 ✗"。

**顺带记一条消息质量问题** ✗：`user_goal_target_not_found` 的正文说
"方案和候选池里都没有找到'北京'相关选择"——而池子里有 **262 条北京** ✓。
这条文案把用户指向"没有数据"，而真实原因是"这条范围没解析成实体" ✗（同第十二轮那条"看起来像缺数据"的家族）。

**边界（本轮到此为止）**：写闭环**机械链路**已在真栈全程走通并可三处独立复核 ✓✓；
**"成功 apply"仍未被构造出来** ✗——不是链路问题，而是**没有任何一条范围能在"不追问"的前提下唯一化** ✗：
能唯一化的（计算机/杭州）没试；不能唯一化的（临床医学/北京）当前一律落到"未解析" ✗。
按要求把这条记为**下一轮的入口** ✓：要么选一条能唯一化的目标（验证"改对了"），
要么先做"多候选 → 反问"（那才是这两例的正确处置）✓。

**六、一处自我更正（把推断标回推断）** ✗

上面第"三"节写的"约束**只带名字** → 重生成**匹配不上**"里，后半句**是推断、不是已验证的机制** ✗。
反证：候选侧匹配用的是 `textMatches`（**包含式**，`RepairCandidateEligibility:176`）✓——
"临床医学"与池里的"临床医学(五年)"按这条规则**应当匹配** ✓。所以"为什么重生成出来是 0 / 26 行"
这一问**本轮没有查到底** ✗：可能是 `generateOrderedPlan` 那条路径不走候选资格过滤 ✓，
也可能是档位/数量约束（`targetCount=45` 而池内符合项不足 45 → 生成不给结果）✓。
**待下一轮用 Java 侧 trace 定**（不改判据、先不改代码）✓。

**已确认的事实照旧成立** ✓：约束落库是名字无 ID ✓、命令 `succeeded` 而动作 `failed` ✓、
方案在失败轮被重生成成 0 单元 ✓、同一用例两轮结果不同 ✓ —— 这四条都有原始读数 ✓。

**七、把第六节的开口查掉了，结论要**加重**（2026-09-25 同日）** ✗✗

按第六节留的入口去读**产物本身**（会话 9751936 的重生成结果，逐条读数）：

| 读数 | 值 |
|---|---|
| `orderedPlanState` | 26 单元 / 65 条专业行，档位 `{冲13, 稳8, 保5}`、`safetyOk=true` |
| 单元内出现"临床"类专业 | **12 / 26** ✓ |
| 其余 14 个单元的专业 | 中医学、针灸推拿学、口腔医学、医学影像学、麻醉学、**中西医临床医学** …… ✗ |
| 已存约束 | `mustIncludeMajors=["临床医学"]`、**`mustExcludeMajors=["中西医临床医学"]`** ✓ |

**两条事实**（都是产物读数，不是推断）：

1. **include 没生效** ✗：`mustIncludeMajors=["临床医学"]` 下，26 个单元里有 **14 个不含任何"临床医学"** 专业；
2. **exclude 也没生效** ✗：被显式排除的"中西医临床医学"**出现在重生成后的方案里**（南昌医学院第509组）。

即第六节那个"为什么重生成出来是 0 / 26 行"的回答不是"数量约束"✗，而是
**重生成没有按刚存下的硬约束筛选** ✓。所以动作层的 `failed` 是**判对了** ✓✓
（P2b 拆开的那两件事在这里救了场：命令 `succeeded` ✗，动作 `failed` ✓，产物**违反约束** ✓）——
若只有命令层，这次会被读成成功 ✗。

**由此，"成功 apply" 的目标口径也要改** ✗：不该只是"方案条数变了"，
而是**"方案满足刚确认的约束"** ✓。本轮两轮都不满足 ✓（一轮空方案、一轮违反 include+exclude ✓）。

**证据边界**：以上全是本地可丢弃数据集上的真栈读数 ✓（会话 9741936 / 9751936）；
Java 侧"哪一步把约束丢了"仍未查（属下一轮）✗。

### 第十四轮·根因定到一行匹配器；并**更正上两节的两处归因**（2026-09-25 同日）

**先更正**（第七节里我自己写错的两处 ✗）：

1. 第七节写"**include 没生效**" ✗ → 错。约束**被执行了** ✓（`generateOrderedPlan` → `resolveEffectiveCandidates`
   → `applyConfirmedPlanRequirements` → `RepairCandidateEligibility.isEligibleForConfirmedHardConstraints` ✓
   这条链是接上的 ✓）。
2. 第七节拿 run A 的约束去解释 **run B 的产物** ✗ → 错。两轮约束不同：run A `mustExcludeMajors=["中西医临床医学"]` ✓、
   run B **exclude 为空** ✓。所以"中西医临床医学出现在方案里"**不是违规** ✗（run B 没排除它）。

**真正的根因（一行匹配器 × 粗粒度分类字段）** ✓✓

```java
// RepairCandidateEligibility.textMatches:325
return normalizedField.contains(normalizedPattern) || normalizedPattern.contains(normalizedField);   // ← 双向
// matchesMajorScope: 拿 majorName / majorCategory / majorDiscipline 三个字段去比
```

池内行的分类字段是**粗粒度**的 ✓：麻醉学 `majorCategory=临床医学类`、中医学/针灸推拿学 `中医学类`、
口腔医学 `口腔医学类`，而**每一行** `majorDiscipline=医学` ✓。于是双向子串把细粒度专业名拿去和粗粒度门类互含：

| 约束词 | 与字段的关系 | 结果 |
|---|---|---|
| `临床医学`（include） | `"临床医学".contains("医学")` = **真** | **所有"医学"门类的行都算命中** ✗（中医学/口腔医学/针灸推拿学全留下） |
| `中西医临床医学`（exclude） | `"中西医临床医学".contains("医学")` = **真** | **所有"医学"门类的行都被排除** ✗（连临床医学自己也被排掉 → 方案 0 单元） |

**同一行代码，两种相反症状** ✓✓：run A 的方案被清空（45→0）✓、run B 的方案留下 14/26 个非临床单元 ✓。

**决定性实验（可复跑）**：约束已存在状态里时**强制再生成**一次
（`POST /inner/planning/1/session/ordered-plan/generate?chatSessionId=…`，`{"forceRegenerate":true}`）
→ 产物**逐字复现**（26 单元 / 12 含临床 ✓），排除"时序/缓存"这一类解释 ✓✓。

**影响面（比"写路径"更大）** ✓：`matchesMajorScope` 同时被 **include/exclude 两条**用，
且 `mustIncludeRegions/Schools` 走的是同族匹配器（`matchesAnyText`）✓——
**用户设的"专业/地域/院校"限定条件，只要命中粗粒度分类字段就会被放大成"整个门类"** ✓。
这解释了本轮两轮失败，也可能解释更早观察到的"档位/筛选表现不对"一类现象（未查，待办）✗。

**下一轮入口（三条，按建议顺序）**：① 修匹配器语义（细粒度名 vs 粗粒度字段：字段侧只允许"字段包含名"，
或按 ID 匹配，或对 category/discipline 单列一条更严的规则）✗；② 为"多候选/直辖市"补反问 ✓；
③ 把"成功 apply"口径写进判据（满足刚确认的约束 ✓，不只看条数 ✓）。

**放大面（run A 会话 9741936 的池，6142 行）** ✓：

| 量 | 值 |
|---|---|
| `majorDiscipline='医学'` 的行 | **599** |
| `majorCategory='临床医学类'` 的行（真正的临床医学类） | **71** |
| include「临床医学」实际命中 | **599**（= 全部医学门类）→ 放大约 **8.4 倍** ✗ |
| exclude「中西医临床医学」实际命中 | **同样 599**（含那 71 行真临床医学）✗ |

两者相叠正好 **0 行存活** ✓✓ —— run A 的空方案不是"没生成"，是**被自己那条排除规则按门类全排掉了** ✓。
若只有 include（run B），则那 599 行全数有资格入选，档位/数量规则再从里面挑 26 个单元 ✓
（12 个碰巧含"临床医学"，14 个是别的医学专业 ✓）。

### 第十五轮·修匹配器 + 真栈红-绿（2026-09-25 同日）

**改动（一处，`RepairCandidateEligibility`）** ✓：`matchesMajorScope` 里
`majorName` 继续用子串（"临床医学" 必须命中 "临床医学(五年)" ✓），
但 `majorCategory` / `majorDiscipline` 改走新的 `equalsTaxonomy`——**整段相等**，不再双向子串 ✓。

**单测红-绿** ✓✓（新增 2 条到 `RepairCandidateEligibilityTest`）：
- 把 `equalsTaxonomy` 临时换回子串 → **红** ✓：`shouldNotMatchCoarseTaxonomyBySubstringWhenRequiringMajor`（中医学被判合格 ✗）、
  `shouldNotExcludeWholeDisciplineBySubstringWhenExcludingMajor`（临床医学被"中西医临床医学"排掉 ✗）——**失败形态与真栈两个症状逐字对应** ✓；
- 换回修复 → **绿** ✓（8/8）；全量 Java `799 passed / 0 failed / 6 skipped`、`BUILD SUCCESS` ✓。

**真栈红-绿** ✓✓（同一会话 9751936、同一端点、强制重生成；新代码跑在**另起的 18093 实例**上，18090 保持不动 ✓）：

| | 单元数 | 含"临床医学"的单元 |
|---|---|---|
| 旧代码（18090） | 26 | **12**（另 14 个是中医学/口腔医学/针灸推拿学/麻醉学…）✗ |
| 新代码（18093） | **12** | **12 / 12 = 100%** ✓ |

**顺带查清一条更重的（独立于本轮修复）** ✗✗：run A 的会话**在新代码上仍是 0 单元** ✓——
不是匹配器没修好，而是它的 `draftPlanState` / `workingPlanState` **已经是 0 行**（池里还有 6142 ✓）。
`generateOrderedPlan` 是**从工作方案生成有序方案**的 ✓，所以：

> **坏的一次重生成会把工作方案清空；此后任何重生成都从那个空方案出发，救不回来** ✗。

即"失败会持久化" ✓：run A 那轮不仅给用户留了个空方案 ✗，而且**没有从候选池重挑的恢复路径** ✓（本轮实测：
新代码 + 强制重生成仍为 0 ✓）。这一条与匹配器无关，属**恢复语义**，单列等裁决 ✓。

**边界（如实记）** ✗：exclude 那半只做到**单测**级红-绿 ✓；真栈上没能复跑——那需要一条
**带 exclude 的模型产出**（约束内容由模型逐轮给，不可控 ✓），而 run A 的会话已被上一条的"空方案"状态污染 ✓。
**未做**：把 18093 的新代码部署到 18090（共享服务，等裁决 ✓）、② 按 ID 匹配（需与"多候选→反问"一起做 ✓）。

### 第十六轮·恢复语义（第一半：失败回滚）落地；第二半发现"原语已存在但被孤立"（2026-09-25 同日）

**第一半——约束把方案排空 ⇒ 整条命令失败回滚** ✓✓

- 改动一处：`PendingPlanningCommandBizService` 的 `apply_constraint_and_regenerate` 分支里，
  重生成前后各读一次工作方案规模，`before>0 && after==0` 就抛
  `BusinessException(40906, "当前约束下方案里没有可保留的条目，未做任何修改（原方案 N 条）")` ✓。
  该类是 `@Transactional(rollbackFor = Exception.class)` ✓，所以**约束更新与方案变更一起回滚** ✓：
  用户看到的是"这次没改成" ✗→✓，而不是"我的方案没了" ✗。
- **单测红-绿** ✓✓（`PendingPlanningCommandBizServiceTest` 新增 2 条：拒绝 + 对照）：
  禁用守卫 → **恰好那 1 条失败**（"Expected BusinessException to be thrown, but nothing was thrown" ✓）、
  对照组照常通过 ✓；恢复守卫 → **40/40 绿** ✓；全量 Java **801 passed / 0 failed / 6 skipped / BUILD SUCCESS** ✓。
- **不追求部分成功** ✓：只筛掉一部分（12/45）仍算成功 ✓（那正是用户要的"只保留 X"），
  只有"一条不剩"才拒绝 ✓。

**第二半——"从候选池重挑"不用新造：原语已存在，但**零调用**** ✗✗

`PlanningStateService.addAutoSelectedByTier`（10754）做的事正是要的：按**档位**目标数，
从排序后的合格候选里**只追加**（跳过已选/已禁 ✓），**不动已有条目** ✓——即"补足到档位目标数" ✓。
但它在**整个 `src` 里只出现一次**（只有定义 ✓，无任何调用点 ✗），而且**不在死代码清单里** ✗。

于是 ① 的正确做法变成**接线**而不是新造 ✓：约束生效后先按约束同步（删不合规的 ✓），
再按 `requiredTierCounts`（会话里就有：`{冲13,稳13,保19}` ✓）从 `effectiveCandidates` 补足 ✓。
需注意：该方法**没有测试** ✗（既死又无测试 ✓），接线时要先给它补红-绿 ✓。

**未做（如实记）** ✗：① 真栈端到端——需要把新 jar 部署到 18090，属部署裁决 ✓（本轮只跑在临时 18093 上 ✓）；
② 手工构造 `pending-command/execute` 请求（要完整 pending + claim 前置）未做 ✓——
本轮的守卫验证停在**单测红-绿 + 全量**两级 ✓，真栈级只有匹配器那一处（第十五轮 ✓）。

### 第十七轮·"failed" 到底从哪儿来（并更正第十三轮的一处归因）（2026-09-25 同日）

**问题**：那两轮 apply 判了 `failed`——是**谁**判的、依据是什么？

**逐层读数**：

| 层 | 报了什么 | 依据 |
|---|---|---|
| 产物 | 方案不合格（run A 0 单元 / run B 26 单元里 14 个非临床） | 池内逐条比对 ✓（第十四轮已验） |
| Java 命令层 | `status=succeeded` | 只记"步骤跑完了"（`constraint_updated` + `ordered_plan_regenerated`）✗，**不判诉求是否满足** ✓ |
| 网关动作层 | `actionStatus=failed` | **不是检出违规** ✗——见下 |

**更正第十三轮的一处归因** ✗：那里我写"动作层的 `failed` 是**判对了** ✓✓（P2b 拆开的那两件事
在这里救了场）"。**错** ✗——动作层**没有**做任何满足度判断 ✓。

**真因**（`app/gateway/conversation_actions.py:71` 的 `_status`）：

```python
    if value in {"applied", "completed"}: return "applied"
    # A successful HTTP/business response alone does not prove execution.
    return "failed"          # ← 默认值
```

它只认响应里的 `status` 字段 ✗；而这条链执行那一步的响应 DTO
（`PendingPlanningCommandRes`）**根本没有 `status` 字段** ✗（字段：operationId/pendingId/commandType/
sourcePlanVersion/resultPlanVersion/replayed/completedSteps/postconditionReport/planningState ✓）。
实盘复核（会话 9751936 的命令行，utf8mb4 读出）：响应里
**没有 status ✓、postconditionReport 也是 null（序列化时被丢掉）✓**，只有 `completedSteps` ✓。

⇒ 结论：**这一类命令的 `actionStatus` 恒为 `failed`** ✗✗，与产物好坏无关 ✓
（"成功"在这条链上**根本报不出来** ✗；claim 那一步的 `applying` 是真的 ✓，因为
`PendingConfirmationRes` 有 `status` ✓）。

**影响** ✓：写闭环现在**没有可用的成败信号** ✗——既不能靠 `actionStatus` 判"落库了没有"，
也不该把它读成"失败了" ✓。要修得三选一：① 给 DTO 补 `status` ✓；
② `_status()` 读 `postconditionReport.satisfied` ✓；③ 由状态推导（方案/版本是否真变了 ✓）。
本轮**未改**（属设计裁决 ✓）；同时它解释了为什么第十三轮我只能靠"方案条数变了"来判成功 ✗。

### 第十八轮·把成败信号修好（Java 补满足度 + 网关读它）（2026-09-25 同日）

**Java 侧：给约束路补满足度报告，且不满足就回滚** ✓

- 新增 `UnifiedPlanPostconditionValidator.validateConstraintApply(commandType, state)` ✓：
  判据是"**方案里每一条都不违反已确认硬约束**" ✓，与筛选**同源**（`RepairCandidateEligibility` ✓；
  组模式按**单元**判、组内任一专业命中即可 ✓，与筛选时怎么算合格逐字一致 ✓）；
  不满足 → 抛 `40905`（沿用 plan-change 路的码 ✓）→ `@Transactional` 回滚 ✓。
- `PendingPlanningCommandBizService` 在约束分支设置该报告，并加一步 `postcondition_verified` ✓
  （与 plan-change 路一致 ✓）。**契约变化**：`completedSteps` 多一步 ✗——断言它的 2 条测试已同步 ✓。

**网关侧：`_status()` 缺 `status` 时改读满足度** ✓

- 新增 `_postcondition_satisfied()` ✓：从 `postconditionReport.satisfied` 取成败 ✓；
  分支位置在显式 `status`/`code` 判定**之后**、兜底 `failed` **之前** ✓；兜底**不变**（仍严格 ✓）。
  影响：**"applied" 第一次可达到** ✓（此前对这条命令恒为 `failed` ✗）。

**红-绿** ✓✓：Java（validator 6/6；把抛异常那行禁用 → **恰好** `shouldFailConstraintApply...` 失败 ✓、
对照通过 ✓）；Python（29 通过；把 `satisfied` 强制为 `None` → **恰好** `..._comes_from_postcondition_report`
失败 ✓、另两条对照照常通过 ✓）。

**全量** ✓：Java `803 passed / 0 failed / 6 skipped / BUILD SUCCESS` ✓；
Python `1964 passed / 35 skipped / 1 failed` ✓。那 1 条失败是**旧账** ✓：
`test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture` ✓
——它要的是 `zhiyuan-server/data/tmp/` 下的志愿夹具（该目录现在只剩 8月14 的两个 ✓），
**与今日改动无关** ✓（今天只往 `.local/codex-local/tmp/` 放过文件 ✓）。
顺带：这条测试**独立佐证了两栈的目录差异** ✓（application-local 期望 `zhiyuan-server/data/tmp` ✓）。

**未做**：`addAutoSelectedByTier` 接线（下一轮 ✓）、真栈端到端（需把新 jar 部署到 18090 ✓）。

### 第十九轮·把补足接上（`addAutoSelectedByTier` 从死代码变成能力）（2026-09-25 同日）

**改动**：`PlanningStateService` 新增

- `refillWorkingPlanByTierTargets(tenantId, chatSessionId)` ✓（公开、事务）：读状态 → 取**按约束过滤后**的
  合格候选 ✓ → 补足 → 同步单元 → 重算摘要 → 存 ✓；
- `refillWorkingPlanByTier(draft, candidates, tierTargets)` ✓（package-private，便于单测直接打 ✓）：
  只追加 ✓、**不动用户已有条目** ✓、跳过已选与已禁 ✓；档位目标数取自候选池的
  `requiredTierCounts` ✓（会话里就有：`{冲13, 稳13, 保19}` ✓），候选按**池内顺序**用 ✓（池即推荐顺序 ✓）。

**接线的顺序坑（值得单列）** ✗：必须**先同步、后补足** ✓。反过来的话，`addAutoSelectedByTier`
统计"该档位已有多少条"时会把**即将被同步删掉的条目**也算进去 ✗ → 补足量算少甚至为零 ✗。
所以命令里是两段：`generateOrderedPlan`（含同步 ✓）→ `refillWorkingPlanByTierTargets`（补足 ✓）
→ 再 `generateOrderedPlan`（把补进来的落成有序方案 ✓）。新增步骤 `working_plan_refilled` ✓
（**契约变化**：`completedSteps` 多一步 ✗，断言它的 2 条测试已同步 ✓）。

**单测红-绿** ✓✓（`PlanningStateServiceRefillTest`，新增 3 条）：补足到档位目标数 ✓、
跳过已选与已禁 ✓、没给目标就不动 ✓（对照）。把实现临时改成直接 return → **恰好那 2 条行为用例失败** ✓
（`expected: <3> but was: <1>` ✓）、对照照常通过 ✓。

**全量** ✓：Java `806 passed / 0 failed / 6 skipped / BUILD SUCCESS` ✓。

**未做（边界）** ✗：**补足的真栈效果未验** ✓——它由命令路径触发，而命令路径要完整 pending + claim 前置，
或把新 jar 部署到 18090 ✓（部署属裁决 ✓）。本轮停在单测 + 全量两级 ✓；
上一轮（第十八）的满足度报告同样是"单测 + 全量"两级 ✓，两处都记在案 ✓。

### 第二十轮·部署受阻（权限）+ 途中抓到的"空方案真空成立"（2026-09-25 同日）

**部署**：新 jar 已打好（`target/zhiyuan-server.jar`，21:05 ✓），但要换掉 18090 上跑的旧实例
必须停进程 ✓——**该动作被本会话的权限拦下了** ✗（`kill` 两次被拒 ✓）。所以：
新代码**只跑在临时 18093 实例上** ✓，18090 仍是旧代码 ✓。停/起 18090 的命令留给人执行 ✓（见台账）。

**途中抓到的（新，与写路径相邻）** ✗✗：对**空方案**，`only_keep_scope` 的编译结论是

> 「当前方案已经都在"临床医学"范围内，本轮不需要为了这个目标调整方案」`status=info` ✓

实测形状（两条只生成了候选池、**没有生成方案**的会话 9761936/9771936，新旧代码**都**这样 ✓）：
方案 0 单元 ✓ → "有没有需要移出的非匹配条目" = 没有 ✓ → 于是判"已经满足" ✓。
**一个一条志愿都没有的方案，会被判成"符合只保留 X"** ✗——用户会以为没问题 ✓。

这与本会话在**回放判据**上抓的那条（`only_keep_*` 在空方案上真空成立 ✗）是**同一类** ✓：
**"没有反例"被当成了"满足"** ✓。修法应是把"方案为空"单列一态（例如 `plan_empty` ✗ 或
沿用 `user_goal_target_not_found` ✓ 的 blocked 语义 ✓），而不是落进 info ✓。属设计裁决，未改 ✓。

### 第二十一轮·部署到 18090 + 真栈复跑抓出 `scopeType` 形状差（2026-09-25 同日）

**部署** ✓（用户指名授权后执行）：`kill 29947` → 新 jar 起在 18090 ✓（pid 4146，21:30:41 ✓）。
**如实记一处自己的失误** ✗：第一次重启用"复合命令 + `&`"拉起，java **没起来** ✓、而旧实例已停 ✗
→ **18090 断了约 1–2 分钟** ✗（21:29–21:30:41 ✓），改用后台任务方式拉起后恢复正常 ✓。教训：
**别把"停服务"和"起服务"绑在同一条后台复合命令里** ✓——停成功、起失败时没人兜底 ✓。

**真栈复跑（会话 9781936，chain 全部新代码）**：结果既好又坏 ✓✗

- **好** ✓✓：方案**没被改动** ✓（`before=83 / after=83` ✓）——今天做的守卫/回滚语义在真栈上
  **真的挡住了损害** ✓（换在昨天，这里会是一条被改坏的方案 ✗）。
- **坏** ✗：确认被 `unmappable_goal_scope` **拒执行** ✓——而这是**新抓到的真缺口** ✓：

```json
{"goalType": "only_keep_scope", "targetScopes": [
  {"rawText":"严格只保留临床医学","resolutionStatus":"pending_clarification",
   "scopeType":"major_scope", "entityType":"major", "name":"临床医学"}]}
```

网关映射表的键是 `major` ✓（**单测里手写的也是 `major` ✓**），而真载荷是 `major_scope` ✗
→ 整条确认被拒 ✓。这是典型的**测试/现实形状差** ✓：单测通、真栈不通 ✓。

**修**（`conversation_actions.py`）✓：新增 `_scope_bundle()` 归一化——先按原值 ✓、再按
**去掉 `_scope` 后缀** ✓、最后回退 `entityType`/`entity_type` ✓；都不认识**仍然拒绝** ✓
（静默丢一条范围更糟 ✓）。错误信息也改成用 `_scope_kind_label()` 取人话 ✅。

**红-绿** ✓✓：新增 3 条（真载荷形状 ✓、`entityType` 回退 ✓、**只有后缀没有 entityType** ✓）。
第三条是**真正区分**两条路径的那条 ✓——去掉后缀归一化时，**恰好它失败** ✓（另两条靠 entityType
回退仍绿 ✓，这一点本身也被如实记下 ✓）；还原后 `test_conversation_actions.py` **32/32** ✓、
全量 Python `1967 passed / 35 skipped / 1 failed（旧账 ✓）` ✓。

**边界** ✗：这条修好后**真栈仍未验**——网关是 Python、跑在 agent 进程里且 `uvicorn` **没开 `--reload`** ✓，
所以要重启 **18091** 才能验 ✓（等授权 ✓）。**连带影响**：Java 那四处改动（匹配器/守卫/满足度/补足）
虽然已经**部署到 18090** ✓，但它们**仍未被真栈验证** ✗——因为这条链在更早的一步（网关映射）就被拒了 ✓。
即 `scopeType` 这处修好之前，Java 侧的改动在真栈上都够不着 ✓。

### 第二十二轮·写闭环在真栈上**第一次走通并判成功**（2026-09-25 同日）

**部署** ✓：18090 = 新 jar ✓；18091 = agent 重启 ✓（环境从 `/proc` 原样继承 21 个变量 ✓，
含 `GATEWAY_MODE=codex_write` ✓；用 `start_new_session` 真正脱离 ✓——不再用上一轮那种失败写法 ✓）。

**真栈复跑（会话 9791936，整条链皆新代码）**：用例 `only_keep_clinical_proposal` → **`passed`** ✓✓

| 读数 | 值 | 对照（修前） |
|---|---|---|
| `actionStatus` | **`applied`** ✓✓ | 恒为 `failed` ✗ |
| `pendingConfirmation` | **`applied` / `resolved_action=complete`** ✓✓ | `expired` / `fail` ✗ |
| `planning_pending_command` | `apply_constraint_and_regenerate` / `succeeded` ✓ | 同 |
| 非临床条目 | **0**（`afterMatchCount=0`，`before=83`）✓ | 14/26 不合规 ✗ |

**独立复核（不看用例判词，直接读状态）** ✓✓：方案 **32 单元 / 37 条专业行**，
**37/37 都含"临床医学"、0 条不含** ✓；档位 `{冲17, 稳7, 保8}` ✓。

**补足在真栈上被证明了** ✓✓：同一用例此前只有 **12** 个合规单元（且是从 45 缩下来的 ✗），
现在是 **32** 个 ✓——`refillWorkingPlanByTierTargets` 按档位目标从合格候选补了进来 ✓，
这正是"只删不补"缺的那一半 ✓。

**一次性验掉的改动** ✓✓：匹配器（全部合规 ✓）、回滚守卫（本轮未触发、但上一轮真栈上已挡下损害 ✓）、
满足度报告（`applied` ✓）、补足（12→32 ✓）、网关范围映射（`major_scope` ✓）、网关状态读数（`applied` ✓）、
回写（`complete` ✓）。

**仍留的边界** ✗：① `只看北京` 类用例仍卡在**实体未解析**（直辖市无市级实体 ✓）——属下一轮的设计项 ✓；
② "空方案上 `only_keep` 判已满足"那条待裁决 ✓；③ 本轮的用例判据里 `after` 允许非空即可 ✓，
"满足刚确认的约束"这一条已由 Java 侧 postcondition 兜住 ✓（34 行那句 `satisfied` ✓）。

### 第二十三轮·② 的第一半：直辖市"问清楚"而不是"说没有数据"（2026-09-25 同日）

**把 ② 拆成两半，先做能验的那半** ✓（另一半见"未做"）：

**查清的三处形状差**（同族，都是"词表不匹配" ✗）：

| 位置 | 单测/代码认的 | 真载荷给的 |
|---|---|---|
| 网关范围束 | `major` ✓ | `major_scope` ✗（**上一轮已修** ✓） |
| Java 澄清判据 | `unknown/multiple_match/needs_clarification/ambiguous` ✓ | `unresolved` ✗、`pending_clarification` ✗ |
| 省略（`matchesRegion`） | — | 市级 scope **只看 `cityName`** ✗，而北京候选的 `cityName` 是"海淀/朝阳/大兴" ✓ |

**落地**（`UserGoalProposalBuilder.ScopeMatcher.needsClarification`）✓：加入 `unresolved` ✓——
"压根没映射上"就该问清楚 ✓。效果：`只看北京的学校` 的结论从
「方案和候选池里暂时都没有找到"北京"相关选择」✗（把用户指向"没有数据" ✗）
变成「"北京"还没有对应到明确范围，需要先确认后再生成调整预览」✓✓（`user_goal_entity_needs_clarification` ✓）。

**刻意不做的**（并把理由写进代码注释 ✓）：**不**把 `pending_clarification` 也当成"该反问" ✗——
它是"有歧义但名字可用"（"临床医学" 本科/专科同名 ✓），**名字级匹配仍成立** ✓，
正是带着这个状态，`只保留临床医学` 在真栈上刚走通并判 `applied` ✓（会话 9791936 ✓）。
把它也算进来会让那条路退回反问 ✗。

**红-绿** ✓✓：新增 2 条（问清楚 ✓、**回归护栏**：`pending_clarification` 不退回反问 ✓）。
去掉 `unresolved` → **恰好**第一条失败 ✓（失败信息就是"应当问清楚" ✓）、护栏通过 ✓；
还原后 `UserGoalProposalBuilderTest` **68/68** ✓、全量 Java `808 passed / 0 failed / 6 skipped` ✓✓。

**未做（如实记）** ✗：② 的另一半"**按 ID 匹配**"没做 ✓——理由：区域/专业的名字级匹配**现在是通的** ✓
（临床那条已验证 ✓），改按 ID 需要在**约束下发**那一层把解析出的 ID 带下去 ✓，
属契约级改动 ✓；本轮不动它 ✓。
**真栈未验** ✗：这条是 Java 改动，要重新部署 18090 才能看 ✓（等授权 ✓）。

### 第二十四轮·② 的真栈红-绿：直辖市从"说没有数据"变成"问清楚"（2026-09-25 同日）

**对照方式**（不动 18090 的部署 ✓）：新 jar 起在临时 **18093** ✓，18090 上是**上一版** jar ✓
（不含本轮的 `unresolved` ✓）→ 同一请求、同源夹具（session 2947 的志愿文件 4.7MB ✓）两条会话各打一次 ✓。

**请求**（照真载荷逐字 ✓，会话 9822947 / 9812947）：

```json
{"goalType":"only_keep_scope","targetScopes":[{"rawText":"只看北京的学校",
  "resolutionStatus":"unresolved","scopeType":"city","entityType":"city",
  "name":"北京","scopeLevel":"city","normalizedName":"北京"}]}
```

**结果** ✓✓（修后，18093）：

| | 值 |
|---|---|
| `status` | `blocked` ✓ |
| `blockingReasonCodes` | **`["user_goal_entity_needs_clarification"]`** ✓✓ |
| 正文 | 「**"北京"还没有对应到明确范围，需要先确认后再生成调整预览**」✓✓ |

**修前**（18090，上一版 jar）的读数已在第十三/十四轮留档 ✓：
`user_goal_target_not_found` + 「方案和候选池里暂时都没有找到"北京"相关选择」✗
——同一件事，一个说"**请你确认范围**" ✓、一个说"**没有数据**" ✗（而池里当时有 262 条北京 ✓）。

**落地的语义边界（重要）** ✗✓：这**不是**让"只看北京"变得能直接执行 ✓——它仍然会被拦 ✓，
但拦的理由**从"没有数据"改成"范围没定清楚"** ✓，用户可以答一句（"按省份" ✓）然后把路走通 ✓。
把直辖市按省级**静默降级**是另一条路 ✗，本轮**没走** ✓（那要改的是匹配语义 ✗，属设计裁决 ✓）。

**边界** ✗：② 的另一半"按 ID 匹配"仍未做 ✓（理由见第二十三轮 ✓）；
`pending_clarification`（多候选）**维持按名字匹配** ✓——它是 clinical 那条已验通路的前提 ✓。

### 第二十五轮·按用户裁决改回：北京**自动定级**、不反问（2026-09-25 同日）

**裁决**（用户原话）："北京 这个不用澄清吧(意图很明确) 肯定需要系统自动解决" ✓。

**落地三处** ✓：

1. `ScopeMatcher.matchesRegion`：**层级是提示、不是硬约束** ✓——`city` 级的值在
   `cityName` 不中时兜底比 `provinceName` ✓（`province` 级同理兜底 `cityName` ✓）。
   安全性：真市名（"杭州"）在另一级无从同名 ✓，匹配结果不变 ✓；只有"值其实是另一级名字"时才多中 ✓，
   而那正是要修的形态 ✓。
2. **反问收窄**：从"看状态词"改成"**看结果**" ✓——新增 `isUnresolvedRegionScope()` ✓，
   只在**算完匹配、一条都没中**时才落 `user_goal_entity_needs_clarification` ✓
   （判据是结果而非状态词：状态词各说各的 ✗，上一轮已被现实打脸两次 ✓）。
3. **撤销**上一轮"把 `unresolved` 塞进 `needsClarification()`"那条 ✗——它会在匹配**之前**就把
   "只看北京"拦成反问 ✓，与本次裁决直接冲突 ✓。

**红-绿** ✓✓（`UserGoalProposalBuilderTest`，69/69 ✓）：
- `shouldResolveMunicipalityScopeWithoutAskingBack` ✓——北京（city 级 ✗、直辖市 ✓）**出提案** ✓，
  且动作里**移出天津那条** ✓（只保留北京 ✓）；去掉层级兜底 → **恰好**这条失败 ✓
  （失败信息正是"北京意图明确，不该反问" ✗→✓）；
- `shouldAskForClarificationWhenRegionScopeMatchesNothingAtAnyLevel` ✓（"银河系" ✓ → `blocked` +
  `user_goal_entity_needs_clarification` ✓：谁也对不上时，指向"范围需要先确认"而不是"没有数据" ✓）。
- 全量 Java **`809 passed / 0 failed / 6 skipped`** ✓✓。

**同轮事故（我的）** ✗：22:42 重新打包时**覆盖了正在运行的 18090 所加载的 jar** ✓ →
JVM 懒加载失败并被缓存 ✓（日志：`NoClassDefFoundError: ch/qos/logback/classic/spi/ThrowableProxy` ✓）→
该实例**错误路径一碰就崩** ✗（我的探针 20s 超时就是这么来的 ✓）。**必须重启**才能恢复干净状态 ✓——
正好与"把本次北京的改动一起上线"合并成一次 ✓（等授权 ✓）。教训：**给运行中的服务换 jar 要重启，不是热替换** ✗。

**未做**：按 ID 匹配（契约级改动 ✓，见下条问答 ✓）。

### 第二十六轮·"只看北京"端到端走通（2026-09-25 同日）

**部署** ✓：18090 重启到含北京改动的 jar（pid 28860 ✓、健康检查 200 ✓）。
**注意**：这一轮的重启一并修掉了上一轮我自己造成的类加载失败 ✗→✓（换 jar 必须重启 ✓）。

**真栈复跑（会话 9832947，源 2947 夹具）**：用例 `only_keep_beijing_proposal` → **`passed`** ✓✓

| 读数 | 值 |
|---|---|
| `actionStatus` | **`applied`** ✓ |
| 用例判据 | `beforeMatchCount=56` → **`afterMatchCount=0`** ✓ |
| **独立复核**（直接读状态 ✓） | 方案 **23 单元，省份分布 = 北京 23/23** ✓✓（档位 `{冲5, 稳2, 保16}` ✓） |

**这条用例的完整变化史**（同一句话"只看北京的学校"）：

| 阶段 | 结果 |
|---|---|
| 八月（旧链） | `pending_not_applied:expired` ✗、方案纹丝不动 ✗ |
| 9-25 修前 | `user_goal_target_not_found` ✗——"方案和候选池里都没有找到'北京'相关选择" ✗（池里有 **262** 条北京 ✗） |
| 本轮 | **`applied`** ✓、方案 **23 条全部北京** ✓✓ |

**边界** ✗：23/45（目标 45 ✓）——合格候选就这么多 ✓（北京 + 该夹具的分数带 ✓），
**不是**被拦 ✓；若要更多，属候选池/分数带的事 ✓，与约束链路无关 ✓。

### 第二十七轮·"区域按 ID"：先把**身份**落成规范化相等（2026-09-25 同日）

**先说清 ID 在哪** ✓✓：**源头就有**，是**装载时被丢掉的** ✗——
志愿文件里是 `area={"data":"新疆","key":"650000"}`、`city={"data":"阿克苏","key":"652900000000"}` ✓，
而 `CandidateItemDTO` 只有 `provinceName`/`cityName` **两个名字字段** ✗（没有 ID ✓）。

**本轮交付（能立刻验证的那半）** ✓：

- 新增 `RegionScopeSupport.sameRegionName()` ✓——去"省/市/自治区/特别行政区"后缀 ✓、去空格 ✓、
  小写后**相等** ✓，即"同一个身份" ✓；"北京市"＝"北京" ✓、"内蒙古自治区"＝"内蒙古" ✓。
- **两层同时换** ✓（这是关键 ✗→✓）：提案编译的 `ScopeMatcher.matchesRegion` ✓ 与
  约束过滤的 `RepairCandidateEligibility.matchesAnyRegionScope` ✓ 用**同一条判据** ✓——
  否则会出现"编译时匹配上、过滤时匹配不上"的自相矛盾 ✗。
- 区域路径**不再用双向子串** ✗（"医学"⊂"临床医学"那类放大，在区域这条路上也从根上去掉了 ✓）；
  层级**仍是提示** ✓（保留上一轮的兜底 ✓）。
- 测试 ✓：新增"**省名后缀形态必须命中**" ✓（这是收紧的**风险侧** ✗→✓：相等比子串严，容易把该中的丢掉 ✗）；
  北京（直辖市 ✓）、银河系（谁也对不上 ✓）两条沿用 ✓。全量 Java **`810 passed / 0 failed / 6 skipped`** ✓✓。

**未做，且要一个契约决定** ✗：真·ID 匹配需要三件——
① 把 `areaId`/`cityCode` 从源数据**装上候选** ✓（加字段 + 装载点，additive ✓）；
② **约束里带 ID** ✗——现在 `mustIncludeRegions` 是 `List<String>` 的**名字** ✓，带 ID 要么加并列字段 ✓、
   要么换形状 ✓（**这是契约决定**，我不擅自定 ✓）；
③ 网关用 `catalog_lookup_province/city` 把名字解析成 ID ✓（客户端方法已在 ✓）。
**注意** ②③ 做完才有效果 ✓：只做解析、候选没有 ID，匹配仍旧只能靠名字 ✓（所以本轮没白做，但也没做完 ✓）。

**边界** ✗：本轮改动**真栈未验** ✓（要再部署一次 18090 ✓）；上一轮验过的"只看北京 → applied + 23/23 北京"
不受本轮影响 ✓（同一条路 ✓），但**回归**要在部署后一并复跑 ✓。

### 第二十八轮·"规范化身份"上线 + 两条端到端回归（2026-09-25 同日）

**部署** ✓：新 jar 上线（pid 4476 ✓、健康检查 200 ✓）。

**回归（两条用例同跑，会话 9841936 / 9842947）** ✓✓ 两条 `passed`：

| 用例 | `actionStatus` | 独立复核（直接读状态 ✓） |
|---|---|---|
| `only_keep_clinical_proposal` | **`applied`** ✓ | 32 单元，**37/37 行含"临床医学"、0 条不含** ✓（档位 `{冲17,稳7,保8}`）|
| `only_keep_beijing_proposal` | **`applied`** ✓ | 23 单元，**省份分布 北京 23/23** ✓（档位 `{冲5,稳2,保16}`）|

⇒ **规范化身份没有丢掉任何该中的** ✓（这正是本轮改动的风险侧 ✗→✓：相等比子串严 ✓），
两条主路径都仍然走通 ✓✓。

**"区域按 ID"的可派发清单**（本轮**未做**，属契约级切片 ✓，等评审 ✓）：

| # | 层 | 文件（相对 zhiyuan-server 或 zhiyuan-agent） | 改动 |
|---|---|---|---|
| 1 | 推荐响应 | `model/dto/volunteer/VolunteerRecommendListResponse`（`VolunteerSchool`） | +`province_id`/`city_id` 两个字段 ✓ |
| 2 | 响应构建 | `service/biz/VolunteerResponseBuilder` | 把**群组已有的** ID 写进去 ✓（`VolunteerDataTransformService:70-75` 早就保住了 ID ✓） |
| 3 | 候选 DTO | `model/dto/planning/CandidateItemDTO` | +`provinceId`/`cityId` ✓ |
| 4 | 池装载 | 推荐响应 → 候选池那一步 | 抄两个字段 ✓ |
| 5 | 约束 DTO | `HardConstraintsDTO` | +`mustIncludeRegionIds`/`mustExcludeRegionIds` ✓（**方案 (a)**：并列字段 ✓，名字保留 ✓） |
| 6 | 约束映射 | `updateConstraintState` / `updateConstraintState` 的 req | 把新键映进去 ✓ |
| 7 | 匹配器 | `RepairCandidateEligibility` + `UserGoalProposalBuilder.ScopeMatcher` | **ID 优先、名字兜底** ✓（两侧同一条判据 ✓） |
| 8 | 网关 | `app/gateway/conversation_actions.py` | 用 `catalog_lookup_province/city` 把名字解析成 ID ✓，随 `constraintUpdate` 下发 ✓ |
| 9 | 测试 | 每层各自 | 红-绿 + 对照 ✓（ID 命中 ✓、ID 缺失回退名字 ✓、ID 与名字冲突时以 ID 为准 ✓） |

**为什么不半截铺** ✗：1–4 铺完、5–8 未铺时，候选与约束**任何一边都不带 ID** ✓，
匹配只能照旧按名字 ✓——**没有任何可观察的差别** ✗，只留下几处没人用的字段 ✗。
所以这份清单整片做或不做 ✓，不做半截 ✓。

### 第二十九轮·ID 数据路径：四层改完，但**真栈验证没进池**（2026-09-25 同日）

**已改（四层，编译与全量绿 ✓✓）**：
1. `VolunteerRecommendListResponse.VolunteerSchool` +`province_id`/`city_id` ✓；
2. `VolunteerRecommendBuilder`（group → response 那两行）从群组写 ID ✓（群组早就带着 ✓）；
3. `CandidateItemDTO` +`provinceId`/`cityId` ✓；
4. `PlanningStateService.fillSchoolFields` 抄两个字段 ✓。
全量 Java **`810 passed / 0 failed / 6 skipped`** ✓✓。

**真栈验证：失败** ✗。会话 9851936（源 1936 ✓）生成候选池后，**6236 条里带区域 ID 的 = 0** ✓。
**已排除的一支** ✓：该会话的 `tmp` 目录里**只有原始文件**（`session_volunteer_9851936.json` ✓，
里面 `area.key`/`city.key` 齐全 ✓）、**没有 temp 快照** ✗ → 不是"读了一份没有 ID 的旧快照" ✓。

**下一手第一件事（已定位到门口 ✓）** ✗：`recommendVolunteerList` 走的是
`doRecommendVolunteerList(...)` ✓（**重新推荐**），而本轮改的是 `VolunteerRecommendBuilder`
里"群组 → 响应"那条 ✓——**要确认这两条是不是同一条** ✓。若不是（很可能 ✗），
响应实际由上游 `queryProgramByLimitNum` 的 `ProgramPageDTO.SchoolDetail` 那条拼 ✓，
那就要在**那条**上补 `area.key`/`city.key` ✓（`SchoolDetail` 里也带 `area`/`city` 对象 ✓，
`VolunteerDataTransformService:70-75` 读的就是它 ✓）。**查清这条再改，别再加一层** ✓。

**两次重启事故（都是我的）** ✗✗：① 把"停 + 起"绑在一条后台复合命令里 → 停成功、起失败、服务断了 1–2 分钟 ✗；
② 换 jar 时**没等端口真正释放**就起新的 → `BindException: 地址已在使用` ✗ → 新旧一起掉、
又断约 2 分钟 ✗。**已固化的做法** ✓：停 → **等端口不再监听** → 起 → **验证监听与健康检查** → 才宣布成功 ✓
（本轮最后一次就是按这个来的 ✓）。共享服务两次中断都要记在案 ✗。

### 第三十轮·**更正第二十九轮**：ID 数据路径其实是**通的**（2026-09-25 同日）

**探针结果** ✓✓（临时 `log.info` 打在 `buildVolunteerSchoolFromDetail` ✓，跑一次建池 ✓）：

```
ID probe: school=西安交通工程学院第503组 province=陕西/610000 city=西安/610100000000
（1288 行，全部有值 ✓）
```

**池里** ✓✓：重新生成后 **6128 / 6128 条都带** `provinceId`/`cityId` ✓
（`山东/370000`、`济南/370100000000` ✓）。

**因此第二十九轮的结论要更正** ✗：
- 那条"6236 条里 0 条带 ID"**是量错了对象** ✗——那个池由 **23:37** 时**正在被替换的旧实例**生成 ✓
  （新实例 23:38 才起 ✓），我量到的是**旧代码的产物** ✓。**教训**：验证"新代码的产物"之前，
  先确认**产出它的进程**是哪一个 ✓（同类错误今天第二次 ✗：第一次是把"停+起"绑一起 ✗）。
- 另一处误判 ✗：**第一次探针 0 行 ≠ "没走这条路"** ✗——那次重生成其实**失败了** ✓
  （`404 用户分数信息不存在` ✓：我手插的探针会话**只写了会话行和志愿文件** ✓，
  没写分数/画像 ✗——那是 harness 的活 ✓）。**教训**：探针为 0 时先证"那一步真的执行过" ✓。

**收尾** ✓：探针已删 ✓；按固化顺序（停 → 等端口释放 → 构建 → 起 → 验证监听与健康 ✓）干净重部署 ✓
（pid 23859 ✓、健康 200 ✓、**本轮无中断** ✓）。

**ID 切片进度** ✓：数据路径四层（响应 → 构建器 → 候选 DTO → 池装载 ✓）**已完成并真栈验证** ✓✓；
剩 **5–7（约束带 ID + 匹配 ID 优先 ✓）与 8（网关解析 ✓）** ✗——属风险较高的一半 ✓：
要在"已确认约束"的合并/去重规则（hard/soft 两条分支 ✓）里穿一条**并列的 ID 列表** ✓，
错一步就是**静默筛错** ✗，所以每步都要红-绿 ✓。

### 第三十一轮·"区域按 ID"落地：**匹配层完成，单元携带未完成**（2026-09-26 凌晨）

**已做且已验证** ✓✓：

| 层 | 状态 | 证据 |
|---|---|---|
| 网关解析 + 下发 | **完成** ✓ | 约束里出现 `mustIncludeRegionIds: ["110000"]` ✓（"北京"按目录是省级 ✓）|
| 候选池携带 | **完成** ✓ | 池 **1454 / 1454 条**都带 `provinceId` ✓ |
| Java 约束结构 | **完成** ✓ | `HardConstraintsDTO` + 并列 ID 列表 ✓、`mergeRegionIdGroup` 与名字**同规矩**（去重/互斥 ✓）|
| **匹配（ID 优先、名字兜底）** | **完成** ✓✓ | 红-绿：ID 命中 ✓、**冲突时以 ID 为准** ✓、缺 ID 回退名字 ✓；两侧判据一致 ✓ |
| 写闭环回归 | **未破坏** ✓ | 北京 23/23、`applied` ✓（同前 ✓）|

**全量**：Java **813 passed / 0 failed / 6 skipped** ✓✓；Python **1969 / 35 skipped / 1 failed（旧账）** ✓。

**未完成** ✗：**计划单元**（`orderedPlanState.units[].provinceId`）**仍是 null** ✗——
组模式的匹配对象是**单元** ✓，所以那一层目前**回退到名字** ✓（行为正确 ✓、无回归 ✓，
但"ID 优先"在组模式上**没被激活** ✗）。为它我补了 **6+ 处**"单元 ← 候选"的拷贝点 ✗
（`UserGoalProposalBuilder` / `fillOrderedUnitGroupFieldsFromInitialUnit` / `PlanningStateService:4107,:10977` /
`CanonicalPlanningRuntime` / `PriorityRuleSupport` / `RepairCandidateEligibility` / 后验校验器 ✓），
**仍未命中真正那条路** ✗。**我停止继续猜** ✓——下一步应当是**一支探针** ✓：
在 `fillOrderedUnitGroupFieldsFromInitialUnit` 与 `buildOrderedUnitsFromOrderedItems` 各打一行 ✓，
看这条会话的 ordered unit 到底由哪条路产生 ✓（今天已经证明"探针比读代码快" ✓✓）。

**本轮的三处自己的失误（记档）** ✗：
1. **量具缺 force** ✓：harness 调 `candidate-pool/generate` 时没带 `forceRegenerate` ✗ → 沿用了 asset 里
   **六月预置的旧池** ✗（只有名字 ✓）→ 于是我一度以为"ID 没进池" ✗。**已修** ✓（harness 现在强制重算 ✓）。
2. **`--user-id` 打错** ✗（9909001 vs 900001 ✓）→ 回合被身份校验挡住 ✓、白跑一轮 ✓。
3. 反复"补点"而非先探针 ✗（本轮改了 6+ 处拷贝点才承认该装探针 ✓）。

### 第三十二轮·探针定位到方法名；单元携带停手（2026-09-26 上午）

**探针读数** ✓✓（三处打点，跑一次建池+方案 ✓）：

| 探针 | 次数 | 结论 |
|---|---|---|
| `fillFromInitialUnit` | **132** | 全部 `initialProvinceId=null` ✗——**初始单元就没 ID** ✓ |
| `PlanningStateService:4107`（我先前补的那处） | **0** ✗ | 初始单元**不由它建** ✓（补错了地方 ✗）|
| `buildOrderedUnitsFromOrderedItems` | 5 | 有序单元由初始单元派生 ✓ |

**并且** ✓：用 `forceRegenerate + overwriteExistingDraft` 强制重建初始方案后 ✗，
那 45 个初始单元**一模一样、仍然没有 ID** ✗ → **这条路既不是 4107、也不吃"强制重建"** ✗
（初始推荐存在**缓存/短路**，值得单独记一笔 ✓）。

**收窄后的下一步（方法名已定 ✓，约 5 分钟）**：探
`PlanningStateService.buildInitialRecommendationState(state)` ✓——它就是
`initialRecommendationState` 的构建点 ✓（`generateInitialPlan` 里那句
`state.setInitialRecommendationState(buildInitialRecommendationState(state))` ✓）。
探它就能看到初始单元到底从哪个对象抄字段 ✓（以及为什么抄不到 ID ✗）。

**我停手的理由（记档）** ✓：连续三处自己的笔误（`--volunteer-data-dir` 打错 ✗、
`--user-id` 打错 ✗、以及反复"补点"而非先探针 ✗）——**笔误密度上升是本该停的信号** ✓，
继续在长上下文里改同一块代码，风险高于收益 ✓。探针已清 ✓、按固化顺序干净重部署 ✓
（pid 7352 ✓、健康 200 ✓、无中断 ✓）。

**"区域按 ID"的最终状态** ✓：
- **匹配层完成并验证** ✓✓：约束带 `mustIncludeRegionIds` ✓、池 1454/1454 带 ID ✓、
  ID 优先 / 冲突以 ID 为准 / 缺 ID 回退名字（三层红-绿 ✓）；
- **单元携带未完成** ✗：组模式的匹配对象是单元 ✓ → 那一层**仍走名字兜底** ✓
  （行为正确 ✓、无回归 ✓，但"ID 优先"在组模式**未激活** ✗）；
- 写闭环回归 ✓：北京 23/23 或 11/11、`applied` ✓（各轮均通过 ✓）。

### 第三十三轮·第三十二轮那个"补错了地方"**不成立**：根因是 clone 漏抄 ID（2026-09-26 上午）

**一行代码就能定位** ✓✓：`PlanningStateService.java` 里 `new PlanningUnitDTO()` **只有一处** ✓
（4102 `buildPlanningUnit` ✓）——所以初始单元**只能**由它建 ✓，第三十二轮"不由它建 ✗"的结论站不住 ✗。
它当时补的 4110 那行 `unit.setProvinceId(representative.getProvinceId())` **本身没错** ✓，
错在**输入**：`representative` 是克隆来的 ✗，而克隆漏抄了 ID ✗。

**根因（两个漏抄点，都在 `PlanningStateService.java`）**：

| 漏抄点 | 方法 | 后果 |
|---|---|---|
| 8236 抄了 `provinceName`/`cityName` ✗、**没抄 `provinceId`/`cityId`** ✗（同 DTO 里其他 7 个 ID 字段都抄了 ✓） | `cloneCandidateItem` | 三处调用全中 ✗：**7988 覆盖合并**（生产主路径 ✓✗）、**4225 单元代表**（初始单元无 ID 的直接来因 ✓）、8305 身份归一 |
| 4189 同样是名字抄了 ✗、ID 没抄 ✗ | `toPlanningUnitRepresentativeCandidate`（单元 → 代表候选） | 组模式"单元回代成候选"那一层仍按名字 ✓ |

**链路（修前 vs 修后）**：

```
响应 → 候选（fillSchoolFields 8330 带 ID ✓）→ clone ✗✗【丢 ID】→ 单元代表（4225）
     → buildPlanningUnit 4110（补对了 ✓ 但输入为 null ✗）→ 初始单元 provinceId=null ✗
     → 匹配层 regionRequired（108：两边都有 ID 才 ID 优先 ✓）
     → candidateHasIds=false ✗ → 回退名字兜底 ✓
```

**为什么 4107 探针是 0 次** ✓：与报告自己记的"初始推荐有**缓存/短路**"一致 ✓——
那次运行里初始状态是**既有**的（持久化读回 ✓），根本没重新构建 ✓。所以这一层
**必须用新会话 / 强制重建**才能看到效果 ✗（第三十二轮已验：`forceRegenerate` 对它无效 ✗）。

**红-绿（新增 `PlanningStateServiceRegionIdCarryTest`，3 条 ✓）**：

| 测试 | 修前 | 修后 |
|---|---|---|
| 候选 → 组模式单元（`groupCandidatesToPlanningUnits`） | `expected: <110000> but was: <null>` ✗ | ✓ |
| 候选 → 覆盖合并（`mergeOverlayIntoCandidates`，生产主路径 ✓） | `null` ✗ | ✓ |
| 单元 → 代表候选（`toPlanningUnitRepresentativeCandidate`） | `null` ✗ | ✓ |

**全量** ✓：Java **816 passed / 0 failed / 6 skipped** ✓（813 + 新增 3 ✓，无回归 ✓）。
Python 未动 ✓。

**真栈红-绿** ✓✓（重建 18090 + **新会话** ✓；用例 `only_keep_beijing_proposal` ✓）：

| 读数（新会话，池均为 1454 条 ✓） | 修前（旧代码，9962947） | 修后（新代码，9972947） |
|---|---|---|
| 候选池带 `provinceId` | **1454 / 1454** ✓ | 1454 / 1454 ✓ |
| **初始单元**带 `provinceId` | **0 / 45** ✗ | **45 / 45** ✓✓ |
| **有序单元**带 `provinceId` | **0 / 11** ✗ | **11 / 11** ✓✓ |
| 单元样例（`44020261001761` 北师大专业组215） | `provinceId=null` ✗ | `provinceId=110000` / `cityId=110108000000` ✓ |
| 端到端 | `passed` ✓（119 → 0 ✓） | `passed` ✓（119 → 0 ✓，无回归 ✓） |

**"ID 优先"激活的**直接**证据** ✓✓（不只是"带了 ID"✓）：

| | 约束 `mustIncludeRegionIds` | 有序单元 `provinceId` 集合 | 两侧都有 ID 的分支 |
|---|---|---|---|
| 修前 9962947 | `["110000"]` ✓ | **`[]`** ✗ | **不可达** ✗（`candidateHasIds=false` → 名字兜底 ✓） |
| 修后 9972947 | `["110000"]` ✓ | **`["110000"]`** ✓ | **可达** ✓✓（相交 ✓） |

**市级词汇表已核对同源** ✓：网关目录 `cityCode` 就是 12 位（"杭州"→`330100000000` ✓），
与单元 `cityId`（`110108000000` ✓）同格式 ✓——所以"ID 优先"不会因为格式差把合规单元**误判掉** ✗
（市级只在单测级见过 ✓，真栈只跑了省级 ✓）。

**部署**：按固化五步 ✓（停 7352 ✓ → 轮询到端口释放 ✓ → **停后**构建 ✓ → python 包装器起（env 原样 ✓、
`start_new_session` ✓）→ 验监听 + 业务读 200 ✓）。新 pid **19888** ✓，`/tmp/backend-18090.log` ✓。
**共享栈停机约 2 分钟**（08:30 前后 –08:31:58 ✗，含构建 ✓；已获**指名授权** ✓、一次成功无中断 ✓）。

**待续 ① 完结** ✓：代码层 ✓ + 单测红-绿 ✓ + **真栈红-绿** ✓✓。

### 第三十四轮·"专业按 ID"（同套路，区域先行）——**功能通 ✓、ID 路径未激活** ✗（2026-09-26 上午）

**做完了什么** ✓：

| 层 | 改动 | 证据 |
|---|---|---|
| 目录/网关 | `_resolve_major_scope_ids` ✓（只认 `exact` ✓、带会话学历层次去歧义 ✓）；`majorPreferenceIds` 与名字**同序、同正负** ✓ | Python 新增 4 条 ✓（3 条先红 `KeyError: 'majorPreferenceIds'` ✓ 后绿 ✓）|
| Java 约束 | `HardConstraintsDTO.mustInclude{Major,Exclude}Ids` ✓；合并复用 `mergeHardIdGroup` ✓（由 `mergeRegionIdGroup` 更名 ✓，区域/专业同一实现 ✓）| `PlanningStateServiceHardConstraintIdMergeTest` 3 条 ✓（区域那条此前**无单测** ✗，一并补上 ✓）|
| Java 匹配 | 候选侧 ✓ + **单元侧** ✓ 都"ID 优先、名字兜底" ✓ | `RepairCandidateEligibilityTest` +5 条 ✓（ID 命中 ✓ / 冲突以 ID 为准 ✓ / 缺 ID 回退名字 ✓ / 排除侧 ID 命中即排 ✓ / 单元侧 ✓）|

**顺带修掉一个真缺陷** ✗→✓：`confirmedHardConstraints` 判"有没有约束"时**只看名字列表** ✗——
**只带 ID 的约束会被读成"无约束"** ✗（单测红时抓到的 ✓）。已把两个 ID 列表纳入 ✓。

**词汇表真栈核对** ✓（这是"ID 优先"安不安全的**前提** ✓）：池里真 `majorId`（1008 条 ✓）与目录
`/catalog/lookup/major` **同一套** ✓（临床医学 `774` ✓、低空技术与工程 `15223549801738240` ✓）；
**446 条 `"0"`** ＝大类/试验班 ✗（没有单一专业身份 ✓）→ 按"缺 ID"处理 ✓、回退名字 ✓、**不判死** ✗✓。

**真栈·功能** ✓：资产池跑 `only_keep_clinical_proposal` ✓ → **passed** ✓（83 → **0** ✓），
方案 **30/30 全含"临床医学"** ✓、无残留 ✓、非空 ✓。

**真栈·ID 路径（先 ✗ 后 ✓）**：
- **第一遍 ✗**：约束里只有名字 ✓、**`mustIncludeMajorIds` 为空** ✗。原因定位 ✓：网关在**确认那一刻**
  拿到的快照里没有 `scoreContext` ✗ → 学历层次缺失 ✗ → 目录对"临床医学"返回 `multi` ✗
  → **安全阀按设计不取 ID** ✓（只发名字 ✓、行为正确 ✓、无回归 ✓）。
- **根因** ✓：`build_snapshot` 把 `score_context` **从 `studentSummary` 现推** ✗，
  而真载荷的 `studentSummary` **没有 `batch`** ✗✓——`turn-snapshot` 明明已经算好了
  `scoreContext`（含 `batch`/`batchScore`/`strengthSubjects` ✓）却没被用 ✗。
- **接通** ✓：投影改为**派生值优先、只补缺** ✓（空值也算缺 ✓；别名 `strengthSubjects`→`subjects` ✓，
  否则真载荷的选科会整个丢掉 ✗）。红-绿 ✓：`KeyError: 'batch'` → 绿 ✓；Python 全量
  **1975 / 59 skipped / 1 failed（旧账 ✓）** ✓。
- **真栈复验** ✓✓（只重启 agent，Java 未动 ✓）：约束 **`mustIncludeMajorIds=['774']`** ✓、
  案子 **passed** ✓（83 → 0 ✓）、方案 **30/30 全"临床医学"** ✓ 0 残留 ✓、
  单元携带 `majorId={774}` ✓ → **两侧都有 ID 的分支可达且相交** ✓✓。

**真栈·一个前置数据的发现（不是本轮改动 ✗）** ✓✓：临床案子的**前置数据只对"资产池"成立** ✗——
- **强制重算池**（第三十一轮给 harness 加的 ✓）后，该案子的初始方案**不含任何"临床医学"** ✗
  （池里有 51 条 ✓，但初始方案 45 个单元一条都没选到 ✗）→ 约束把它排空 ✗ → `40906` **正确地**回滚 ✓；
- 换回**资产池**（`generateCandidatePool: false` ✓，旧成功轮次走的就是这条 ✓）→ 通过 ✓ 83→0 ✓。
- 旧轮次会话 9791936 / 9841936（同一源 1936 ✓）：初始单元含临床 **12** ✓、有序单元 **32** ✓。
- 归因（逐条排除 ✓）：ID 抄写做 bisect（摘掉 → 同样失败 ✗）✓；其余编辑在"约束无 ID"时逐条等价 ✓
  → **不是本轮改动** ✓，是"重算池"让该案子的前置不再成立 ✓（第十一轮"数据前置"同类 ✗✓）。

**复现配方** ✓：`replay-cases-id-scope-local.json`（**本目录、受版本管理** ✓——`assets/` 在
`.gitignore` 里 ✗，放那儿会随 clone 丢掉 ✗）+
`--session-offset 10010000` ✓ → `passed` ✓（83→0 ✓，约束带 ID ✓）。

**真栈·排除侧与"ID 比名字精确"** ✓✓（第四轮加跑 ✓，案子 `exclude_clinical_proposal` ✓
（同上文件里 ✓）、资产池 ✓、offset 10020000 ✓）：

| 读数（会话 10021936） | 值 |
|---|---|
| 约束 | `mustExcludeMajors=['临床医学']` ✓ + **`mustExcludeMajorIds=['774']`** ✓✓ |
| 方案 | **83 条**（非空 ✓、没被排空 ✓——与 include 侧的 `40906` 守卫正好对照 ✓）|
| 含"临床医学"的条目 | **0** ✓ |
| 774（真临床医学） | 已排除 ✓ |
| **800（中西医临床医学）** | **也已排除** ✓——名字含"临床医学" ✓，按**排除侧"命中即排"**的既定口径 ✓ |
| 775/776/778（麻醉学／医学影像学／精神医学） | **保留 16 处** ✓（名字不含"临床医学" ✓）|

而**包含侧**（会话 10011936 ✓）单元只带 `{774}` ✓——即"只保留临床医学"**没把 800 留下** ✓✓，
这正是名字路径做不到的（`"中西医临床医学".contains("临床医学")` ✓ 是第三十四轮之前的老问题 ✗）：
**同一对数据，ID 路径比名字路径精确** ✓✓。

**全量** ✓：Java **824 passed / 0 failed / 6 skipped** ✓（816 + 8 ✓）；Python **1974 / 59 skipped / 1 failed（旧账 ✓）** ✓。

**部署** ✓：按固化五步重启 **3 次**（含一次 bisect 构建 ✓），**均一次成功、无中断** ✓；
终态 pid **7010** ✓（源码 = 本轮全部改动 ✓，与备份逐字节一致 ✓）。

### 第三十五轮·三条裁决**落地**（用户："按建议的就行" ✓）— 2026-09-26

**① 空方案不算"已满足"** ✓（建议：把"非空"提为三类约束的共同前提 ✓）：

- **更正我自己在裁决页里的一处定位** ✗✓：真正接线的是 `validateConstraintApply`（`:108-142` ✓）
  那条**数违反条目**的路（`violating == 0` → 满足 ✓），**空方案零违反 → 恒满足** ✗——
  我先前引用的 `!isEmpty()` 保护在**另一条**报告路（`populateRequirements` ✓）上 ✓。
  两条都改了 ✓：前者加 `total == 0 && hasConfirmedHardConstraints` ✓，
  后者把"非空"提为三类共同前提 ✓。
- **原因码** ✓：`PlanChangePostconditionReportDTO.reasonCode` ✓（报告级 ✓）+
  `RequirementResultDTO.reasonCode` ✓（逐条 ✓），值 `plan_empty_vacuous` ✓；
  失败信息也带上它 ✓（否则下游只能猜"是违反了什么、还是根本没有可比对象" ✗）。
- **红-绿** ✓：临时关掉判据 → `Expected BusinessException to be thrown, but nothing was thrown` ✓✓。
- **对照** ✓：**没有已确认约束**时空方案照旧不算失败 ✓（"零违反"本来就对 ✓，别改坏 ✗）——单测 ✓。
- **诚实标注** ✗：路径 2 的改动**未单独加单测**（它的入口要一份带投影硬约束的 fix proposal ✓，
  构造 fixture 的成本高于收益 ✓）；全量套件会拦住 `only_keep` 那条既有行为 ✓。

**② 排除类遇到同名多候选 → 拒绝执行** ✓（建议：排除类反问 ✓；本架构的落地 ✓）：

- 网关**不能对用户说话** ✓（能说话的是模型 ✓），所以落地为**指名失败** ✓：
  抛 `exclude_scope_ambiguous` ✓，由 `_execute_claimed_command` 的 `ValueError` 通道
  转成 `actionStatus=failed` + `code` ✓ + **可转述的 message** ✓。
- **测试抓出第一版不可用** ✗✓：我最初把候选清单写成"临床医学、临床医学" ✗——用户没法据此回答 ✗；
  改成带**代码与层次** ✓（"临床医学（本科/100201K）、临床医学（专科/520101K）" ✓）。
- **红-绿** ✓：临时关掉判据 → `expected failed but was applied` ✓✓——即无拦时它**直接写下去** ✗，
  正是那个静默行为 ✓。
- **范围** ✓：只拦 `multi`（同名多候选 ✓）；**大类/门类名仍走名字的整段相等** ✓
  （2026-09-25 定的口径 ✓，不动 ✓）；**包含类保持现状** ✓（按名字兜底是安全的 ✓，
  用户能在方案里看见选了什么 ✓）——两个对照单测 ✓。

**③ 并列字段形状维持** ✓（建议：不改嵌套 ✓）：口径表写进 `TASK.md` 新增的「二之三」✓
（包含/排除 ✓、缺身份 ✓、目录取值 ✓、排除类同名多候选 ✓、空方案 ✓ 五行判据 ✓ + 形状裁决 ✓）。

**真栈复跑** ✓✓（只重启 agent ✓，pid 27389 ✓；案子用受版本管理的
`replay-cases-id-scope-local.json` ✓）：

| 会话 | 约束 | 方案 | 结论 |
|---|---|---|---|
| 10031936（"只保留临床医学" ✓） | 含 `['临床医学']`+`['774']` ✓、**排 `['中西医临床医学']`+`['800']`** ✓ | 30 条全含临床 ✓ | passed ✓ 83→0 ✓ |
| 10041936（"不要临床医学" ✓） | 排 `['临床医学']`+`['774']` ✓ | 83 条、含临床 **0** ✓ | passed ✓，**拒绝没误伤** ✓ |

**全量** ✓：Java **826 / 0 / 6** ✓（824 + 2 ✓）；Python **1977 / 59 skipped / 1 failed（旧账 ✓）** ✓（1975 + 2 ✓）。

---

## 本轮交付清单（2026-09-25/26，本地会话；共 35 轮记录，**全部未提交** ✗）

> 给评审方的入口：先读这一节，再按需回看第二十二～三十五轮 ✓。
> 变更**未提交** ✗——按分工模型由评审方决定去留 ✓。

### 一、已改文件（10 个源文件 + 9 个测试文件 + 1 脚本 + 1 案子文件）

| 文件 | 改了什么 | 关键轮次 |
|---|---|---|
| `zhiyuan-server/.../RepairCandidateEligibility.java` | 粗粒度分类字段改**整段相等** ✓；区域**ID 优先/名字兜底** ✓；两层判据同源 ✓；**34 专业 ID 优先（候选+单元）✓、被读成"无约束"的缺陷修掉 ✓** | 15 / 31 / 34 |
| `zhiyuan-server/.../PendingPlanningCommandBizService.java` | 约束排空方案 → `40906` 回滚 ✓；补足接进两段式 ✓ | 16 / 19 |
| `zhiyuan-server/.../UnifiedPlanPostconditionValidator.java` | 约束路的**满足度报告** ✓（不满足抛 `40905` 回滚 ✓）；**35 空方案不算满足（两条路 ✓ + `plan_empty_vacuous` ✓）** | 18 / 35 |
| `zhiyuan-server/.../PlanningStateService.java` | 补足（`refillWorkingPlanByTierTargets` ✓）；区域 ID 一路携带 ✓；**33 修掉两处 clone 漏抄 ID** ✓；**34 专业 ID 并入（`mergeHardIdGroup` ✓）** | 19 / 31 / 33 / 34 |
| `zhiyuan-server/.../UserGoalProposalBuilder.java` | 直辖市**自动定级**（层级是提示 ✓）；反问收窄到"谁也对不上" ✓；`unresolved` 词表 ✓ | 23 / 25 |
| `zhiyuan-server/.../RegionScopeSupport.java` | 新增 `sameRegionName()`（规范化身份相等 ✓） | 27 |
| `zhiyuan-server/.../VolunteerRecommendBuilder.java`、`model/dto/inner/VolunteerRecommendListResponse.java`、`model/dto/planning/{CandidateItemDTO,HardConstraintsDTO,UpdateConstraintStateReq,PlanningUnitDTO,OrderedUnitDTO}.java` | 区域 ID 数据路径（响应 → 候选 → 约束 ✓）；**34 专业 ID 并列列表 ✓** | 29 / 31 / 34 |
| `zhiyuan-agent/app/gateway/conversation_actions.py` | 范围词表归一化（`major_scope` ✓）；**状态读数改读满足度** ✓；区域 ID 解析与下发 ✓；**34 专业 ID 解析与下发（只认 `exact` ✓、带会话学历层次 ✓）**；**35 排除类同名多候选 → 指名拒绝 ✓** | 21 / 18 / 31 / 34 / 35 |
| `zhiyuan-agent/app/gateway/snapshot.py` | **34 成绩上下文补缺** ✓（派生值优先 ✓、`strengthSubjects`→`subjects` ✓）：真载荷 `studentSummary` 没有 `batch` ✗ → 学历层次缺失 ✗ → 专业 ID 下发不了 ✗ | 34 |
| `scripts/replay_production_dialog_flow_local.py` | 九个缺口（票 ✓、owner ✓、志愿目录 ✓、原生卡 ✓、池生成 ✓、确认帧 ✓、判据 ✓、**force 重算池** ✓、**重建初始方案** ✓） | 12–19 / 31 |
| `docs/superpowers/tasks/P2-write-closed-loop/replay-cases-id-scope-local.json`（新增 ✓） | **本目录、受版本管理** ✓：`only_keep_clinical_proposal`（走**资产池** ✓）+ `exclude_clinical_proposal` ✓——`assets/` 在 `.gitignore` 里 ✗，配方放那儿会丢 ✗ | 34 |

### 二、已验证（真栈）✓✓

- 写闭环端到端：**`applied`** ✓ + 回写 `complete` ✓（会话 9791936 / 9841936 / 9842947 / 9932947 ✓）；
  「只保留临床医学」37/37 合规 ✓、「只看北京」全北京 ✓。
- 区域匹配：规范化身份 ✓、ID 优先/冲突以 ID 为准/缺 ID 回退（三层红-绿 ✓）；
  约束带 `mustIncludeRegionIds` ✓、候选池 1454/1454 带 ID ✓。
- **区域 ID 携带（第三十三轮真栈红-绿 ✓✓）**：初始单元 0/45 → **45/45** ✓、
  有序单元 0/11 → **11/11** ✓（新会话 9962947 修前 ✗ / 9972947 修后 ✓）。
- 全量：Java **826 passed / 0 failed / 6 skipped** ✓（三十三轮 3 ✓ + 三十四轮 8 ✓ + 三十五轮 2 ✓）；
  Python **1977 / 59 skipped / 1 failed（旧账 ✓）** ✓。
- **专业约束真栈**（第三十四轮 ✓✓）：`only_keep_clinical_proposal` **passed** ✓（83 → 0 ✓、
  方案 30/30 全"临床医学" ✓）；约束**同时带名字与 `mustIncludeMajorIds=['774']`** ✓，
  单元携带 `majorId={774}` ✓ → ID 优先分支可达且相交 ✓✓。
- **排除侧真栈**（第三十四轮 ✓）：案子 `exclude_clinical_proposal` ✓ `passed` ✓；约束带
  `mustExcludeMajorIds=['774']` ✓、方案 **83 条非空** ✓、**0 条含"临床医学"** ✓；
  **ID 比名字精确** ✓：包含侧只留 `{774}` ✓（不含 800 中西医临床医学 ✓）、
  排除侧按"命中即排"把 774 与 800 都排掉 ✓、相邻专业（775/776/778）保留 ✓。

### 三、待续（按优先级 ✓）

1. ~~组模式"ID 优先"未激活~~ **已完结** ✓✓（第三十三轮 ✓）：根因（clone 漏抄 ID ✗）已修 ✓、
   单测红-绿 ✓、**真栈红-绿 ✓✓**（初始单元 0/45 → **45/45** ✓、有序单元 0/11 → **11/11** ✓、
   两侧都有 ID 的分支从**不可达** ✗ 变成**可达且相交** ✓✓）。
2. ~~专业按 ID~~ **已完结** ✓✓（第三十四轮 ✓）：并列 ID 列表 ✓、匹配候选+单元"ID 优先名字兜底" ✓、
   顺带修掉"只带 ID 的约束被读成无约束" ✗→✓、投影补缺接通确认链 ✓；
   **真栈双向都验过** ✓：约束带 `mustIncludeMajorIds=['774']` ✓、方案 30/30 全"临床医学" ✓、
   ID 分支可达且相交 ✓✓。
3. ~~待裁决三条~~ **已裁决并落地** ✓✓（第三十五轮 ✓；裁决过程见 `DECISIONS-PENDING.md` ✓）：
   ① 空方案不算"已满足" ✓（两条路都改 ✓ + `plan_empty_vacuous` ✓ + 对照 ✓）；
   ② 排除类同名多候选 → 指名拒绝 ✓（`exclude_scope_ambiguous` ✓ + 含代码层次的清单 ✓）；
   ③ 形状维持并列 ✓ + 口径表进 `TASK.md`「二之三」✓。
4. **未验边界** ✗：~~exclude 那半只有单测级~~ **真栈已验** ✓（第三十四轮加跑 ✓，见下 ✓）；
   ~~`only_keep` 真栈未跑~~ **已验** ✓（临床 ✓／北京 ✓）；
   `addAutoSelectedByTier` 的真栈补足：**第二次观察到** ✓（会话 10011936 ✓）——约束把工作方案
   从 95 收敛到 **12**（＝资产方案里含"临床医学"的条目数 ✓ 实测 ✓），补足拉回 **30** ✓
   （冲18／稳7／保5 ✓），且**补进来的每一条都满足约束** ✓（30/30 含"临床医学" ✓✓）——
   正是第十九轮那条性质 ✓；
   **ID 与名字冲突时以 ID 为准**仍是单测级 ✓——那需要**构造**"名字像、ID 不是"的数据 ✗，
   真栈的候选是从真志愿文件来的 ✓，造不出来 ✓（这条留单测级是**设计使然** ✓，不是漏验 ✓）。
5. **回放前置（第三十四轮新增 ✗✓）**：`generateCandidatePool: true`（第三十一轮加的 ✓）
   会让**临床案子**的初始方案不含"临床医学" ✗ → `40906` 正确回滚 ✓。
   按案子选池：临床案子走**资产池** ✓（配方见第三十四轮 ✓）。

### 四、运维事故（两次共享服务中断，各 1–2 分钟 ✗，均因我的重启方式 ✗）

已固化的正确姿势 ✓：**停 → 等端口不再监听 → 构建 → 起 → 验证监听与健康 → 才宣布成功** ✓。
第三十三轮按此姿势再部署一次 ✓：**一次成功、零中断** ✓（计划内停机约 2 分钟 ✓，非事故 ✓）——
说明这套姿势可复制 ✓✓。健康检查用**业务读**（`/session/state` 200 ✓）而非 `/actuator/health` ✗
（后者在本 profile 下恒 500 ✗，不是"不健康"✓）。
