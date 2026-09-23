---
task: P2e（P2d 第四节遗留的检查）
status: DONE
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 08:3x +0800
source: docs/superpowers/tasks/P2d-contract-schema-alignment/REPORT.md 第四节第 2 条
---

# P2e 报告：工具契约的三处漂移，查一修二

## 一、结论

P2d 留的那条"工具契约与夹具 schema 没做同样比对"**查出了两次真实漂移**——
与 `artifactType` 同源：**同一件事有两个说法，其中一个悄悄长歪了**。

| 工具 | 编排层 `TOOL_CONTRACTS` | 真实 MCP 工具（`server.py` 的 `_input_schema(...)`） | 冒烟夹具 | 判定 |
|---|---|---|---|---|
| `admission.get_history` | `{schoolId, **majorId**, areaId, batch, year, subjectType}` ✗ | `{schoolId, areaId, batch, year, subjectType}` ✓ | 6 个（含 majorId）✗ | **编排层与夹具都错**，真实工具对 |
| `catalog.search_schools` | `{}` ✓ | `{}` ✓ | `{query}` ✗ | 夹具比真实更严 |

**哪一侧对，是查出来的不是猜的**：`get_history` 缺 `majorId` 时，真实处理器只追加一条口径限制
（`caliber_unit_level_not_major`——"这是**院校/专业组级**投档线"），**不是错误**：
这条查询本来就是学校级口径。所以 schema 是对的，编排层多要了一个参数。

**后果链（用户可见）**：编排层多要 `majorId` → 模型按学校级口径查询时不传它 →
`prepare_tool_invocation` 判 `blocked` → 批次报告降级 → `result_synthesis`
（P2b 的只降不升）把整轮状态压低并补一句"请补充缺失参数后继续"——
**而工具本可以正常回答**。同时 `render_tool_contracts()` 还在告诉模型"必需参数=…majorId…"，
于是它要么为一个学校级问题去问专业，要么猜一个专业填进去。

## 二、交付

| 路径 | 变更 |
|---|---|
| `app/engine/tool_orchestration.py` | `admission.get_history` 的必需参数去掉 `majorId`（与真实工具对齐，注释写明为什么多要一个参数不是"更严格"） |
| `tests/fixtures/mcp/semantic_readonly_server.py` | 两处对齐：`get_history` 的 required 去掉 `majorId`（保留该 property）；`catalog.search_schools` 的 required 改为 `[]` |
| `tests/unit/test_tool_orchestration.py` | 新增 `test_the_orchestration_contract_matches_the_real_mcp_tool_schemas`：逐条比对编排层与真实 MCP schema 的必需参数（含"编排层不许列真工具里没有的名字"）。**红-绿**：把 `majorId` 加回去即 `1 failed` |
| `tests/unit/test_turn_trace.py` | 更正一条断言：它原来把**漂移后的清单**当成事实（期望里带着 `majorId`）。**它此前是绿的，因为它和 bug 一致**——本项目第四次遇到"仪表与缺陷同向"这个形状 |

## 三、验收（原始输出）

比对脚本的输出（修复前）：

```text
[编排 vs MCP] admission.get_history: ['areaId','batch','majorId','schoolId','subjectType','year']
                                    vs ['areaId','batch','schoolId','subjectType','year']
[MCP vs 夹具] admission.get_history: 5 个 vs 6 个
[MCP vs 夹具] catalog.search_schools: [] vs ['query']
（其余差异是刻意的：夹具只声明 3 个工具、编排层只管 4 个工具）
```

修复后：

```text
$ .venv/bin/python -m pytest tests/unit tests/integration -q
1 failed, 1939 passed, 35 skipped        # 那 1 条是既有的 test_dialog_quality_gate（缺文件）
$ .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history
passed=True failures=[]                  # 夹具改动后冒烟照常
```

## 四、边界与未做

- **编排层只治理 4 个工具**（真实服务暴露 14 个）：不在编排层里的工具**没有缺参检查**
  （调用它们不会进批次报告）。这是既有设计，**本次未动**，只记一句。
- **没有重跑 P0 的 20×2 测量**：那次测量（`P0-acceptance-measurement/REPORT.md`）发生在本修正
  之前，而本修正**同时改了模型看到的必需参数清单**（`render_tool_contracts` 进了冒烟的输入）
  与夹具。两处改动方向都是"更贴近真实"，**不预期改变结论**，但严格说 P0 那两个数
  应当以修正后的代码复跑一次（命令在同一份报告里，约 20 分钟）。
- **没有**做"真实 MCP 工具 vs Java 侧语义"的比对（那要 Java 侧参与，超出本会话范围）。
