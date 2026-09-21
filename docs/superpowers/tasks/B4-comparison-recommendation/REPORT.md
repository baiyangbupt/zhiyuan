---
task: B4
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 09:20 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B4 报告（部分）：同口径比较与个性化推荐

## 一、结论

**比较的口径合同做完了，推荐侧没做**：`CandidateComparisonService`（Java，7 条测试）
+ `tools_recommendation.py`（Python 守约检查，10 条测试）。

候选预览（把取数从会写工作区的 `/candidate-pool/generate` 里抽出来）、
Rank 接线、MCP 工具与 inner 端点都没做。所以"推荐"这一半还是空的。

## 二、交付

| 路径 | 变更 |
|---|---|
| `model/dto/planning/ComparisonEntityDTO.java` | 新增：实体 + **口径身份** |
| `model/dto/planning/ComparisonCellDTO.java` | 新增：单元格 + 来源 + 不可用原因 |
| `model/dto/planning/CandidateComparisonDTO.java` | 新增：实体/维度/矩阵/整列不可比 |
| `service/biz/CandidateComparisonService.java` | 新增，7 条测试 |
| `test/.../CandidateComparisonServiceTest.java` | 新增 |
| `app/mcp_server/tools_recommendation.py` | 新增：`comparable` + `comparison_problems` |
| `tests/integration/test_recommendation_contract.py` | 新增，10 条 |

## 三、这一层的核心不是算术，是**可比性判定**

比较最容易出的错不是"算错了"，而是**把不可比的数放在一起比**：

- 2024 年的位次减 2026 年的位次；
- 学校口径的率减专业组的率；
- 缺失值补零之后"看起来更低"。

三种都会得出一个**方向相反**的建议。所以实现里三条约束：

1. **口径不一致时整列不可比**，而不是逐格标一下——一张表里有一列能比一列不能比，
   读者会以为整张表都能比。
2. **缺失保持 `null` 并注明原因**（`tuition_missing` 等），不补零。
3. **缺失口径算不可比**："不知道口径是否相同"不等于"相同"。

另外**每格自带来源**（`entity.admissionRatio` 等）：没有来源的格子无法被核对，
而核对不了的数字和没有数字一样没用。

## 四、两个必须分开的字段

`CandidateItemDTO` 里有两组容易被合并的字段，这里在维度上就分开了：

| 字段 | 是什么 | 不是什么 |
|---|---|---|
| `schoolEnrollRatio` | **学校口径**的录取率 | 该专业组的录取率 |
| `admissionRatio` | 该招生单元口径的率 | 学校率 |
| `finalScore` | Rank 算出的**匹配分** | 录取概率 |

匹配分与概率合成一个字段，会让"这所学校适合我"被读成"我大概率能上"——
两个完全不同的问题。测试里断言了它们单位不同（`score` vs `percent`）、来源不同。

## 五、Python 侧只做守约检查，不重算矩阵

矩阵由 Java 算。在 Python 再实现一遍就是"同一个规则两处实现"，两边迟早分叉，
而分叉的表现恰好是"把不可比的数放在一起比"——**错了也看不出来**。
所以 Python 只检查底线：不可比的口径下**有没有出现数字**、每格**有没有来源**、
缺失**有没有原因**。

## 六、与计划的一处不符（需要设计侧确认）

计划要求"复用旧候选生成取数及 **RankRequestMapping**"。**本仓没有
`RankRequestMapping` 这个类**（`grep` 全仓无匹配）。现有的 Rank 接入口是
`manager/rank/VolunteerRankClient`（`getRecommendSubMajor` / `getRecommendVolunteer` /
`queryWeight`）。

按台账的规矩，我没有照计划的名字造一个类，而是先如实记录这处不符。
B4 的推荐侧要接的应当就是 `VolunteerRankClient`。

## 七、未完成

1. **`CandidatePreviewService` 没建**：计划的要点是"复用取数但**不能**调用会保存
   工作区的 `/candidate-pool/generate`"，并把候选计算抽到独立类、结果存 B0 Artifact。
   这需要读懂 11762 行的 `PlanningStateService` 里那条路径——本任务没做。
2. **MCP 工具 `recommendation.compare` / `recommendation.generate_candidates` 没接**，
   inner 端点（`/inner/planning/{tenant}/session/comparison`、`candidate-preview`）也没建。
   所以 `tools_recommendation.py` 目前是一个**没有调用方**的守约检查器。
3. **硬约束过滤 → 软偏好排序 → Rank → 概率独立列**这个顺序没有落成代码：
   它主要在那条候选生成路径里，属第 1 项。
4. **产物绑定画像/候选版本、Top20/分页 50** 没做（属第 1 项）。
5. 计划里"固定画像'学费≤10000、排除某专业、保留锁定项'"那组测试没写——
   它测的是候选生成，而候选生成还没抽出来。

## 八、验收

```
zhiyuan-server: mvn -o test
# Tests run: 751, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS

zhiyuan-agent: pytest tests/ -q
# 2 failed, 1839 passed, 56 skipped
# 两条 failed 与台账基线逐字同名
```

## 九、证据边界

- 比较矩阵的测试全部是**构造数据**，没有接真实候选或真实 Rank 输出。
- `comparison_problems` 只验"合同有没有被违反"，不验数值对不对——那是 Java 的事。
- 没有端到端：Python 侧的函数目前没有生产调用方。
