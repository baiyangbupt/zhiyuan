# P1c-2：四态核验接进 Gateway + 第六章分流表 + 重查一次

> 指派：本地会话（本任务书由执行方按设计文档翻译，2026-09-22）
> 来源：`docs/superpowers/plans/2026-09-10-P1权威证据台账设计.md` 5.3 / 第六章 / 第八章 P1c
> 类型：代码改动（Java + Python，两处，各自独立）
> 协议：`docs/superpowers/tasks/README.md`
> **前置：P1b-2、P1b-3、P1c-1 都已到位。** P1c-1 的三处拒收已在工作区落地
> （账本 `merge_evidence(snapshot, turn)`；证据侧的 `stateVersion`/`threadId` 等值检查已删，
> artifact 侧保留），2026-09-22 补了它的验收用例并红-绿验证。

---

## 一、目标

P1a 建成了四态核验（`/internal/evidence/verify`），P1b 让权威证据进了 snapshot，
P1c-1 拆掉了三处结构性拒收。**但没有任何生产代码调用核验端点**——证据的权威性
目前是"摆到模型面前就算数"，而不是"每次引用都去问一次台账"。

两件事：

1. **Java**：`currentDataVersion()` 查不到版本记录时返回 `""`，于是比对必然不等、
   `verifyOne` 判成 `stale`。**"我没有当前版本的记录"与"当前版本跟你签的不一样"
   是两个不同的问题**，四态里的 `unknown` 正是为前者准备的。
   （P1b-1 REVIEW 第六节；V15 的 `DROP TABLE` 撞上它会让全部在世证据判 `stale`——
   报出来的却是"上游数据变了"，处置完全不同。）
2. **Python**：在现有的逐条校验**之前**插入一次批量核验，按设计文档第六章分流。

一句话验收：**模型引用一个不存在的 ID → 整轮 `evidence_not_authoritative`，
且用户侧没有任何自然语言兜底输出；引用一条 `stale` → 恰好触发 1 次重查，
仍失败则整轮 fail closed。**

---

## 二、背景（你的会话没有这些上下文）

Java 是权威数据层，Python 是对话引擎。证据由 Java 签发（`sign()`）、Java 可复验
（`verify()` 返回四态）。四态的含义：

| 状态 | 含义 |
|---|---|
| `valid` | 记录在、没过期、数据没变 → 可引用 |
| `stale` | 当时正确，现已失效 → 必须重查 |
| `expired` | 新鲜度未知（过了 `expires_at`，或无 `expires_at`）→ 必须重查 |
| `unknown` | 从未成立（台账里没有）→ 伪造或 bug |

**第六章分流表（逐态写死，照抄，不要自行发挥）**：

| 核验状态 | Gateway 行为 | 理由 |
|---|---|---|
| 全部 `valid` | 继续现有校验链 | — |
| 任一 `unknown` | **硬失败**，`OutputContractError("evidence_not_authoritative", <id>)`，整轮作废，**不重试** | 台账里没有就是没发生过。重试只会让模型再编一遍 |
| 任一 `stale` / `expired`，且被 `fact` 类输出引用 | **拒绝本轮输出**，把失效 ID + `sourceSystem` + `paramsDigest` 回注给模型，要求重查后重新作答；重查上限 **1 次**，仍失败则整轮 fail closed | 失效是正常数据演进，值得给一次重查机会；但不能无限循环 |
| 任一 `stale` / `expired`，仅被非 `fact` 输出引用 | 剥离该引用，输出继续 | 非事实表述不承载招生数据，无需重查 |
| Java 不可达 | **硬失败**，不放行 | 验证不了就不能盖权威章。这里放行等于把 fail-closed 改成 fail-open |

最后一条是**最容易手滑**的地方（"依赖不可用时放宽校验"非常自然），必须写进注释并配单测。

---

## 三、已核实的环境事实（不要重新调查）

| 事实 | 值 |
|---|---|
| 核验端点 | `POST /internal/evidence/verify`，`EvidenceLedgerController`；请求 `{tenantId, chatSessionId, threadId, evidenceIds}`，响应 `{results: {<id>: {status, sourceSystem, paramsDigest, dataVersion, observedAt, expiresAt}}}` |
| 四态判定 | `EvidenceLedgerService.verifyOne`（`stale`/`expired`/`unknown`/`valid`）；Python 侧无任何调用方 |
| 空版本串 | `currentDataVersion()` 查不到记录返回 `""` → `verifyOne` 现在判 `stale`（**本任务要改成 `unknown`**） |
| 校验入口 | `app/gateway/service.py` 的 `_codex_turn`：`evidence_ledger = merge_evidence(...)`（`:1052`）→ `validate_turn_output(...)`（`:1069`）；逐条检查在 `app/gateway/output_validation.py` |
| 重查的现成先例 | `_repair_turn_output`（`service.py:1171`）：拿一条指令再跑一轮 `start_turn_and_collect` 并取结构化输出。**重查走同一机制**，只是指令不同 |
| 一轮的账本语义 | `evidence_ledger` 参数**保留**，语义收窄为「本回合工具结果的自洽性检查」；权威性由新的核验步骤负责。**两层都要过** |
| Python 内部客户端 | `app/util/internal_client.py`（尚无 verify 调用；`http_client` 失败会抛） |

---

## 四、步骤

### 步骤 1（Java）：版本记录缺失 → `unknown`，不是 `stale`

`EvidenceLedgerService.verifyOne`：`currentDataVersion(...)` 返回空串时，
状态给 `unknown`（"我没有当前版本的记录"），不再落到 `stale`（"当前版本跟你签的不一样"）。
**只改这一个判定**；`listSessionEvidence` 那条路（快照只放 valid）不受影响——
空串与记录的 `dataVersion` 天然不等，仍旧进不了快照，那是它该有的行为。

配单测：版本行缺失 → `unknown`；**对照**：版本行在但摘要不同 → 仍是 `stale`。

### 步骤 2（Python）：批量核验客户端

`app/util/internal_client.py` 新增 `verify_evidence(tenant_id, chat_session_id, evidence_ids, thread_id)`
→ 调 `POST /internal/evidence/verify`，返回 `{evidenceId: status}`。
**Java 不可达时必须抛**（沿用 `http_client` 的既有行为），由调用方按"硬失败"处理——
不要在客户端里降级成空结果。

### 步骤 3（Python）：分流表

新增 `app/gateway/evidence_verification.py`，把第六章的表写成**纯函数**：

```python
def classify(output, statuses) -> Decision   # Decision ∈ PROCEED / STRIP / RECHECK / FAIL
```

- `FAIL` 带码（`evidence_not_authoritative`）与被拒的 ID；
- `STRIP` 带要剥掉的 ID 列表；
- `RECHECK` 带失效 ID + `sourceSystem` + `paramsDigest`（回注给模型用）；
- 只被非 `fact` 输出引用才允许 `STRIP`；被 `fact` 引用一律 `RECHECK`。

纯函数的好处是六行分流表可以逐行写单测，不需要起栈。

### 步骤 4（Python）：接进 `_codex_turn`

- 在 `validate_turn_output` **之前**调用核验（注入式：`GatewayService` 新增
  `evidence_verifier` 参数，测试可替身；生产接步骤 2 的客户端）。
- `PROCEED` → 照旧。
- `STRIP` → 从 `output.evidenceRefs` 里去掉那些 ID，再走现有校验链。
- `RECHECK` → 走 `_repair_turn_output` 同款机制跑**一次**重查指令（把失效 ID 与
  `sourceSystem`/`paramsDigest` 回注），拿到新输出后**再核验一次**；仍不合格 → 整轮 fail closed。
  **上限 1 次，不许写成循环。**
- `FAIL` → `OutputContractError`，整轮作废、**不重试**。
- Java 不可达（客户端抛） → `OutputContractError("evidence_verification_unavailable")`，
  **不许放行**；注释里写清为什么。

---

## 五、验收

**Java**

```bash
cd zhiyuan-server && mvn -o -Dtest=EvidenceLedgerServiceTest test
```
- 版本行缺失 → `unknown`；**对照**：版本行在但摘要不同 → `stale`。

**Python（单测，逐行覆盖分流表）**

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_evidence_verification.py tests/unit/test_gateway_evidence_flow.py -q
```
1. 全部 `valid` → 输出通过。
2. 任一 `unknown` → 整轮作废，`evidence_not_authoritative`，**输出为空**
   （"用户侧没有任何自然语言兜底"是 fail-closed 的实质，光看错误码不够）。
3. `stale` 且被 `fact` 引用 → 恰好 1 次重查；再次核验仍失败 → 整轮 fail closed
   （**断言调用次数 = 1**，不是"小于等于"）。
4. `stale` 只被非 `fact` 引用 → 该引用被剥离，输出继续。
5. Java 不可达（客户端抛） → 整轮硬失败，**不放行**。
6. **真栈那条**：停掉 backend（或指向不可达端口）跑一轮 → 整轮硬失败。
   设计文档原话："不能用 mock 断言'如果不可达就失败'——那只测了 mock"。

**端到端**：跑整套验收（`scripts/evaluate_zhiyuan_acceptance.py`，1 遍即可），
确认灰度路径没有因为这次接入而系统性变红。

---

## 六、边界（不要越界）

- **不动** `output_validation.py` 的逐条检查（P1c-1 已划完边界，artifact 侧两处保留）。
- **不动** `listSessionEvidence`（快照只放 valid 已由 P1b-3 定稿）。
- 重查**只允许 1 次**；不做退避、不做队列。
- 分流表**不许加行**（例如"`stale` 且非 fact 但用户问的是分数"这类细化）——
  要加先改设计文档。
