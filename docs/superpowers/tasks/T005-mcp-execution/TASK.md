# T005：让只读 MCP 工具真正执行，并修好语义冒烟的观测仪表

> 指派：DeepSeek
> 来源：`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 第三章 P1 的前置；T003 REVIEW 勘误
> 类型：代码改动 + 验证复现
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

`scripts/codex_semantic_smoke.py` 是当前唯一验证「模型真实交互能力」的入口。它现在有两个独立缺陷：只读 MCP 工具被 codex 判为需审批而遭拒；脚本用来观测工具调用的 `mcpCalls` 仪表根本没有读数。两个缺陷叠加，导致这个脚本的结论**既不能证明跑通、也不能证明没跑通**。本任务把两处都修好，然后给出一份可信的语义评估基线。

一句话验收：`reference-complete-history` 场景连续 3 次 `evaluation.passed == true`，且同一批运行的 `mcpCalls` 非空并与夹具自身记录的调用一一对应。

---

## 二、背景（你的会话没有这些上下文）

这是一个高考志愿填报咨询系统。对话引擎正从旧的状态机迁移到由 codex App Server 托管、DeepSeek 驱动的新引擎。新引擎的核心安全约束是：**模型陈述的任何招生事实都必须绑定到真实工具返回的证据**，不允许凭空生成。

`scripts/codex_semantic_smoke.py` 拉起真实 codex 进程 + 真实 DeepSeek 端点 + 一个只读 MCP 夹具服务器（`tests/fixtures/mcp/semantic_readonly_server.py`），跑 4 个语义场景，检查模型是否做对了：选对工具、填对参数、该澄清时澄清、该拒绝写操作时拒绝、事实是否带证据。判定结果在返回 JSON 的 `evaluation.passed` / `evaluation.failures`。

上一个任务（T003）修好了 schema 兼容性，让请求不再被 DeepSeek 以 HTTP 400 拒收。但 T003 的验收条件写的是 `status=completed`——那只表示 codex 这一回合正常收尾，量不出场景是否真的跑通。补跑语义评估后发现 6 次运行里 4 次 `evaluation.passed == false`。本任务处理其中的工具执行部分。

---

## 三、已核实的环境事实（不要重新调查，直接用）

| 事实 | 值 |
|---|---|
| Python 环境 | `/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python` |
| 系统 python3 | 3.6.8，**不要用** |
| 冒烟脚本 | `scripts/codex_semantic_smoke.py`，`--scenario` 四选一 |
| 单次运行耗时 | 9–25 秒，走真实 DeepSeek 端点，会产生费用，别无脑循环 |
| codex 本地副本 | `/root/dev/codex`（只读参考，**不要改**） |

### 已实测确认的因果链（设计会话做的探针，结论可直接采信）

**缺陷 A —— 只读工具被拒执行：**

- codex `codex-rs/core/src/mcp_tool_call.rs:2256` `requires_mcp_tool_approval()`：只有当工具 annotations 里 `readOnlyHint == true` 时才 `return false`（免审批）。取不到时 `unwrap_or(false)`，随后 `destructive_hint.unwrap_or(true)` 为真 → 判定需要审批。
- 同文件 `:1390` 在 `AppToolApproval::Auto`（`config/src/mcp_types.rs:26` 的 `#[default]`）下走上面这条判定；`strict_auto_review` 默认 `false`，不会绕开。
- 同文件 `:1482`：一旦判定需要审批而 `approval_policy == Never`，直接 `ReviewDecision::denied("MCP tool call requires approval, but approval policy is never")`。
- `tests/fixtures/mcp/semantic_readonly_server.py` 的 `tool_list()` 只给了 `name` / `description` / `inputSchema`，**没有 `annotations`**，因此两个只读工具全部落进"需审批"分支。
- 探针实测：给两个工具各加 `"annotations": {"readOnlyHint": True}` 后，`reference-complete-history` 单次运行 `evaluation.passed == true`、`failures == []`、`evidenceIds` 首次非空（两条 `history:school-*:major-cs:...`）、耗时 9.0 秒。

**结论：不要改 `approval_policy`。** `never` 是刻意选的生产默认值，它同时挡着 shell 和写操作。codex 自带的只读豁免通道正是我们要的，缺的只是工具没声明。

**缺陷 B —— `mcpCalls` 仪表没有读数：**

- 脚本 `:132` 用 `os.environ["ZHIYUAN_SEMANTIC_MCP_TRACE"] = trace_file.name` 传 trace 路径；夹具 `:12` 在导入时读这个变量，`record()` 在变量为空时直接 `return`。
- 探针实测：在夹具里无条件写一行日志，拿到 `BOOT trace_env=None`——**codex 不把这个环境变量传给 MCP 子进程**。所以 `record()` 每次都早退，trace 文件恒空，`payload["mcpCalls"]` 恒为 `[]`，与工具是否执行**完全无关**。
- 同一次运行，夹具的无条件日志记到了两次真实调用：

  ```
  CALL admission.get_history {'schoolId': 'school-1', 'majorId': 'major-cs', 'areaId': '330000', 'batch': '本科批', 'year': 2025, 'subjectType': '物理类'}
  CALL admission.get_history {'schoolId': 'school-2', 'majorId': 'major-cs', 'areaId': '330000', 'batch': '本科批', 'year': 2025, 'subjectType': '物理类'}
  ```

- **argv 是通的**：脚本 `:139` 已经在用 `fixture_args.append("--authoritative")` 给夹具传参并生效，说明 codex 转发 `args`。这是替代环境变量的现成通道。

---

## 四、步骤

### 步骤 1：让两个只读工具声明 `readOnlyHint`

在 `tests/fixtures/mcp/semantic_readonly_server.py` 的 `tool_list()` 里，给 `catalog.search_schools` 和 `admission.get_history` 各加：

```python
"annotations": {"readOnlyHint": True},
```

只加这一个键。**不要**顺手加 `destructiveHint` / `openWorldHint`——`requires_mcp_tool_approval()` 对它们的默认取值已经是我们要的，多写反而增加以后误配的面。

### 步骤 2：把 trace 通道从环境变量改成 argv

按缺陷 B 的实测，环境变量传不进去。改成用命令行参数传：

- 脚本侧：在 `fixture_args` 里追加 trace 文件路径（形如 `--trace <path>`），保留现有 `--authoritative` 的传法不变。
- 夹具侧：从 `sys.argv` 解析 `--trace`，解析不到时**再**回退到现有的环境变量读法（保留回退，别删——夹具也被 `tests/unit/test_semantic_readonly_server.py` 直接调用）。

改完后 `record()` 必须真的落盘。

### 步骤 3：让 `observed.tools` 可信

`evaluation.failures` 里的 `missing_tools` 目前依赖 `observed.tools`，而实测出现过「工具确实执行了但 `observed.tools == []`」。步骤 2 修好 trace 之后，确认 `observed.tools` 的取值口径把 `mcpCalls` 也算进去（现在它主要依赖 turn events，而 codex 把 MCP 调用报成通用的 `item/started` / `item/completed`，没有专门的事件类型）。

口径怎么改由你定，但必须满足：**夹具日志记到了调用，`observed.tools` 就不能是空**。

### 步骤 4：加一条回归测试

在 `tests/unit/test_semantic_readonly_server.py` 里加断言：`tool_list()` 返回的每个工具都带 `annotations.readOnlyHint == True`。

这条测试的意义是防止以后有人加新工具时漏声明——漏了就会退回到"静默被拒"，而那个失败模式极难从现象上看出来。

### 步骤 5：给出可信的语义评估基线

四个场景（`reference-missing-scope`、`reference-complete-history`、`reference-authoritative-history`、`mixed-read-write`）各跑 3 次，**每次记录 `evaluation.passed`、`evaluation.failures`、`mcpCalls` 条数、`observed.tools`、`observed.evidenceIds`、`elapsedMs`**，整理成一张表放进报告。

**这一步不要求全过。** 它的目的是拿到一份诚实的基线。跑出来什么样就报什么样，失败的场景照实列 `failures` 原文，**不要为了让它过而去改场景期望值或评估逻辑**。

---

## 五、陷阱（会让你踩坑或误伤的地方）

1. **别改 `approval_policy` 或 `sandbox_policy`。** `app/config.py:147-148` 的 `"never"` / `"read-only"` 和 `codex_semantic_smoke.py:169` 的 `approval_policy="never"` 都是刻意的安全默认值。本任务的整个论点就是不用动它们。
2. **别改 `TURN_OUTPUT_SCHEMA`。** 那是 T003 刚验过的资产，`app/gateway/service.py` 里的 `_normalize_nullable_for_upstream()` 及其单测不要碰。
3. **别改场景的期望值。** `SemanticExpectation(...)` 里的 `required_tool_names` / `response_type` / `execution_status` 等是契约，不是可调参数。步骤 5 跑不过就如实报告。
4. **夹具 stderr 看不到。** codex 吞掉 MCP 子进程的 stderr，调试时想看夹具内部状态只能写文件。
5. **单次运行会真实计费。** 步骤 5 一共 12 次运行，别为了"多验几遍"自行加量。

---

## 六、验收

按顺序执行，全部必须通过：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# 1. 回归测试：夹具工具全部声明 readOnlyHint
.venv/bin/python -m pytest tests/unit/test_semantic_readonly_server.py -v

# 2. 仪表自证：跑一次，mcpCalls 必须非空
#    （这一条是在验"仪表是活的"，不是在验业务；见 README 规则 4）
.venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history \
  | .venv/bin/python -c "import sys,json; d=json.loads(sys.stdin.read().strip().splitlines()[-1]); \
print('mcpCalls=',len(d.get('mcpCalls') or [])); print('tools=',d['evaluation']['observed'].get('tools')); \
print('passed=',d['evaluation']['passed']); print('failures=',d['evaluation']['failures'])"

# 3. 主验收：同场景连续 3 次，evaluation.passed 全为 true
#    把三次的完整 evaluation 段落原样贴进报告
for i in 1 2 3; do
  echo "--- run $i ---"
  .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history \
    | .venv/bin/python -c "import sys,json; d=json.loads(sys.stdin.read().strip().splitlines()[-1]); \
e=d['evaluation']; o=e['observed']; \
print('passed=',e['passed'],'failures=',e['failures'],'mcpCalls=',len(d.get('mcpCalls') or []),'tools=',o.get('tools'),'evidenceIds=',o.get('evidenceIds'),'ms=',d.get('elapsedMs'))"
done

# 4. 全量单测：与基线对照
bash scripts/run_unit_tests.sh 2>&1 | tail -20
```

第 5 步的四场景 × 3 次基线表另附在报告第七节，**不计入通过与否**。

### 已知失败基线（不是你造成的，不要去修）

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1699 passed, 34 skipped
```

第一条因 `zhiyuan-server/data/tmp/session_volunteer_*.json` 本地夹具缺失，第二条与 web base path 有关，两条都与 codex 引擎链路无关。

出现基线以外的失败时，**逐条列出用例名和报错原文**，不要自行扩大修复范围。

---

## 七、边界：不要做这些

- 不要动 `app/gateway/service.py` 的 `TURN_OUTPUT_SCHEMA` 及相关归一化函数。
- 不要动 `app/config.py` 的 `approval_policy` / `sandbox_policy`。
- 不要动 `/root/dev/codex`（只读参考）。
- 不要动 `app/service.py`、`app/zhiyuan_agent/tools.py`（各近万行，正在演进）。
- 不要修改场景定义里的 `SemanticExpectation` 期望值。
- 不要"顺手"重构、格式化、改 import 顺序、加类型标注。
- 不要 commit。改完等 review。

---

## 八、报告

把报告写到：

```
/root/dev/zhiyuan/docs/superpowers/tasks/T005-mcp-execution/REPORT.md
```

格式见 `docs/superpowers/tasks/_templates/REPORT.md`，逐节填写，不要增删小节。第七节「观察到的异常现象（只列事实）」用来放步骤 5 的四场景基线表。

要点：状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`；验收命令贴**原始输出**；**不写修复建议、不写下一步、不写根因推测**。
