# P1c-1：拆掉三处恒真的证据检查，让权威证据能进校验器的账本

> 指派：DeepSeek
> 来源：`docs/superpowers/plans/2026-09-13-P1c证据校验器的三处结构性拒收.md`（**先读完再动手**，尤其第五、六节）
> 类型：代码改动（Python）
> 协议：`docs/superpowers/tasks/README.md`
> **前置：P1b-2 与 P1b-3 都已合入。** 没有它们，本任务的验收构造不出来。

---

## 一、目标

P1b 让 Java 签发的证据真正到达 Agent 并进入 snapshot。但 `output_validation.py` 有三处检查会把它们**全部拒收**——三处今天都恒真、从未真正做过判定，证据一变成跨回合的真东西就全部转为恒假。

本任务把这三处修好。**不接四态核验**（那是 P1c-2），本任务只负责让权威证据不再被结构性拒收。

一句话验收：**第 3 回合产出的证据，在中间发生过一次工作区写入之后，第 7 回合引用它必须通过。** 这一条在当前代码上必然失败。

---

## 二、背景（你的会话没有这些上下文）

系统分两层：Java (`zhiyuan-server`) 权威数据层，Python (`zhiyuan-agent`) 对话引擎。P1 把"招生事实的证据"从 Agent 自铸改成 Java 签发、可复验。

`app/gateway/output_validation.py` 是回合输出的契约校验器，逐条检查模型引用的证据。它的逐条检查**本身是好的**，P1 明确要保留。问题在于其中三条检查的**前提**已经变了。

---

## 三、三处要改的地方（已逐行核实，不要重新调查）

### 1. 账本没接 snapshot（`app/gateway/service.py:770-781`）

```python
evidence_ledger = _by_id(
    _collect_records(
        [turn.get("evidenceLedger", []), turn.get("events", [])] if isinstance(turn, Mapping) else [],
        "evidenceLedger", "evidence", "evidenceRefs", "evidence_refs",
    ),
    "evidenceId", "evidence_id",
)
```

账本**只**来自本回合 codex turn events。P1b-3 用 `fillEvidence()` 填进 snapshot 的权威证据一条都不在里面 → `output_validation.py:127` `entry is None` → `evidence_not_found` 硬失败。

**改法**：账本合并 `working_set.evidence_refs`（来自 snapshot 的权威集合）与本回合 turn events。

**冲突处理**：同一个 `evidenceId` 两边都有时，**以 snapshot（权威）那份为准**。理由：本回合 turn events 里的那份是工具结果里带回来的同一条记录，但 snapshot 那份经过了 Java 的 `valid` 过滤。两份不一致时权威的那份更可信。

### 2. `stateVersion` 等值检查（`app/gateway/output_validation.py:137-146`）

```python
entry_state = _field(entry, "stateVersion", "state_version")
if entry_state not in (None, ""):
    parsed_state = int(entry_state)
    if parsed_state != snapshot.snapshot_version:
        raise OutputContractError("stale_state", evidence_id)
if reference.state_version is not None and reference.state_version != snapshot.snapshot_version:
    raise OutputContractError("stale_state", evidence_id)
```

证据记的是**签发那一刻**的 `stateVersion`；`snapshot_version` 每次工作区写入都推进。于是第 3 回合的证据在第 7 回合必然 `stale_state`。

**改法**：**删掉证据的这两个 `stateVersion` 等值检查。**

语义上它们本来就是错的：工作区版本推进的是**我们的方案**，不是**招生数据**。用户第 3 回合查到的投档线，不会因为第 4 回合往方案里加了一所学校就不可引用。

> **`artifact_refs` 那边（`:168-171`）的同名检查保留，不要动。** 产物确实绑定在产生它的工作区版本上——那个检查是对的。**只删证据这一侧。**

### 3. `threadId` 等值检查（`app/gateway/output_validation.py:131-133`）

```python
entry_thread = _scoped_field(entry, "threadId", "thread_id")
if (strict_scope and thread_id and entry_thread in (None, "")) or (thread_id and entry_thread not in (None, "", thread_id)):
    raise OutputContractError("evidence_scope_violation", evidence_id)
```

`app/gateway/service.py:372` 的 `self._threads` 是**纯进程内 dict，从不持久化**，`:654-663` 一个 session 一个 thread、懒创建。**Gateway 一重启，同一 session 拿到新 thread，存量证据全部 `evidence_scope_violation`。**

**改法**：**删掉证据的 `threadId` 检查。**

裁决依据（2026-09-13，设计笔记第四节）：thread 与 session 是 1:1，不存在"同一会话的两个线程"，且 **thread_id 会随进程重启而改变——这样的标识符不能承载安全语义**。隔离边界是 `(tenantId, chatSessionId)`，Java 侧一直强制。

> **`artifact_refs` 那边（`:175-176`）的同名检查保留，不要动。**

`ConversationEvidenceDTO.scope.threadId` 字段**保留**，作为审计信息记录"这条证据在哪个线程下签的"，但不参与准入判定。**记录与判定是两件事。**

---

## 四、这是在放松校验吗？——必须讲清楚，验收也要证明

是，方向上是放松。以下是它不等于 fail-open 的理由，**你的验收要证明这段话是真的**：

> 删掉的两个检查**今天恒真、从未做过判定**（证据每回合自铸、填的就是当前值）。而"这条证据还作不作数"这个问题，由 P1a 已经建好的**四态核验**回答——`valid` / `stale` / `expired` / `unknown` 四态都已在 P1a 验收里被真实构造出来并正确区分。**换上的是一个会真的说"不"的判定。**

但有个时序上的坑：**四态核验要到 P1c-2 才接进 Gateway。** 也就是说本任务合入后、P1c-2 合入前，证据这一侧的拒收能力**确实是暂时减弱**的（会话级隔离、`evidence_not_found`、`evidence_mismatch`、`admission_mode_mismatch` 都还在，减弱的是 `stateVersion` / `threadId` 那两维）。

**这是有意接受的中间态，理由写在设计笔记第六节**：反过来先接核验、不删这两条，结果是两道门都关着，`fact` 回合永远出不去——那不是更安全，那是功能不存在。

**你要做的是**：在 `output_validation.py` 删除处**留注释**写明"证据的时效性由 `/internal/evidence/verify` 四态核验负责（P1c-2 接入），此处不再用 stateVersion/threadId 代偿"，并在报告里明确写出本任务合入后到 P1c-2 之间存在这个中间态。**不要为了让它看起来安全而自己补一个替代检查**——那会变成第四个恒真的检查。

---

## 五、验收

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# 1. 【核心】跨回合正例 —— 这条在改之前必然失败
#    第 3 回合产出证据 → 做一次工作区写入让 snapshot_version 推进
#    → 第 7 回合引用它 → 必须通过
#    建议先在未改的代码上跑一遍确认它确实失败（贴出失败输出），再修到通过。
#    两次输出都要贴 —— 这是本任务唯一能证明"问题真实存在过"的证据。

# 2. 【核心】账本合并 —— 带对照
#    正向：只在 snapshot 里、不在本回合 turn events 里的证据，引用后必须通过
#    对照：一个两边都不存在的 evidenceId，必须仍然 evidence_not_found
#    —— 没有对照，"通过了" 也可能是因为把 evidence_not_found 整个删了

# 3. 【核心】会话级隔离没被一起删掉
#    换一个 session 引用同一个 evidenceId → 必须仍然被拒
#    （entry_session 检查在 :129-130，不要动它）

# 4. 【核心】artifact 那两处检查还活着 —— 带对照
#    构造一个 stateVersion 与当前不符的 artifact_ref → 必须仍然 stale_state
#    构造一个 threadId 与当前不符的 artifact_ref → 必须仍然 artifact_scope_violation
#    —— 这条防止你把证据和产物两侧一起删了

# 5. 重启模拟：清空 self._threads 后，存量证据引用必须仍然通过
#    （直接把 gateway 的 _threads 置空即可，不必真的重启进程）

# 6. 全量
python -m pytest tests/ -q
```

**验收 1 的"改之前先跑一遍确认失败"不是形式。** 本项目的三条方法论规则之一就是：**恒真的检查和坏掉的检查在测试里长得一模一样**（`README.md` 第六节）。先看到它红，才能证明后来的绿是修好了，而不是测试没跑到。

### 已知失败基线（不是你造成的，不要去修）

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1700 passed, 34 skipped
```

P1b-2 / P1b-3 合入后通过数会变。**以你开工时实际跑出来的数为准，并在报告里写明这个基线数**——否则下一个人无法区分"新增用例"和"漏跑用例"。

---

## 六、边界：不要做这些

- **不要接 `/internal/evidence/verify` 四态核验。** 那是 **P1c-2**，本任务只清障。
- **不要动 `output_validation.py` 里 `artifact_refs` 那一段**（`:160` 往后）。
- **不要动证据的这些检查**，它们都是对的：`evidence_not_found`（`:127`）、`entry_session` 会话隔离（`:129-130`）、`entry_tenant` 租户隔离（`:134-136`）、`dataVersion` 比对（`:147-149`）、`admission_mode`（`:150-152`）、`admissionUnitId`（`:153-155`）、`admission_evidence_missing`（`:118-119`）、`non_authoritative_admission_fact`（`:76-91`）。
- **不要自己补一个替代检查**来"弥补"删掉的两维。见第四节。
- **不要动 `zhiyuan-server/`。** 本任务纯 Python。
- **不要动 `app/mcp_server/`、`app/util/internal_client.py`。** P1b-2 的地盘。
- 不要"顺手"重构、格式化、改 import 顺序。
- **不要 commit。** 改完等 review。

---

## 七、报告

写到 `/root/dev/zhiyuan/docs/superpowers/tasks/P1c-1-validator-unblock/REPORT.md`，格式见 `_templates/REPORT.md`。

状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`；验收贴**原始输出**；不写修复建议、不写下一步、不写根因推测。

两件事必须在报告里明确写出来，不要含糊：

1. **验收 1 改之前的失败输出**，和改之后的通过输出，**分别贴**。
2. **本任务合入后到 P1c-2 之间存在校验能力的中间态**（见第四节）。如实写出来是本任务的正确交付，不是缺陷。
