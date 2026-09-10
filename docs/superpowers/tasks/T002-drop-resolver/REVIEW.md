---
task: T002
verdict: ACCEPTED_WITH_FOLLOWUP
reviewer: 设计会话（Claude Opus 5）
reviewed_at: 2026-09-10
note: 本任务在分派协议建立前执行，实现方未提交 REPORT.md。本文由设计会话自行重跑验收后补做。
---

# T002 回收判定

## 一、判定

`ACCEPTED_WITH_FOLLOWUP`。主体改动正确，遗留一处文档漏网项（T004）。

## 二、自行重跑的验收

### 命令 1：悬空模块引用

```
app/models/conversation_phase.py:126:    - ActionResolver 根据 state 判断可用动作
examples/dialog_quality_gate.py:292: ... SemanticIntentFrame observation expectations ...
examples/dialog_case_evaluation_report.py:899: ... Map a SemanticIntentFrame ...
examples/semantic_frame_evaluator.py:2,229: ... SemanticIntentFrame ...
```

任务书写的是「应无输出」，实际有 5 处命中。逐条核对后判定**不构成偏离**：

- `conversation_phase.py:126` 是**注释文字**，不是代码引用。属于文档陈旧，与 T004 同类，不影响运行。
- 其余 4 处是 `SemanticIntentFrame`——与被删的 `IntentFrame` **是不同的类型**，被 grep 的子串模式误捕。属于任务书验收命令写得不够精确，是设计会话的问题，不是实现方的。

### 命令 2：生产模块覆盖仍在

```
tests/regression/test_keyword_matchers.py
```

保住了。这是本任务最容易犯的错（删掉它等于静默移除 `app/tools/review_issue_registry.py` 的全部测试覆盖，而该模块被生产的 `app/zhiyuan_agent/tools.py` 使用），实现方避开了。

### 命令 3：改写后的文件独立通过

```
................                                                         [100%]
16 passed in 0.03s
```

### 命令 4：全量单测

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1698 passed, 34 skipped, 22 warnings in 26.72s
```

两项失败均与本任务无关，已确认：

- 第一项断言 `zhiyuan-server/data/tmp/session_volunteer_*.json` 夹具存在，94 条缺失，属本地数据问题；该用例遍历 `FINAL_ACTION_CASE_FILES`，与本次改动的 `LOCAL_PYTEST_TARGETS` 无关。
- 第二项是 web base path，与被删模块无关。

两项已登记为**已知失败基线**（`README.md` 第六节），后续任务书必须携带。

## 三、改动核对

`git status` 与预期一致：删除 8 个文件（`intent_frame.py`、`typed_actions.py`、`resolver/` 整包、4 个测试文件），修改 4 个（`models/__init__.py`、`dialog_quality_gate.py`、`test_keyword_matchers.py`、`CLAUDE.md`）。边界清单内的文件（`app/service.py`、`app/zhiyuan_agent/tools.py`、`app/gateway/`、`app/engine/`、`app/harness/`、`app/mcp_server/`、`skills/`）均未被动。未 commit。

`dialog_quality_gate.py` 的 diff 是精确的单行删除，无附带改动。

## 四、遗留项

`zhiyuan-agent/CLAUDE.md` 的「Tools（意向提取工具）」一节仍写「位于 `app/tools/`，**注册到 ChatAgent**」。任务书 Part 4 只点名了第 65 行的 `ChatAgent` 条目，实现方照做删除，但同一文件另一处对 `ChatAgent` 的引用没被覆盖到——**任务书列举不全，责任在设计会话**。

→ **T004**，一行改动，并入下次文档类任务。

## 五、方法结论

T002 的意义不只在删代码：它是校准实现方是否真的遵守「陷阱」与「边界」的对照实验。结论是遵守了——最关键的一条（不要删 `test_keyword_matchers.py`）没有踩。因此可以把「绝对不缓冲」这类靠自觉执行的行为约束交给同一实现方，T001 事后也确认这条被严格执行。
