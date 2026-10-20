# 方案执行失败独立审计验收（2026-10-20）

> 状态更新：本地审计批已提交为 `65f58a7`；下文保留实现阶段证据，最新提交前复验见末节。未推送或部署。

## 范围与状态

基线为 `5574a46`。本轮落实已批准的 J5.5 设计 §4.4 中失败命令独立事务审计，
不扩大到完整目标摘要闭环，不更新 3201 / 3001 的运行产物。

实现、红绿回归、Java 全量和独立 MySQL 事务边界测试已完成；改动仍在工作区，
未提交、推送、部署或重启原服务。前端已有改动和历史未跟踪文档保持不变。

设计依据：`docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md`。
此前修复与隔离 HTTP / 工具验收：
`docs/superpowers/reviews/2026-10-20-planning-integrity-stack-acceptance.md`。

## 根因与实现契约

原 executor 在方案事务内插入 `running` command 并执行变更。后置校验失败时，
方案写入和 command 行一起回滚；pending 留在 `applying`，后续 reconcile 无法
区分“未送出”与“确实执行失败”。

不能在持有 pending / 方案行锁的外层事务中同步启动另一个写同一行的事务，
否则会等待自己尚未释放的锁。本轮使用：

1. 保留原方案事务以及 owner、claim、冻结请求绑定、版本和重放检查。
2. 仅对新 review command 开关开启、且与 pending 冻结的 operationId、proposalId、
   sourceVersion 相符的已认领执行，在失败时注册事务完成回调。
3. 只有 `afterCompletion(ROLLED_BACK)` 才调用独立 Spring bean 的
   `REQUIRES_NEW` 写入器；主事务先回滚释放行锁，再写失败审计。
4. 新插入 `failed` command，保留命令身份与 requestDigest。不能复用已回滚 insert
   分配的主键；不能覆盖已有 `succeeded` / `running` / `failed` operation。
5. 失败回执只保存状态、数值错误码及有界 reasonCode，不保存原始异常详情、方案内容或 claimToken。
6. 锁内核对原 pendingId、revision、claimToken、status 和 operationId 后，才将原 owner
   CAS 到 `expired`，记录 `resultCode`、`resolvedAction=fail`，同步快照 status / revision。
   新 claim、新 pending 或已完成状态不被旧失败回调修改；pending 内容损坏不抹掉失败台账。
7. reconcile 将 `failed` 识别为已知执行失败，不再返回 `operation_result_unknown`；
   对已落定 pending 保留 resultCode。失败 operation 不允许当作新命令再次执行，需重新预览。
8. 开关关闭与 user-goal 的原执行失败路径不变；非法 claim、篡改摘要或冻结身份不匹配，
   不得借失败审计污染当前合法 pending。

无新增依赖、数据库列或迁移；使用现有 command.resultJson 和 pending.resultCode。

## 红绿与回归证据

- 根因回归先红：6 项中 2 failures / 0 errors；正常执行失败、真实版本漂移均未注册回滚后审计。
- 边界补充先红：41 项中 3 failures / 0 errors；分别为已知失败被当作未知、已落定 pending 丢失失败码、pending JSON 损坏导致审计写入器异常回滚。
- 修后覆盖回滚完成时机、commit / unknown 不写、审计存储失败不覆盖原错误、非法 claim、
  digest / operation / proposal / sourceVersion 篡改、失败重放、开关关闭及 user-goal 兼容。
- 写入器覆盖新主键、脱敏回执、原 owner 过期、三类已有 operation 不覆盖、新 claim / pending
  保护、损坏数据和审计 insert 失败时不推进 pending。
- 上一阶段 Java 全量：**1628 项，0 failures / 0 errors / 11 skipped**，退出码 0。
  原有 10 项跳过保持；新增真实数据库测试类默认 opt-in，因此全量另计 1 项条件跳过。
- Python 相关确认客户端、候选生命周期及 plan-change 契约回归：**66 passed**，退出码 0。
- `git diff --check` 通过；原运行 jar 哈希保持不变。

```bash
mvn -o -f zhiyuan-server/pom.xml test
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_pending_confirmation_client.py \
  tests/unit/test_review_fix_candidate_lifecycle.py \
  tests/unit/test_release_410_plan_change_contract.py -q --tb=short
```

单测日志：`/tmp/planning-command-failure-audit-red.log`、
`/tmp/planning-command-failure-audit-edges-red.log`、
`/tmp/planning-command-failure-audit-full-final.log`、
`/tmp/planning-command-failure-audit-python.log`。

## 独立 MySQL 事务验证

`PlanningCommandFailureTransactionIntegrationTest` 使用真正的 Spring 事务代理、
DataSourceTransactionManager 和 MySQL InnoDB 行锁；shared-service 的存储适配器及方案
变更体为测试替身，通过同一 DataSource 的 JDBC 执行 SQL。这不是完整业务 ORM、HTTP 或 WS 验收。

测试只允许 `127.0.0.1:13306/zhiyuan_audit_test_*` 专用新库，
不访问或清理原会话库，不启动任何服务。通过连接级参数将锁等待限制为 3 秒。

最终 **4 项通过，0 failures / 0 errors / 0 skipped**：

| 场景 | 持久化结果 |
|---|---|
| 已修改方案后抛 40905 | 方案版本回滚；failed command 独立提交；原 pending 过期并记录 40905 |
| 独立审计事务写 pending 时失败 | 方案仍回滚；审计 insert 一并回滚；原 40905 不被覆盖 |
| 执行前真实版本漂移 | 当前方案不变；独立记录 failed / 40904 |
| 未预期运行异常 | 方案回滚；failed / 500 独立提交；回执不包含异常私有文本 |

通过库：`zhiyuan_audit_test_20261020_175438_809872`。
私有证据：`.local/codex-local/zhiyuan_audit_test_20261020_175438_809872/run.json`
及同目录 `integration.log`，均不提交。

首轮集成测试的 4 项失败来自测试适配器中的 Java 泛型可变参数推断：Mockito
`getArgument(0)` 被当作 `Object[]`，实际为 String。改用显式 String 局部变量后复跑通过；
未据此修改生产事务逻辑。首轮证据保留于独立库
`zhiyuan_audit_test_20261020_174754_349a12` 的同名私有目录，不能当作产品红例计数。

## 后续完整业务栈验收（2026-10-20）

新增 `PlanningCommandFailureStackIntegrationTest`：真实 Spring Boot、事务代理、MyBatis mapper、
shared-service、preview / prepare / pending claim / executor / 失败写入器。未模拟方案执行或存储层。
只对最终 `UnifiedPlanPostconditionValidator` 使用 spy，在失败场景先确认同一事务内已读到真实
方案写入与版本增加，再注入 40905；成功场景调用原 validator。TaskScheduler 被替换以阻止定时任务。

专用 datasource 和 Flyway URL 都强制指向 `127.0.0.1:13306/zhiyuan_audit_stack_*`，
并隔离 Redis 逻辑库和临时文件目录。使用源库的只读克隆；没有启动 HTTP 服务或操作已有服务进程。
测试依赖本地准备的夹具和克隆 schema，不是默认 CI 的数据库测试。

最终 **8 项通过，0 failures / 0 errors / 0 skipped**：

- 普通专业 Direct、普通专业 Search、专业组 Direct、专业组 Search 各验证一次写后失败：
  planningState 原 JSON 字节与版本回滚；failed command 独立持久化；原 pending expired；
  reconcile 返回 40905，回执不保存私有异常内容。
- 上述四种模式各验证一次正常提交和幂等重放；Search 回执另校验独立目标摘要及已验证目标结果。

最终修正后复验通过库：`zhiyuan_audit_stack_20261020_183530_4494ba`。私有证据为同名
`.local/codex-local/` 子目录中的 `run.json` / `integration.log`；源会话行哈希和运行 jar 均未变化。

首轮业务栈的两个失败来自测试误将 executor 的顶层 nullable `status` 当作成功权威；
实际回滚验证均已通过。测试改读真实 `postconditionReport.satisfied` 和 command 状态后通过。
该测试假设修正不算产品红例，证据保留在 `zhiyuan_audit_stack_20261020_181133_3d1aca`。

另补审计存储异常日志保护：只打印 operationId 和异常类型，不打印异常 message 或堆栈；
13 项执行审计测试中新增回归先红 1 项，再全部通过。审计本身失败仍保留原执行错误。
红绿日志：`/tmp/planning-failure-audit-log-red.log` / `/tmp/planning-failure-audit-log-green.log`。

与目标契约修复合并后的 fresh Java 全量：**1643 项，0 failures / 0 errors / 12 skipped**；
原有 10 项跳过，加两个 opt-in 数据库测试类默认跳过。Python 相关回归 **66 passed**。
最终日志：`/tmp/review-solver-contract-full-final-2.log` / `/tmp/review-solver-contract-python.log`。

独立审计事务的 4 项边界场景也已 fresh 复跑通过；专用库
`zhiyuan_audit_test_20261020_183012_733959`，同名私有目录保留 `run.json` / `integration.log`。
该 4 项仍是前节说明的 JDBC 存储适配器测试，不与完整业务栈的 8 项混称。

## 边界与后续

- 本轮是新 review 命令的正常异常路径审计，不改变其他动作族及 legacy 执行语义。
- `REQUIRES_NEW` 不是持久 outbox：进程在回调前退出、数据库不可用或独立审计事务失败时，
  仍不能承诺失败行必达。此时保留方案回滚和原异常，并记录审计写入错误；未增加自动重试。
- failed 行不纳入当前只清理 succeeded 的任务，避免误删失败证据；失败台账的归档策略仍需单独定义。
- 后续已补“确认目标原始摘要 / enrich+patch 后求解摘要 / 最终目标结果”的执行侧对照，
  见 `docs/superpowers/reviews/2026-10-20-review-solver-contract-verification.md`；仍未提交或部署。
- 真实模型驱动 WS、浏览器卡片端到端和更新后的真实服务验收仍未完成。
  本轮数据库事务测试不能替代这些发布验收。

## 用户批准后的分批提交与独立复验

本节属于后续本地提交阶段，不改写前文实现阶段“未提交”的事实。

- 第一批 `65f58a7` 仅包含失败独立审计、reconcile、日志脱敏与对应测试，共 9 个文件。
- 提交前在起点 `5574a46` 上单独应用该批，Java 全量 **1630 项，0 failures / 0 errors / 12 skipped**；
  同一 audit-only 快照的完整 Spring / MyBatis 栈 **8 项全部通过**。为保证拆批独立性，第一批不含
  Search 成功回执的新目标摘要断言；该断言随第二批提交。
- audit-only 快照位于 `/tmp/planning-review-submit-Ds1HZ3/audit-only/`；数据库证据位于
  `.local/codex-local/zhiyuan_audit_stack_20261020_184442_fdc462/`，manifest 记录了真实 `tested_project`。
- 第二批 `915a8df` 完成目标契约与专业组边界修复。完整最终源码快照 fresh 验证：Java **1652 项，
  0 failures / 0 errors / 12 skipped**；Python 相关 **66 passed**；完整业务栈 **8 passed**；
  独立 Spring 事务边界 **4 passed**。
- 最新两类数据库证据分别位于 `.local/codex-local/zhiyuan_audit_stack_20261020_190611_fadbbd/`
  和 `.local/codex-local/zhiyuan_audit_test_20261020_190627_773a9b/`。前者是真实 ORM 业务栈，后者仍有
  JDBC 存储适配器与变更体替身，不能混称。
- 原运行 jar、源会话行哈希和已有前端改动指纹保持不变；没有覆盖运行包或操作现有服务。

HTTP 隔离验收另记于 `2026-10-20-planning-integrity-stack-acceptance.md`；真实模型 WS、浏览器、
进程崩溃恢复、审计存储失败重投和 failed 归档仍不在本批完成声明内。
