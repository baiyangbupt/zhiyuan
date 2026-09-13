---
task: T008
verdict: ACCEPTED_WITH_FOLLOWUP
reviewer: claude-opus-5（设计会话）
reviewed_at: 2026-09-13
followup: T009
---

# T008 复核

## 一、判定

**`ACCEPTED_WITH_FOLLOWUP`。** 两项改动（解析层分层取值、仪表层恒写 `evaluation`）都已交付、都在边界内、验收由我独立重跑复现。遗留一项转 T009。

实现方自评 `DONE_WITH_CONCERNS`，两条偏离我都认可，见第五节。

---

## 二、我自己重跑了什么

按第七节协议，报告里的输出只用于比对差异，不用于替代复核。

| 验收 | 我跑的 | 结果 | 与报告一致？ |
|---|---|---|---|
| 第 1–6 条（新增单测） | `pytest tests/unit/test_codex_output_extraction.py tests/unit/test_codex_harness_client.py -q` | `28 passed in 12.34s`（12 新 + 16 既有） | 一致 |
| 第 7 条（全量单测） | `bash scripts/run_unit_tests.sh` | `2 failed, 1712 passed, 34 skipped, 22 warnings in 27.95s` | **逐字一致** |
| 第 8 条（真实端点 ×10） | 我自己的 10 次连跑，另起文件名 `/tmp/rev-t008-*` | **10/10 `hasEvaluation=True`，10/10 `passed=True`，10 次全是 `source=direct`** | 报告是 9/10，见第四节 |

两条失败与基线逐条对齐，无基线外新增失败：

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
```

通过数 1700 → 1712，差额 12 全部来自本任务新建的 `tests/unit/test_codex_output_extraction.py`，`34 skipped` 未变。**基线一节已按本任务更新。**

### 文件清单核对（并行工作树，按改动面分别核对）

`git status --short` 的总清单里有 16 项，但 T008 声明的只有 4 项。按台账「两个实现方同时在一个工作树里」一节的要求，不能只看总清单：

- **T008 面**：`app/harness/codex.py`、`app/harness/turn_result.py`、`scripts/codex_semantic_smoke.py`（M）+ `tests/unit/test_codex_output_extraction.py`（??）——**与报告声明逐条相符，无多无少**。
- **其余 12 项全部落在 `zhiyuan-server/`**：`GaotuClient`、`EvidenceSourceVersionMapper`、`ResponseDTO`、`EvidenceSourceVersionEntity`、`EvidenceLedgerService(+Test)`、新增 `EvidenceContentDigest(+Test)`、`V15__evidence_source_version_params.sql`、两个 evidence 脚本——**逐项落在 P1b-1 台账声明的改动面内**，不是 T008 的溢出。

`git diff --stat` 显示 T008 三个被改文件合计 `143 insertions(+), 26 deletions(-)`，与"两项定点改动"的量级相符，没有夹带。

### 边界

任务书列的边界文件我用 `git status --short --` 限定查过，输出为空：`app/engine/turn_trace.py`、`app/engine/` 整个目录、`tests/fixtures/`（含只读 MCP 夹具）、`docker-compose.codex-local.yml`。**一个都没被动过。** 含 `TURN_OUTPUT_SCHEMA` 的文件同样未出现在改动清单里。

---

## 三、代码本身

### 解析层

`_parse_json_object` 改成四层：`direct` → `fenced` → `embedded` → `missing`，每层报告命中来源。三处判断我逐行看过：

- **分层顺序是对的。** `direct` 在最前，纯 JSON 的 happy path 不经过任何正则，行为与改动前完全一致（对应验收 5）。
- **`fenced` 层扫全文所有围栏、取最后一个能解析成 dict 的**，并报告 `candidateCount`。取最后一个是对的：模型先给草稿再给定稿是常见形状，且 `candidateCount` 让"有多个候选"这件事可见，而不是静默选一个。
- **`embedded` 层**（`_find_outermost_braces`）用朴素深度计数，不感知字符串字面量里的花括号。**这个缺陷只会造成漏判、不会造成误判**——字符串里多出来的括号会让深度不平衡，切出来的片段解析失败，退回 `missing`。方向是安全的。这一层由任务书验收第 3 条明确授权（"防第 3 层兜底退化成抠片段"），并有中文花括号的负向用例把关。
- **`_extract_output` 保留原 `dict | None` 签名**，内部委托给新的 `_extract_output_ex`。既有 16 个 harness 单测全绿，向后兼容成立。
- 终态分支的 `or` 语义（`event_output or final_output`）被保留，`extraction` 跟着 output 走同一个三元判断，两者不会错配。

### 仪表层

`payload["evaluation"]` 现在在**全部三条路径**上都写：`outputValidationError` 早退分支（:264）、正常分支（:273）、缺失分支（:275）。函数体内再无"不写 evaluation 就返回"的路径。

`_missing_output_evaluation` **故意不合成 `trace`**，注释写明了理由（"there is no trace without an output"）。这个选择是对的，且正是规则 4 想要的：读 `payload["trace"]` 的消费方会拿到 `KeyError` 炸出来，而不是一个看起来正常的空 trace。**造一个假的 trace 会把这次修好的问题原样复刻到隔壁字段上。**

---

## 四、两项改动的证明强度不一样，必须分开说

这是本次复核最要紧的一条结论。

| 改动 | 真实端点上的证据 | 结论 |
|---|---|---|
| 仪表层（恒写 `evaluation`） | 20 次真实调用 **20/20** 出现 `evaluation` 键，其中 1 次是 `passed=False` 的真失败 | **在真实端点上被证明了**，且立刻抓到一次以前会静默的缺失 |
| 解析层（散文+围栏） | 20 次真实调用里 `source=fenced` 出现 **0 次**、`embedded` **0 次** | **只由单测证明**，真实端点没有复现过它要修的那个形状 |

**这不是缺陷，是任务书明确许可的**："解析逻辑由第 1 条单测负责证明，真实端点不负责复现低频事件。" 实现方没有去改场景或提示词强行复现，处理正确。但复核必须把这句话记下来：**解析层今天是"按设计工作"，不是"在生产上被验证过"**——T005 撞到的那个形状在 20 次里一次都没再出现，它是低频事件，低频不等于不存在。

### run 8 我独立查过，结论与报告不同层

报告只说"三条路径都没取到，属真实的没拿到输出"（符合规则 3，只列事实）。定性是我的活，我做了：

从 `/tmp/t008-run-8.json` 的 **671 个 `item/agentMessage/delta` 片段**重建模型原文，得到 2460 字符。内容是——

**模型把 JSON Schema 本身原样回吐了，而不是一个符合 schema 的实例**（`{"type":"object","required":["responseType","message","artifactRefs",...],"properties":{...}}`），**并且被截断了**，`json.loads` 报 `Invalid control character at: line 1 column 2445 (char 2444)`。

我把改动后的 `_parse_json_object` 直接喂给这段原文，返回 `(None, {'source':'missing','candidateCount':None})`。**`source: missing` 是正确读数，不是解析器失灵。**

这是一个**与 T008 要修的那个形状不同的失败模式**，而且是**被 T008 修好的仪表照出来的**——改动前这次运行会连 `evaluation` 键都没有，看起来跟"普通的没通过"没区别（正是 README 规则 4 记的那一条）。仪表修好的第一个产出就是让一个以前不可见的故障显形，这件事本身比 9/10 这个数字更能说明改动的价值。

### 可靠性的真实分母

| 来源 | 代码版本 | 结果 | 失败形态 |
|---|---|---|---|
| T005 复核时我跑的 8 次 | 改动前 | 7/8 | 散文 + 围栏，旧解析器够不着（**新代码能处理**） |
| 实现方 10 次 | 改动后 | 9/10 | schema 回吐 + 截断 |
| 我自己 10 次 | 改动后 | 10/10 | — |

**改动后合计 19/20 = 95.0%，Wilson 95% 置信区间 [76.4%, 99.1%]。**

置信区间必须写出来：20 个样本区分不了 80% 和 99%。**不要把"95%"当成已知量去做后续判断。**

---

## 五、两条偏离，都认可

1. **把 for 循环放进后台任务，每轮加时间戳。** 循环内真正产生判定的两条语句（脚本调用与内联判定 snippet，含 `'evaluation' in d` 而非 `.get()`）与任务书逐字一致；时间戳显示严格串行（下一轮 `starting` == 上一轮 `finished`）。**不影响判定口径，认可。**
2. **报告没能写进指定路径**：实现方的 Write 工具对报告类文件有策略拦截。**关键是它没有绕过**——没改用 Bash heredoc、没转派。这是正确处理：遇到策略边界就如实报告，而不是找路子翻过去。文件由我逐字转录，转录说明写在 `REPORT.md` 开头。

**同时更正一处署名。** 报告原文 frontmatter 写 `executor: deepseek`，实际执行方是 Claude subagent，不是本地 DeepSeek 会话。本协议里"谁做的"影响判定权重（同模型自评的可信度与异构实现方不同），因此必须准确。台账同步更正。

---

## 六、遗留：T009

> **本节已按复核后的实测更正，原说法被推翻，见第八节勘误。**

**`eventSummaries` 丢的是"拼好的那一份"，不是正文本身。** `scripts/codex_semantic_smoke.py:202-214` 构造摘要时只读事件顶层的 `text` / `message` / `delta`，而 agentMessage 的**完整正文**在 `event["item"]["text"]`，于是 6 条 `item/completed` 的摘要是空串。

但**正文并没有丢**：`item/agentMessage/delta` 的顶层 `delta` 键是被读到的，671 个片段逐个落盘了。把它们按序拼起来就是完整的 2460 字符原文（最长的片段只有 10 字符，**没有任何片段碰到 500 字符上限**）。

**所以这是人机工程问题，不是数据丢失问题**：要看模型写了什么，读的人得先知道"去 `eventSummaries` 里筛出 `item/agentMessage/delta` 再拼接"。**一个需要知道诀窍才能做的诊断，在真出事的时候就是不会有人做的诊断。** 修法很小——把 `item/completed` 的 `item.text` 也采下来，拼好的那份就有了。

顺带两条实测数据，T009 的任务书要用：单次运行的 `eventSummaries` 有 **1477–1725 条**、payload **228–260 KB**，其中 **95% 以上是 delta 片段**（run 8：671 条 agentMessage delta + 1034 条 reasoning delta）。真要动这段代码，delta 洪流的成本比正文更值得先想清楚。

这项不在 T008 的任务书范围内（那段构造代码本次未改动），实现方如实记录了现象而没有顺手改——**符合规则 3 和边界要求，处理正确**。转 T009。

### run 8 的失败原因可以说得更准

不是笼统的"截断"。拼出来的 2460 字符尾部是 `...{"type":["string","\n... (truncated)`——**模型自己吐了一个字面的 `... (truncated)` 标记，而它前面那个裸换行落在字符串字面量里**，这才是 `json.loads` 报 `Invalid control character at: line 1 column 2445 (char 2444)` 的直接原因。

合起来是：模型回吐 schema 而非实例 → 撞上某个长度限制 → 自己加了截断标记 → 产生非法 JSON。**三个环节，只有最后一个是解析器看得见的。**

---

## 七、另记两条待办

两条都**不属于 T009**：

- **schema 回吐这个失败模式本身**没有定性。模型在 `output_schema` 下回吐 schema 而非实例，与 P2 第 1 条（`executionStatus` / `limitations` / `nextStep` 被说进散文）是同一类问题的两个面：**模型没有把输出契约当契约**。建议并进 P2 一起定，不单开任务。
- **P0 第一条验收条的写法本身有问题**（规则 4 的对象是这条验收，不是被测系统）：「连续 3 次 `evaluation.passed == true`」被我这 10 次的前 3 次**字面满足**了。但连续 3 次通过的概率在真实可靠性 95% 时是 85.7%，90% 时是 72.9%，85% 时仍有 61.4%——**这个判据区分不了 85% 和 100%**。它不是恒真的检查（能失败），但它的分辨力低到接近没有。P0 收口时应改成带分母的形式（如"20 次中至少 19 次"），否则"P0 清零"这句话撑不住。

---

## 八、勘误（同日，写完本文后自查）

第六节原先写的是「**实现方无法从 payload 本身回看 run 8 模型到底写了什么**」。**这句话是错的**，实测推翻了它：从 `/tmp/t008-run-8.json` 的 `eventSummaries` 里筛出 671 个 `item/agentMessage/delta` 拼接，得到的正是那 2460 字符全文，字节不差。**信息一直在 payload 里。**

错因值得记下来：实现方报告第八节 2 说的是事实（`item/completed` 的 `text` 是空串），**我把它的含义放大了**——从"拼好的那份没采到"滑成了"正文采不到"。**报告只列事实是对的；把事实推成结论是我的活，这一步我推错了。**

代价是它会直接放大 T009 的范围：按错误的说法，T009 是"补采数据"；按实测，T009 是"把已有的碎片拼好存一份"，小得多。**在任务书写出去之前查出来，是这次没出事的唯一原因。**

这给第七节协议那条"重跑次数要够看出抖动"添一个同类项：**转述实现方的观察时，观察本身要复核，观察的推论更要复核。** 我复核了它报的每一个数字，却没复核自己给那些数字加上的那句解释。

---

## 七、可提交

改动落在 `zhiyuan-agent/` 四个文件，与 P1b-1 的 Java 改动零重叠，可单独提交，不影响 `zhiyuan-48` 正在进行的未提交工作。
