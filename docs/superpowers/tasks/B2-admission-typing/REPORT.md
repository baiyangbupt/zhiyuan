---
task: B2
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 07:20 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B2 报告：拆开历史、概率、资格和当前方案

## 一、结论

分型层建好并测了 12 条；tenant 硬编码、groupCode 口径、新旧工具名三件事落地；
并且**按计划 §3 完成了工具出口的契约切换**——统一外层改成
`{schemaVersion, kind, status, data, evidenceRefs, limitations, nextCursor}`，
`admission.get_history`（major 口径）现在返回 `kind: history` 的逐年事实，
不再返回"事实+录取率"。

这个切换是用户拍板的（三个方向里选了 a）。

## 二、交付

| 路径 | 变更 |
|---|---|
| `app/admission/tool_results.py` | 新增：`envelope`、`percentage`、`normalize_history/probability/eligibility` |
| `tests/unit/test_admission_tool_results.py` | 新增，12 条 |
| `app/util/internal_client.py` | `get_working_plan` / `get_planning_ordered_plan` 的 tenant 改为必填 |
| `app/mcp_server/tools_readonly.py` | groupCode → `unsupported_scope`；工具别名；`_ADMISSION_SHAPED_TOOLS` |
| `app/mcp_server/server.py` | 别名的输入 schema；`TOOL_OUTPUT_SCHEMA` 换成 §3 形状；`_call_domain_tool` 带上 kind |
| `app/mcp_server/response.py` | `ok`/`error` 产出 §3 外层（`kind`/`schemaVersion`/`evidenceRefs`/`nextCursor`） |

## 三、三条写进代码的语义

**历史事实里不出现录取率。** 前者是"去年这个专业录到多少位次"，后者是
"你这个位次今年有多大概率被录"。把前者当后者用，是在用过去回答未来，
而且还答错了对象。

**单位必须显式配置，不猜。** 用"值 ≤1 就当小数"去推，会在真实值是 0.5%
时把结论放大一百倍——而录取率放大一百倍是"稳上"，一个足以改变填报决定的
方向性错误。区间外的值（≥100、<0）直接拒绝，不静默截断：截断后的值看起来
合理，而它已经不代表上游说的任何事。

**缺条件不是 false。** "我不确定你符不符合"和"你不符合"是两个结论，处置相反：
前者去补条件，后者去换志愿。合成一个布尔值会让系统把"不知道"报成"不行"，
学生因此白白放弃一个本来能报的志愿。

## 四、过程中抓到的一个真 bug

别名测试当场抓到：`planning.get_working_plan` 与 `admission.get_current_plan`
路由到同一个后端方法，但 `_envelope` 按 **名字前缀** 判断走哪条包装路径
（`name.startswith("admission.")`）——于是**同一个工具因名字不同给出两种结果
形状**。这正是计划禁止的"保留两个语义"。

改成显式集合 `_ADMISSION_SHAPED_TOOLS`：别名不可能再分叉。

这条值得记一笔：如果我按计划只写"别名映射存在"的断言，它会通过——
映射确实存在。是"两个名字必须给出同一结果"这条断言把它逼出来的。

## 五、验收

```
zhiyuan-agent: pytest tests/ -q
# 2 failed, 1819 passed, 56 skipped
# 两条 failed 与台账基线逐字同名；B2 新增 12 条

zhiyuan-server: mvn -o test
# Tests run: 735, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS
# （本轮 Java 未改动，跑一遍确认没有被 Agent 侧契约变更牵连）
```

## 六、未完成

1. **`admission.get_probability` 没建。** 计划要求接真实 program 接口
   （`/inner/gaotu/program/query-by-limit-num`，分层 `enrollRatio`）。
   归一化器写好了，工具与真实数据源没接。
2. **`normalize_eligibility` 没接进 `admission.check_eligibility`**，
   所以 `checkedConstraints` / `uncheckedConstraints` 目前不会出现在真实结果里。
3. **学校口径的率没有被隔离。** 归一化器**接收**单位率，但没有任何代码阻止
   调用方把学校率传给专业组行——这条约束靠调用方自觉。
4. **`major_group` 口径的历史仍走旧的事实路径**（组级率应当来自 program
   接口，属 get_probability）。这是有意的：拆它需要先有 get_probability，
   否则组级历史会既没有率也没有来源。
5. `admission.get_ordered_plan`（新工具）没建。
6. **契约切换会波及 Skills 与提示词**：`TOOL_OUTPUT_SCHEMA` 换了形状，
   技能里若引用了旧字段名（`evidence`）需要同步——B7 的词表更新时要一并核。

## 七、证据边界

- 12 条测试验的是**归一化器**；生产路径这一轮改了四处（tenant 必填、
  groupCode 口径、别名与包装路径、§3 契约切换），其中契约切换的影响面最大，
  它的证据来自**整仓测试转绿**而不是某一条针对性测试。
- fixture 是手写的事实/概率形状，**不是真实上游响应**：真实 `enrollRatio`
  的实际字符串形态（是否带 `%`、精度）没有实测过。
- 契约切换后**没有跑过真实模型回合**：新的工具产出形状会不会让模型困惑
  （例如它开始把 `kind` 当业务字段引用），只有真实回合能回答。
- 概率区间 0–99 沿用业务 DTO 的口径，没有对真实上游做过端到端确认。
