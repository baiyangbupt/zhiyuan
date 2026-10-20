# J5.5 Review Solver Contract Verification — 2026-10-20

> 状态更新：目标契约批已本地提交为 `915a8df`；下文保留原实现阶段证据，最新复核与提交前验证见末节。未推送或部署。

## 范围与状态

承接已批准设计 §2.5 / §4.3 / §4.4，修复 solver-backed review proposal 在冻结执行侧的目标摘要、
选择结果及硬目标结果校验。工作区基线 `5574a46`；当前改动未提交、未推送、未部署、未重启。
不表示全部 J5.5 或发布验收完成；审计批单列于
`docs/superpowers/reviews/2026-10-20-planning-failure-audit-verification.md`。

## 实现

1. 保留 `canonicalObjectiveDigest` 的 pre-enrich 口径。review frozen apply 写前用
   `compileConfirmed(state)` 对比 pending 顶层与 frozenProposal；目标不一致时返回 409
   `review_fix_objectives_changed`，没有方案写入。
2. 新增独立 `solverObjectiveDigest`，在 staged solver 接收已 enrich / patch 的目标时，按实际
   目标内容重新计算，不信任可能尚未重冻的 `objectiveDigest` 属性。审计摘要还包含 utilityModel
   和 diversityPolicy；不改变原 canonical 摘要算法或 solver inputDigest 算法。
3. 通过 solverResult → user-goal builder / Search / Safety / Ratio / RiskReplace → proposal →
   prepare pending 透传新摘要。所有八条 major / unit solver-backed review 预览路径均将它纳入
   previewDigest；即使最终选择相同，求解目标变化也必须重新预览。
4. 新增纯校验器 `ReviewSolverContract`：验证 pending / proposal / solverResult 的摘要与求解元数据
   一致、硬目标 major 可支持。新 audit digest 只用于冻结元数据一致性，不代替 confirmed digest，
   不在 apply 重建 solver 目标，也不重新求解。
5. 写前与写后保留原 finding probe，并校验 frozen selected / ordered identities、已冻结组内专业、
   working selection 与 ordered selection 一致。由最终状态的 actual selected facts 独立计数
   selection_target、已确认 coverage 与 tier bounds，与 frozen objectiveResults 逐项比对。
   缺失、重复、未知或数值不一致均 fail-closed，40905，交由原方案事务回滚。
6. review 执行回执携带已验证的 objectiveResults、canonical / solver 目标摘要、solver 版本及 inputDigest。
   回执复核使用执行阶段已做实时 factsDigest 校验的冻结 selectedFacts，不回读可能滞后的候选池缓存；
   写前/写后的核心校验仍使用当次 resolveEffectiveCandidates 的事实，不降低候选漂移检查。
   safety / churn / utility / diversity 阶段值不被错误提升为 confirmed hard objectives；原安全 finding
   的修复仍由原探针验证。
7. 旧 frozen review pending 若 pending / proposal / solverResult 三侧均无新 audit 字段，继续按现有
   canonical 与硬目标结果契约验证；单侧出现或不一致则拒绝。Direct 无 solver、开关关闭、user-goal
   原执行路径不新增上述 review 限制，无依赖或数据库迁移。

## 红绿与回归

- 首轮 90 项中 **8 failures / 0 errors**，分别复现目标摘要不检查、顶层与冻结元数据不一致、
  solver 审计摘要缺失/不一致、伪造 actualCount、删除 coverage 结果、冻结顺序与 solver 不一致。
  日志：`/tmp/review-solver-contract-red.log`；最小修复后原 90 项通过。
- 新增目标变化但 selection 不变时的预览绑定回归：11 项中 **1 failure / 0 errors**，补上所有
  solver-backed review previewDigest 的 solverObjectiveDigest 绑定后通过。
  日志：`/tmp/review-solver-preview-binding-red.log`。
- 新增 working selection 单独缺项回归：**1 failure / 0 errors**，证明原 finding probe 和正式方案
  正确仍不足以保证两份载体一致。补 working identities 校验后通过。
  日志：`/tmp/review-solver-working-selection-red.log`。
- 收尾 review 复现回执错误依赖旧候选缓存：单项先出现 **1 error**（业务 40905），并非编译或
  环境错误；即使核心执行已按权威事实通过，滞后缓存也会让回执误拒绝。改为上述已验证冻结事实
  后回归通过。日志：`/tmp/review-solver-receipt-facts-red.log`。
- 兼容回归覆盖旧 audit 字段全缺失、重复 objective 以及不支持的 hard-objective major，原 Direct、
  count / coverage / safety / ratio / risk 及专业组 apply 测试继续通过。
- 最终 Java 全量：**1643 项，0 failures / 0 errors / 12 skipped**，退出码 0。
- 最终 Python 确认客户端、review 候选生命周期和 plan-change 契约：**66 passed**，退出码 0。
- 完整 Spring Boot / MyBatis 专用克隆库：**8 项，0 failures / 0 errors / 0 skipped**。普通专业和
  专业组的 Direct / Search 分别验证真实写后失败回滚、失败独立审计，以及成功提交与幂等重放；
  Search 正常回执另验证新摘要及目标结果。仅失败注入替换最终 validator 行为，存储和执行均真实。
  最终修正后私有证据：`.local/codex-local/zhiyuan_audit_stack_20261020_183530_4494ba/run.json` 及同目录日志。

```bash
mvn -o -f zhiyuan-server/pom.xml test
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_pending_confirmation_client.py \
  tests/unit/test_review_fix_candidate_lifecycle.py \
  tests/unit/test_release_410_plan_change_contract.py -q --tb=short
```

最终日志：`/tmp/review-solver-contract-full-final-2.log` / `/tmp/review-solver-contract-python.log`。
两个数据库测试类默认 opt-in；完整业务栈需外部配置专用新库、隔离 Redis 与本地 fixture 文件，
不应直接用原库开启。真实数据库验收不是 HTTP / WS / 浏览器验收。

## 收尾与后续

- 原运行 jar 哈希和用户已有前端 diff 指纹未变化；暂存区为空，HEAD 保持 `5574a46`。
- 建议分两批审查提交：失败独立审计（含完整栈验证与日志保护）；目标摘要与冻结结果契约。
- 发布前仍需在受控环境重做 HTTP / 真实模型 WS / 卡片闭环验证，不能用单测或本次库内测试替代。
- 审计回调不是持久 outbox，进程崩溃窗口、审计存储失败恢复和 failed 台账归档仍需单列推进。

## 分批提交前追加复核与修复

用户随后批准复核、分批本地提交及隔离验收。本节补充该阶段事实，不将前文 1643 项历史验证改写为新结果。

### 追加边界

1. Search 必须携带 frozen solverResult。仅删除结果或连 solver 元数据一起删除时均须写前拒绝，
   不能误当作 Direct 的无 solver 兼容路径；仅真正的 `probability_inversion + SORT_BY_PROBABILITY`
   保留无 solver 路径。
2. 专业组 working units 中每组 majorItems 的身份及顺序必须与 ordered units 一致。
   上述两类共 3 项回归先红 **3 failures / 0 errors**，修后 apply 类 **65 passed**。
3. 独立复核再发现 coverage 重算误扫描组内全部 rawCandidates：未选中的池内匹配专业会把实际覆盖
   1 组误算为 2 组，拒绝合法修复。改用与 staged solver 相同的实际选择专业口径。
4. workingPlan.items 原未与其 units / majorItems 的平铺结果核对。新增空、缺项、乱序、未知身份
   四类拒绝回归；即使原探针和 ordered plan 正确，也不得写入不一致草案。
5. 旧组模式状态可能有 units 而无 volunteerModel。planner 已在副本归一，但 apply 原来直接按
   普通专业编译 confirmed digest，导致合法 coverage 提案误拒绝。现在先验证原始 planContentDigest，
   再仅对 solver-backed 且当前 units 非空的内存状态复用相同归一化；写前失败不落盘，成功执行及回执
   共用明确的 majorGroup 模式，不影响 Direct 路径。

后三类共 6 项先红 **6 failures / 0 errors**，分别命中业务 40905、目标摘要误拒绝及四类漏检；
legacy 案例进一步经完整 executor 再现，先红 **1 failure / 0 errors**。逐项修后通过，最终 apply 类
**71 passed**。独立只读复核确认三个 P2 均已关闭，未发现本次最小修复的阻塞风险。

### 最新提交前证据

- 审计批 `65f58a7` 先独立验证与提交；目标契约批 `915a8df` 共 17 个文件，暂存 blob 与实际验证的
  `/tmp/planning-review-submit-Ds1HZ3/complete/` 快照逐个一致。
- 完整离线 Java `package`：**1652 项，0 failures / 0 errors / 12 skipped，BUILD SUCCESS**。
  原运行 jar 未替换，临时 jar 只生成于该 `/tmp` 快照。
- Python 相关回归 **66 passed**；完整 Spring / MyBatis 业务栈 **8 passed**；独立 Spring 事务边界
  **4 passed**。数据库证据为 `zhiyuan_audit_stack_20261020_190611_fadbbd` 与
  `zhiyuan_audit_test_20261020_190627_773a9b` 同名私有目录。
- 红绿日志、完整 Java 打包日志和 Python 日志均位于上述 `/tmp/planning-review-submit-Ds1HZ3/`，
  分别为 `review-gates-*`、`group-review-red-final.log`、`group-legacy-executor-red.log`、
  `group-review-green-final.log`、`java-complete-package-final.log`、`python-related.log`。

隔离 HTTP 验收的实际结果另记于 `2026-10-20-planning-integrity-stack-acceptance.md`。
此处单测和数据库测试不替代 HTTP、真实模型 WS、浏览器或发布环境验收。
