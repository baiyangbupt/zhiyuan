---
task: P1b-3
status: PARTIAL（Python 半边完成；Java 半边已随 `23db5da` 落地，未由本会话实现）
executor: 本地会话（2026-09-21 晚，A7 复现过程中）
finished_at: 2026-09-22 00:30 +0800
source: docs/superpowers/tasks/P1b-3-snapshot-evidence/TASK.md
---

# P1b-3 报告：Snapshot 携带权威证据，且不再被进程内存盖掉

## 一、结论

任务书里的两件事，**现在的状态是一半已落地、一半由本会话补上**：

1. **Java `fillEvidence()`：已落地。** 不是本会话做的——`23db5da`（2026-09-21 08:40，
   "会话产物与幂等存储、招生来源接入、会话访问票据"）里已经实现，且**在真实栈上生效**：
   实测 `/inner/planning/1/session/turn-snapshot` 的回包里带 `evidence[]`，每条含
   `evidenceId` / `sourceLevel` / `dataVersion` / `sourceSystem` / `paramsDigest` /
   `expiresAt` / `scope` / `observedAt`。
2. **Python 覆盖行：本会话改掉。** `app/gateway/service.py` 的
   `working_set.evidence_refs = list(previous_working_set.evidence_refs)` 删除，
   证据改为**以 snapshot 为准**（进程内存里有、snapshot 里没有的一律丢弃）。

**为什么现在才做**：任务书写这句话时（09-13）`fillEvidence()` 是空方法体，"盖了也一样"；
它同时预判了"第 1 条一落地，这行立刻开始把权威数据盖成进程内存"。第 1 条落地了，
这行就变成活的 bug。**它还是 2026-09-21 那次"任何会话从第二轮起秒失败"的另一半**：
证据从第一轮跑工具时开始落台账，第二轮的快照才开始带证据，于是快照解析失败——
契约少三个字段（见第六节）。

## 二、交付

| 路径 | 变更 | 验证 |
|---|---|---|
| `zhiyuan-agent/app/gateway/service.py` | 删掉"证据从进程内存继承"那一行；留下注释说明为什么这里是**没有赋值**（"取交集"写成表达式会让行为边界看起来像实现细节）。同一个 `if` 块里其余五行未动（任务书明确要求） | 见第三节 |
| `zhiyuan-agent/tests/integration/test_shadow_gateway.py` | 新增 `test_evidence_follows_the_snapshot_not_the_process_memory` | 验收 4，红-绿对照 |

## 三、验收（任务书第五节 4 + 5）

任务书要求：**进程内存里有一条 snapshot 中不存在的 `evidence_ref` → 回合开始后它必须已被丢弃；
对照：snapshot 和进程内存都有的那条必须还在。** 对照是硬要求（本项目吃过"仪表恒为 `[]`
被读成没有调用"的亏）。

用例形状：第一轮模型经工具拿到 `ev-stale`（于是进程内存里有它），第二轮 Java 的快照
只有 `ev-valid`（= Java 已判定 `ev-stale` 不再 valid）。断言**第二轮注入给模型的
workingSet 载荷**：

```text
红（改之前）：ids = ['ev-valid', 'ev-stale', 'ev-stale', 'ev-stale']
绿（改之后）：ids = ['ev-valid']
```

红的那一次恰好还暴露了一件事：内存里的证据**会重复累积**（同一 id 出现三次）。
"以 snapshot 为准"顺带把重复也消掉了，但**去重不是这次的目的**，别把它当成已验证的性质。

```text
$ .venv/bin/python -m pytest tests/integration/test_shadow_gateway.py -q -k evidence
3 passed, 11 deselected in 0.23s
```

Python 全量（打真实 Redis，2026-09-22 00:2x）：

```text
$ CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9 .venv/bin/python -m pytest tests/unit tests/integration -q
1 failed, 1915 passed, 35 skipped, 22 warnings in 30.78s
```

唯一失败是 `test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture`
——它读的 `session_volunteer_*.json` 本机只有 11802971/11802972 两个（与 A7 报告第四节
记的是同一条，已有原始输出为证）。

## 四、Java 半边：验收项 1 **一开始不满足**，已补

### 4.1 实测：`listSessionEvidence` 当时只过滤过期，stale 照进快照

任务书要求"**只放 `valid`**……判定复用 `EvidenceLedgerService` 已有的四态逻辑"。
2026-09-22 00:5x 实测（真 MySQL + 真 Java，方法照抄
`zhiyuan-server/scripts/evidence_p1a_acceptance.sh` 第 6 步：改版本表摘要造 stale）：

```text
会话 900237 改之前 snapshot.evidence: [ev_…VPMR(schoolMajorScoreLine), ev_…ZDT(schoolMajorScoreLine), ev_…PMW(batchList)]
把 batchList 那条的 (source_system, params_digest) 在当前版本表里的摘要改掉（= 打成 stale）
改之后 snapshot.evidence: […VPMR, …ZDT, …PMW]     ← **stale 那条还在** ✗
```

原因：`listSessionEvidence` 只做了 `tenant_id / chat_session_id / expires_at > now` 三个条件，
**没有版本比对**——`verifyOne` 里那套四态逻辑（`currentDataVersion(sourceSystem, paramsDigest)`
与记录里的 `dataVersion` 比）没有被复用到这条路上。

### 4.2 改动（Java，本会话）

`EvidenceLedgerService.listSessionEvidence`：在遍历里补上版本比对，**复用 `verifyOne` 的同一套**
（同一个 `currentDataVersion` + 同一个「来源 + 参数摘要」缓存键口径），不一致就 `continue`。
不另写一套判定——任务书原话："两套判定迟早分叉，而分叉的方向一定是宽松那一边赢"。

| 路径 | 变更 | 验证 |
|---|---|---|
| `zhiyuan-server/.../EvidenceLedgerService.java` | `listSessionEvidence` 增加 stale 过滤（复用现成四态逻辑） | 见 4.3 |
| `zhiyuan-server/.../EvidenceLedgerServiceTest.java` | 新增 2 条（stale 被丢且 valid 仍在、版本行缺失也丢）；改 1 条既有用例的名字与铺陈（它原来只铺"未过期"，按新语义会被判 stale） | `mvn -o -Dtest=EvidenceLedgerServiceTest test` → 16 passed |

### 4.3 红-绿（同一实验，重打包并重启 backend 后重跑）

```text
打成 stale 之后: [ev_…VPMR, ev_…ZDT]
被打成 stale 的 ev_…PMW: 已消失 ✓
对照（其余 2 条）: 仍在 ✓
还原版本表后与改前一致: True
```

**对照是硬要求**：只断言"stale 不在"的话，"整个列表被清空"也能通过。

Java 全量：`Tests run: 783, Failures: 0, Errors: 0, Skipped: 6`。

端到端（重打包 + 重启 backend 之后，整套验收 1 遍 × 16 case）：
`16 通过 / 0 业务失败 / 0 环境失败`（`.runtime/zhiyuan-acceptance-after-stale-fix.json`）
——快照变严之后，链路上没有出现新的失败。

### 4.4 验收项 2（查库异常降级）**同样一开始不满足**，已补

任务书："查库异常 → **记 ERROR，返回空列表，snapshot 照常返回**。取证失败不放大成
取快照失败（与 `EvidenceLedgerService.sign()` `:114-119` 同一方向）。"

实测：`getTurnSnapshot` → `fillEvidence` → `listSessionEvidence` **一路没有 try/catch**，
DB 一抖异常就穿到控制器——链路上就是"当前会话状态暂时不可用"（本会话早些时候撞过的
那个用户可见症状），整轮对话跟着挂。红-绿：

```text
红（改之前）：两条新用例都是 ERROR —— RuntimeException("db down") 从 listSessionEvidence 穿出来
绿（改之后）：18 passed
```

改动：`listSessionEvidence` 的查询循环包 `try/catch (RuntimeException)`，`log.error` 后
返回空列表。**版本查不通时整批降级**是刻意的——分不出 valid 与 stale 的时候，宁可不摆到
模型面前，也不赌它们没过期（这一条写进注释了）。

Java 全量 `Tests run: 785, Failures: 0, Errors: 0, Skipped: 6`；重打包 + 重启 backend 后
用同一个 stale 实验复验取证路径：`3 条 → 打成 stale 后 2 条（stale 消失 ✓、对照仍在 ✓、
还原一致 ✓）`。

### 4.5 `expires_at IS NULL` 的口径差：已统一（2026-09-22 裁决）

原先两条路对"没有过期时间"的处置相反：快照那条（SQL `expires_at > now`）把 NULL **排除**，
核验那条（`verifyOne`）把 NULL 当**永不过期 → valid**。同一条记录两个口径。

**裁决：统一到 fail-closed** —— 没有过期时间 = **新鲜度未知** = `expired`（必须重查），
与四态里 `expired` 的定义（"新鲜度未知 → 必须重查"）一致，也与快照那条路一致。
改动在 `verifyOne`：`getExpiresAt() == null ||` 加进过期分支并早返回。

红-绿（同一条用例，临时还原旧判据跑）：

```text
旧判据：expected: <expired> but was: <valid>   ← 红
新判据：19 passed                              ← 绿
```

Java 全量 `Tests run: 786, Failures: 0, Errors: 0, Skipped: 6`；重打包 + 重启 backend 后
实盘抽查 `POST /internal/evidence/verify`（正常行仍是 `valid`，未误伤）。

**必须说清的一点**：`evidence_ledger.expires_at` 是 **NOT NULL**（V14），所以 NULL
只可能来自绕过约束的行或代码里造的实体——**这次统一是把缝堵上，不是修一个线上正在发生的错**；
也正因如此，它在真实栈上**造不出端到端场景**，证据只有单测这一层。

### 4.6 仍未验证

- **`unknown` 那一路**：`listSessionEvidence` 按 `(tenantId, chatSessionId)` 查，天然只可能
  拿到本会话的记录；"记录被删 → unknown"这种形状在这条路上**结构上不会出现**
  （查不到就是查不到），所以没有可造的场景。四态里的 `unknown` 只在 `verify` 端点那条路上可观测。

## 五、与 P1c 的边界（照任务书执行）

任务书明确：`service.py` 构造校验器账本这一段**不要动**，`output_validation.py` 的检查
**不要放宽**。本会话只改了那一行；账本那侧在工作区里已由 A 线改成
`merge_evidence(snapshot_evidence, turn_evidence)`——因此**实测模型引用权威证据的回合是成功的**
（随机取 3 条 rollout，末条都是 `task_complete` 且结构化输出里带 `ev_…` 证据 id）。
即：任务书预判的"引用必 `evidence_not_found`"在**当前工作区**已经不成立，P1c-1 的前提需要复核。

## 六、另一条：契约少三个字段（不是本任务的范围，但它挡住了本任务的验证）

Java 快照开始真的带证据之后的**第一小时**，任何会话**从第二轮起**秒失败
（`当前会话状态暂时不可用`）。根因：`ConversationEvidenceDTO` 比 Python 的 `EvidenceRef`
多 `sourceSystem` / `paramsDigest` / `expiresAt`，而 `EvidenceRef` 是 `extra="forbid"`，
于是**整条快照**解析失败。已在 `app/gateway/contracts.py` 收下这三个可选字段并补契约测试。
**这是越界改动，需要裁决**：若口径是"Java 不该发这三个字段"，删字段、改测试形状即可。
详见 A7 报告四之三。
