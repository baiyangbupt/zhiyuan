# Planning Integrity 真栈验收记录

日期：2026-10-20。原轮验收基线：`485cb2a` 加当轮修复；后续本地提交与新验收见文末。

## 最新结论

- 后续审计批 `65f58a7`、目标契约批 `915a8df` 已分开本地提交，未推送或部署。
- 最终 Java 1652 项，0 failures / 0 errors / 12 skipped；Python 相关 66 passed；完整业务栈 8 passed、事务边界 4 passed。
- 新包已在专用克隆库完成 6 条 HTTP 主链路、6 项取消/过期/锁定检查、5 类拒绝与失败审计、2 类兼容成功验收。
- 临时服务已停止，原服务 PID/启动时间、原会话行与运行包哈希、已有前端改动均未变。真实模型 WS 和浏览器仍未验收。

## 前轮 P2 结论

**用户批准的 P2 已修复并复验通过，修复代码已获批准并分三批本地提交；不等于全部 J5.5 或发布验收通过。**

- 新增 4 个真实 loader / executor 回归和 1 个 user-goal 兼容回归；Java 全量 1601 项，0 failures / 0 errors / 10 skipped。
- 新隔离环境的 22 个验收场景全部通过；六类主链路直接使用 `targetCount=0` 的历史态，不再预先 GET state 回填。
- Python 生命周期专项 44 项通过；工具跨轮真后端复测通过，真实模型 WS 仍未覆盖。
- 两轮私有证据分别保留，未覆盖首轮失败记录；验收阶段原库、原服务和原运行 jar 保持不变，未提交或部署；后续提交阶段未推送或更新运行产物。

## 首轮结论（修复前）

**验收已执行并收尾，但尚不能宣称整批通过或直接发布。**

- 20 个验收场景通过：真实 Java HTTP、MySQL 事务，以及 Python 工具调用真实后端。
- 2 个历史态场景失败，归并为同一个 P2：执行器读取时的兼容回填使冻结摘要发生自漂移，正常确认被判为 `review_fix_stale`。
- 真实模型驱动的 WebSocket 多轮对话未覆盖；没有用工具层验收替代模型层验收。
- 本轮未提交、部署或改动生产代码；原有服务、原库夹具及运行 jar 未变。

## 隔离环境

只读预检发现，3201 和 3001 对应的两套 Java 都连接 `zhiyuan_codex_local`，不能当成可重置的独立数据集。

| 项目 | 本轮处理 |
| --- | --- |
| 构建 | 复制当前 `pom.xml`、`src` 到 `/tmp/planning-integrity-stack-build-vhrCev/server/`，离线打包成功 |
| 新 jar | 只使用隔离目录产物；未覆盖原项目 `target/zhiyuan-server.jar` |
| MySQL | 本地 13306，新 schema `zhiyuan_integrity_acc_20261020_163403`，复制 19 张表结构及必要行 |
| 数据 | 只在副本中重置 900700 / 900045，并注入既有 Java 测试的合成规划夹具 |
| Redis | 使用启动前为空的 DB 14；未 flush 任何共享数据库 |
| Java / Agent | 临时端口 18390 / 18391；仅本轮 JVM 开启 review command/search、initial solver 和 group-inner 开关 |
| Rank | 复用本地只读 18292；不调用外部模型 |
| 原环境 | 3201 / 3001 及各自 Java、Agent 的原 PID 和监听保留，没有重启 |

Java 与 Agent 的 authenticated health 均通过。鉴权配置、账号和原 PID 文件均未修改。

私有配置、原始响应、哈希及 PID 清单保留于 ignored 目录：
`.local/codex-local/planning-integrity-acceptance-20261020/`。
配置未输出到公开文档；目录权限 0700，配置与清单权限 0600。

## 通过场景

| 场景组 | 数量 | 核验内容 |
| --- | ---: | --- |
| 完整 HTTP 执行 | 6 | major / majorGroup × count / coverage / inversion，preview → prepare → confirm claim → execute → complete |
| 拒绝写入边界 | 4 | 两种模型的 count / inversion：取消后不能 claim、过期 claim 不能执行、working item 锁定后不能产生可确认修复 |
| 陈旧确认 | 2 | 两种模型在 prepare 后变更副本 plan version，execute 返回 40904，持久化状态不变 |
| 初始生成回滚 | 2 | 已确认数量分别为 85 / 49，但仅有 84 个专业 / 48 个组；返回 `candidate_shortage`，全部会话 extra-data 哈希不变 |
| Python 工具跨轮 | 2 | 两种模型的 coverage：取消屏障、更新预览屏障、精确覆盖身份、新预览确认和防重复确认 |
| 置顶保护 | 4 | 两种模型的 count / inversion：ordered item / unit 置顶后不可确认，状态不变 |

六个完整执行场景均额外核验：

- preview 前后规划持久化哈希相同；readonly preview 不创建 pending。
- public apply 在新开关下返回 `review_fix_requires_pending`，未领取的 execute 也拒绝，均不写方案。
- 成功执行只从 version 7 变为 8，postcondition satisfied；完成后 pending 为 applied。
- 完成前在同一有效 claim 内重复 execute 返回 replayed，版本及持久化哈希不再变化。
- completedSteps 包含 `proposal_applied`、`ordered_plan_regenerated`、`review_rerun`、`postcondition_verified`。
- 最终实体身份与冻结预览一致；普通 count 补足保留原有选择，major 为 80→82、majorGroup 为 44→46。
- 三个组模式场景的最终组内专业身份集合与冻结 ordered plan 一致；有 solver major map 时，进一步逐组核对完整 map。

Python 工具验收直接调用当前 `preview_plan_change` / `confirm_pending`，使用实际 `BackendAdapter`、`SandboxFileCache` 和真实 HTTP client，没有 mock 后端。各轮使用新的 RequestContext 并携带工具历史，验证：

1. `coverage:0` 预览可确认，但不落 pending / 方案。
2. 取消后再确认，不能复活历史预览，方案不变。
3. 生成新预览后请求 `coverage:1`，不能误匹配 `coverage:0`；这份不可用的新结果也阻断更老的可确认结果。
4. 再生成有效 `coverage:0` 预览，可以正常 prepare、claim、execute、complete；再次确认不能重复写。

这是确定性工具层真栈验收，不是 LLM 自行选择工具、跨轮理解自然语言或浏览器卡片的端到端验收。

## 首轮发现：P2 历史摘要自漂移

### 复现与影响

在未预先回填的历史态夹具中，`orderedPlanState.summary.targetCount=0`，candidate pool 的 requiredCount 为 82 / 46。

两种模型均出现：

1. preview 返回 ready、requiresConfirmation=true，且只读哈希不变。
2. prepare 成功冻结，pending 为 active；用户没有修改方案。
3. resolve(confirm) 成功，pending 为 applying，token 与租约有效。
4. execute 返回 `409 review_fix_stale`，不能完成合法确认。
5. 命令事务回滚，原规划 extra-data 哈希不变；未出现部分方案写入。

对同一夹具，先通过 GET state 完成兼容回填，再重新生成 preview / prepare，则完整执行成功。此操作仅用作定位控制变量，**不等于产品问题已修复**。

### 已定位的调用链

- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizService.java:109`：执行前为核对版本调用 `getPlanningState`，并非只读 loader。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java:6808`：普通 loader 会回填 legacy summary；同时触发 data-freshness/cache-notice 补写时，回填后的 summary 一并持久化。夹具实测 targetCount 从 0 变为 82 / 46。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/DirectReviewPreviewPlanner.java:419`：摘要覆盖 working / ordered plan，包含该 summary。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java:1264`：冻结回放重新只读加载，摘要与 prepare 冻结值不同，因此抛 `review_fix_stale`。

这是生产路径支持的 legacy 数据形状与正常读取兼容行为发生冲突，不是夹具导出 `$ref` 错误；`$ref` 导出问题已单独纠正。影响是合法确认误拒绝，不是放宽鉴权或静默覆盖方案。实际存量影响比例尚未统计。

### 建议的最小修复

审查修复命令的执行前版本检查，与 preview / prepare / frozen replay 使用同一只读加载口径，避免在摘要验证前做隐式迁移；其他命令的兼容读取路径保持不变。不要删除摘要检查，也不要在确认时重写用户已确认的冻结内容。

补回归时必须同时覆盖真实 loader 的回填副作用和 executor 调用链，不能继续把 `getPlanningState` 完全 mock 成一个无副作用 getter；保留真正版本/内容漂移、过期 claim 和重复执行的拒绝规则。首轮尚未实施该修复；后续批准的实现与复验见本文末节。

## 未覆盖与保留项

- 用内部服务凭据请求临时 Java 的浏览器 WS ticket 返回 HTTP 401、`unauthenticated`。本轮未提供浏览器用户登录态，没有绕过登录、伪造票据或修改账号；因此没有发起真实模型 WS 对话。
- 尚未证明自然语言主模型的正确工具选择、完整消息历史压缩及浏览器确认卡片的跨轮端到端行为。
- 失败命令的独立事务审计（`REQUIRES_NEW` / outbox）和 review 完整目标摘要闭环仍为后续工作；不据此关闭全部 J5.5。
- 既有 Java / Python 单测结果见上一轮 repair-verification 文档；本轮没有重跑全量，也没有把其计入本次 20 个场景。

## 首轮收尾与后续建议

- 按清单核对命令身份后，仅 SIGTERM 本轮 Java 25028 / Agent 25146；进程已退出，18390 / 18391 无监听。
- 原会话 extra-data SHA256 与预检一致；原运行 jar SHA256 未变。
- 原 3201、3001、18290、18291、18090、18091、18292 的监听及对应 PID 保持不变。
- 独立 schema 和私有证据保留，未执行 DROP、flush、原库恢复或任何共享环境重置。
- `http-results.json` 包含 20 条 passed 和 2 条 failed；其他重点证据包括 `*-execution.json`、`*-legacy-summary-defect.json`、`*-initial-rollback.json`、`*-tool-lifecycle.json`、`frozen-step-offline-checks.json` 和 `ws-auth-preflight.json`。
- 建议先修复上述 P2 并重跑原始历史态确认场景，再按 Python 对话边界、Java planner/solver、Java executor 与验收记录分批提交；前端已有改动不混入。当前不建议把整批标记为已通过发布验收。

## P2 修复与复验（已完成）

### 最小实现

`zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizService.java:109`：
仅当命令为 `apply_plan_change_proposal`、review command 开关开启且来源为 `review_check` 时，执行前版本检查改用 `loadPlanningStateReadOnly`。

其他命令及开关关闭的 legacy 路径仍使用原有 `getPlanningState`。冻结摘要、版本、claim token / 租约、pending ownership 和 operation replay 校验均保留，未修改摘要算法、冻结 payload、HTTP API 或数据库结构。

### 红绿回归

在既有 `PlanningStateServiceReviewFixApplyTest` 中接入真实 `PendingPlanningCommandBizService` 与真实 `PlanningStateService`，只替代共享存储和外部 source-hash 依赖。存储行携带真实场景所需的 ID，使读取回填 CAS 可以执行，避免无 ID 夹具跳过写入而产生假绿。

修复前的有效红例为 4 项：

- major / majorGroup 合法确认各抛一次 `review_fix_stale`。
- 真正版本漂移与内容漂移虽然拒绝，但读取回填已经改动存储，两个“拒绝前无补写”的断言失败。

修复后四项均通过；新增一项兼容回归，确认 review 开关开启时 user-goal 仍正常执行，未被误切到审查 loader。

验证命令与结果：

```bash
mvn -o -f zhiyuan-server/pom.xml '-Dtest=PlanningStateServiceReviewFixApplyTest#executor*' test
mvn -o -f zhiyuan-server/pom.xml -Dtest=PlanningStateServiceReviewFixApplyTest,PendingPlanningCommandBizServiceTest,PlanningIntegrityRuntimeTest test
mvn -o -f zhiyuan-server/pom.xml test
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_review_fix_candidate_lifecycle.py -q
```

- 有效红例：4 项，2 failures / 2 errors；错误为预期的摘要自漂移，不是缺少依赖造成的 NPE。
- 修复后定向：123 项，0 failures / 0 errors。
- 修复后 Java 全量：1601 项，0 failures / 0 errors / 10 skipped，退出码 0。
- Python 专项：44 passed，退出码 0；本轮没有改 Python 生产代码，没有重跑其全量。
- 隔离离线打包成功；隔离 `src/main` 与当前工作区逐文件比较一致。
- `git diff --check` 通过。未操作或混入已有前端改动。

### 新隔离栈结果

使用全新的 schema `zhiyuan_integrity_acc_20261020_170509`，不覆盖首轮数据及失败证据。
构建目录为 `/tmp/planning-integrity-readonly-build-FKutnH/server/`；临时 Java / Agent PID 为 10731 / 10832，端口仍为 18390 / 18391。
私有配置、产物哈希与原始响应保留于 `.local/codex-local/planning-integrity-acceptance-readonly-20261020/`。

| 场景组 | 结果 | 与首轮的区别 |
| --- | --- | --- |
| 两种模型 × count / coverage / inversion | 6 / 6 通过 | 全部从原始 `summary.targetCount=0` 开始；preview / prepare 前后规划哈希不变；不先 GET state |
| 取消、过期 claim、锁定 | 4 / 4 通过 | 同样使用未回填夹具，拒绝后持久化哈希不变 |
| 真正版本漂移 | 2 / 2 通过 | prepare 后改版本，仍返回 40904，无补写 |
| 真正内容漂移 | 2 / 2 通过 | prepare 后改变 ordered item / unit 保护状态，版本不变，仍返回 `review_fix_stale`，无补写 |
| 不可行初始目标回滚 | 2 / 2 通过 | 保留已确认目标 85 / 49，候选仅 84 / 48，仍 `candidate_shortage`，无部分写入 |
| 置顶保护 | 4 / 4 通过 | ordered item / unit 置顶仍不可确认 |
| Python 工具跨轮 | 2 / 2 通过 | 沿用首轮预览前 warm-up 的工具测试设置；真实后端、不经 LLM，不将其冒充冷启动或模型对话覆盖 |

共 22 个不同场景，22 passed、0 failed。六个完整主链路均核对完成步骤、版本 7→8、public apply / 未 claim 拒绝、有效 claim 内幂等重放和 applied 终态。三组组模式冻结专业身份集合进一步与实际执行结果核对一致。

### 收尾与提交边界

- 仅停止并确认本轮 Java 10731 / Agent 10832 已退出，18390 / 18391 不再监听。
- 原会话 extra-data 哈希与本轮预检一致，原 3201 Java 的运行 jar 哈希未变。
- 原 3201 / 3001 及其 Java、Agent、Rank 的 PID / 监听保持不变；原运行环境没有包含此次新 jar 的部署更新。
- 独立 schema 与证据保留，未清理共享数据，没有提交、推送或部署。
- 首轮 P2 在本次批准范围内关闭，可以进入修复代码的分批提交审查；仍不据此宣称真实模型 WS、失败独立审计或完整目标摘要闭环已经完成。

## 批次提交收尾（2026-10-20）

以下是验收结束后、用户明确批准的本地提交阶段，不改写前述首轮失败和复验事实。

| 提交 | 内容 |
|---|---|
| `b38eaf4` | Python 对话确认候选生命周期与精确 coverage 身份 |
| `60b10f3` | Java planner / solver 保护规则、事实及候选裁剪完整性 |
| `41747d1` | Java 执行 claim 边界、初始事务、冻结专业回放及历史摘要自漂移 |

提交前 fresh 验证：Java 1601 项，0 failures / 0 errors / 10 skipped；Python 2978 passed / 32 skipped / 20 warnings，均退出码 0。第二批另在不含执行修复的基线快照中独立全量验证，1581 项，0 failures / 0 errors / 10 skipped。

本次收尾只重跑单测，不重新启动真栈或操作数据库；22 个通过场景仍指上节已完成的隔离验收。已有前端改动、旧未跟踪文档及私有证据全部保留在提交范围外。计划与验收记录作为单独文档批次保存，不推送、不部署、不重启原服务，也不宣称已关闭真实模型 WS、独立失败审计或完整目标摘要闭环。

## 后续独立审计进展

在 `5574a46` 之后，经用户批准继续落实失败命令的独立事务审计。该后续批次已通过
Java 全量及专用新库中的 4 个事务测试，尚未提交或部署；它不改写本记录的原验收范围。
实现、红绿证据、事务测试的替身边界与剩余目标摘要工作，见
`docs/superpowers/reviews/2026-10-20-planning-failure-audit-verification.md`。

## 后续执行契约与完整栈验证

后续继续补齐日志脱敏、完整 Spring Boot / MyBatis prepare → claim → 执行事务验收，
并落实 confirmed / solver 目标摘要分离与最终 frozen objectiveResults 对照。
Java fresh 全量为 1643 项、0 failures / 0 errors / 12 skipped，Python 相关 66 passed；
另在专用克隆库完成普通专业 / 专业组 Direct / Search 共 8 项真实回滚审计与成功重放验证。
这些不是本记录原有的 22 个 HTTP/tool 场景，不冒充新的 HTTP、浏览器或真实模型 WS 验收。
当前仍未提交或部署，运行包与原会话数据未变。详见
`docs/superpowers/reviews/2026-10-20-review-solver-contract-verification.md`。

## 分批提交后的新包 HTTP 验收

本节针对 `65f58a7` 与 `915a8df` 两批代码。前文 22 个 HTTP/tool 场景及 1643 项单测均保留为历史证据，
不将其冒充本次新包的全部覆盖；本次没有调用真实模型、WS 或 Python 对话工具。

### 隔离边界

- 构建项目：`/tmp/planning-review-submit-Ds1HZ3/complete/zhiyuan-server/`。最终离线 `package`
  为 1652 项，0 failures / 0 errors / 12 skipped；运行 jar 仅由该临时目录提供。
- 临时 jar SHA-256：`b1b07d60f8f8ebee8e3fd751d1cd1188846f86bf2e87bca0bd7903a1e3182298`。
- 新 schema：`zhiyuan_integrity_acc_20261020_190727`；datasource 和 Flyway 的 URL/user/password
  均显式指向新库，并移除继承环境中可能覆盖隔离配置的 Spring / JVM 参数；Redis 和临时文件独立。
- 临时 Java / Agent 为 22645 / 22794，端口 18390 / 18391；Agent 只启动并做健康检查，HTTP 业务探针
  直接访问临时 Java，不据此声称 Agent 对话链或模型 WS 已验收。
- 原 3201 / 18290 / 18291 / 18292 服务未重启，原 `zhiyuan-server/target/zhiyuan-server.jar` 未替换。

### 结果

| 场景 | 数量 | 验证结果 |
| --- | --- | --- |
| 普通专业 / 专业组 × count / coverage / Direct inversion | 6 条主链路 | preview / prepare 只读；public apply 和未 claim 拒绝；claim → execute → replay → complete → applied；版本只增加一次、选择及组内专业身份与冻结结果一致 |
| 普通专业 / 专业组 count 的取消、过期 claim、锁定 | 2 组、6 项检查 | 取消后不可 claim；过期 claim 不写方案；锁定方案不可确认 |
| canonical 摘要篡改、objectiveResults 缺失、Search solverResult 缺失、平铺草案缺失、组内专业缺失 | 5 类拒绝链路 | 分别 409 / 40905；规划行哈希不变；failed command 独立持久化；原 pending expired；reconcile 保留失败码；同 operation 重放不再执行 |
| 未选池内专业增加 coverage 匹配 | 1 条成功链路 | 冻结和回执的实际 coverage 均为 1，不误算为池内匹配的 2；完成正常提交和幂等重放 |
| 有 units、缺 volunteerModel 的历史组状态 | 1 条成功链路 | 合法 coverage 提案完成确认执行，最终明确 majorGroup，摘要和目标回执均有效 |

全部表列检查通过，探针退出码均为 0。五类损坏冻结数据通过**仅修改专用新库的 pending JSON**构造，
用于验证持久化契约的拒绝边界，并不表示公开接口允许任意修改冻结内容；这五类均为写前拒绝，
真正“方案已写入后注入失败再回滚”的证据仍来自同源码的 8 项完整 Spring / MyBatis 栈测试。

### 收尾与证据

- 仅停止本次临时 Java / Agent；确认两 PID 已消失、18390 / 18391 端口关闭。
- 原 Java 20914、Agent 914、Rank 4258 / 2035、前端 31139 的 PID 和启动时间与验收前逐字一致。
- 原会话 extra-data 行哈希、原运行 jar 哈希、已有前端 diff 指纹均未变化；新库与证据保留，不清理原库。
- 私有目录：`.local/codex-local/planning-solver-contract-http-submit-20261020/`，包含 `run.json`、
  `http-summary.json`、`http-results.json`、原始响应及执行脚本快照；配置和完整回执不进入 Git。
  总结按表列验收动作计数，原始 JSON 记录粒度包含边界合集和兼容场景补充标记，不以 JSON 行数充当场景数。
- 本节与计划、两份修复验证记录单独作为文档批次本地提交；没有 push、部署或现有服务重启。

**下一发布关口仍是受控更新运行包，再做真实模型 WS、浏览器卡片和对话确认闭环。**
失败审计进程崩溃窗口、存储失败重投及 failed 台账归档另列后续，不因本次 HTTP 通过而关闭。
