---
task: B3
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 08:40 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B3 报告（部分）：年度招生计划与章程来源接入

## 一、结论

**B3 的前提被推翻了。** 计划假设"年度计划与章程没有现成来源，要建受控导入"；
实际是上游仓库里两张计划表、一批章程表都在，而且有现成的免 token 查询端点。

已按真实情况改接：`GaotuClient.queryPlanMajorData` / `getSchoolRule` +
`AdmissionSourceService`，9 条测试。受控导入降级为兜底。

章程也已定位到**表与端点**（`z_school_admission_rule` + `GET /school/noToken/getSchoolRule`），
并接进 `AdmissionSourceService.getPolicy`，但**这条端点不能当原文条款用**（见第七节）。

## 二、推翻的过程（值得记）

| 步骤 | 结论 |
|---|---|
| 只查本仓上游客户端清单 | "没有 plan/policy 接口" → `blocked_data_source` |
| 用户指出 `../hl-wish-server` | 上游有 `z_plan_school_data` / `z_plan_major_data`，字段几乎正好覆盖 B3 合同 |
| 继续查控制器 | `POST /h5/school/noToken/planMajorDataList` 就是招生计划查询，免 token |

**教训与 P1a 同型**：只看消费侧，看不到生产侧有什么。"本仓没接"被当成了
"上游没有"——而这两件事的处置完全相反（前者写接入，后者建导入）。

## 三、交付

| 路径 | 变更 |
|---|---|
| `docs/contracts/admission-sources-v1.md` | **重写为 v2**，更正结论 |
| `docs/contracts/upstream-authoritative-data-map.md` | 新增：上游数据地图与稳定取数原则 |
| `scripts/import_admission_catalog.py` | 新增（降级为兜底） |
| `model/dto/gaotu/req/QueryPlanMajorDataReq.java`、`res/PlanMajorDataRes.java` | 新增 |
| `manager/gaotu/GaotuClient.java` | 新增 `queryPlanMajorData(req, scope)` |
| `EvidenceLedgerService` | 新增签发来源 `SOURCE_GAOTU_PLAN_MAJOR_DATA` |
| `service/biz/AdmissionSourceService.java` | 重写：走上游端点；新增 `getPolicy` |
| `model/dto/gaotu/res/SchoolRuleRes.java` | 新增（章程展示文案） |
| `manager/gaotu/GaotuClient.java` | 新增 `getSchoolRule(schoolId)` |
| `test/.../AdmissionSourceServiceTest.java` | 新增，9 条 |
| `zhiyuan-agent/tests/unit/test_import_admission_catalog.py` | 新增，10 条 |

## 四、这次梳理最重要的结论

**±10 分不是数据层的属性，是一条端点的属性。**

分数线接口的入参是 `EnrollDataRequest{areaId, batch, majorId, schoolId, subjectType, year}`
——**不含分数**；计划接口同样不含。分数带只属于候选推荐那条
（`queryProgramByLimitNum`，按分取冲稳保）。

**而概率是唯一"本质依赖分数"的一项**：上游实现是
`VolunteerProbabilityService.getByScore(userScore, schoolScore)`——概率是
"你的分 vs 学校线"的**函数**，不是学校或专业的属性。所以"打破分数带就能回答
所有院校专业"这句话**对概率项不成立**。

## 五、稳定取数的三条原则

1. **用 ID 不用名字**：名字只用于解析，解析成 ID 之后再取数。
2. **口径显式**：`PrepareType{PREDICT 模拟填报, VOLUNTEER 志愿填报}`；
   计划侧多一档 `PlanDataType{VOLUNTEER, PREDICT_ONE, PREDICT_TWO}`。
3. **年份口径透传上游**：`PlanDisplayYearUtil`（预测=数据年−1、正式=数据年；
   已发布省批次命中 Apollo 配置时预测也用数据年）。本仓**不重算**。

## 六、验收

```
zhiyuan-server: mvn -o test
# Tests run: 744, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS

zhiyuan-agent: pytest tests/unit/test_import_admission_catalog.py -q
# 10 passed
```

## 七、未完成

1. **章程不能当原文条款用。** 端点找到了（`GET /school/noToken/getSchoolRule`），
   但它有两个形状限制：**(a)** 该校没有规则时回配置的**占位文案**
   （默认 `正在更新中`），而响应**没有标志位**区分；**(b)** 年份缺失时取的是
   全局 `selectYear()`，不代表该校该年有章程。
   已按事实接：`getPolicy` 无条件带上
   `policy_source_is_display_text_not_verbatim` 与 `policy_placeholder_content_possible`
   两条 limitations，且**不签发证据**（它不是取数结果，给它签证据等于把
   "查过数仓"的权威性借给一段可能只是"正在更新中"的文本）。
   **要让 `admission.get_policy` 按"原文条款"发布，需要上游补一个带
   "是否命中该校"标志的端点**，或者本仓另找原文来源。
2. **`z_select_subject_policy` 没接**：它是**选科政策**
   （`subjectIds`、`firstNum/secondNum/maxNum`），与 `admission.check_eligibility`
   相关，但给的是**规则参数**而非条款原文，接法要与资格判定的合同一起定。
3. **真实上游调用**：`/hl-wish/ci/h5/school/noToken/planMajorDataList` 这个前缀是
   从"现有路径都是 `/hl-wish/ci/` + 上游路径"推出来的，**没有真实样本**。
   第一次联调时先确认前缀，别把 404 当成"上游没这功能"。
4. **zhiyuan 侧的 inner 端点**（`/inner/admission/{tenant}/enrollment-plan`）没建，
   所以 MCP 工具 `admission.get_enrollment_plan` 也还没接。
5. **`RemoteData<String,String>` 的线上形状未验证**：`batch` 在响应 DTO 里是
   `Object`，等真实样本回来再定类型——强类型等于替上游声明一个没验证过的形状。
6. **`planMajorFilterList`（筛选条件）没接**：`latestPublishedYear` 的入参目前
   只能由调用方给，还没有从上游取年份的那一步。

## 八、证据边界

- 全部来自**上游源码**，零真实调用：字段名与端点是代码事实，"线上真的这么返回"未验证。
- 表结构来自实体注解，**没有查过真实 DDL**（索引、字符集、软删策略、数据量级）。
- 章程已核到表与端点；但**占位文案的实际取值、`selectYear()` 的来源**没核，
  这两者直接决定"这条 content 能不能当原文引用"。
- 上游计划表有没有 `publishedAt` / `sourceUrl` 这类发布元数据**没有核**——
  没有的话，"这是哪一年哪份文件"就答不出来。
