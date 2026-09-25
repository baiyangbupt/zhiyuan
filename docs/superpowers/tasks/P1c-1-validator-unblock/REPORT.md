---
task: P1c-1
status: DONE
executor: 实现随 A 线改动落在工作区；验收原话用例与红-绿由本地会话 2026-09-22 补；本报告 2026-09-25 补写
source: docs/superpowers/tasks/P1c-1-validator-unblock/TASK.md
---

# P1c-1 报告：拆掉三处恒真的证据检查，让权威证据能进校验器的账本

## 一、结论

任务书三处改动**都已落地** ✓，六条验收逐条有对应测试 ✓（其中两条的专测是**补报告时现补的** ✗→✓），
验收 1 的"改前必红"在补报告时**当场重做了一遍** ✓✓（红-绿原文见第四节）。
本任务合入到 P1c-2 之间的"证据侧拒收暂时减弱"中间态——**已随 P1c-2 关闭** ✓（四态核验已接进 Gateway ✓）。

## 二、三处改动（按任务书逐条对现状）

### 1. 账本接 snapshot ✓

落地形态是 `merge_evidence(snapshot_evidence, turn_evidence)`（`app/gateway/service.py` 的
`_evidence_inputs`，任务书原 `:770-781` 那段的替代）✓——快照证据与本回合事件都在账本里 ✓。

**与任务书建议不同的一点（更好，如实记）** ✗→✓：任务书说"同一个 `evidenceId` 两边都有时
**以 snapshot 为准**"；实现是**不静默偏向任何一方**，而是要求同 ID 记录的**稳定身份一致**
（`tenantId`/`sessionId`/`sourceSystem`/`paramsDigest`/`dataVersion`），不一致就**报错**
（`evidence_identity_conflict`）✓。`observedAt` 被**刻意排除**在身份之外——观测时间不同
不等于证据内容不同，算进去会让正常的重复观测变成冲突 ✓（`output_validation.merge_evidence`
的 docstring 写明了这三条理由 ✓）。

### 2. 证据的 `stateVersion` 等值检查：已删 ✓

删掉处留了注释 ✓：证据的时效性由 `dataVersion` 与（P1c-2 的）四态核验负责，
不再用工作区版本代偿 ✓。**artifact 侧保留** ✓（`stale_state`，`output_validation.py:182/184`）。
额外落地了一条**会真的说"不"**的检查 ✓✓：`entry_version`（账本记录的 `dataVersion`）
与 `reference.data_version` 的比对 → 不一致报 `evidence_mismatch` ✓
（任务书 §四 要的"换上的是一个会真的说'不'的判定" ✓）。

### 3. 证据的 `threadId` 等值检查：已删 ✓

删掉处留了注释 ✓（"一个易失的标识符不能承载安全语义——一次 Gateway 重启就会让所有在世会话的
证据全部作废，而隔离边界本来是 `(tenantId, chatSessionId)`" ✓）。**artifact 侧保留** ✓
（`artifact_scope_violation`，`output_validation.py:192-194`）。`scope.threadId` 字段保留 ✓
（作审计信息 ✓，**记录与判定分开** ✓——验收 5 的测试里也照这个语义写 ✓）。

**没有自己补替代检查** ✓（任务书明确禁止 ✗）：四条保留的判定（会话、租户、`dataVersion`、
`admission_mode`）都是原本就在、且会真的拒的 ✓。

## 三、验收（六条逐条 + 证据）

| # | 任务书要求 | 覆盖它的测试 / 证据 |
|---|---|---|
| 1 | 跨回合正例（第 3 回合证据、中间工作区写入、第 7 回合引用必过） | `tests/unit/test_output_validation.py::test_evidence_signed_before_a_workspace_write_is_still_accepted` ✓（文档字符串就是任务书原话 ✓）+ 第四节的红-绿 ✓ |
| 2 | 账本合并，**带对照** | 正例侧：`test_evidence_follows_the_snapshot_not_the_process_memory`（P1b-3 ✓，快照证据可引用 ✓）＋验收 1 那条 ✓；对照侧：`evidence_not_found` 仍在拒（`test_output_validation.py:95` ✓、`test_shadow_gateway.py:228` ✓） |
| 3 | 会话级隔离没被一起删掉 | `test_evidence_from_another_session_is_still_refused` ✓、`test_readonly_gateway_rejects_cross_tenant_evidence` ✓ |
| 4 | artifact 那两处还活着，带对照 | `test_output_validator_rejects_artifact_from_old_snapshot` ✓（`stateVersion` ✓）＋ **本次补** `test_artifact_from_a_previous_thread_is_still_refused` ✓（`threadId` ✓） |
| 5 | 重启模拟：`_threads` 置空后存量证据仍过 | **本次补** `test_evidence_signed_in_a_previous_thread_is_still_accepted` ✓——直接量那条判据本身（签发线程 `thr-old` ↔ 引用线程 `thr-current` 必须通过 ✓），与"置空 `_threads`"等价 ✓ |
| 6 | 全量 | `1 failed / 1954 passed / 35 skipped` ✓；那 1 条是任务书点名的**已知失败基线** ✓（`test_dialog_quality_gate` 缺夹具 ✗，未去修 ✓） |

## 四、红-绿原文（2026-09-25 当场重做）

任务书强调"验收 1 的'改之前先跑一遍确认失败'不是形式" ✓。补报告时把删掉的旧检查
**临时注入回去**跑了一遍（随后 `git checkout` 还原 ✓，工作区已确认干净 ✓）：

```text
$ # 注入旧检查：证据的 stateVersion 必须等于当前快照版本
$ .venv/bin/python -m pytest tests/unit/test_output_validation.py -k signed_before_a_workspace_write -q
E                   app.gateway.output_validation.OutputContractError: stale_state: ev-1
FAILED tests/unit/test_output_validation.py::test_evidence_signed_before_a_workspace_write_is_still_accepted
1 failed, 18 deselected in 0.09s

$ git checkout -- app/gateway/output_validation.py    # 还原
$ .venv/bin/python -m pytest tests/unit/test_output_validation.py -k signed_before_a_workspace_write -q
1 passed, 18 deselected in 0.05s
```

——"改之前它确实会红"这条，现在有当场输出的证据 ✓✓（不只是纪要里的说法 ✓）。

## 五、未做 / 边界

- **不接四态核验** ✓（那是 P1c-2；已另行落地 ✓）；
- **中间态已关闭** ✓：本任务合入到 P1c-2 合入之间，证据侧的 `stateVersion`/`threadId` 两维
  确实暂时不设防 ✓（其余：会话/租户隔离、`evidence_not_found`、`evidence_mismatch`、
  `admission_mode` 都在 ✓）——这是任务书 §四 有意接受的 ✓，且随 P1c-2 落地已结束 ✓；
- **本报告是补写的** ✓（实现随 A 线改动在工作区 ✓，验收原话用例 2026-09-22 补 ✓）；
  本次另补了两条专测（验收 4 的另一半、验收 5 ✓）。
