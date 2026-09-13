---
task: T008
status: DONE_WITH_CONCERNS
executor: claude-subagent（非 DeepSeek，见文末「转录说明」）
finished_at: 2026-09-13 17:20 +0800
---

> **转录说明（设计会话补记）**：本报告由实现方（Claude subagent）撰写，但它的 Write 工具被策略拦截（"Subagents should return findings as text, not write report files"），无法写入本路径。实现方**没有绕过拦截**（没有改用 Bash heredoc、也没有转派给别的 agent），而是把全文作为文本返回——这个处理是对的。正文由设计会话逐字转录，**未作内容改动**，仅有两处修正：
>
> 1. 原文 frontmatter 写 `executor: deepseek`，实际执行方是 Claude subagent。本协议里"谁做的"影响判定权重，故更正。
> 2. 第六节偏离项 2 的措辞按实际情况保留。
>
> 复核结论见同目录 `REVIEW.md`。

# T008 报告

## 一、结论

解析层（`_parse_json_object` 分层取值）与仪表层（`payload["evaluation"]` 恒写入）改动已完成；任务书第 1–8 条验收命令均已实际执行，原始输出见第四节，第 8 条真实端点连跑 10 次，10/10 次 payload 里都出现 `evaluation` 键。

## 二、交付物

| 路径 | 字节数 | 说明 |
|---|---|---|
| app/harness/codex.py | 16426 | 解析层：`_parse_json_object` 改为分层尝试（direct → fenced → embedded → missing），新增 `_extract_output_ex` 返回 `(output, extraction)` 元组；`_extract_output` 保留原 `dict \| None` 签名，内部委托给 `_extract_output_ex`，不影响既有调用方 |
| app/harness/turn_result.py | 612 | `CodexTurnResult` 新增 `output_extraction: dict` 字段，`default_factory` 为 `{"source": "missing", "candidateCount": None}` |
| scripts/codex_semantic_smoke.py | 14397 | 仪表层：payload 恒写入 `outputExtraction`；新增 `_missing_output_evaluation()`，在 `status != "completed"` 或 `output` 不是 dict 时把 `payload["evaluation"]` 显式置为 `passed: False`，`failures` 含字符串 `"output_missing"`；不合成 `trace` |
| tests/unit/test_codex_output_extraction.py | 9589 | 新增文件，12 个用例，覆盖任务书验收第 1–6 条 |

## 三、实际改动的文件

以下为 `git status --short` 限定到本任务 4 个文件的实际输出（同一工作树里还有其他会话未提交的改动，按任务书边界要求不在此列出）：

```
 M app/harness/codex.py
 M app/harness/turn_result.py
 M scripts/codex_semantic_smoke.py
?? tests/unit/test_codex_output_extraction.py
```

## 四、验收命令与原始输出

### 命令 1（对应任务书验收第 1–6 条：新增单测）

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_codex_output_extraction.py -v
```

```
============================= test session starts ==============================
platform linux -- Python 3.10.14, pytest-9.0.3, pluggy-1.6.0 -- /root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /root/dev/zhiyuan/zhiyuan-agent
configfile: pyproject.toml
plugins: asyncio-1.4.0, mock-3.15.1, logfire-4.37.0, anyio-4.13.0
asyncio: mode=auto, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 12 items

tests/unit/test_codex_output_extraction.py::test_pure_json_is_direct_source_happy_path_unchanged PASSED [  8%]
tests/unit/test_codex_output_extraction.py::test_prose_prefixed_fenced_json_is_extracted PASSED [ 16%]
tests/unit/test_codex_output_extraction.py::test_whole_value_as_fence_still_works PASSED [ 25%]
tests/unit/test_codex_output_extraction.py::test_two_fenced_blocks_hits_last_and_reports_candidate_count PASSED [ 33%]
tests/unit/test_codex_output_extraction.py::test_prose_without_any_json_is_missing PASSED [ 41%]
tests/unit/test_codex_output_extraction.py::test_non_json_chinese_braces_do_not_degrade_to_regex_scraping PASSED [ 50%]
tests/unit/test_codex_output_extraction.py::test_embedded_balanced_json_without_fences_is_extracted PASSED [ 58%]
tests/unit/test_codex_output_extraction.py::test_extract_output_end_to_end_prose_then_fence PASSED [ 66%]
tests/unit/test_codex_output_extraction.py::test_extract_output_end_to_end_missing_json PASSED [ 75%]
tests/unit/test_codex_output_extraction.py::test_smoke_payload_evaluation_present_and_failed_when_output_missing PASSED [ 83%]
tests/unit/test_codex_output_extraction.py::test_smoke_payload_evaluation_present_when_status_not_completed PASSED [ 91%]
tests/unit/test_codex_output_extraction.py::test_smoke_payload_evaluation_passed_true_when_output_present_control PASSED [100%]

============================== 12 passed in 0.14s ==============================
```

各验收编号对应的用例名：

- 验收1（散文+尾部围栏 JSON 取得到，`source=fenced`）→ `test_prose_prefixed_fenced_json_is_extracted`、`test_extract_output_end_to_end_prose_then_fence`
- 验收2（散文里没有 JSON 仍为 `None`，`source=missing`）→ `test_prose_without_any_json_is_missing`、`test_extract_output_end_to_end_missing_json`
- 验收3（中文花括号非法 JSON 仍为 `None`，不退化为抠片段）→ `test_non_json_chinese_braces_do_not_degrade_to_regex_scraping`
- 验收4（两个围栏 JSON 命中最后一个，`candidateCount==2`）→ `test_two_fenced_blocks_hits_last_and_reports_candidate_count`
- 验收5（纯 JSON 的 happy path 不变，`source=direct`）→ `test_pure_json_is_direct_source_happy_path_unchanged`
- 验收6（output 取不到时 `payload.evaluation` 存在且 `passed=False`，且同一分支对正常 output 给出 `passed=True` 的对照）→ `test_smoke_payload_evaluation_present_and_failed_when_output_missing`、`test_smoke_payload_evaluation_present_when_status_not_completed`、`test_smoke_payload_evaluation_passed_true_when_output_present_control`

### 命令 2（补充验证，非任务书编号项：确认向后兼容未破坏既有测试）

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_codex_harness_client.py -v
```

```
============================= test session starts ==============================
platform linux -- Python 3.10.14, pytest-9.0.3, pluggy-1.6.0 -- /root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /root/dev/zhiyuan/zhiyuan-agent
configfile: pyproject.toml
plugins: asyncio-1.4.0, mock-3.15.1, logfire-4.37.0, anyio-4.13.0
asyncio: mode=auto, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 16 items

tests/unit/test_codex_harness_client.py::test_client_correlates_response_and_notification PASSED [  6%]
tests/unit/test_codex_harness_client.py::test_harness_passes_thread_approval_policy PASSED [ 12%]
tests/unit/test_codex_harness_client.py::test_harness_sends_structured_turn_sandbox_policy PASSED [ 18%]
tests/unit/test_codex_harness_client.py::test_client_surfaces_json_rpc_error PASSED [ 25%]
tests/unit/test_codex_harness_client.py::test_client_times_out_without_leaking_pending_request PASSED [ 31%]
tests/unit/test_codex_harness_client.py::test_client_supports_concurrent_requests_without_id_collision PASSED [ 37%]
tests/unit/test_codex_harness_client.py::test_client_marks_pending_requests_failed_when_process_exits PASSED [ 43%]
tests/unit/test_codex_harness_client.py::test_harness_waits_for_turn_completed_notification PASSED [ 50%]
tests/unit/test_codex_harness_client.py::test_harness_waits_for_turn_completion_after_agent_message_item PASSED [ 56%]
tests/unit/test_codex_harness_client.py::test_harness_waits_even_after_final_agent_message PASSED [ 62%]
tests/unit/test_codex_harness_client.py::test_nested_turn_terminal_status[completed] PASSED [ 68%]
tests/unit/test_codex_harness_client.py::test_nested_turn_terminal_status[failed] PASSED [ 75%]
tests/unit/test_codex_harness_client.py::test_nested_turn_terminal_status[interrupted] PASSED [ 81%]
tests/unit/test_codex_harness_client.py::test_turn_match_accepts_thread_scoped_mcp_notification_without_turn_id PASSED [ 87%]
tests/unit/test_codex_harness_client.py::test_extract_output_accepts_json_markdown_fence PASSED [ 93%]
tests/unit/test_codex_harness_client.py::test_client_routes_concurrent_notification_waiters_without_cross_turn_blocking PASSED [100%]

============================== 16 passed in 12.22s ==============================
```

### 命令 3（对应任务书验收第 7 条：全量单测）

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
bash scripts/run_unit_tests.sh 2>&1 | tail -8
```

（任务书原文是 `tail -6`；实跑时多留了 2 行 warning 上下文，未删减任何内容，6 行判定信息完整包含在内。）

```
  /root/dev/zhiyuan/zhiyuan-agent/app/agent/base_agent.py:375: PydanticAIDeprecationWarning: `AgentRun.usage` is no longer a method; access it as a property (drop the parentheses).
    usage = agent_run.usage()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
=========== 2 failed, 1712 passed, 34 skipped, 22 warnings in 27.85s ===========
```

### 命令 4（对应任务书验收第 8 条：真实端点 × 10）

实际执行的核心命令（`codex_semantic_smoke.py` 的调用方式、参数、重定向路径，以及内联判定 snippet）与任务书原文逐字一致：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
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

这段循环整体放在一个后台 shell 任务里执行，且每次调用前后各加了一行时间戳记录（用于跟踪长耗时后台任务的进度），细节见第六节。以下是 `/tmp/t008-summary.txt` 的完整原始内容（10 次全部顺序跑完，无一跳过）：

```
=== starting run 1 at 17:08:13 ===
run 1: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 1 at 17:08:25 ===
=== starting run 2 at 17:08:25 ===
run 2: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 2 at 17:08:36 ===
=== starting run 3 at 17:08:36 ===
run 3: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 3 at 17:08:51 ===
=== starting run 4 at 17:08:51 ===
run 4: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 4 at 17:09:00 ===
=== starting run 5 at 17:09:00 ===
run 5: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 5 at 17:09:09 ===
=== starting run 6 at 17:09:09 ===
run 6: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 6 at 17:09:18 ===
=== starting run 7 at 17:09:18 ===
run 7: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 7 at 17:09:29 ===
=== starting run 8 at 17:09:29 ===
run 8: status=completed outputPresent=False extraction={'source': 'missing', 'candidateCount': None} hasEvaluation=True passed=False
=== finished run 8 at 17:09:39 ===
=== starting run 9 at 17:09:39 ===
run 9: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 9 at 17:09:50 ===
=== starting run 10 at 17:09:50 ===
run 10: status=completed outputPresent=True extraction={'source': 'direct', 'candidateCount': None} hasEvaluation=True passed=True
=== finished run 10 at 17:10:00 ===
ALL_DONE
```

判定口径核对：`hasEvaluation=True` 出现 **10/10**（任务书唯一的门禁指标）。`passed=True` 出现 9/10（run 1–7、9、10），`passed=False` 出现 1/10（run 8，`extraction.source=missing`，即该次连内嵌兜底都没有取到 JSON，属于真实的"没拿到输出"，不是伪造的失败）。`extraction.source` 分布：`direct` 9 次，`missing` 1 次，`fenced` 0 次，`embedded` 0 次——10 次真实调用未复现 T005 报告的"散文+围栏"包装，按任务书判定口径这是正常情况，未去改场景或提示词以强行复现。

10 个 `/tmp/t008-run-*.err` 文件全部是 0 字节：

```
369014 /tmp/t008-run-1.json      0 /tmp/t008-run-1.err
289839 /tmp/t008-run-2.json      0 /tmp/t008-run-2.err
408671 /tmp/t008-run-3.json      0 /tmp/t008-run-3.err
228621 /tmp/t008-run-4.json      0 /tmp/t008-run-4.err
260124 /tmp/t008-run-5.json      0 /tmp/t008-run-5.err
217811 /tmp/t008-run-6.json      0 /tmp/t008-run-6.err
299875 /tmp/t008-run-7.json      0 /tmp/t008-run-7.err
259555 /tmp/t008-run-8.json      0 /tmp/t008-run-8.err
322168 /tmp/t008-run-9.json      0 /tmp/t008-run-9.err
243437 /tmp/t008-run-10.json     0 /tmp/t008-run-10.err
```

补充（非任务书要求的门禁，仅作记录）：对 9 次非缺失 run 直接读取 `evaluation.passed`/`failures`/`elapsedMs`：

```
run 1: evaluation.passed=True failures=[] elapsedMs=12161.8
run 2: evaluation.passed=True failures=[] elapsedMs=10381.9
run 3: evaluation.passed=True failures=[] elapsedMs=14017.2
run 4: evaluation.passed=True failures=[] elapsedMs=8383.2
run 5: evaluation.passed=True failures=[] elapsedMs=8994.9
run 6: evaluation.passed=True failures=[] elapsedMs=8146.5
run 7: evaluation.passed=True failures=[] elapsedMs=10284.6
run 9: evaluation.passed=True failures=[] elapsedMs=11143.0
run 10: evaluation.passed=True failures=[] elapsedMs=8893.9
```

run 8（唯一一次 `passed=False`）的完整关键字段：

```
status: completed
errorCode: None
output: None
outputExtraction: {'source': 'missing', 'candidateCount': None}
evaluation: {"caseId": "reference-complete-history", "passed": false, "failures": ["output_missing"], "observed": {"status": "completed", "errorCode": null, "outputExtraction": {"source": "missing", "candidateCount": null}}}
elapsedMs: 9396.6
errors: []
mcpCalls count: 2
```

## 五、与已知失败基线的对照

| 失败用例 | 在基线内？ | 说明 |
|---|---|---|
| tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture | 是 | 与任务书给出的基线一致 |
| tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session] | 是 | 与任务书给出的基线一致 |

基线外无新增失败。总数从基线的 `2 failed, 1700 passed, 34 skipped` 变为 `2 failed, 1712 passed, 34 skipped`：新增的 12 个全部是本任务新建的 `tests/unit/test_codex_output_extraction.py`，`34 skipped` 与基线一致。

## 六、偏离任务书之处

1. 任务书第 8 条给出的验证命令是一段会阻塞前台的 `for i in $(seq 1 10); do ... done` 循环。实际执行时，本会话把整段循环放进了一个后台 shell 任务，并在每次调用前后各加了一行 `echo "=== starting/finished run $i at <时间> ==="` 写入 `/tmp/t008-summary.txt`，用于在后台运行期间跟踪进度（10 次真实调用总耗时约 107 秒）。循环内部真正产生判定结果的两条语句——`codex_semantic_smoke.py` 的调用方式/参数/重定向路径，以及内联判定 snippet（用 `'evaluation' in d` 而非 `.get()`，打印字段与顺序）——与任务书原文逐字一致，未做任何修改。判断依据：`/tmp/t008-summary.txt` 里 10 行 `run N: ...` 的字段名、字段顺序、取值方式与任务书给出的 `print` 语句完全对应；各次调用的起止时间戳显示是严格顺序执行（下一轮的 `starting` 时间等于上一轮的 `finished` 时间），不是并发跑的，与任务书"连跑 10 次"的意图一致。
2. 报告本身未能写入任务书指定路径 `/root/dev/zhiyuan/docs/superpowers/tasks/T008-output-extraction/REPORT.md`：本会话的 Write 工具对"报告/总结/结论"类 .md 文件有强制拦截（工具原文："Subagents should return findings as text, not write report files"），未尝试用 Bash/Edit 等其他方式绕过这个拦截。完整报告内容改为在最终回复文本里给出。

其余步骤（解析层分层实现、`output_extraction` 字段的引入方式、`_extract_output`/`_extract_output_ex` 的签名拆分、`output_missing` 失败字符串的选取）均在任务书第四节明确授权"形式自定/字符串自定"的范围内，不构成偏离。

## 七、未做的事

无（报告文件本身的写入受阻，已在第六节第 2 条说明；其余任务书要求的代码改动与验收步骤均已完成）。

## 八、观察到的异常现象（只列事实）

1. 真实端点 10 次运行中，第 8 次（run 8）的 `outputExtraction` 为 `{'source': 'missing', 'candidateCount': None}`：模型这次回合的最终输出里，直接解析、所有围栏块解析、最外层平衡花括号解析三条路径均未取到字典。这与任务书背景一节描述的"散文+围栏取不到"（T005 撞到的形状）不是同一种失败：run 8 是"整个回合确实没有可解析的 JSON"，而不是"JSON 存在但被散文包裹导致解析器够不着"。该次 `status=completed`、`errorCode=None`、`errors=[]`、`mcpCalls=2`（两次工具调用均已执行）、`elapsedMs=9396.6`。
2. run 8 的 `eventSummaries` 中 6 条 `item/completed` 事件的 `text` 字段全部是空字符串 `""`。`codex_semantic_smoke.py` 里 `eventSummaries` 的构造只读事件顶层的 `text`/`message`/`delta` 三个键，而 agentMessage 的正文实际嵌在 `event["item"]["text"]` 里；这段构造代码本次任务未改动。结果是无法从 payload 本身回看 run 8 模型当时具体写了什么文本。
3. 10 次运行里，9 次成功提取的 `outputExtraction.source` 全部是 `direct`，没有出现 `fenced` 或 `embedded`。
4. 10 个 `.err` 文件全部是 0 字节，没有进程崩溃、超时或未捕获异常的痕迹。
5. 对 4 个改动/新增文件执行 `grep -InE "auth\.json|api[_-]?key|sk-[A-Za-z0-9]"` 无匹配；确认 `.codex-semantic-home/` 在 `.gitignore` 第 40 行覆盖。
