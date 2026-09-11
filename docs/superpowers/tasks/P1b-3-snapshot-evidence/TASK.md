# P1b-3：让 Snapshot 携带权威证据，并停止用进程内存覆盖它

> 指派：DeepSeek
> 来源：`docs/superpowers/plans/2026-09-10-P1权威证据台账设计.md` 4.5 / 5.2 / 第八章 P1b
> 类型：代码改动（Java + Python，两处，各自独立）
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

跨回合的证据现在走 Agent 进程内存，不走权威来源。两件事要修，**它们在同一条因果链上**：

1. **Java 不填**：`ConversationSnapshotService.fillEvidence()` 是空方法体，`snapshot.getEvidence()` 恒为空。
2. **Python 会盖**：`app/gateway/service.py:545` 用上一回合的进程内存覆盖从 snapshot 读来的证据。

第 2 条现在看起来无害——反正 snapshot 是空的，盖了也一样。**但它是个埋着的坑：第 1 条一落地，这行立刻开始把权威数据盖成进程内存。** 所以两件事必须一起改，单改第 1 条等于没改。

一句话验收：**构造一条 `stale` 证据和一条 `valid` 证据，`valid` 的出现在 snapshot 里、`stale` 的不出现；且进程内存里一条 snapshot 中不存在的证据，在回合开始后必须已被丢弃。**

---

## 二、背景（你的会话没有这些上下文）

系统分两层：Java (`zhiyuan-server`) 是权威数据层，Python (`zhiyuan-agent`) 是对话引擎。P1 要把"招生事实的证据"从 Agent 自己造，改成 Java 签发、Java 可复验。

P1a 已在 Java 侧建成台账：`evidence_ledger` 表、ULID 形式的 `evidenceId`（`ev_` 前缀）、以及四态核验——

| 状态 | 含义 |
|---|---|
| `valid` | 记录在、没过期、数据没变 → 可引用 |
| `stale` | **当时正确，现已失效** → 必须重查 |
| `expired` | 新鲜度未知 → 必须重查 |
| `unknown` | **从未成立** → 伪造或 bug |

`stale` 与 `unknown` 能分开，是这张表存在的核心理由。

Snapshot 是每回合发给模型的"你现在可以引用什么"。**它只应该装 `valid`**——把 `stale` / `expired` 放进去，等于邀请模型引用失效数据。

---

## 三、已核实的环境事实（不要重新调查，直接用）

| 事实 | 值 |
|---|---|
| Java 工程根 | `/root/dev/zhiyuan/zhiyuan-server`，构建 `mvn -o test` |
| Python 工程根 | `/root/dev/zhiyuan/zhiyuan-agent`，测试 `python -m pytest tests/ -q` |
| 空方法体位置 | `ConversationSnapshotService.java:177-181` |
| 它的调用点 | 同文件 `:48`，在 `getTurnSnapshot(Long tenantId, Long chatSessionId, String skill)` 里 |
| **`tenantId` / `chatSessionId` 在调用点都拿得到** | `:28` 的方法签名上就有，且 `:29-31` 已做非空校验 |
| 台账服务 | `EvidenceLedgerService`，`sign()` `:75`、`verify()` `:135` |
| 台账 Mapper | `EvidenceLedgerMapper` |
| 覆盖行 | `app/gateway/service.py:545`（`working_set.evidence_refs = list(previous_working_set.evidence_refs)`） |
| 正确的读取点 | `app/engine/working_set.py:77` 的 `from_snapshot()`，已经在从 `snapshot.evidence` 取，**这一处是对的，不要动** |
| 本地 MySQL/Redis | `bash scripts/codex-local-infra.sh start` |

---

## 四、步骤

### 步骤 1（Java）：实现 `fillEvidence()`

按 `(tenantId, chatSessionId)` 查本会话**当前 `valid`** 的证据，填进 `snapshot.getEvidence()`。

- `fillEvidence` 现在的签名是 `(List<ConversationEvidenceDTO> evidence, PlanningWorkspaceStateRes workspace)`。`workspace` 里没有证据（原注释说的是实话）。**把签名改成接收 `tenantId` / `chatSessionId`**，调用点 `:48` 跟着改。
- **只放 `valid`。** `stale` / `expired` / `unknown` 一律不放。判定复用 `EvidenceLedgerService` 已有的四态逻辑，**不要另写一套**——两套判定迟早分叉，而分叉的方向一定是宽松那一边赢。
- 原注释里那句 `do not synthesize or infer references here` **保留并加强**。它的含义从"暂不实现"变成"只透传，不推断"：这里只搬运台账里已有的记录，不补默认值、不推断、不合成。
- 查不到证据 → 空列表，**不是抛异常**。新会话本来就没有证据。
- 查库异常 → **记 ERROR，返回空列表，snapshot 照常返回**。取证失败不放大成取快照失败（与 `EvidenceLedgerService.sign()` `:114-119` 同一方向）。调用方拿不到证据只能降级，这是安全的那一边。

**`threadId` 拿不到，这是已知的。** `getTurnSnapshot` 的签名上没有它。按 `(tenantId, chatSessionId)` 查即可——会话级隔离已经够了，跨会话不泄露（P1a 第 8 步验收已证明换会话必 `unknown`）。**不要为了拿 `threadId` 去改 `getTurnSnapshot` 的签名或它的调用方**；线程级隔离的口径统一是另一件事，见第六节。

### 步骤 2（Python）：改成"以 snapshot 为准，进程内存只做交集"

`app/gateway/service.py:545`：

```python
working_set.evidence_refs = list(previous_working_set.evidence_refs)   # 现状：进程内存盖掉权威
```

改成：**`from_snapshot()` 拿到的权威集合是上界**。进程内存里有、而 snapshot 里没有的，**一律丢弃**——那说明 Java 已经判定它不再 `valid`。

按 `evidenceId` 取交集。丢弃是静默的还是要记一条 debug 日志，你定；但**不要把丢弃变成告警或异常**，证据随数据演进而失效是正常现象，不是错误。

**同一个 `if` 块里的其余五行不要动**（`candidate_entities` / `admission_facts` / `artifact_refs` / `last_response_type` 等）。它们各有各的正确性论证，不在 P1 范围。设计文档明写了这条边界。

---

## 五、验收

```bash
# === Java ===
cd /root/dev/zhiyuan/zhiyuan-server

# 1. 只放 valid（**必须带对照**）
#    同一会话造两条证据：一条 valid、一条 stale
#    （造 stale 的办法：改 evidence_source_version 让该记录的 data_version 比不中，
#      P1a 的 scripts/evidence_p1a_acceptance.sh 第 6 步就是这么干的，照抄）
#    断言：valid 那条出现在 snapshot.evidence 里
#    对照：stale 那条必须不出现
#    —— 没有这条对照，"valid 出现了" 也可能是因为把两条都放进去了
#
#    注意：P1b-1 正在把 evidence_source_version 的主键从 (source_system)
#    改成 (source_system, params_digest)。如果它先合入，你的造 stale 手法
#    要多带一个 params_digest 列。合入顺序不确定时，**优先写成不依赖表结构的
#    单测**（直接构造实体喂给判定逻辑），端到端那条作为补充。

# 2. 新会话取 snapshot → evidence 为空列表，不抛异常

# 3. 全量
mvn -o test

# === Python ===
cd /root/dev/zhiyuan/zhiyuan-agent

# 4. 进程内存里有一条 snapshot 中不存在的 evidence_ref
#    → 回合开始后它必须已被丢弃
#    对照：snapshot 和进程内存都有的那条必须还在
#    —— 没有对照，"被丢弃了" 也可能是因为整个 evidence_refs 被清空了

# 5. 全量
python -m pytest tests/ -q
```

验收 1 和 4 的**对照是硬要求**。本项目吃过亏：曾有一个仪表恒为 `[]`，被当成"没有调用"读了很久，其实是仪表根本没通电（`README.md` 规则 4）。**只做正向断言的验收，通过和坏掉长得一模一样。**

### 已知失败基线（不是你造成的，不要去修）

Java：`mvn -o test` 当前 `Tests run: 708, Failures: 0, Errors: 0, Skipped: 5`，**无失败**。

Python：

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1700 passed, 34 skipped
```

只有这两条。出现第三条就是本次引入的。

---

## 六、边界：不要做这些

- **不要动 `app/mcp_server/tools_readonly.py`、`app/util/internal_client.py`、`app/mcp_server/server.py`。** 那是 **P1b-2** 的文件，正在被另一个会话同时改。
- **不要动 `GaotuClient.java`、`ResponseDTO.java`、任何 migration，也不要改 `EvidenceLedgerService` 里 `sign()` / `verify()` / `currentDataVersion()` 三个已有方法的实现。** 那是 **P1b-1** 的改动面，也在被同时改。

  **但你大概率需要在 `EvidenceLedgerService` 上加一个只读方法**（比如 `listValid(tenantId, chatSessionId)`），这是允许的，规则是：**只增不改**——新增方法可以，动已有方法体不行。同理 `EvidenceLedgerMapper` 可以加查询方法（P1b-1 不碰这个文件，它改的是 `EvidenceSourceVersionMapper`）。

  两个任务会同时改 `EvidenceLedgerService.java`，**这是已知的、可接受的**：改动落在文件的不同区域，合并由设计会话负责。**在报告第六节明确列出你新增了哪些方法**，别让合并的人去猜。
- **不要动 `app/gateway/output_validation.py`。** 那是 P1c。
- **不要动 `working_set.py:77` 的 `from_snapshot()`。** 它已经是对的。
- **不要改 `getTurnSnapshot` 的签名或调用方**去拿 `threadId`。
- 不要"顺手"重构、格式化、改 import 顺序。
- **不要 commit。** 改完等 review。

**关于线程级隔离的口径不一**（P1a 复核跟进项 4，**本任务不解决，知道就行**）：`EvidenceLedgerService.verifyOne()` `:167-170` 只在请求与记录的 `threadId` **都非空**时才校验线程；而 Agent 侧 `output_validation.py:126-145` 在 `strict_scope=True` 时要求 scope 字段必须存在。Java 比 Agent 松。影响面封在单会话内（`tenantId` + `chatSessionId` 仍强制），不构成跨会话泄露。**这件事归设计会话裁决**——要么 Java 侧也要求必填，要么写明"线程级隔离由 Agent 侧负责"。你遇到它时不要自行收紧或放宽，在报告里提一句即可。

---

## 七、报告

写到 `/root/dev/zhiyuan/docs/superpowers/tasks/P1b-3-snapshot-evidence/REPORT.md`，格式见 `_templates/REPORT.md`。

状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`；验收命令贴**原始输出**；不写修复建议、不写下一步、不写根因推测。

验收 1 和 4 的正向与对照**分别贴输出**，不要合并成一句"通过"。
