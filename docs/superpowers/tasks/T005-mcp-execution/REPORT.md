---
task: T005
status: DONE
executor: deepseek
finished_at: 2026-09-10 22:00 +0800
---

# T005 报告

## 一、结论

四条验收命令全部通过：夹具回归测试 `2 passed`；仪表自证 `mcpCalls= 2` 且 `observed.tools= ['admission.get_history']`；`reference-complete-history` 连续 3 次 `passed= True failures= []`（`mcpCalls` 均 2、`evidenceIds` 均非空）；全量单测 `2 failed, 1700 passed, 34 skipped`，两条失败与已知基线逐字相同，通过数差额 +1 恰为本次新增的回归测试。步骤 5 的 12 次基线 9 过 3 不过（`mixed-read-write` 0/3），failures 原文见第八节。

## 二、交付物

| 路径 | 字节数 | 说明 |
|---|---|---|
| `/root/dev/zhiyuan/zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py` | 5458 | 步骤 1+2（夹具侧）：两个工具各加 `"annotations": {"readOnlyHint": True}`；新增 `_argument_value()`，`TRACE_PATH` 改为先读 `--trace` argv、取不到再回退环境变量 |
| `/root/dev/zhiyuan/zhiyuan-agent/scripts/codex_semantic_smoke.py` | 13423 | 步骤 2（脚本侧）：`fixture_args = [str(fixture), "--trace", trace_file.name]`；新增 `_recorded_tool_calls()`，供 `ValidationError` 回退分支填 `toolCalls` |
| `/root/dev/zhiyuan/zhiyuan-agent/app/engine/turn_trace.py` | 5990 | 步骤 3：`build_turn_trace()` 的抽取循环跳过 `type` 含 `mcpserver` 的事件 |
| `/root/dev/zhiyuan/zhiyuan-agent/tests/unit/test_semantic_readonly_server.py` | 1211 | 步骤 4：抽出 `_list_tools(tmp_path)`；新增 `test_semantic_readonly_server_marks_every_tool_read_only` |
| `/root/dev/zhiyuan/.runtime/t005/accept3-ch-1.json` | 248234 | 验收命令 3 第 1 次运行的完整 stdout |
| `/root/dev/zhiyuan/.runtime/t005/accept3-ch-2.json` | 239334 | 验收命令 3 第 2 次运行的完整 stdout |
| `/root/dev/zhiyuan/.runtime/t005/accept3-ch-3.json` | 269896 | 验收命令 3 第 3 次运行的完整 stdout |
| `/root/dev/zhiyuan/.runtime/t005/baseline-<场景>-<1..3>.json` | 12 个文件，合计 3841330（另有 12 个同名 `.err`，均 0 字节） | 步骤 5 的四场景 × 3 次原始 stdout |
| `/root/dev/zhiyuan/.runtime/t005/baseline-run.sh` | 568 | 步骤 5 执行脚本 |
| `/root/dev/zhiyuan/.runtime/t005/baseline-run.log` | 669 | 步骤 5 运行日志（12 行 `exit=0` + `ALL_DONE`） |
| `/root/dev/zhiyuan/.runtime/t005/unit-tests.log` | 211298 | 验收命令 4 原始输出 |

## 三、实际改动的文件

```
$ git status --short
 M zhiyuan-agent/app/engine/turn_trace.py
 M zhiyuan-agent/scripts/codex_semantic_smoke.py
 M zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py
 M zhiyuan-agent/tests/unit/test_semantic_readonly_server.py
```

```
$ git diff --stat -- zhiyuan-agent/app/engine/turn_trace.py zhiyuan-agent/scripts/codex_semantic_smoke.py zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py zhiyuan-agent/tests/unit/test_semantic_readonly_server.py
 zhiyuan-agent/app/engine/turn_trace.py                   |  3 +++
 zhiyuan-agent/scripts/codex_semantic_smoke.py            | 16 ++++++++++++++--
 .../tests/fixtures/mcp/semantic_readonly_server.py       | 12 +++++++++++-
 .../tests/unit/test_semantic_readonly_server.py          | 13 +++++++++++--
 4 files changed, 39 insertions(+), 5 deletions(-)
```

完整 diff：

```diff
diff --git a/zhiyuan-agent/app/engine/turn_trace.py b/zhiyuan-agent/app/engine/turn_trace.py
index 43aaefc..a5c1ae9 100644
--- a/zhiyuan-agent/app/engine/turn_trace.py
+++ b/zhiyuan-agent/app/engine/turn_trace.py
@@ -48,6 +48,9 @@ def build_turn_trace(payload: Any, output: TurnOutput, *, entity_ids: list[str])
     orchestration: list[dict[str, Any]] = []
     for item in _walk(payload):
         item_type = str(item.get("type") or "").lower()
+        if "mcpserver" in item_type:
+            # MCP 服务器生命周期事件（如 mcpServer/startupStatus/updated）不是工具调用
+            continue
         if "mcp" not in item_type and not any(
             key in item for key in ("toolName", "tool_name", "toolCall", "tool_call")
         ):
diff --git a/zhiyuan-agent/scripts/codex_semantic_smoke.py b/zhiyuan-agent/scripts/codex_semantic_smoke.py
index 9730e9a..9362a0d 100644
--- a/zhiyuan-agent/scripts/codex_semantic_smoke.py
+++ b/zhiyuan-agent/scripts/codex_semantic_smoke.py
@@ -136,7 +136,7 @@ async def run_scenario(
         os.environ["ZHIYUAN_SEMANTIC_AUTHORITATIVE"] = "true"
     else:
         os.environ.pop("ZHIYUAN_SEMANTIC_AUTHORITATIVE", None)
-    fixture_args = [str(fixture)]
+    fixture_args = [str(fixture), "--trace", trace_file.name]
     if expectation.case_id == "reference-authoritative-history":
         fixture_args.append("--authoritative")
     model_config = ["mcp_servers.semantic_readonly={"
@@ -250,7 +250,7 @@ async def run_scenario(
             except ValidationError as exc:
                 payload["outputValidationError"] = str(exc)
                 payload["trace"] = {
-                    "toolCalls": [],
+                    "toolCalls": _recorded_tool_calls(mcp_calls),
                     "evidenceIds": [],
                     "entityIds": payload["modelUsedCandidateIds"],
                     "responseType": result.output.get("responseType"),
@@ -276,6 +276,18 @@ async def run_scenario(
         Path(trace_file.name).unlink(missing_ok=True)
 
 
+def _recorded_tool_calls(calls: list[dict[str, object]]) -> list[dict[str, object]]:
+    return [
+        {
+            "name": str(call["name"]),
+            "status": "completed",
+            "argumentKeys": sorted(str(key) for key in call.get("arguments") or {}),
+        }
+        for call in calls
+        if isinstance(call.get("name"), str) and call["name"]
+    ]
+
+
 def _recorded_mcp_events(calls: list[dict[str, object]]) -> list[dict[str, object]]:
     events: list[dict[str, object]] = []
     for call in calls:
diff --git a/zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py b/zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py
index d9f6c65..5710f4f 100644
--- a/zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py
+++ b/zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py
@@ -9,7 +9,15 @@ import sys
 from pathlib import Path
 
 
-TRACE_PATH = os.environ.get("ZHIYUAN_SEMANTIC_MCP_TRACE", "")
+def _argument_value(flag: str) -> str:
+    if flag in sys.argv[1:]:
+        index = sys.argv.index(flag)
+        if index + 1 < len(sys.argv):
+            return sys.argv[index + 1]
+    return ""
+
+
+TRACE_PATH = _argument_value("--trace") or os.environ.get("ZHIYUAN_SEMANTIC_MCP_TRACE", "")
 AUTHORITATIVE = os.environ.get("ZHIYUAN_SEMANTIC_AUTHORITATIVE", "").lower() == "true" or "--authoritative" in sys.argv[1:]
 
 
@@ -31,6 +39,7 @@ def tool_list() -> list[dict]:
         {
             "name": "catalog.search_schools",
             "description": "只读查询学校候选。",
+            "annotations": {"readOnlyHint": True},
             "inputSchema": {
                 "type": "object",
                 "properties": {"query": {"type": "string"}},
@@ -41,6 +50,7 @@ def tool_list() -> list[dict]:
         {
             "name": "admission.get_history",
             "description": "只读查询某学校某专业的历史录取分数。缺少范围参数时必须先澄清。",
+            "annotations": {"readOnlyHint": True},
             "inputSchema": {
                 "type": "object",
                 "properties": {
diff --git a/zhiyuan-agent/tests/unit/test_semantic_readonly_server.py b/zhiyuan-agent/tests/unit/test_semantic_readonly_server.py
index df54371..9b12786 100644
--- a/zhiyuan-agent/tests/unit/test_semantic_readonly_server.py
+++ b/zhiyuan-agent/tests/unit/test_semantic_readonly_server.py
@@ -5,7 +5,7 @@ import sys
 from pathlib import Path
 
 
-def test_semantic_readonly_server_lists_only_read_tools(tmp_path: Path) -> None:
+def _list_tools(tmp_path: Path) -> list[dict]:
     fixture = Path(__file__).parents[1] / "fixtures" / "mcp" / "semantic_readonly_server.py"
     process = subprocess.Popen(
         [sys.executable, str(fixture)],
@@ -19,5 +19,14 @@ def test_semantic_readonly_server_lists_only_read_tools(tmp_path: Path) -> None:
     process.stdin.flush()
     result = json.loads(process.stdout.readline())
     process.terminate()
-    names = {tool["name"] for tool in result["result"]["tools"]}
+    return result["result"]["tools"]
+
+
+def test_semantic_readonly_server_lists_only_read_tools(tmp_path: Path) -> None:
+    names = {tool["name"] for tool in _list_tools(tmp_path)}
     assert names == {"catalog.search_schools", "admission.get_history"}
+
+
+def test_semantic_readonly_server_marks_every_tool_read_only(tmp_path: Path) -> None:
+    for tool in _list_tools(tmp_path):
+        assert tool.get("annotations", {}).get("readOnlyHint") is True, tool["name"]
```

## 四、验收命令与原始输出

### 命令 1

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_semantic_readonly_server.py -v
```

```
platform linux -- Python 3.10.14, pytest-9.0.3, pluggy-1.6.0 -- /root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /root/dev/zhiyuan/zhiyuan-agent
configfile: pyproject.toml
plugins: asyncio-1.4.0, mock-3.15.1, logfire-4.37.0, anyio-4.13.0
asyncio: mode=auto, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/unit/test_semantic_readonly_server.py::test_semantic_readonly_server_lists_only_read_tools PASSED [ 50%]
tests/unit/test_semantic_readonly_server.py::test_semantic_readonly_server_marks_every_tool_read_only PASSED [100%]

============================== 2 passed in 0.06s ===============================
```

### 命令 2

```bash
cd /root/dev/zhiyuan/zhiyuan-agent && .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history \
  | .venv/bin/python -c "import sys,json; d=json.loads(sys.stdin.read().strip().splitlines()[-1]); \
print('mcpCalls=',len(d.get('mcpCalls') or [])); print('tools=',d['evaluation']['observed'].get('tools')); \
print('passed=',d['evaluation']['passed']); print('failures=',d['evaluation']['failures'])"
```

首次执行（`app/engine/turn_trace.py` 改动**前**，此读数已作废，仅因第六节要引用而列出）：

```
mcpCalls= 2
tools= ['admission.get_history', 'semantic_readonly']
passed= True
failures= []
```

`turn_trace.py` 改动后重跑（最终读数）：

```
mcpCalls= 2
tools= ['admission.get_history']
passed= True
failures= []
```

### 命令 3

```bash
cd /root/dev/zhiyuan/zhiyuan-agent && for i in 1 2 3; do
  echo "--- run $i ---"
  .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history \
    | tee /root/dev/zhiyuan/.runtime/t005/accept3-ch-$i.json \
    | .venv/bin/python -c "import sys,json; d=json.loads(sys.stdin.read().strip().splitlines()[-1]); \
e=d['evaluation']; o=e['observed']; \
print('passed=',e['passed'],'failures=',e['failures'],'mcpCalls=',len(d.get('mcpCalls') or []),'tools=',o.get('tools'),'evidenceIds=',o.get('evidenceIds'),'ms=',d.get('elapsedMs'))"
done
```

```
--- run 1 ---
passed= True failures= [] mcpCalls= 2 tools= ['admission.get_history'] evidenceIds= ['ev-history-school-1-major-cs-2025-330000', 'ev-history-school-2-major-cs-2025-330000'] ms= 9301.8
--- run 2 ---
passed= True failures= [] mcpCalls= 2 tools= ['admission.get_history'] evidenceIds= ['ev-2025-330000-major-cs-school-1-min-score', 'ev-2025-330000-major-cs-school-2-min-score'] ms= 9124.7
--- run 3 ---
passed= True failures= [] mcpCalls= 2 tools= ['admission.get_history'] evidenceIds= ['hist-school-1-major-cs-330000-2025-本科批-物理类', 'hist-school-2-major-cs-330000-2025-本科批-物理类'] ms= 10652.5
```

三次运行的完整 `evaluation` 段落（从 `accept3-ch-{1,2,3}.json` 中原样取出）：

run 1（1054 字节）：

```json
"evaluation": {"caseId": "reference-complete-history", "passed": true, "failures": [], "observed": {"entities": ["school-1", "school-2"], "tools": ["admission.get_history"], "evidenceIds": ["ev-history-school-1-major-cs-2025-330000", "ev-history-school-2-major-cs-2025-330000"], "responseType": "fact", "message": "已按你确认的范围查询两所候选学校 2025 年、浙江（areaId=330000）、物理类、本科批、计算机科学与技术（majorId=major-cs）的历史录取数据，结果为：\n\n- 甲大学（school-1）：2025 年最低分 612\n- 乙大学（school-2）：2025 年最低分 598\n\n两校差 14 分，甲大学门槛更高。注意：返回数据只包含最低分，不含最低位次、招生计划数、录取人数和批次控制线，因此不能据此推算录取概率或冲/稳/保档位。", "clarificationRequested": false, "proposalRef": null, "executionStatus": "completed", "limitations": ["数据版本 dataVersion=semantic-fixture-1，工具自述 semantic_fixture_only，属语义冒烟/测试数据，非正式录取数据", "证据范围限定为 areaId=330000、majorId=major-cs、2025、本科批、物理类，不覆盖其他年份、省份、批次或专业", "admissionFacts 为空：工具未返回录取率、位次等完整字段，不做推算"], "nextStep": "如需判断这两校对某位考生的冲/稳/保档位，请提供考生分数（及位次，如有）与年份；也可指定是否要补充其他年份或其他省份的对比。", "conversationAction": {"actionType": "continue_readonly", "proposalRef": null, "expectedSourceVersion": 42, "intent": "not_applicable"}}}
```

run 2（1290 字节）：

```json
"evaluation": {"caseId": "reference-complete-history", "passed": true, "failures": [], "observed": {"entities": ["school-1", "school-2"], "tools": ["admission.get_history"], "evidenceIds": ["ev-2025-330000-major-cs-school-1-min-score", "ev-2025-330000-major-cs-school-2-min-score"], "responseType": "fact", "message": "已按你指定的口径查询到两所学校 2025 年浙江（areaId=330000）物理类、本科批、计算机科学与技术（majorId=major-cs）的历史最低分：\n\n| 学校 | 专业 | 年份 | 批次 | 科类 | 历史最低分 |\n| --- | --- | --- | --- | --- | --- |\n| 甲大学（school-1） | 计算机科学与技术 | 2025 | 本科批 | 物理类 | 612 |\n| 乙大学（school-2） | 计算机科学与技术 | 2025 | 本科批 | 物理类 | 598 |\n\n两校相差 14 分，甲大学在同口径下最低分更高。\n\n需要说明：本次返回的只是「历史最低分」这一项，没有返回招生单位、计划数、录取率、位次等信息，因此我不能据此推算录取概率或「冲/稳/保」档位。另外数据版本为 semantic-fixture-1，标注为 semantic_fixture_only（测试/样例数据），仅可用于流程验证，不能作为正式填报依据。", "clarificationRequested": false, "proposalRef": null, "executionStatus": "completed", "limitations": ["数据版本 semantic-fixture-1，标记 semantic_fixture_only，属样例/测试数据，非正式权威发布数据。", "查询范围仅为 2025 年、areaId=330000、本科批、物理类、专业 major-cs（计算机科学与技术），未覆盖其他年份、批次与专业。", "工具仅返回历史最低分字段，未返回计划数、最低位次、录取率、专业组等信息。", "本次为只读查询，未生成或修改任何方案。"], "nextStep": "如需继续，请提供你的分数与位次（或指定其他年份/批次/专业），我可以按同一口径补充查询或做多校对比；在你明确要求之前不会生成任何写入型方案。", "conversationAction": {"actionType": "continue_readonly", "proposalRef": null, "expectedSourceVersion": 42, "intent": "explicit"}}}
```

run 3（1040 字节）：

```json
"evaluation": {"caseId": "reference-complete-history", "passed": true, "failures": [], "observed": {"entities": ["school-1", "school-2"], "tools": ["admission.get_history"], "evidenceIds": ["hist-school-1-major-cs-330000-2025-本科批-物理类", "hist-school-2-major-cs-330000-2025-本科批-物理类"], "responseType": "fact", "message": "已按你给的参数查询（省份：浙江 areaId=330000，科类：物理类，批次：本科批，年份：2025，专业：计算机科学与技术 majorId=major-cs）：\n\n- 甲大学（school-1）计算机科学与技术 2025 年历史最低分：612\n- 乙大学（school-2）计算机科学与技术 2025 年历史最低分：598\n\n两校分差 14 分（甲大学高）。请注意：本次工具仅返回“历史最低分”一个字段，未返回录取率、位次或风险档位，因此我不做任何冲/稳/保判断。", "clarificationRequested": false, "proposalRef": null, "executionStatus": "completed", "limitations": ["数据版本 semantic-fixture-1，标记 semantic_fixture_only，可能为测试/样例数据，不可直接作为正式填报依据。", "查询范围仅覆盖 2025 年、浙江(330000)、本科批、计算机科学与技术(major-cs) 这一组参数，未覆盖其他年份、批次或专业。", "每条记录只返回历史最低分，未返回平均分、位次、招生计划数。"], "nextStep": "如需把这批结果用于筛校或生成冲稳保方案，请补充你的分数/位次以及期望的批次与专业范围，我再据此继续只读分析。", "conversationAction": {"actionType": "continue_readonly", "proposalRef": null, "expectedSourceVersion": 42, "intent": "not_applicable"}}}
```

三次运行的 `mcpCalls`（从落盘 stdout 取出，各 2 条，与夹具记录一一对应）：

```json
[{"name": "admission.get_history", "arguments": {"schoolId": "school-1", "majorId": "major-cs", "areaId": "330000", "batch": "本科批", "year": 2025, "subjectType": "物理类"}}, {"name": "admission.get_history", "arguments": {"schoolId": "school-2", "majorId": "major-cs", "areaId": "330000", "batch": "本科批", "year": 2025, "subjectType": "物理类"}}]
```

### 命令 4

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
bash scripts/run_unit_tests.sh > /root/dev/zhiyuan/.runtime/t005/unit-tests.log 2>&1
tail -20 /root/dev/zhiyuan/.runtime/t005/unit-tests.log
```

```
tests/unit/test_base_agent.py::test_run_repeated_readonly_explore_tool_loop_reuses_recent_return
tests/unit/test_base_agent.py::test_run_stops_repeated_score_line_tool_loop_before_request_limit
tests/unit/test_base_agent.py::test_run_stops_repeated_admission_score_tool_loop_before_request_limit
tests/unit/test_base_agent.py::test_run_repeated_policy_tool_loop_renders_json_summary_as_user_text
  /root/dev/zhiyuan/zhiyuan-agent/app/agent/base_agent.py:263: PydanticAIDeprecationWarning: `AgentRun.usage` is no longer a method; access it as a property (drop the parentheses).
    usage = agent_run.usage()

tests/unit/test_zhiyuan_agent_direct.py::test_zhiyuan_agent_continues_after_query_plan_tool
tests/unit/test_zhiyuan_agent_direct.py::test_zhiyuan_agent_continues_after_answer_policy_tool
tests/integration/test_request_context_integration.py::test_request_context_in_real_agent_run
tests/integration/test_request_context_integration.py::test_request_context_with_message_history
tests/integration/test_request_context_integration.py::test_different_contexts_for_different_requests
  /root/dev/zhiyuan/zhiyuan-agent/app/agent/base_agent.py:375: PydanticAIDeprecationWarning: `AgentRun.usage` is no longer a method; access it as a property (drop the parentheses).
    usage = agent_run.usage()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
=========== 2 failed, 1700 passed, 34 skipped, 22 warnings in 28.43s ===========
```

## 五、与已知失败基线的对照

| 失败用例 | 在基线内？ | 说明 |
|---|---|---|
| `tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture` | 是 | 用例名与任务书「已知失败基线」逐字一致 |
| `tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]` | 是 | 用例名与任务书「已知失败基线」逐字一致 |

基线外失败：无。

计数对照：

| 项 | 已知基线 | 本次 | 差 |
|---|---|---|---|
| failed | 2 | 2 | 0 |
| passed | 1699 | 1700 | +1 |
| skipped | 34 | 34 | 0 |

通过数差额 +1 即本任务步骤 4 在 `tests/unit/test_semantic_readonly_server.py` 新增的 `test_semantic_readonly_server_marks_every_tool_read_only`。

## 六、偏离任务书之处

1. **多改了一个文件：`app/engine/turn_trace.py`。** 任务书步骤 3 授权「口径怎么改由你定」，但没有把该文件列进改动面。改动是在 `build_turn_trace()` 的抽取循环里加两行：`type` 字符串含 `mcpserver` 的事件直接 `continue`。触发事实：命令 2 首次执行读出 `tools= ['admission.get_history', 'semantic_readonly']`，`semantic_readonly` 是 MCP 服务器名（来自 `mcpServer/startupStatus/updated` 事件），不是工具名。改动只从 `toolCalls` / `orchestration` 里删除条目，不新增；另用合成 payload 单测过该函数（4 个事件输入，输出 `['admission.get_history', 'admission.get_history']`）。
2. **`scripts/codex_semantic_smoke.py` 的 `ValidationError` 回退分支也改了。** 该分支原先把 `"toolCalls": []` 写死。任务书只要求把 trace 通道从环境变量改到 argv；为了让这个分支下的 `observed.tools` 同样不空，新增 `_recorded_tool_calls()` 并用它填 `toolCalls`（同一份 `mcp_calls` 数据）。
3. **验收命令 2 与命令 3 各跑了两次。** 第一次在 `turn_trace.py` 改动前执行，读数 `tools= ['admission.get_history', 'semantic_readonly']`；改动后重跑并把最终读数作为验收输出（见第四节，两次读数都列出）。因此本任务在真实端点上共执行 20 次冒烟：命令 2 两次、命令 3 六次（每次运行的完整 stdout 已落盘）、步骤 5 十二次，未额外加量。
4. **步骤 4 按任务书原文实现**：断言写在 `tests/unit/test_semantic_readonly_server.py` 内，对 `tool_list()` 返回的每个工具检查 `annotations.readOnlyHint is True`。为复用 subprocess 交互，把原有用例的 body 抽成 `_list_tools(tmp_path)`，原用例名与断言不变。

## 七、未做的事

无。

## 八、观察到的异常现象（只列事实）

### 8.1 步骤 5 的四场景 × 3 次基线

执行命令（`/root/dev/zhiyuan/.runtime/t005/baseline_run.sh` 主体）：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
for scenario in reference-missing-scope reference-complete-history reference-authoritative-history mixed-read-write; do
  for i in 1 2 3; do
    .venv/bin/python scripts/codex_semantic_smoke.py --scenario "$scenario" > "$OUT/baseline-$scenario-$i.json" 2> "$OUT/baseline-$scenario-$i.err"
  done
done
```

原始汇总输出（逐字）：

```
=== mixed-read-write run 3 21:54:27 ===
exit=0
ALL_DONE
=== 汇总 ===
mixed-read-write-1                 status=completed passed=False failures=["execution_status_mismatch", "limitations_missing", "next_step_missing"] mcpCalls=2 tools=["admission.get_history"] evidenceIds=0 ms=15509.5
mixed-read-write-2                 status=completed passed=False failures=["proposal_missing", "execution_status_mismatch", "limitations_missing", "next_step_missing"] mcpCalls=2 tools=["admission.get_history"] evidenceIds=0 ms=19097.0
mixed-read-write-3                 status=completed passed=False failures=["response_type_mismatch", "clarification_mismatch", "proposal_missing"] mcpCalls=2 tools=["admission.get_history"] evidenceIds=2 ms=22003.3
reference-authoritative-history-1  status=completed passed=True  failures=[]                                       mcpCalls=2 tools=["admission.get_history"] evidenceIds=2 ms=8924.0
reference-authoritative-history-2  status=completed passed=True  failures=[]                                       mcpCalls=3 tools=["admission.get_history"] evidenceIds=2 ms=10996.9
reference-authoritative-history-3  status=completed passed=True  failures=[]                                       mcpCalls=3 tools=["admission.get_history"] evidenceIds=2 ms=9735.9
reference-complete-history-1       status=completed passed=True  failures=[]                                       mcpCalls=2 tools=["admission.get_history"] evidenceIds=2 ms=11182.7
reference-complete-history-2       status=completed passed=True  failures=[]                                       mcpCalls=3 tools=["admission.get_history"] evidenceIds=2 ms=10779.2
reference-complete-history-3       status=completed passed=True  failures=[]                                       mcpCalls=2 tools=["admission.get_history"] evidenceIds=2 ms=10114.9
reference-missing-scope-1          status=completed passed=True  failures=[]                                       mcpCalls=0 tools=[] evidenceIds=0 ms=6240.1
reference-missing-scope-2          status=completed passed=True  failures=[]                                       mcpCalls=0 tools=[] evidenceIds=0 ms=5823.1
reference-missing-scope-3          status=completed passed=True  failures=[]                                       mcpCalls=0 tools=[] evidenceIds=0 ms=8889.0
```

12 次运行全部 `status=completed`、退出码 0（`baseline-run.log` 中 12 行 `exit=0`），12 个 `.err` 文件均为 0 字节。汇总计数：passed 9 / failed 3。

### 8.2 `mixed-read-write` 三次未通过的原始字段

以下三块从 `baseline-mixed-read-write-{1,2,3}.json` 中原样取出（`"evaluation":` 键到配对大括号为止，未编辑）：

run 1（1055 字节）：

```json
"evaluation": {"caseId": "mixed-read-and-write-request", "passed": false, "failures": ["execution_status_mismatch", "limitations_missing", "next_step_missing"], "observed": {"entities": ["school-1", "school-2"], "tools": ["admission.get_history"], "evidenceIds": [], "responseType": "fact", "message": "已按你给的参数（浙江 areaId=330000、2025 年、物理类、本科批、计算机科学与技术 majorId=major-cs）分别查询了两所学校的历史最低分：\n\n| 学校 | 专业 | 年份 | 历史最低分 | 数据版本 |\n|---|---|---|---|---|\n| 甲大学（school-1） | 计算机科学与技术（major-cs） | 2025 | 612 | semantic-fixture-1 |\n| 乙大学（school-2） | 计算机科学与技术（major-cs） | 2025 | 598 | semantic-fixture-1 |\n\n说明：本次返回的字段只有「最低分」，没有招生人数、录取率、位次等字段，因此我不能据此推导任何录取概率或冲/稳/保档位。\n\n关于「把方案里的第三个删掉」：按最新 Snapshot（snapshotVersion=42），当前方案 plan-1 的条目为 [school-1 甲大学, school-2 乙大学, school-3]，第三个是 school-3。删除属于写操作，当前只读阶段不能直接执行，我已按你的原话生成一个待确认的 Proposal（从 plan-1 中排除第 3 项 school-3）。请明确确认后才会提交由后端做 CAS 校验与落库。", "clarificationRequested": false, "proposalRef": "proposal-plan-1-remove-item3-school-3", "executionStatus": null, "limitations": [], "nextStep": null, "conversationAction": {}}}
```

run 2（1109 字节）：

```json
"evaluation": {"caseId": "mixed-read-and-write-request", "passed": false, "failures": ["proposal_missing", "execution_status_mismatch", "limitations_missing", "next_step_missing"], "observed": {"entities": ["school-1", "school-2"], "tools": ["admission.get_history"], "evidenceIds": [], "responseType": "fact", "message": "已完成两所学校的历史最低分查询（参数：areaId=330000 / 浙江、majorId=major-cs（计算机科学与技术）、year=2025、batch=本科批、subjectType=物理类）：\n\n1) 甲大学（school-1）计算机科学与技术：2025 年历史最低分 612 分。\n2) 乙大学（school-2）计算机科学与技术：2025 年历史最低分 598 分。\n\n说明：以上仅为专业历史最低分事实，返回数据中不含录取率、专业组、位次等信息，因此我不推导录取概率、冲/稳/保档位或其他字段，admissionFacts 留空。数据为语义测试数据（dataVersion=semantic-fixture-1），限制标记 semantic_fixture_only，不能当作真实招生数据使用。\n\n关于“把方案里的第三个删掉”：这属于对已保存方案 plan-1 的写操作，当前处于只读阶段，我没有执行任何写入。已按现有效方案草拟提案：plan-1 当前 items = [school-1 甲大学, school-2 乙大学, school-3]，删除第三个后将只保留 甲大学、乙大学 两项。\n\n需要你确认的问题：方案第三项在 WorkingSet 中只有 entityId=school-3、没有名称，且它不在当前候选集合（甲大学、乙大学）内，我无法确认它具体是哪所学校，也无法确认它是否与你口中的“第三个”完全一致。请确认后我再提交该删除提案。", "clarificationRequested": false, "proposalRef": null, "executionStatus": null, "limitations": [], "nextStep": null, "conversationAction": {}}}
```

run 3（1704 字节）：

```json
"evaluation": {"caseId": "mixed-read-and-write-request", "passed": false, "failures": ["response_type_mismatch", "clarification_mismatch", "proposal_missing"], "observed": {"entities": ["school-1", "school-2"], "tools": ["admission.get_history"], "evidenceIds": ["ev-admission-history-school-1-major-cs-330000-2025", "ev-admission-history-school-2-major-cs-330000-2025"], "responseType": "clarification", "message": "已按你给的参数（浙江 areaId=330000、物理类、本科批、2025 年、计算机科学与技术 majorId=major-cs）分别查询了两所候选学校的历史最低分：\n\n1) 甲大学（school-1）：2025 年最低分 612。\n2) 乙大学（school-2）：2025 年最低分 598。\n\n说明：该历史查询接口本次只返回了最低分，没有返回位次、招生计划、录取率等字段，因此我不对录取概率或“冲/稳/保”档位做任何推断。数据版本 semantic-fixture-1，来源标注为语义测试数据（semantic_fixture_only），正式填报前需以官方数据复核。\n\n关于“把方案里的第三个删掉”，我暂时不能执行，原因是：\n- 我从当前业务状态能看到的方案是 plan-1，其条目为 school-1、school-2、school-3（第三项为 school-3）。\n- 但本会话的只读工具 admission.get_current_plan 返回“unsupported call”，无法读到方案的实时明细，因此我无法确认第三项到底是哪所学校、叫什么名字；候选集合里目前只有甲大学（school-1）和乙大学（school-2），school-3 并不在候选集合中。\n- 按当前阶段规则，删除属于写入操作，必须先给出明确的待确认提案、经你确认后由后端校验执行；我不会在身份未确认的情况下直接删除。\n\n请确认：要删除的是 plan-1 中第三项（entityId=school-3）吗？确认它对应的学校名称后，我会生成一个待你确认的删除提案。", "clarificationRequested": true, "proposalRef": null, "executionStatus": "partial", "limitations": ["历史分数来自语义测试数据集（dataVersion=semantic-fixture-1，limitations=[semantic_fixture_only]），非正式生产数据。", "只读工具 admission.get_current_plan 在本会话不可用（unsupported call），未能读取方案明细。", "历史结果仅含 minimumScore，未包含招生计划数、录取位次、录取率等字段，故未生成 admissionFacts 中的录取率与风险档位。", "当前阶段为只读，删除等写入操作未执行，也未生成已确认的提案。"], "nextStep": "你确认待删除的志愿项（plan-1 第三项 school-3）及其学校名称后，我会生成一个待确认的删除提案；你明确确认后再由后端执行。", "conversationAction": {"actionType": "request_clarification", "proposalRef": null, "expectedSourceVersion": 42, "intent": "explicit"}}}
```

三次运行的 `mcpCalls` 均为 2 条，逐条内容与第四节 `reference-complete-history` 列出的两条相同。

### 8.3 步骤 5 期间观察到的其他事实

- `reference-missing-scope` 三次 `mcpCalls` 均为 0、`observed.tools` 均为 `[]`，三次均 `passed=True`。
- `reference-authoritative-history` 三次 `mcpCalls` 为 2 / 3 / 3，`reference-complete-history` 为 2 / 3 / 2；`mcpCalls` 条数在同一场景的不同次运行之间不一致。
- `mixed-read-write-3` 的 `limitations` 第二条提到 `admission.get_current_plan` 为 `unsupported call`；夹具 `tool_list()` 只声明了 `catalog.search_schools` 与 `admission.get_history` 两个工具。
