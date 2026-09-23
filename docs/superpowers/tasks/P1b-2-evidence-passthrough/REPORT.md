---
task: P1b-2
status: NEEDS_CONTEXT
executor: deepseek
finished_at: 2026-09-13 19:25 +0800
---

# P1b-2 报告

## 一、结论

按设计侧裁决，**步骤 1（scope 四跳）与步骤 6（groupCode）已完成并验过**；**步骤 2 / 3 / 4 / 5 未做**，等 (a) 的裁决——分数线究竟是「真实存在录取率只是没开通道」还是「全仓从未产出过录取率」，这两种情况下的写法相反，不猜。

另：步骤 3 的原始前提（「按 `QuerySchoolMajorScoreLineRes` 的 11 个字段映射即可让 `_admission_envelope` 吃下数组」）经查不成立，证据见第四节命令 7；设计侧已确认这是任务书的洞。

## 二、交付物

| 路径 | 变更 | 说明 |
|---|---|---|
| `zhiyuan-agent/app/util/internal_client.py` | +46 −2 | `HttpClient.post()` 新增可选 `params`；新增 `_evidence_scope_params()`；`query_school_major_score_line()` 加 scope 三参 + `group_code`；`query_program_by_limit_num()` 加 scope 三参 |
| `zhiyuan-agent/app/mcp_server/tools_readonly.py` | +14 −2 | `InternalClientBackend.__init__` 接收并保存 `thread_id`；`get_history()` 下传 scope 三值与 `groupCode` |
| `zhiyuan-agent/app/mcp_server/server.py` | +1 | 构造 `InternalClientBackend` 时补 `thread_id=binding.thread_id` |

`zhiyuan-server/` 一行未动（本次只在 `zhiyuan-agent/` 改动）。

## 三、实际改动的文件

```
 M zhiyuan-agent/app/mcp_server/server.py
 M zhiyuan-agent/app/mcp_server/tools_readonly.py
 M zhiyuan-agent/app/util/internal_client.py
```

（上表仅列本任务改动；工作树中另有 `zhiyuan-server/` 下 P1b-1 的改动与 `docs/superpowers/` 下设计侧的改动，均不属本任务。）

## 四、验收命令与原始输出

### 命令 1：新增的生产者形状测试

**未做**——属于步骤 4，依赖步骤 3 的形状判断，等裁决。

### 命令 2：防回归测试（authoritative 且非 `ev_` 开头必须失败）

**未做**——属于步骤 4，同上。

### 命令 3：现有 MCP 工具测试不回归

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_domain_mcp_tools.py -q
```

```
......................                                                   [100%]
22 passed in 0.37s
```

### 命令 4：全量

```bash
.venv/bin/python -m pytest tests/ -q
```

```
=========================== short test summary info ============================
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1730 passed, 43 skipped, 22 warnings in 27.92s
```

两条失败与任务书列出的基线**逐字同名**，无第三条。

### 命令 5：端到端

**未做**——需与步骤 2/3 一起做（信封要留着才看得到 `evidence`），等裁决。

### 命令 6：真实调用的 HTTP 请求行（证明三个 scope 确实发出去了）

用一个只记录请求行、不解析业务的本机回环服务接住调用，把 `http_client.base_urls` 指过去：

```bash
PYTHONPATH=/root/dev/zhiyuan/zhiyuan-agent .venv/bin/python /tmp/p1b2-request-line.py
```

```
--- 1) query_school_major_score_line（带完整 scope + groupCode）---
POST /gaotu-assistant-bot/inner/gaotu/score-line/query?tenantId=7&chatSessionId=42&threadId=thread-1 HTTP/1.1
  Content-Type: application/json

--- 2) query_program_by_limit_num（另一个签发端点）---
POST /gaotu-assistant-bot/inner/gaotu/program/query-by-limit-num?tenantId=7&chatSessionId=42&threadId=thread-1 HTTP/1.1
  Content-Type: application/json

--- 3) 不传 scope（应无查询串，退回不签发）---
POST /gaotu-assistant-bot/inner/gaotu/score-line/query HTTP/1.1
  Content-Type: application/json
```

两个签发端点都把三个 scope 挂在查询串上；不传 scope 时查询串为空——**第 3 组即第 5 条验收所要求的那个方向的对照的最底层证据**（scope 确实在起作用，不是碰巧走了别的路）。scope 走查询串而非 body，第 3 组也顺带证明 body 未被污染。

`_evidence_scope_params` 的空值剔除行为：

```
scope full:    {'tenantId': 7, 'chatSessionId': 42, 'threadId': 'thread-1'}
scope partial: {'tenantId': 7}
```

### 命令 7：步骤 3 前提不成立的证据（本任务另一项产出）

```bash
sed -n '110,155p' zhiyuan-agent/app/admission/facts.py
cat zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/gaotu/res/QuerySchoolMajorScoreLineRes.java
grep -rn "admissionFacts\|AdmissionFactDTO" --include=*.java zhiyuan-server/src/main
```

- `validate_admission_fact` 必需：`admissionUnitId`、`schoolId`、`majorId`(major 模式)/`groupCode`(major_group 模式)、以及录取率；录取率只认 `unitAdmissionRate` / `admissionRatio` / `schoolEnrollRatio`，且注释明写「不对缺失数据填充或猜测」。
- `QuerySchoolMajorScoreLineRes` 的 11 个字段是 `year/name/batch/batchTitle/enrollNum/maxScore/minScore/averageScore/minPos/maxPos/selectInfo`——**没有 `admissionUnitId`、没有 `schoolId`、没有任何录取率字段**。逐行都会在 `admission_rate_required` 处被跳过，`facts` 恒为空，`result_status` 恒为 `insufficient_data`。
- `AdmissionFactDTO`（带身份与录取率）只出现在 `ConversationTurnSnapshotDTO.admissionFacts`，**没有任何 HTTP 端点返回它**。

## 五、与已知失败基线的对照

| 失败用例 | 在基线内？ | 说明 |
|---|---|---|
| `tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture` | 是 | 与任务书基线同名 |
| `tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]` | 是 | 与任务书基线同名 |

无基线外失败。**计数与任务书写的 `1714 passed, 34 skipped` 不一致**（实跑 `1730 passed, 43 skipped`），失败集合本身逐字相同——按任务书「只有那两条失败，出现第三条就是本次引入的」的判据，本次未引入失败。

## 六、偏离任务书之处

1. **步骤 6 的落点**：`get_history` 现在把 `groupCode` 放进请求体（`payload["groupCode"]`）而不是丢弃。需要说明的是 **Java 侧 `QuerySchoolMajorScoreLineReq` 只有 `areaId/batch/majorId/schoolId/year/subjectType` 六个字段，没有 `groupCode`**，因此这个值被送到了 Java 但不会被其消费（Spring Boot 默认忽略未知 JSON 字段，不会 400；且 Java 的 `toParams(request)` 从 DTO 取参数，`paramsDigest` 不受影响）。任务书只写「往下传」，没有指定落点，我选了不改 Java、不发明映射的最小做法，实际语义等价于「不再默默丢掉」。
2. **`InternalClientBackend.__init__` 的 `thread_id` 做成可选带默认值**（任务书陷阱 2 预期签名变化会波及 `tests/unit/test_domain_mcp_tools.py:387`）。做成可选后该测试无需改动即通过（命令 3），因此没有改它。
3. `query_program_by_limit_num` 只加了 scope 形参；它当前的调用方（`app/tools/*`）没有 scope 可传，故未改调用方——任务书要求的是「两个签发端点都接上」，指的是函数具备发 scope 的能力，这一点已具备（命令 6 第 2 组）。
4. 步骤 1 的 `_evidence_scope_params` 顺带剔空值（`tenantId`/`chatSessionId`/`threadId` 为空时不拼进查询串）。任务书未提，但 Java 侧声明的是 `required = false`，空串拼进去反而会让 `EvidenceScope.of("", ...)` 之类落到"不完整"分支。

## 七、未做的事

- **步骤 2**（保住信封）：未做。设计侧确认「必须和数组处理一起做」——`_admission_envelope:230` 的 `payload = dict(result.get("data") or result)` 在 `data` 是数组时会直接抛 `TypeError`，单独做等于把 `insufficient_data` 换成崩溃。
- **步骤 3**（对齐形状）：未做。等 (a) 裁决。已定：形状来源取生产者侧 `QuerySchoolMajorScoreLineRes`（ruling (b)）；`check_eligibility` 原样透传布尔、不接事实、不进事实账本（ruling (c)）。
- **步骤 4**（生产者形状测试 + 防回归测试）：未做，依赖步骤 3。
- **步骤 5**（删自铸分支）：未做，依赖步骤 2/3/4，且任务书要求排在其后。
- 命令 2 要求的「防回归对照」（故意构造 `evidenceId="admission-unit:x:unknown"` + `sourceLevel="authoritative"` 必须让测试挂）随步骤 4 一并做。

## 八、观察到的异常现象（只列事实）

1. 全量测试计数与任务书基线不一致：任务书写 `1714 passed, 34 skipped`，实跑 `1730 passed, 43 skipped`；失败集合逐字相同（两条）。未推测原因。
2. `zhiyuan-agent/app/util/internal_client.py` 的 `HttpClient.post()` 原有 39 处调用，全部使用 `endpoint=` 关键字形式（无位置传参），因此把新形参 `params` 插在 `json_data` 之后不会移动任何既有实参。
3. 设计侧已更正其先前说法：`scripts/codex-local-infra.sh` 确实出现在 P1b-1 任务书第四节里（P1b-1 报告偏离第 6 条已如实记录该文件不存在），并非我记串。

---

## 附：裁决 (a) 已查清（2026-09-22，事实核查，非偏好）

**结论：这条路（以及全仓）从未产出过录取率。** 依据三条，都可复核：

1. **生产者侧没有这个字段**：`zhiyuan-server/.../dto/gaotu/res/QuerySchoolMajorScoreLineRes.java`
   共 11 个字段——`year / name / batch / batchTitle / enrollNum / maxScore / minScore /
   averageScore / minPos / maxPos / selectInfo`。**没有率**，也没有可当率用的比率字段。
   即：`admission.get_history` 这条路上**结构上不可能**带出录取率。
2. **契约里有、没人填**：`AdmissionFactDTO.unitAdmissionRate` / `AdmissionMajorDetailDTO.majorAdmissionRate`
   只出现在 DTO 声明里；全仓 `grep` 不到任何 `setUnitAdmissionRate` / 构造 `AdmissionFactDTO` 的生产代码
   （`ConversationTurnSnapshotDTO` 只是持有这个列表）。Java 今天不产出率。
3. **Python 侧明说是"上游算好的"**：`app/admission/tool_results.py:117` 的 `normalize_probability`
   注释写着"上游已算好的录取概率……缺真实接口时这项能力显示不可用，而不是用别的东西凑一个
   看起来像概率的数"，缺率时追加 `unit_admission_rate_missing` 并降级——**不是**补零。

**对步骤 3/4 的直接含义**：形状对齐严格按 `QuerySchoolMajorScoreLineRes` 的 11 个字段来，
**不要为"率"预留位置、不要补默认值**；测试的"真实信封形状"里也不该出现率。

---

## 附二：步骤 2–5 的复核（2026-09-22）

裁决 (a) 查清之后回头核对工作区，发现**步骤 2–5 早已落地**（台账那句『2–5 等裁决』
已经过期），逐条核对如下：

| 步骤 | 状态 | 证据 |
|---|---|---|
| 2 保住信封 | **已做** | `tools_readonly.py::_history_envelope`：`normalize_history({"data": result.get("data")}, …)` + `evidenceRefs = result.get("evidence")`（**原名原样**，没有重写字段）+ limitations/stateVersion/admissionMode |
| 3 对齐形状 | **已做（换了实现方式）** | 数组分支带注释『真实上游的 `data` 是**数组**』；`check_eligibility` 的布尔**单列一条分支**（注释写明它以前被 `insufficient_data` 吞掉）——这正是任务书要的『能区分』，只是没用 `unexpected_shape` 这个码 |
| 4 生产者形状测试 + 防回归 | **测试已做，护栏没做 → 本次补上** | 已在：`test_real_array_data_does_not_break_the_envelope`、`test_java_evidence_id_survives_the_mcp_layer_unchanged`、`test_no_evidence_means_no_evidence_not_a_self_minted_one`；**缺**：`authoritative ⇒ ev_` 前缀的护栏（全仓 `grep` 不到），本次补在 `app/mcp_server/response.py::ok()`（所有工具结果的唯一收口）+ 2 条测试（含对照），红-绿：去掉护栏即 1 failed |
| 5 删自铸分支 | **已做** | `tools_readonly.py` 里自铸点只剩注释：『这里曾经在无证据时自铸一条 `ev-{name}` / sourceLevel=authoritative』 |

**一句话验收（真栈）**：`POST /internal/evidence/verify` 的入参
`evidenceIds=[ev_01M32ZZS7DS5A84CPMEWCX3C88, ev_01M32ZZQT136FF92VTDVZ1FZ4D]`
——是 Java 签发的 ULID，不是 `admission-unit:…:unknown` ✓。

**没复跑的一条对照**：验收 5 要求的『把步骤 1 的 scope 传递注释掉再跑一次，必须退回
无证据』。步骤 1 当时已验过（台账记『已完成并验过』），本次**没有复跑**这条对照——
它要临时改运行时接线并重启，我没有把它算成已验。
