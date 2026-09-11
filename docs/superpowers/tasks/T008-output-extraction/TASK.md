# T008：让 harness 取得到"散文包着的 JSON"，并让"取不到"变成显式失败

> 指派：DeepSeek
> 来源：`docs/superpowers/tasks/T005-mcp-execution/REVIEW.md` 第四节第 2 条
> 类型：代码改动
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

两件事，都在 `zhiyuan-agent` 侧：

1. **解析层**：模型把合规 JSON 放在一段散文后面的 ` ```json ` 围栏里时，harness 现在取不到它，整回合的输出变成 `None`。改成取得到。
2. **仪表层**：真取不到的时候，现在是**静默少一个键**（`evaluation` 根本不写入），看起来和"跑了但没通过"无法区分。改成显式失败，且失败原因可读。

一句话验收：`reference-complete-history` 连跑 10 次，**10 次的输出 JSON 里都有 `evaluation` 键**（不要求 `passed` 都为真），且单测能证明"散文 + 围栏 JSON"取得到、"散文 + 没有 JSON"仍然取不到。

---

## 二、背景（你的会话没有这些上下文）

这套系统在把高考志愿规划的对话引擎从旧状态机迁到 codex App Server 托管的引擎上。`zhiyuan-agent` 是 Python 侧的 Gateway/harness，通过 `codex app-server --stdio`（JSON-RPC 2.0）驱动模型（后端是 DeepSeek）。每个回合我们在 `turn/start` 上带原生 `output_schema`，期望模型直接吐出符合 `TurnOutput` 的结构化 JSON。

**已经证实：DeepSeek 上 `output_schema` 不保证结构化输出。** 上一个任务（T005）的门禁我独立重跑 8 次，7 次正常，1 次模型先写了一段中文说明加一张 Markdown 表格，**最后**才补一段 ` ```json … ``` ` 围栏。那一次：

- `status=completed`、`errorCode=null`、`errors=[]`、`mcpCalls=2`（工具确实执行了）、`elapsedMs=9189.6`
- 但 `output=null`

原因定位到 `app/harness/codex.py` 的 `_parse_json_object()`：它只在字符串**以** ` ``` ` 开头时剥围栏。前面有散文就不剥，`json.loads` 抛错，返回 `None`。

**判别性对照（已做过，结论可靠）**：同一条模型消息，整条喂进去得到 `None`；把前置散文切掉、只喂围栏块，立刻得到 `dict` 且 `responseType='fact'`。**内容是好的，是解析器够不着。**

然后是第二层：`scripts/codex_semantic_smoke.py` 里，`payload["evaluation"]` 只在 `if result.status == "completed" and isinstance(result.output, dict):` 这个分支内部赋值。`output` 是 `None` 时**整个 `evaluation` 键不写入**，`payload["trace"]` 也不写入。于是任何写成 `d.get('evaluation', {}).get('passed')` 的判定都会读出 `None`——不报错、不为真，长得跟一次普通的不通过一模一样。这是本次要修的第二件事。

为什么这事重要：在真实 Gateway 里，harness 取不到 output 的那一回合就是**废回合**——用户问了，模型答了，系统当没听见。而且因为仪表静默，我们量不出它多久发生一次。

---

## 三、已核实的环境事实（不要重新调查，直接用）

| 事实 | 值 |
|---|---|
| Python 环境 | `/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python`（3.10.14） |
| 系统 python3 | 3.6.8，**不要用** |
| 要改的解析函数 | `zhiyuan-agent/app/harness/codex.py:302` `_parse_json_object()` |
| 它的调用方 | 同文件 `_extract_output()`（`:264`），四处调用：`:270`、`:281`、`:290`，以及递归分支 |
| output 最终落点 | `codex.py:161` / `:168`，`_extract_output(event) or final_output`，仅当 `terminal_status == "completed"` |
| 仪表缺键位置 | `zhiyuan-agent/scripts/codex_semantic_smoke.py:247` `if result.status == "completed" and isinstance(result.output, dict):` |
| 冒烟脚本调用方式 | `cd /root/dev/zhiyuan/zhiyuan-agent && .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history`，打印一行 JSON 到 stdout |
| 可选场景 | `reference-missing-scope` / `reference-complete-history` / `reference-authoritative-history` / `mixed-read-write` |
| `CODEX_HOME` | 脚本自己 `setdefault` 到 `/root/dev/zhiyuan/.codex-semantic-home`，不要手动导出 |
| MCP 夹具 | `tests/fixtures/mcp/semantic_readonly_server.py`，两个只读工具，T005 刚修好 `readOnlyHint` 与 `--trace`，**本次不要动它** |
| 单回合耗时 | 真实端点约 7–26 秒 |
| `mixed-read-write` 场景现状 | 基线 0/3 通过，**本次不负责修它**，见第七节 |

---

## 四、步骤

### 步骤 1：让 `_parse_json_object` 能取到位置任意的围栏 JSON

现状（`app/harness/codex.py:302`）：

```python
def _parse_json_object(value: str) -> dict[str, Any] | None:
    value = value.strip()
    if value.startswith("```"):
        ...
```

改成分层尝试，**顺序固定、每层都必须是"整体解析成功"才算命中**：

1. **直接解析**：`json.loads(value.strip())` 成功且是 dict → 命中，来源记为 `direct`。
2. **围栏扫描**：扫出字符串里**所有** ` ``` … ``` ` 围栏块（含 ` ```json ` 这类语言标注），逐个 `json.loads`，收集所有解析成 dict 的。
   - 恰好 1 个 → 命中它。
   - 多于 1 个 → 命中**最后一个**，因为模型的收尾答案通常在最后。
   - 无论几个，**把解析成功的个数记下来**（见步骤 2）。来源记为 `fenced`。
3. **内嵌兜底**：没有围栏，但散文里有一段平衡的 `{ … }`。取**最外层**平衡花括号跨度，`json.loads`，成功且是 dict → 命中，来源记为 `embedded`。
4. 全部落空 → 返回 `None`，来源记为 `missing`。

约束与理由：

- **不要做字段级修补。** 不许补默认值、不许拼接多个 JSON、不许猜 `responseType`。这个函数的职责是"把模型确实写出来的对象找出来"，不是"让它通过校验"。找不到就必须是 `None`——`TurnOutput.model_validate` 后面还会校验，那才是判合规的地方。
- **第 3 层要小心。** 散文里出现 `{某某}` 这种中文花括号内容是常见的，平衡跨度解析失败就老实返回 `None`，不要退化成正则抠片段。第六节有一条负向单测专门盯这个。
- **第 1 层必须保留在最前。** 现在绝大多数回合走的就是直接解析这条路（我 8 次里 7 次如此）。如果你把所有输入都先送去围栏扫描，happy path 的行为就变了——第六节有一条测试专门验 `direct` 仍然是 `direct`。

### 步骤 2：把"输出是怎么取到的"变成可观测的读数

`_parse_json_object` 现在只返回 `dict | None`，调用方拿不到"怎么取到的"。加一个能被外部读到的记录，形式自定（返回元组、或让 `_extract_output` 往结果里带一个旁路字段、或模块级最近一次记录），但必须满足：

- 能区分 `direct` / `fenced` / `embedded` / `missing` 四种来源。
- `fenced` 时能给出"解析成功的围栏块个数"。
- **这个读数要能一路带到 `codex_semantic_smoke.py` 打印的 payload 里**，键名用 `outputExtraction`，形如 `{"source": "fenced", "candidateCount": 2}`。

为什么要这个：没有它，我们量不出"模型多久包一次散文"，也就没法判断这个问题是罕见抖动还是高频故障。T005 的教训就是仪表坏了还拿它下结论——这次先把仪表立起来。

如果你选的实现方式会让 `codex.py` 的函数签名变化影响到别的调用方，`grep -rn "_parse_json_object\|_extract_output" app/ tests/ scripts/` 先看清楚再动。

### 步骤 3：让冒烟脚本在取不到 output 时显式失败

`scripts/codex_semantic_smoke.py:247` 那个 `if` 之外，现在什么都不写。改成：**无论走哪条路，`payload["evaluation"]` 一定存在。**

取不到 output 时，写一个明确的失败评估，至少包含：

- `passed: False`
- 失败原因里有一条可读的、能一眼看出是"没拿到输出"的标识（建议 `output_missing`，具体串名你定，写进报告）
- `payload["outputExtraction"]` 带上步骤 2 的读数

不要顺手把 `payload["trace"]` 也伪造出来——没有 output 就没有 trace，让它缺着，但 `evaluation` 必须在。

同时把 `status != "completed"` 的情况也覆盖掉（那也是现在会少键的一条路）。

---

## 五、陷阱（会让你踩坑或误伤的地方）

1. **别去关围栏剥离的旧行为。** 现在"整条以 ` ``` ` 开头"的输入是能正常工作的，围栏扫描要覆盖这种情况而不是替换掉它。第六节有测试。
2. **`_extract_output` 是递归的**（`:275` 和 `:298` 会递归自己），且在 `item.content[]` 里逐条尝试。你加的"来源记录"在递归里会被多次写入，注意最终留下的是**真正命中那一次**的来源，不是最后一次尝试的来源。
3. **模型每次输出都不一样。** 这个 bug 是低频的（我 8 次撞 1 次）。**不要靠真实端点去验证解析逻辑**——用单测喂固定文本。真实端点只用来验步骤 3 的"键一定在"。
4. **不要动 MCP 夹具。** `tests/fixtures/mcp/semantic_readonly_server.py` 和 `app/engine/turn_trace.py` 是 T005 刚改完还没提交的，动它们会让两个任务的改动混在一起、没法分别回滚。
5. **鉴权信息不要出现在报告、脚本、日志里。** `$CODEX_HOME/auth.json` 里有真实 API key。`.codex-semantic-home/` 已在 `.gitignore`，别把它的内容贴进报告。
6. **不要原地改 `.codex-semantic-home/config.toml`。** 需要不同配置就另起一个 `CODEX_HOME` 目录。

---

## 六、验收

按顺序执行，全部必须通过。**每条都要贴原始输出。**

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# 1. 单测：散文 + 尾部围栏 JSON → 取得到，且 source == "fenced"
#    （你自己新建测试文件，建议 tests/unit/test_codex_output_extraction.py）
.venv/bin/python -m pytest tests/unit/test_codex_output_extraction.py -v

# 2. 单测：散文里根本没有 JSON → 仍然是 None，source == "missing"
#    这条是防"修过头开始凭空造输出"的，必须有

# 3. 单测：散文里有中文花括号但不是合法 JSON → 仍然是 None
#    这条是防第 3 层兜底退化成抠片段的

# 4. 单测：两个围栏 JSON → 命中最后一个，candidateCount == 2
#    这条是让歧义可见而不是静默择一

# 5. 单测：整条就是纯 JSON（现有 happy path）→ source == "direct"
#    这条是防你把所有输入都改走围栏扫描、悄悄改了主路径行为

# 6. 单测：output 取不到时，冒烟脚本的 payload 里 evaluation 存在且 passed 为 False
#    用注入/打桩造一个 output=None 的结果，不要靠真实端点撞运气
#    对照：正常 output 的同一段代码必须给出 passed=True，否则说明这个检查恒为假

# 7. 全量单测（对照下面的基线）
bash scripts/run_unit_tests.sh 2>&1 | tail -6

# 8. 真实端点 × 10，统计 evaluation 键的出现率与 outputExtraction 的分布
for i in $(seq 1 10); do
  .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history \
    > /tmp/t008-run-$i.json 2>/tmp/t008-run-$i.err
  .venv/bin/python - "$i" <<'PY'
import json, sys
i = sys.argv[1]
d = json.load(open(f'/tmp/t008-run-{i}.json'))
has_eval = 'evaluation' in d          # 注意：用 in，不要用 .get()，缺键必须看得见
print(f"run {i}: status={d.get('status')} "
      f"outputPresent={d.get('output') is not None} "
      f"extraction={d.get('outputExtraction')} "
      f"hasEvaluation={has_eval} "
      f"passed={d['evaluation']['passed'] if has_eval else 'N/A'}")
PY
done
```

### 第 8 条的判定口径（重要，别搞错）

- **必须达到**：`hasEvaluation=True` 出现 **10/10**。这是 T008 的目标——不再有静默的洞。
- **只需报告、不作门禁**：`passed=True` 出现几次、`extraction.source` 各自几次。`passed` 是否全真取决于模型这一轮答得好不好，那是 P0 的事，不是你的。
- **如果 10 次里一次 `source` 都不是 `fenced`**：正常，说明这轮运气好没撞上包散文。照实写"10 次全为 `direct`，未在真实端点复现散文包裹"，**不要为了让 `fenced` 出现而去改场景或改提示词**。解析逻辑由第 1 条单测负责证明，真实端点不负责复现低频事件。

### 已知失败基线（不是你造成的，不要去修）

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1700 passed, 34 skipped
```

通过数 1700 里含 T005 新增的 1 条。你新增的测试会让这个数继续往上走，在报告里说明差额是你加了几条。

出现基线以外的失败时，**逐条列出用例名和报错原文**，不要自行扩大修复范围。

---

## 七、边界：不要做这些

- **不要动 `/root/dev/codex`**（codex 自身的 Rust 源码）。
- **不要动 `app/engine/turn_trace.py`、`tests/fixtures/mcp/semantic_readonly_server.py`、`tests/unit/test_semantic_readonly_server.py`**——T005 的未提交改动在里面。
- **不要动 `zhiyuan-server/`**（Java 侧），也不要动 `docker-compose.codex-local.yml`。
- **不要碰 `TURN_OUTPUT_SCHEMA` 本身**，也不要改提示词去"让模型别写散文"。那是 P0 的另一层工作，混进来就分不清是哪层起的作用了。
- **不要去修 `mixed-read-write` 场景的 0/3。** 那是写操作路径的契约问题，留给 P2。
- 不要"顺手"重构、格式化、改 import 顺序、加类型标注。
- **不要 commit。** 改完等 review。

---

## 八、报告

把报告写到：

```
/root/dev/zhiyuan/docs/superpowers/tasks/T008-output-extraction/REPORT.md
```

格式见 `docs/superpowers/tasks/_templates/REPORT.md`，逐节填写，不要增删小节。

要点：状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`；验收命令贴**原始输出**；**不写修复建议、不写下一步、不写根因推测**。

第 8 条那 10 次运行，**十行输出全部贴出来**，不要只贴汇总。跑失败的那几次也要贴——上一个任务的报告只跑 3 次、都过了，我跑 8 次撞出 1 次挂，低频抖动就是这么漏掉的。
