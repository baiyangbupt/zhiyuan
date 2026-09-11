# P1b-2：打通 Java 签发的证据到 Agent 的链路（三处断链）

> 指派：DeepSeek
> 来源：`docs/superpowers/plans/2026-09-11-P1a证据到不了Agent的三处断链.md`（全文，**先读完再动手**）
> 类型：代码改动（Python 为主）
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

P1a 在 Java 侧建成了证据台账并接上了签发点。但**签出来的证据在生产链路上一次都到不了模型**——三处互相独立的断链，任一处不修，另外两处修了也白修。

本任务把三处全修好，让 `admission.get_history` 的返回里真的带着 Java 签发的证据。

一句话验收：**`admission.get_history` 走真实 `InternalClientBackend`（不是手写桩）时，返回的 `evidence[*].evidenceId` 以 `ev_` 开头，而不是 `admission-unit:…:unknown`。**

---

## 二、背景（你的会话没有这些上下文）

系统分两层：Java (`zhiyuan-server`) 是权威数据与业务校验层，Python (`zhiyuan-agent`) 是对话引擎。P1 的目标是**把"招生事实的证据"从 Agent 自己造，改成 Java 签发、Java 可复验**。

现在 Agent 自己造证据：`tools_readonly.py:277-296` 拼一个 `admission-unit:<id>:<版本或 unknown>` 当 `evidenceId`，还自己盖上 `"sourceLevel": "authoritative"`。**"权威"这个章目前 100% 是 Agent 自己盖的，Java 从未参与。**

P1a 建好了 Java 侧的签发机制。P1b 要把它接上。接的过程中实测发现，链路上有三个洞，它们**各自独立**：修好任何一个，另外两个仍然会让证据丢失，且现象都是"回落到自铸证据"——看起来一切正常。

---

## 三、三处断链（已逐跳实测确认，不要重新调查，直接修）

### 断链 1：scope 根本没上路

Java 侧 `EvidenceLedgerService.sign()` 要求 `EvidenceScope`（`tenantId` + `chatSessionId` + `threadId`）完整，缺任一即返回 `null` 不签发。这个 scope 应该由 Python 传过去，但四跳全漏：

| 位置 | 情况 |
|---|---|
| `app/mcp_server/server.py:209-212` | 构造 `InternalClientBackend` 时只传了 `tenant_id` / `chat_session_id`，**`thread_id` 连拿都没拿**（`binding` 上有，`tools_readonly.py:290` 就在用） |
| `app/mcp_server/tools_readonly.py:366-370` | `get_history()` 只往下传 6 个业务参数，scope 一个没传 |
| `app/util/internal_client.py:1699-1706` | `query_school_major_score_line()` 的签名里根本没有 scope 的位置 |
| `app/util/internal_client.py:71-77` | `HttpClient.post()` **没有 `params` 形参**，只有 `headers`。JSON body 里的键绑不到 Java 的 `@RequestParam` |

最后一跳是关键：Java 侧 `GaotuClientDebugController:113-117` 把 scope 声明成 `@RequestParam`（查询串），Python 只发 JSON body。**两边永远对不上，Java 收到的恒为 `EvidenceScope.of(null, null, null)`。**

### 断链 2：信封在读到证据之前就被拆掉了

`app/mcp_server/tools_readonly.py:334-336`：

```python
@staticmethod
def _data(response: Any) -> Any:
    return response.get("data") if isinstance(response, dict) and "data" in response else response
```

P1a 把 `evidence` / `dataVersion` 挂在 **`ResponseDTO` 信封层**（与 `data` 平级）。`_data()` 只留 `data`，把信封连同证据一起扔了。

**这一处与断链 1 完全独立**：就算 scope 接通、Java 真签出了证据，证据也会在回到 Agent 的**下一个函数调用**里被丢掉。然后 `tools_readonly.py:262` 找不到 `source_evidence`，落进 `:277-296` 的自铸分支，产出 `admission-unit:…:unknown`——**正是 P1 要废掉的那个东西**。

### 断链 3：形状对不上

`querySchoolMajorScoreLine` 的返回类型是 `ResponseDTO<List<QuerySchoolMajorScoreLineRes>>`，`data` 是一个 **JSON 数组**。而 `tools_readonly.py:213-221`：

```python
def _admission_envelope(self, name: str, result: Any) -> dict[str, Any]:
    mode = self.binding.admission_mode
    if not isinstance(result, dict):
        return error("insufficient_data", "admission backend returned no structured data", ...)
```

接上真实 backend 后这个分支**无条件命中**。现象是 `admission.get_history` 结构性地永远返回 `insufficient_data`——而这不是"数据不足"，是形状不对，**错误码报错了地方**。

### 为什么三层测试一处都没照出来

- `tests/unit/test_domain_mcp_tools.py:378-391` 是唯一碰 `InternalClientBackend` 的测试，测的是 `get_current_plan`，桩返回 `{"code": 0, "data": {"items": []}}`——`data` 是 dict，**正好绕过断链 3**。
- `:395` 往后所有 admission 测试用手写 `Backend` 桩，直接返回 `{"dataVersion": "v17", "admissionFacts": [...]}`——**消费者期望的形状**，不是生产者真实产出的形状。
- P1a 的端到端验收在 Java 侧测的，压根没跑 Python。

三层各自都有效，缝隙全在层与层之间。这条教训已写进 `README.md` 第六节：**桩的形状要从生产者那一侧取，不要从消费者的期望那一侧编。** 本任务的步骤 4 会强制执行它。

### 附带发现（顺手修）

`tools_readonly.py:109-111` 在 `major_group` 模式下要求 `groupCode` 必填，而 `get_history`（`:366-370`）通过 `**arguments` 收下它之后**默默丢掉**，从不往下传。

---

## 四、步骤

**必须按这个顺序做。** 理由见步骤 5。

### 步骤 1：让 scope 走到 Java（修断链 1）

四跳都要补：

1. `app/mcp_server/server.py:209-212`：构造 `InternalClientBackend` 时加上 `thread_id=binding.thread_id`。
2. `app/mcp_server/tools_readonly.py`：`InternalClientBackend.__init__`（`:330-332`）接收并保存 `thread_id`；`get_history()`（`:366-370`）把三个 scope 值往下传。
3. `app/util/internal_client.py:1699-1706`：`query_school_major_score_line()` 加三个可选的 scope 形参。
4. `app/util/internal_client.py:71-77`：`HttpClient.post()` **加一个可选的 `params` 形参**，透传给 `session.post(url, json=..., params=..., headers=...)`。

**scope 走查询串，不走 header，也不塞进 JSON body。** 三条理由：

- Java 侧 `GaotuClientDebugController` 已经把它声明成 `@RequestParam`，这是 Java 作者定的形状，照着接就行；
- 走 header 要同时改两个仓库，两边发版不同步期间会静默退回"不签发"；
- 塞进 body 会污染业务参数，而 Java 那边 `toParams(request)` 拿 body 去算 `paramsDigest`——**scope 一旦进 body，同一查询在不同会话里会算出不同的参数摘要**，台账直接失去按查询聚合的能力。

`HttpClient.post` 的 `params` 是**新增可选形参**，现有调用方一个都不用改。

**另一个签发端点也要一起接**：`app/util/internal_client.py:1693` 的 `/program/query-by-limit-num` 对应 Java 的 `queryProgramByLimitNum`，同样声明了三个 `@RequestParam` scope。两个都接，不要只接一个——漏掉的那个就是将来不带证据的路径。

### 步骤 2：保住信封（修断链 2）

不要动 `_data()` 本身——它有 **9 处调用，分布在 8 个方法里**，其中 6 个方法（7 处调用）确实只关心 `data`，只有 `get_history` / `check_eligibility` 这两个需要信封。

给 admission 相关的取数路径**单开一条保留信封的通道**：`get_history` / `check_eligibility` 返回完整响应（或返回一个同时带 `data` 和 `evidence`/`dataVersion` 的结构），让 `_admission_envelope` 能读到证据。具体怎么切你定，但要满足：

- **不改 `_data()` 的行为**，其余 6 个调用方零影响；
- `_admission_envelope` 能拿到 `evidence` 和 `dataVersion`；
- 不要在 Python 侧**重命名或改写** Java 给的证据字段——原样透传。Agent 不是证据的作者。

### 步骤 3：对齐形状（修断链 3）

`_admission_envelope` 要能吃下 `data` 是**数组**的情况。

字段名从哪来：**`src/main/java/com/ytell/zhiyuan/model/dto/gaotu/res/QuerySchoolMajorScoreLineRes.java`**（11 个字段）。逐个读，按它的 `@JSONField` / 字段名映射。

> **不要凭 `_admission_envelope` 现在期望什么来反推形状。** 那正是断链 3 的成因。在报告里写明每个字段你是从哪个 Java 文件的哪一行取的。

现有的 `not isinstance(result, dict)` → `insufficient_data` 分支**不要直接删**。改成：形状能识别就走正常路径；**真的无法识别时仍要报错，但换一个能区分的错误码**（比如 `unexpected_shape`），不要继续借用 `insufficient_data`。"数据不足"和"形状不对"是两件事，混用会让下一个人重走这次的弯路。

### 步骤 4：补一条从生产者形状出发的测试（**这是本任务最重要的产出**）

新增单测：**用真实信封形状**喂 `InternalClientBackend.get_history`，断言：

1. 结果能被 `_admission_envelope` 正常吃下（不落 `insufficient_data`、不落 `unexpected_shape`）；
2. `evidence` 没丢；
3. 返回的 `evidenceId` 以 `ev_` 开头。

"真实信封形状"指：`{"code": 0, "data": [ …按 QuerySchoolMajorScoreLineRes 的字段构造… ], "msg": "ok", "timestamp": …, "errorMsg": "", "isSuccess": true, "dataVersion": "…", "evidence": [...]}`。

信封键集是实测过的（2026-09-11 真实上游），**不要自己另编一套**。

再加一条防回归测试（设计文档 5.1 要求）：**任何工具结果里出现 `sourceLevel == "authoritative"` 而 `evidenceId` 不以 `ev_` 开头，即失败。** 自铸证据是个"看起来能跑"的失败模式，很容易被后来的人以"补个默认值"的名义加回来。

### 步骤 5：**最后**才删自铸分支

删掉 `tools_readonly.py:195-203` 和 `:277-296` 两处合成分支。Java 没给证据时**不造**，走已有的降级路径（`limitations` 追加 `evidence_unavailable`，`:314` 的 `result_status` 自然落到 `insufficient_data`）。

> **必须排在 1–4 之后。** 先删会让 `admission.get_history` 从"返回自铸证据"变成"返回无证据"——两种都不对，但后者会让 `fact` 输出直接整轮 fail closed，把一个静默的错误放大成全线挂。

### 步骤 6：顺手修 `groupCode`

`get_history`（`:366-370`）把 `groupCode` 往下传，别再默默丢掉。

---

## 五、与 P1b-1 的关系（必读）

P1b-1 是**并行任务**，改的是 Java 侧的版本口径（把 `dataVersion` 从上游字段改成 Java 对 `data` 算的内容摘要）。**文件零重叠**，你们可以同时开工。

但有一条你必须知道：**真实上游不返回 `dataVersion`**（已实测）。所以在 P1b-1 落地之前，接真实上游时 Java 签不出证据，你的验收项 3（`evidenceId` 以 `ev_` 开头）**在真实上游上不可能通过**。

因此：

- 步骤 1–4、6 的验收**用 `zhiyuan-server/scripts/evidence_fake_upstream.py` 做**，这是正当的——**你测的是 Python 侧的管道，替身在这里是被测对象的输入，不是外部世界的证人**。
- 但步骤 4 的测试数据**形状必须从 Java DTO 取**，不能从替身脚本取。替身返回的 `data` 是 dict，真实的是数组——照替身抄就会原样复制断链 3。
- 如果 P1b-1 还没合入而你跑不通端到端，**如实报 `DONE_WITH_CONCERNS` 并写明卡在哪一步**，不要为了让验收变绿去改 Java 侧的版本逻辑（那是 P1b-1 的边界）。

---

## 六、陷阱

1. **`_data()` 有 9 处调用、覆盖 8 个方法。** 改它的行为会波及 resolve（2 处）/ search_schools / get_school / search_majors / get_major / get_current_plan。步骤 2 要求的是**另开通道**，不是改它。
2. **`InternalClientBackend.__init__` 的签名变了，`tests/unit/test_domain_mcp_tools.py:387` 会受影响。** 那是现存唯一碰它的测试，改测试是本任务的一部分。
3. **`admission.check_eligibility` 与 `get_history` 走不同的后端方法**（`check_major_subject_availability` vs `query_school_major_score_line`），两者的 `data` 形状也不同。不要假设修好一个另一个自动好了——**逐个确认**。
4. **不要在 Python 侧复算 `paramsDigest`。** 摘要是 Java 算的，Agent 不参与签发。Python 侧出现 SHA-256 就说明走偏了。
5. **不要放宽 `output_validation.py` 的校验来让链路"通"。** 那是 P1c 的文件，且放宽校验恰好摧毁整个设计的目的。

---

## 七、验收

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# 1. 新增的生产者形状测试（步骤 4 的三条断言）
python -m pytest tests/unit/test_domain_mcp_tools.py -v -k "<你的新测试>"

# 2. 防回归测试：authoritative 且非 ev_ 开头必须失败
#    对照：故意构造一条 evidenceId="admission-unit:x:unknown" 且
#    sourceLevel="authoritative" 的结果，测试必须挂。
#    —— 没有这条对照，"测试通过"也可能是因为断言压根没跑到。

# 3. 现有 MCP 工具测试不回归
python -m pytest tests/unit/test_domain_mcp_tools.py -v

# 4. 全量
python -m pytest tests/ -q

# 5. 端到端（配 evidence_fake_upstream.py）：
#    调 admission.get_history，断言返回的 evidence[*].evidenceId 以 ev_ 开头。
#    对照：把步骤 1 的 scope 传递注释掉再跑一次，必须退回 insufficient_data
#    或无证据 —— 这条对照证明 scope 确实起作用了，而不是碰巧走了别的路。

# 6. 贴出一次真实调用的 HTTP 请求行（含查询串），证明三个 scope 参数确实发出去了。
#    Java 侧日志里能看到 sign() 没有因 scope 不完整而早退，更好。
```

验收 2 和 5 的**对照**不是可选的。没有对照的"通过"证明不了任何事——这是本项目的四条硬规则之一（`README.md` 规则 4）。

### 已知失败基线（不是你造成的，不要去修）

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1700 passed, 34 skipped
```

只有这两条。出现第三条就是本次引入的。

---

## 八、边界：不要做这些

- **不要动 `zhiyuan-server/` 的任何文件。** scope 走查询串正是为了不改 Java。若你认为**必须**改 Java 才能完成，**停下来报 `NEEDS_CONTEXT`**，说明卡点，不要自己动手——P1b-1 正在同时改 Java 侧。
- **不要动 `app/gateway/output_validation.py`。** 那是 P1c。
- **不要动 `app/gateway/service.py:545`。** 那是 P1b-3。
- **不要改 `_data()` 的行为。**
- **不要删或放宽任何现有防线**：夹具数据不得升格为招生事实（`output_validation.py:76-91`）、跨线程证据拒收（`tools_readonly.py:165-174`）、`dataVersion` 缺失整体降级（`:298`/`:314`）。
- 不要"顺手"重构、格式化、改 import 顺序。
- **不要 commit。** 改完等 review。

---

## 九、报告

写到 `/root/dev/zhiyuan/docs/superpowers/tasks/P1b-2-evidence-passthrough/REPORT.md`，格式见 `_templates/REPORT.md`。

状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`；验收命令贴**原始输出**；不写修复建议、不写下一步、不写根因推测。

步骤 3 的字段映射**逐个注明来源行号**。这是本任务的核心交付之一——不是形式要求，是防止再犯同一个错。
