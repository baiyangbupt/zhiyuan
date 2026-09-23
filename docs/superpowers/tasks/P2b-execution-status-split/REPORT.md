---
task: P2b（P2 第 4 项）
status: DONE_WITH_CONCERNS
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 07:0x +0800
source: docs/superpowers/plans/2026-09-13-P0第二条验收条mixed-read-write的四个成因.md 第六节 表第 4 行
---

# P2b 报告：拆开"工具是否成功"与"诉求是否满足"两个语义

## 一、结论

计划书要求的是"**两个字段**，或者**一个只降不升的合并规则**——后者改动小、方向单调，倾向后者"。

**查证结果：只降不升的合并规则已经在工作区里落地了**（不是本会话做的）：

- `app/engine/result_synthesis.py::synthesize_execution_status` 的 docstring 就写着
  「**只降不升**：工具跑成功不能把用户诉求判成"完成"」，实现是
  `if _SEVERITY[tool_status] > _SEVERITY[status]: status = tool_status`——**单向**的；
- 调用点在 `app/gateway/service.py:1121` ✓。

**但这三件事没跟上**，本会话补了两件、记了一件：

| # | 缺口 | 处置 |
|---|---|---|
| 1 | 单调性的**关键那半**没有专测：既有 4 条量的都是"工具失败/部分成功把状态拉低"，没有"**工具成功不许把模型说的 partial 抬高**" | 已补（`test_result_synthesis.py`） |
| 2 | **冒烟量的是模型原值，不是生产返回值** —— 计划书原话："就算成因 1 修好、模型每次都可靠地填 `partial`，冒烟会变绿，而生产依然返回 `completed`。绿灯和修好之间没有关系" | 已补（冒烟接上同一条合成规则） |
| 3 | 计划书那句"生产依然返回 completed"是**针对当时的生产代码**说的；那之后代码已经改成单向合并，这句话不再成立 | 记在这里，不改计划书正文 |

## 二、交付

| 路径 | 变更 | 验证 |
|---|---|---|
| `tests/unit/test_result_synthesis.py` | 新增 `test_a_successful_batch_never_upgrades_the_models_partial`：模型说 `partial` + 工具全成功 → **仍是 `partial`** | 5 passed |
| `scripts/codex_semantic_smoke.py` | 新增 `_trace_as_production_returns_it(...)`：建 trace → 按批次报告合成 `executionStatus` → **有变化才重建**；判定改用这条 trace | 4 passed（含新增 1 条） |
| `tests/unit/test_codex_semantic_smoke.py` | 新增 `test_the_smoke_measures_what_production_returns_not_the_raw_model_value`：模型说 `completed` + 工具失败 → 判定看到的**是被拉低的值** | 同上 |

**测试分工写清楚了**：反方向（"工具成功不许抬高"）放在 `test_result_synthesis.py`——
那里能用最少的依赖构造出"成功的批次"；冒烟那边构造不出（少一个参数的调用会被批次判成
`blocked`，与工具本身状态无关，实测踩到过）。两边各测自己构造得出来的那一半。

## 三、验收（原始输出）

```text
$ .venv/bin/python -m pytest tests/unit/test_result_synthesis.py tests/unit/test_codex_semantic_smoke.py -q
9 passed
```

真实冒烟（`--scenario mixed-read-write`，接上合成规则之后）：

```text
hasEvaluation = True | failures = ['proposal_missing', 'execution_status_mismatch', 'limitations_missing', 'next_step_missing']
trace.executionStatus = None | calls = ['admission.get_history', 'admission.get_history']
```

即：**判定仍然量到模型原值 `None`**（成因 1：模型把契约字段说进散文、字段留空），
而不是被合成"补"出一个好看的值——这正是要的：合成只降不升，不会替模型把字段填上。

全量（打真实 Redis）：`1 failed, 1937 passed, 35 skipped`——那 1 条是既有的
`test_dialog_quality_gate`（缺 `session_volunteer_*.json`），与本任务无关。

## 四、边界与未做

- **没有**把 `synthesize_execution_status` 换成两个字段（计划书倾向合并规则，实现已经是它）；
- **没有**动 `mixed_read_write_scenario` 的期望（那是 P2 第 2 项，需要 A/B 裁决）；
- **没有**为实现"契约字段不可省略"改 schema/提示词（那是 P2 第 1 项，且计划书规定
  **排在最后**——先定期望才知道要做到什么程度）；
- **未验**：真实运行里"工具失败、模型宣称 completed、生产把它拉低"这一整条端到端路径。
  它需要构造一次工具失败的语义场景；当前场景集里没有（`mixed-read-write` 的工具是成功的）。
  已验到的是它的两个零件：合成规则本身（单测）与"冒烟判定走合成后的值"（单测）。
