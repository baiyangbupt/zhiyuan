# 对话引擎化迭代与独立审查（2026-10-07）

> 性质：当日执行记录 + **独立审查发现清单**（审查方未参与实现，只读）。
> 基线：`81a09d4`（昨夜）→ 当日提交至 `d098da8` 及后续。
> 关联：[10-06 链路打通与恢复](2026-10-06-test-www-chain-recovery.md)、[总计划](../../release-4.0.0-codex-native-zhiyuan-integration-and-frontend-validation-plan.md)。

## 一、当日交付（全部上线演示栈 18290/18291/3201）

| 切片 | 提交 | 关键读数 |
|---|---|---|
| 分数→位次：inner 端点 + 建档/补录自动补保守位次 | `afe9672` | 安徽 600 → 28600–29273（WL）；浙江 610 → 42829–43879 |
| 位次工具 `catalog.get_score_position` + 空档五项/编码一次查规则 | `d437d50` | 空档只给总分 → 追问不硬出卡（三连 110 治愈） |
| 专业方向推荐 `recommendation.preview_majors` + 本科批默认/科类编码规则 | `9061b8f` | Top8 打分（交通运输类 82.5…）；无画像明确不可用 |
| 候选比较 `recommendation.compare_candidates` | `fedb5db` | 6 维 12 格全带来源；幽灵 id 如实报；只读 |
| 规划态读路径 CAS 化 + NPE 家族 + strengthSubjects | `d098da8` | 压测修前 NPE×10/失败×6/覆盖回退实锤 → 修后 293 次全绿、零回退 |
| 前端：心跳判死、流式人话、历史去重、时间线合并、无效 toast | `cbb256d` `a3a6f16` `cf13683` `93d054b` `8bb8b97` `55c0c1b` | 顺序逐对交错、toast 清零、假死 30s 自愈 |

## 二、独立审查发现（2026-10-07，审查方独立于全部实现方）

**结论：无阻断级；高 3 / 中 5 / 低 7 / 疑点 5。** 以下为处置分级：

### 高
- **H1 ProposalCard 不认 `stale_state`**：原样渲染英文机器态 + 按钮复活（F09 的拒绝路径）。
  → **本波修复**（状态映射中文 + 收起按钮 + 与 legacy 卡口径对齐）。
- **H2 写路径仍是整文档读-改-写**：本轮只 CAS 化了读路径；写-写并发仍 lost-update。
  → **专线修复**（写路径统一 CAS；`savePlanningState` 收敛为私有）。
- **H3 submit/export 对缺 volunteerCount 静默产出 0 配额 + ≤15 候补并置 FINISHED**：
  响亮 NPE 被降级成静默持久化坏产物。→ **专线修复**（submit/export 前置校验拒绝）。

### 中
- **M1 失败卡直出 Java 英文内部消息**（含版本号）→ 并入 H1 波（code 作锚点、文案中文）。
- **M2 位次查询失败静默换当年重试**并被新链路落库 → 专线（仅未指定年份才允许回退）。
- **M3 preview「只读」名不副实且字段集≠执行集** → 并入 Java 专线（javadoc + 补位次进预览）。
- **M4 看门狗可能误杀后台标签节流连接** → 并入前端波（visibilitychange 复位/隐藏期跳过）。
- **M5 测试网眼**：F09 断言弱于注释；ProposalCard 无单测 → 并入前端波。

### 低/疑点（择机）
- L1 applying 期间按钮未收；L2 agent 失败文案内部术语；L3 execute 超时 ≠ 未执行的标注；
  L4 导入竞争窄窗非权威读；L5 位次失败静默无 inline 提示；L6 streamText 首匹配小注；
  L7 declined/not_executable 状态漏配。
- D1 CAS 的 SQL 级行为（真库 LONGTEXT 比较/NULL/collation）未测 → 随 H2 专线补真库用例；
  D2 overlay CAS 连输路径无测试；D3 F09 终态实际码；D4 H3 可达性；D5 后台节流真机验证。

### 审查确认无误的关键假设（摘）
CAS 为真比较集（含 dataVersion+dataValue）；撞键赢家语义正确；测试替身是忠实双；
pong 契约完好（ping 不刷新自己）；时间线合并不变量成立；testid 回归面未破裂；
工具诚实口径（不可用不造数）；补录闭环形状正确；SMS 旁路默认关闭。

## 三、独立 e2e 回归读数（全天重建，2026-10-07 晚补录）
回归线 agent 会话已不可达（无法复述），以下按留档重建：

| 轮次 | 时间 | 契约（13） | 写路径（6） |
|---|---|---|---|
| r1（无后缀） | 17:05 / 17:07 | 12/13 —— **F10 刷新恢复待答卡失败** | 6/6 通过，EXIT=0 |
| r2 | 17:20 / 17:22 | 12/13 —— **F10 同表象失败（稳定复现）** | 5/6 —— F14 偶发（重连后新消息未达服务端） |
| r3 | 17:25–17:27 | ——（未跑） | 0/6 —— 提案卡全未渲染 |
| r3-write2 | 17:30–17:32 | —— | 6/6 通过，EXIT=0（替身重启 + 新盐 + runId 匹配后） |

- **稳定回归候选 = F10**：两轮独立运行、同表象（刷新后 `clarification-card` 未随流回放重现；事件在流里、桥请求仍在；其余 12 条全绿）。归因待排查（今日前端改动引入 vs 既有问题）。
- r3 写路径 0/6：`/tmp/verify-run-write4.sh` 自注"修正 run-id 错配"；重启替身 + runId 匹配 + 新盐后全绿 → 初判夹具/编排态问题，非产品回归（待复核）。
- F14：4 次执行中 1 次失败（r2；重连后 send 未达服务端、`turn-progress` 缺席），其余 3 次通过 → 偶发，记观察。
- 证据：`/tmp/e2e-verify-c4-verify-20261007{,-r2,-r3}-{contract,write}.log` 及 `-STATUS`、`-*-artifacts/`（失败快照：r2 F10、r2 F14、r3 六条）。
- **F10 根因（独立只读排查定稿）**：`clarification.requested` 被以 **codex 原生回合号**（`turn_N`）写流——`fbb281c`（10-06 21:41"事件自带 turnId 优先"，`session_runtime.py:127`）让原生号直通；而刷新补发 `_replay_active_turn` 的过滤（`server.py:676-678`）只认业务 UUID → 回放时该事件被滤掉、卡不重现。窗口：最后全绿 `/tmp/contract-run-1.log`=10-06 12:03 → `fbb281c` 当晚落地 → 今日 r1/r2 为改动后首跑；**与今日前端改动无关**（逐条排除）。副产物：卡被画进原生号另块（F02 因 resolved 后空回合不渲染而侥幸仍绿）。修复方向：broker 边界翻译原生→业务号（勿回退通道盖章）+ 同回合 turnId 一致性不变量测试；补发过滤可加双号防御（非充分）。证据：`/tmp/stream-900022.txt`、r2 error-context、`git show fbb281c -- app/gateway/session_runtime.py`。

## 四、pending（更新）
- **F10 已修复并推送 ✅**：`072ff5c`（broker 边界原生→业务号翻译 + 回放过滤防御放行 + 2 条新单测；全量 unit 2012 passed，唯一红为既有 dialog_quality_gate 夹具问题）。沙箱 r4 契约 **13/13 全绿（F10 回绿）**，日志 `/tmp/e2e-verify-c4-verify-20261007-r4-contract.log`；Redis db9 数据佐证澄清事件已同盖业务 UUID。✅ **已部署演示栈 18291**（19:50 重启，pid 32605，health 200；env 先抓活进程快照再搬运、与 demo 姿势逐项比对；启动日志 `codex_write vs MCP_MODE=readonly` 警告经查为历史常态、非本次引入）。备注：沙箱事件流 24h TTL 跨轮残留，若遇"卡串轮"先换盐/epoch。
- **Java 专线交付 ✅**：H3 `ab4a292` / M2 `90cacec` / M3 `92fbf90` 实现+单测绿；H2 按授权止步，交 D1 真库 SQL 用例 8/8（`2c5a96e`；写共享库的既有表、仅自建随机 session id/随机 key，复核残留 0）与 `H2-WRITE-CAS-PLAN.md`（17 调用点分类+三策略+DoD）。全量单测 931/0/7skip。写路径沙箱 e2e 5/6，唯一红 F09 已移交前端波（嫌疑=WIP 用例/夹具 turnId 覆盖，非本波后端改动）。
- **演示栈 18290（Java 后端）19:59 被内核 OOM 杀死**（今晚并行负载 + 无 swap；dmesg 实锤 19:59:33 杀 pid 31744、RSS 2.8G；20:10/20:18 同因连杀两只 Chromium）→ 已用 `/tmp/restart-18290.sh` 重启（pid 22119，health 200），**jar 含 H3/M2/M3（即三项已上线演示栈）**；`oom_score_adj=-500` 保护。同因降载：**F10 沙箱（18293/18294/3202）已停**（腾 ~1.6G）。
- **前端波交付 ✅**：`41d37e6`（H1/M1 提案卡认 stale_state/失败码、中文口径、按钮收起）/ `8b2e5dd`（M4 看门狗跳过后台节流）/ `bc1e216`（M5 F09 断言补强）+ **跨线真根因 `35ddbf5`**（服务端 prepare upsert 带 CAS 修订号，7 行，与补录路径 `7d23ade` 同口径——此前转述的"turnId 覆盖"嫌疑被证伪）。单测 25/25 + 118/118；沙箱 e2e **契约 13/13 + 写 6/6（F09 首次全断言绿）**。**已部署演示栈**：服务端用 `/tmp/f09fix` 源码树（与 bc1e216 逐字节一致、即沙箱实测同一构件）重建 jar 重启 18290（pid 16146，health 200，OOM 保护 -500）；前端为 3201 dev 直读工作树（刷新即生效）。前端波沙箱（3205/18301-18304）已停（腾内存 + 给 H2 让路）。F09 绿依赖 `35ddbf5`，若回退会回红。
- **runner 补丁**：`scripts/run-codex-e2e-in-container.sh` 补透传 `ZHIYUAN_E2E_CONTROL_URL`（此前 fixtures 闸门控制会默认打到 18293 沙箱，易串线）。
- 磁盘救援：**已执行（用户批准"全批"）**——binlog.000001–000010 已 PURGE（~9.8G），过期 30d→2d 已 `SET PERSIST`（重启不丢）；Docker 四个旧镜像/容器已删（~4.1G）；/tmp 995 个旧文件（0.73G，清单存 `/tmp/cleanup-manifest-20261007.txt`）与 head-build（0.24G）已删。**剩余 15G / 62%**（清理前 752MB）。
