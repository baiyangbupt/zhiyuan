# `app/gateway/service.py` 误覆盖事故与恢复记录

日期：2026-09-23。范围：死代码普查引出的文件回滚事故，涉及 `zhiyuan-agent/app/gateway/service.py`（codex 网关）与 `zhiyuan-agent/app/service.py`（legacy，两者同名）。本文只写现场取证与复跑结果，推测处显式标注。

## 一、事故

- 背景：死代码 A 批删除（59 个顶层定义）之后，为排查套件 `skipped 35→50` 的位移，执行了一次**按文件名**的整体回滚：把 `/tmp/a-batch-backup/<basename>` 拷回仓里所有同名文件。
- 缺陷在索引方式：备份与回滚都按 **basename** 索引。而 `service.py` 在这棵工作树里有两份——`app/service.py`（legacy，387549 字节）与 `app/gateway/service.py`（codex 网关，52462 字节）。于是 legacy 那份把网关那份覆盖了。
- 损失范围：网关 `service.py` 上叠着**未提交**的三方改动（台账"文件占用矩阵"记的 P1b-3 / P1c-1 / P2 第 4 项，以及 2026-09-22 的 P1c-2、P2d）。其余 10 个备份 basename 唯一，未受波及（逐一 `cmp` 验证一致）。
- 发现方式：事故后全量套件报 `13 errors`，其中 `ImportError: cannot import name 'TURN_OUTPUT_SCHEMA' from 'app.gateway.service'`。

## 二、取证：没有 golden copy 可用

| 可能的来源 | 结论 |
|---|---|
| 文件系统上第二份网关 `service.py` | 全盘 `find` 无 |
| git（staged / dangling blob / 分支） | staged 无；`git fsck` 的 dangling blob 里没有任何含 `TURN_OUTPUT_SCHEMA` 的对象 |
| `app/gateway/__pycache__/service.cpython-310.pyc` | 是**损坏态**编译的（pyc 头：源 size=387549、mtime=9-23 18:26），不是网关内容 |
| 编辑器备份 / swap | 无 |

因此唯一可用的底是 `/tmp/service.py.keep`（9-21 19:58 的网关快照，52462 字节，md5 `898bcae71d80`）。它落后于真实文件约两天，缺 9-22 那批改动。

## 三、恢复方式：以 keep 为底，按任务报告 + 无损测试重建

三处被覆盖掉的改动**全部另有独立规格**：任务报告在、当时写的测试也都在（测试是无损的，它们定义了行为边界）。重建按这三份规格做，每处都做到"对应测试从红转绿"：

| 改动 | 规格来源 | 重建内容 | 验证 |
|---|---|---|---|
| P1b-3 快照证据优先 | `P1b-3/REPORT.md` 第一节第 2 条 | 删掉"证据从进程内存继承"那一行（`working_set.evidence_refs` 不再从 `previous_working_set` 复制；`ConversationWorkingSet.from_snapshot` 本就带 `snapshot.evidence`），留注释说明为何这里是"没有赋值" | `test_shadow_gateway.py::test_evidence_follows_the_snapshot_not_the_process_memory` 红→绿 |
| P1c-2 四态核验接入 | `P1c-2/REPORT.md` 第二节表 | `__init__` 收 `evidence_verifier`；`_settle_evidence`（问 Java 台账 → `evidence_verification.classify` 分流）；`_recheck_turn`（回注 `recheck_instruction`，重跑**恰好一次**）；`_evidence_inputs`（重建账本，重查轮复用同一份逻辑）；事件展开挪到核验之后 | `test_gateway_evidence_flow.py` 8 条 红→绿 |
| P2d schema 补 enum | `P2d/REPORT.md` 第二节表 | 3 处 enum：`artifactType`（4 值）、`evidenceRefs[].admissionMode`（可空形态按 `_normalize_nullable_for_upstream` 对 `Optional[Literal]` 的既有写法：enum 列字面量、可空性由 type 表达）、`admissionFacts[].admissionMode` | `test_gateway_contracts.py::test_the_model_facing_schema_exposes_every_contract_enum` 红→绿 |

未动的语义（刻意保持原样）：`validate_turn_output` 的既有检查与拒收日志、`_repair_turn_output`、`merge_evidence(snapshot, turn)` 的账本构成、`ingest_payload` / `apply_output` / `build_turn_trace` / `synthesize_execution_status` 的位置、分流表纯函数（`evidence_verification.py` 未受损，一个字没改）。

## 四、验收（复跑原文）

```text
$ pytest tests/unit tests/integration -q
  1 failed, 1924 passed, 50 skipped
```

- 那 1 条失败 = `test_dialog_quality_gate::test_final_action_explicit_clone_sources_have_volunteer_fixture`（读缺失的 `session_volunteer_*.json`，旧账，P1c-2 报告第四节已记），与事故前一致。
- 50 skipped = 35（既有）+ **15 条环境位移**：`test_conversation_replay.py` 14 条 + `test_gateway_thread_recovery.py` 1 条，理由都是 `CODEX_TEST_REDIS_URL is required`。带上该变量复跑 = **1939 passed / 35 skipped**，与 P2e 台账记的"全量 1939 通过"精确一致——**这 15 条是环境差异，与事故和删除无关**（此前一度被误当成删除的副作用，见第六节）。
- 符号级核对：全仓 `from app.gateway.service import …` 的每个符号逐个验证存在（`GatewayService`、`TURN_OUTPUT_SCHEMA`、`_collect_records`）；`import app.server`（全部接线的入口）成功。
- 删除残留核对：`git diff -U0 HEAD -- app/` 里**没有任何顶层 `def`/`class` 被删**——A 批删除已随回滚全部撤销，无漏网文件。

## 五、残留不确定性（必须写下来）

1. **不是逐字节还原。** P2b 报告记的调用点 `service.py:1121`（9-22 的真实文件）在重建版里是 `:1180`——重建把"取输出"与"过校验"抽成了两个内部函数（`_extract_output` / `_validate_round`），比原版多约 50 行；注释与日志文案也可能与原版不同。行为边界由三份报告的验收项 + 全部相关测试锁定，但**原版若有"报告没写、测试没覆盖"的细节（例如额外日志字段、注释里的实测记录），无法恢复**。
2. **未做真栈验收。** P1c-2 原验收是真栈上把 `/internal/evidence/verify` 打成 500 的那条；重建后没有重跑真栈（本地栈未起）。单测/集成全绿不替代它。
3. **A 批删除是否重做待定。** 重做前必须修脚本：备份与回滚一律按**完整路径**索引，绝不按 basename——本次事故就是这一条。

## 六、真栈复验（2026-09-23 19:00，事故当天补做）

事故当时"真栈未复验"是最大的缺口（第 2 条），当天补完。方法：重启 18091 上的 agent 让它加载工作区代码（`/tmp/restart_agent.py`，从旧进程 `/proc` 继承环境），用 `/tmp/fact_turn.py`（B7 验收同款客户端：Java 建会话 → 取票 → compat WS → 一句话）提问。

**A/B 对照**（同一句事实题"浙江大学2025年在浙江省的最低录取分数线"）：

| 组 | 跑的代码 | 结果 | 核验端点 |
|---|---|---|---|
| A 参照 | 事故前启动的进程（内存里是**原始**代码，9-22 07:08 起） | `type=text` 26.4s 562 字，658 分/位次 7462 | 调用 → 200 |
| B 重建 | 重启加载重建版 | `type=text` 19.0s 600 字，**同一事实** | 3 条 evidenceId 一次批量调用 → 200 |
| C 断依赖 | 重建版 + 只对 `/internal/evidence/verify` 返回 500 的代理（`/tmp/verify_breaker.py`） | `type=error` **18 字**"当前对话引擎暂时不可用，请稍后重试。"，**无事实性回答** | 0 次到达 backend（全被代理挡下） |
| D 恢复 | 杀代理、指回 18090 重启 | `type=text` 33.4s 594 字，同一事实 | 调用 → 200 |

日志侧：C 组留下 `evidence verification unavailable … code=500 msg=probe: verify endpoint is down`（与 P1c-2 报告记的形状一致），D 组进程日志零 `unavailable`。**四条与 P1c-2 原验收（报告第二、六节）逐项对上**——`_settle_evidence` 的分流（proceed / unavailable 硬失败）在真栈上走通了。

**带 Redis 的全量基线**：`CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9`（栈里那个事件存储 Redis）→ `1 failed（旧账）/ 1939 passed / 35 skipped`，与 P2e 台账记的"全量 1939 通过"**精确一致**。第四节那 15 条 skip 的归因至此是实测结论，不是推断。

**仍未复验的**：重查路径（`stale → 重查一次 → 成功/仍失效则 fail closed`）的**成功那一半**。见下面第七节：机制与 fail-closed 那一半已在真栈复现。

**16 案例验收回归**（`scripts/evaluate_zhiyuan_acceptance.py`，1 遍 16 case）：**16/16，0 业务失败 0 环境失败**（逐条 `[ok]`，9.9s–37.0s；明细 `.runtime/zhiyuan-acceptance-0923-rebuild.json`），与 2026-09-22 的记录一致。这一遍同时覆盖了 P2d 那 3 处 enum 改动对**真实模型回合**的影响（plan-generate-readonly 等提案类 case 全过）。

## 七、真栈复验之二：重查路径（2026-09-23 19:08）

方法：用 `/tmp/flip_version.py`（一次性工具，只改 `gaotu.batchList` 那一行的 `data_version`，`finally` 还原）在回合进行中反复翻转版本，逼出 `stale`。共 7 轮，观察到的收场：

| 收场 | 次数 | 证据 |
|---|---|---|
| **重查一次 → 仍失效 → 整轮作废** ✓ | 1 | 会话 900325：`type=error` 18 字、无事实性回答；日志 `evidence settlement failed the turn code=evidence_recheck_failed detail=ev_01M36Z8BPEKJ5GWC1MVS8KEXPM`；backend **恰好 2 次 verify 调用**（首次 + 重查后各一次）——"上限 1 次"成立，没有第三次 |
| 首次即有效 → 正常作答 | 5 | `type=text`，1 次 verify 调用 |
| 模型抄错 evidenceId → `evidence_not_found` → 硬失败 | 1 | 会话 900326：模型引用 `ev_01M36ZC1WM`**HME7C8TZMYV5R9SNZ**，账本里实际是 `ev_01M36ZC1WM`**JPR5XXGV3AZ1T3DP**（同前缀、尾部被编造，ULID 相似性）——这是模型侧老毛病、不是本重建引入的，`evidence_not_found` 本来就是为了拦它 |

**没观察到的**：重查后第二次核验返回 `valid` → 回合继续成功。它和上面第一条走**同一条重建代码**（重查轮也走"重建账本 → 重过校验 → 再核验"），差别只在纯函数 `classify` 对第二次结果给出的处置；单测 `test_stale_on_a_fact_output_triggers_exactly_one_recheck` 覆盖了这个组合（含"输出在场、恰好 2 轮、核验两次"）。**如实记：真栈上未复现，属概率性未撞到，不是失败。**

翻转工具的还原每次都执行并核对过：每轮结束 `FLIP-` 残留 0 行、靶子行恢复原值 `fc7bd2c8d3cd6dad653afc03d4c7b40a`。

## 八、附：15 条 skip 的归因更正

`skipped 35→50` 曾出现在 A 批删除后的那次跑里，被当成"删除引起的位移"去查（事故正是这次追查的回滚引起的）。实际归因：`test_conversation_replay.py`（14 条）与 `test_gateway_thread_recovery.py`（1 条）整文件 `skipif(not os.environ["CODEX_TEST_REDIS_URL"])`——**有没有这个环境变量决定跑还是跳**，与代码状态无关。对照：`test_zhiyuan_agent_direct.py` 单独跑 289 passed / 33 skipped，删前删后一致（这也曾作为"不在这个文件里"的证据）。带变量的实测（1939/35）已把这条钉死。

## 九、复核指南（给设计评审）

> 交给独立评审会话的交办书：`2026-09-23-gateway-service-rebuild-review-brief.md`（自足，含指纹、规格出处、
> 必须逐条判定的 5 个可疑点、边界与产出要求）。本节是它的详细版。

复核的对象是**重建版**（`app/gateway/service.py`，md5 `a7f406d97a49e9f73c22cbdec30db06c`）。目标不是"逐字节等于原版"——那不可能（原文件已丢，第二节），目标是三条：**①** 重建的每一处都能在任务报告里找到出处；**②** 相关测试从红转绿（当前全绿）；**③** 没有报告之外的新行为。

### 复核材料

| 材料 | 位置 |
|---|---|
| 全部改动（相对 HEAD） | `git diff HEAD -- zhiyuan-agent/app/gateway/service.py`（+483/−119） |
| 重建版快照（与工作区一致） | `/tmp/gateway-service-recovered.py` |
| 三处改动的规格来源 | `tasks/P1b-3-snapshot-evidence/REPORT.md` 一节二；`tasks/P1c-2-verify-in-gateway/REPORT.md` 第二节表；`tasks/P2d-contract-schema-alignment/REPORT.md` 第二节表 |
| 定义行为的测试（无损） | `tests/unit/test_gateway_evidence_flow.py`（8 条）、`tests/integration/test_shadow_gateway.py::test_evidence_follows_the_snapshot_not_the_process_memory`、`tests/unit/test_gateway_contracts.py::test_the_model_facing_schema_exposes_every_contract_enum` |

### 逐项检查点

**① P1b-3（一行删除 + 注释）**——`_handle_uncached` 里 `evidence_refs` 不再从 `previous_working_set` 继承；
反证：`grep -n "evidence_refs = list(previous" zhiyuan-agent/app/gateway/service.py` 应无命中；`from_snapshot` 本就带 `snapshot.evidence`（`app/engine/working_set.py:77`）。
**② P1c-2（核验接入）**——五处必须对上报告：`__init__` 收 `evidence_verifier`；`_settle_evidence` 三条分支与错误码
（`evidence_not_authoritative` / `evidence_verification_unavailable`（verifier 抛）/ `evidence_recheck_failed`（重查后仍失效））；
`_recheck_turn` **只跑一次**（上限由调用方保证，函数里不循环）；`_evidence_inputs` 在重查后**重建**账本；
事件展开在核验之后（`decision.blocks_the_turn` 时返回 `events: []`）。特别注意：**行号与报告不符**——
P2b 报告记的调用点在原版 `:1121`，重建版是 `:1180`，因为我把「取输出」与「过校验」抽成了
`_extract_output` / `_validate_round` 两个内部函数（这是我的结构选择，不是原版结构，重点看这里）。
**③ P2d（3 处 enum）**——`artifactType`（4 值）、`evidenceRefs[].admissionMode`（可空：enum 列字面量、可空性由 type 表达）、
`admissionFacts[].admissionMode`；可空那处的形态是我的判断（依据是 `_normalize_nullable_for_upstream` 对 `Optional[Literal]` 的既有写法）。

### 附：我自己认为最该被怀疑的五处（主动交靶）

1. `_recheck_turn` 的 `start_turn` 回退分支——真栈与单测覆盖的都是 `start_turn_and_collect` 路径；
2. 重查轮的进度事件（`emit`）没有传给它——若原版传了，UI 上重查轮会多一段进度；
3. 可空 `admissionMode` 的 enum 形态（不含 `null`）；
4. 我新加的日志文案（`evidence settlement failed the turn …`）未必与原版一致；
5. `_extract_output` / `_validate_round` 是我抽的，不是原版结构。

### 分层复核（10 分钟 → 1 小时）

**第 1 层（10 分钟，只读）**：读 `git diff`，对上面 ①②③ 逐条问"报告里有这条吗、注释说清了 why 吗"。
**第 2 层（10 分钟，跑测试）**：
```bash
cd zhiyuan-agent
CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9 .venv/bin/python -m pytest tests/unit tests/integration -q
# 期望：1 failed, 1939 passed, 35 skipped（那 1 failed = test_dialog_quality_gate 缺夹具，旧账）
.venv/bin/python -m pytest tests/unit/test_gateway_evidence_flow.py \
    tests/unit/test_gateway_contracts.py tests/unit/test_evidence_verification.py -q
# 期望：全绿
```
**第 3 层（约 10 分钟，真栈，会真发问、耗模型配额）**：
```bash
cd zhiyuan-agent
.venv/bin/python /tmp/fact_turn.py "浙江大学2025年在浙江省的最低录取分数线是多少？"
# 期望：type=text，正文含 658 分/位次 7462，backend 日志出现 /internal/evidence/verify 200

# 断依赖阶段：起代理（记下 PID）→ agent 指向它 → 同题 → 期望硬失败
nohup .venv/bin/python /tmp/verify_breaker.py > /tmp/verify_breaker.out 2>&1 & echo $! > /tmp/breaker.pid
.venv/bin/python /tmp/restart_agent.py "" http://127.0.0.1:18099
.venv/bin/python /tmp/fact_turn.py "浙江大学2025年在浙江省的最低录取分数线是多少？"
# 期望：type=error、18 字"当前对话引擎暂时不可用…"、无任何数字；agent 日志出现 evidence verification unavailable

# 恢复：杀代理 + agent 指回 18090
kill "$(cat /tmp/breaker.pid)"
.venv/bin/python /tmp/restart_agent.py "" http://127.0.0.1:18090
```
注意两点：**①** 杀代理用 PID 文件，**不要用 `pkill -f`**——模式会匹配到你自己这条命令的 shell（实测两次把我自己的会话杀了）；**②** `restart_agent.py` 每次重启会把 `/tmp/agent-18091.log` 轮转成 `.prev-<时间戳>`，所以断依赖阶段的证据在**上一份**日志里。
**第 4 层（可选，约 4 分钟）**：16 案例验收回归（`scripts/evaluate_zhiyuan_acceptance.py --attempts 1`，期望 16/16）。

### 复核**不能**解决的两件事（先说清，免得当成漏项）

1. **逐字节等价**：原文件已丢，任何复核都无法证明"与事故前的文件一字不差"；能证明的只有"行为与三份报告一致 + 测试全绿 + 真栈对照通过"。
2. **我的结构选择是否与原版相同**：例如 `_extract_output` 的抽取、重查块的位置。只能评审"这个结构本身对不对"，无法比对原版。

## 十、独立复核与修复（2026-09-23 晚）

独立评审（主脑）按交办书复核重建版，结论 **有条件不通过**：三项要修、一项无法判定、一项通过。
复核记录：`2026-09-23-gateway-service-rebuild-review.md`。三项的处置与修复后的复跑如下。

### 修 1（P1，阻断）：可空 `admissionMode` 的 enum 缺 `None`

**这是重建时我自己引入的缺陷，而且我当时还替它论证过**——用"与 `_normalize_nullable_for_upstream`
处理 `Optional[Literal]` 的形态一致"给"enum 不含 null"背了书。复核用 `jsonschema` 实测推翻：
JSON Schema 的 `type` 与 `enum` 是**合取**，`{"type":["string","null"],"enum":["major","major_group"]}`
会把契约允许的 `null` 判非法（`None is not one of [...]`）。这正是 P2d 要修的那类
「模型可见 schema 与内部契约不一致」，我在反方向又犯了一次。

- 修复：该节点 enum 改为 `["major", "major_group", None]`；
- 新增回归测试 `tests/unit/test_gateway_contracts.py::test_nullable_contract_literals_are_expressible_in_the_model_facing_schema`：
  对每个契约 Literal 字段，schema 同名节点去 None 后必须**等于**契约字面量集合、且**可空性一致**
  （契约可空 ⟺ enum 含 None）——比原来那条"字面量在不在 enum 里"更强，补的正是它漏掉的那一半；
- 复核的最小复现重跑：`None accepted` ✓（不可空的 `admissionFacts[].admissionMode` 仍正确拒收 null）。

### 修 2（P2）：重查轮没拿到实时回调与 native turn 绑定

首轮传 `on_notification` / `on_turn_started`，重查只传了 thread/输入/schema。后果两层：
浏览器收不到重查过程的进度；`on_turn_started` 是把 native turn 绑到会话运行时的唯一入口，
缺了它 `turn/steer`、`turn/interrupt` 会指到**已经结束的首轮**。

- 修复：`collect_kwargs` 提到分支外，**同一份**交给 `_recheck_turn`；
- 新增测试 `test_recheck_round_gets_the_same_progress_callbacks_as_the_first_round`
  （断言两轮 collect 的 kwargs 相同 + 两次 `bind_codex_turn`）。

### 修 3（P2）：`start_turn` 回退分支把启动确认当回合结果

`start_turn` 只发 `turn/start` 就返回启动确认（`app/harness/codex.py`），等终态是
`start_turn_and_collect` 的职责；原实现把那个 ack 转成 dict 返回，与"拿不到结构化输出返回 None"
的自身契约不符。

- 修复：没有 `start_turn_and_collect` 的 harness → **返回 None**（调用方按 `evidence_recheck_failed`
  整轮作废）+ 日志说明；宁可整轮失败，也不拿"还没生成完"骗过重查判定；
- 新增测试 `test_recheck_without_a_collect_harness_returns_none_instead_of_the_ack`。

### 未改动的两项

- 复核第 4 项（新加的日志文案 `evidence settlement failed the turn …`）判定**无法判定** ✓ 保留
  （日志不是对外契约；它也确实是重建时写的，不是原版文案）；
- 第 5 项（`_extract_output` / `_validate_round` 抽取）判定**通过** ✓。

### 修复后的复跑

| 项 | 结果 |
|---|---|
| 定向（3 个文件） | **30 passed**（27 + 新增 3） |
| 全量（带 `CODEX_TEST_REDIS_URL`） | **1 failed / 1942 passed / 35 skipped**，跑两遍均 ~31s 完成（复核那次 29% 中断**未复现**） |
| 真栈·正常路径 | `type=text` 23.0s 747 字、verify 200——**上游接受了带 `None` 的 enum** |
| 真栈·断依赖 | `type=error` 18 字、无数字、日志 `evidence_verification_unavailable` ✓ |
| 真栈·重查 fail-closed | 2 次 verify + 18 字 ✓ |
| **真栈·重查后成功** | **本次补上** ✓（见下） |

### 真栈"重查后成功"：确定性复现（并查清了一个机理）

复核建议"按需重跑重查成功路径"。这次不靠碰运气，先查清了机理：

- **版本行是派生的**：签发路径会**重算并重写** `evidence_source_version`（模型每调一次工具刷新一次），
  所以"把值钉成 `FLIP-1` 等模型来取"必被覆盖（实测：钉住后那一轮签发的证据仍记原值）；
- **核验路径直接读表**、不重算——于是"失效"只能出现在「最后一次签发之后、核验读表之前」
  那一小段窗口里。

按这个机理写了一次性工具 `/tmp/flip_until_verify.py`：**一直翻**版本行，直到 backend 日志出现
**首次核验**立刻停翻并还原。后半段因此是确定的：首次核验 stale → 重查 → 重查轮重新取数
（签发重算、新证据记原值）→ 二次核验一致 → 回合成功。

实测（会话 900338）：`verify 调用 2 次`、`type=text`，模型正文自述
"已用完全相同的查询参数（areaId=330000）重新取数，旧证据 ev_01M374RA… 已作废，以下结论只基于本次新返回的证据" ✓。
靶子行已还原、`FLIP-` 残留 0。

### 复核后的指纹

复核记录核对的是**修复前**的 `a7f406d97a49e9f73c22cbdec30db06c`；修复后
`app/gateway/service.py` = `cd873230408d61c0ee7af960fb17c9fe`（+520/−129 vs HEAD）。
复查修复时请按新指纹核对，并看上面三条新增测试。

## 十一、复审判定与一个环境归因（2026-09-23 21:1x）

**复审判定：放行。** 修复后逐项复评——可空 enum **通过**、重查轮回调 **通过**、`start_turn`
回退终态语义 **通过**；另两项维持（新增日志文案「无法判定」、抽取重构「通过」）。复核记录已就地更新：
`2026-09-23-gateway-service-rebuild-review.md`（"修复后逐项复核证据"一节，指纹 `cd873230…` ✓）。

**但复核记录里有两个环境现象需要归因，否则下次还会踩**：

| 复核会话观察 | 执行会话同一时期的实测 |
|---|---|
| `18090` / `18091` / `18092` 三个端口 curl 全部 "couldn't connect" | 四端口（含 `16379`）**全开**；agent、Java backend、rank 三个进程都在跑（`ps` 有据） |
| 全量跑到 ~40% 长时间无输出，手动中断；`test_shadow_gateway + test_gateway_live_events` 组合在前 21 例后长等 | 全量**四次自然完成**（两次 ~31s，两次 ~32s），都得到 `1 failed / 1942 passed / 35 skipped` |

三个端口同时"连不上"而不是"拒绝"，配合"跑到需要网络的那批用例就长时间无输出"，指向一个解释：
**复核会话的 bash 跑在无网络（或丢包式屏蔽）的沙箱里**——SYN 被丢弃时 connect 会挂在超时上
（表现为"长时间无输出"），而不是立刻 `ECONNREFUSED`。这解释了两个现象，也解释了为什么
`--maxfail=1` 那次能跑到 551 passed（那批单测不需要网络），之后一批需要 Redis/本地栈的用例就卡住。

**这条归因是可证伪的，请复核自证**：在复核会话里跑下面两条，与执行会话的结果对照——

```bash
curl -sS -o /dev/null -w 'agent health %{http_code}\n' http://127.0.0.1:18091/health   # 执行会话：200
redis-cli -h 127.0.0.1 -p 16379 ping                                                    # 执行会话：PONG
```
若复核侧是连接超时/被拒而执行侧正常，则沙箱解释成立；那么"全量统计"与"真栈三项"这两类复核
应当**由执行会话代跑**（本轮已代跑：全量四次、真栈 fact/断依赖/重查成功，会话号与日志都可溯），
或在允许网络的环境里重跑。**我不替复核下这个结论，只给出证据与判据。**

**另一个操作提示**（与本轮无关但会造成同样的现象）：执行会话在真栈复验期间会 `SIGTERM`
旧 agent 再拉新的（`/tmp/restart_agent.py`），`18091` 会有**几秒不可用**；`18090`/`18092` 不受影响。
live-stack 类复核请避开重启窗口，或事先打个招呼。
