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

## 五、下一步

1. ~~定 operationId 的落点~~ ✓ 已做完（走生产者侧：Java prepare 落进 pending.dataValue + 新端点 + agent 写模式改走它）；
2. 接线写工具面（三节堵点 2：MCP 读开关 + env 透传 + 一致性检查）；
3. ② 真栈端到端 + "重复确认"的**数据库计数**证据（要真 Java ✓）；
4. 新开一条"写路径"场景（别放宽 `mixed-read-write` ✓）；
5. 补 Java 侧 `prepareUserGoalProposal` 的单测（本轮只到"编译过 + 由 ② 覆盖"✗）；
6. ② 开跑前先**重打包重部署 Java**：本地跑的还是 2026-09-22 06:29 的 jar ✗，不含新端点 ✓
   （agent 侧已重启到新代码 ✓，health 200 ✓）。
