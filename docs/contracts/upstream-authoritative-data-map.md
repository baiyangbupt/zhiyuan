# 上游权威数据地图：能不能脱离"分数带"取数

> 日期：2026-09-21。依据：上游仓库 `../hl-wish-server` 的实体与控制器源码。
> **没有**对上游发起真实调用——字段与端点是代码事实，"线上真的这么返回"未验证。

## 一、结论先行

现在 zhiyuan 只能回答"用户分数 ±10 分区间内"的院校专业。**这个限制不是数据层的属性，
而是其中一条端点的属性。**

| 数据 | 能不能按身份无线取 | 依据 |
|---|---|---|
| 历年录取分数线 | **能** | `EnrollDataRequest{areaId, batch, majorId, schoolId, subjectType, year}` —— **入参里没有分数** |
| 招生计划 | **能** | `PlanMajorDataRequest{schoolId, areaId, year, subject, batch, schoolUnitId}` |
| 学校/专业身份 | **能** | `z_school` / `z_major` / `z_profession` 等主表按 ID |
| 章程与规则 | **能**（表在，端点待定） | `z_school_admission_rule` 等 |
| **录取概率** | **不能，而且不该** | 上游是 `getByScore(userScore, schoolScore)` —— 概率是"你的分 vs 学校线"的**函数** |

最后一行是这次梳理最重要的一条：**概率不是学校或专业的属性，而是（用户分数、学校分数线）
的函数。** 所以"打破分数带限制能回答所有院校专业"这句话对概率项**不成立**——
任何概率都必须先知道用户分数。"查任意学校的历史/计划"可以，"问任意学校的录取概率"不行。

`±10` 的来源是候选推荐端点（`queryProgramByLimitNum`，按分取冲稳保），
它天然需要分数；把它当成整个数据层的限制是误读。

## 二、身份主数据（先解析身份，再取数）

| 表 | 作用 |
|---|---|
| `z_school` | 学校主表：`schoolBaseId`、`name`、`area`、`city`、`type`、`level`、`tag` |
| `z_school_base` / `z_school_info` / `z_school_introduction` | 学校基础/详情/简介 |
| `z_school_alias` | 别名——**实体解析歧义的落点** |
| `z_major` / `z_profession` / `z_major_category` / `z_profession_category` | 专业与门类 |
| `z_school_major_base` + `_relation` | 学校—专业基础关系 |
| `z_school_unit` / `z_school_unit_base` / `_relation` | **招生单元**（专业组）身份 |
| `z_pre_school_unit*` / `z_pre_school_major_base*` | 同上，**预测口径**一套 |

**稳定取数的第一条原则**：一律用 ID（`schoolId` / `majorId` / `schoolUnitId`），
不用名字。名字只用于解析，解析结果落成 ID 之后再取数——用名字取数会把
"同名专业"这类歧义一路带到结果里。

## 三、录取数据与口径

| 表 | 口径 |
|---|---|
| `z_enroll_major_data` | 录取（专业级）：`maxScore`/`minScore`/`maxPos`/`minPos` |
| `z_enroll_school_data` | 录取（学校级） |
| `z_pre_enroll_major_data` / `z_pre_enroll_school_data` | **模拟**口径 |

关键字段（专业级）：`schoolId`、`schoolUnitId`、`schoolUnitBaseId`、`planSchoolId`、
`planMajorId`、`majorId`、`majorEnrollCode`、`majorTitle`/`majorSubtitle`、`subject`、
`batch`、`dataType`、`dataLevel`、`maxScore`、`minScore`、`maxPos`、`minPos`。

**稳定取数的第二条原则**：口径必须显式传，不能靠"表名里带 pre 就是预测"去猜。
上游的口径枚举是 `PrepareType{PREDICT 模拟填报, VOLUNTEER 志愿填报}`；
计划侧还多一档 `PlanDataType{VOLUNTEER 志愿计划, PREDICT_ONE 模拟计划1, PREDICT_TWO 模拟计划2}`。

取数端点：`POST /querySchoolMajorScoreLine`（`VolunteerFacadeController`），
入参见第一节——**identity-keyed，不含分数**。zhiyuan 现在走的就是它。

## 四、招生计划

见 `admission-sources-v1.md`。要点复述：`z_plan_school_data` + `z_plan_major_data`，
端点 `POST /h5/school/noToken/planMajorDataList`，入参不含分数。

## 五、概率：唯一一项**必须**有分数的数据

```java
VolunteerProbabilityService.getByScore(BigDecimal userScore, BigDecimal schoolScore)
```

存储是 `z_volunteer_probability`：`schoolDiff`、`majorDiff`、`probability`(String)、
`describe`、`isSchool`。

读法：**按分差查表**。`probability` 是字符串（这也是为什么上游 DTO 里
`enrollRatio` 一直是字符串——单位/格式不在数值里）。

三条推论：

1. **zhiyuan 不该自算概率**，也不该用历年最低分冒充——上游已经算好了，
   自算必然与上游口径不一致（B2 已按此实现 `normalize_probability`）。
2. **单位必须显式配置**：字符串形态意味着 `"45"` / `"45%"` / `"0.45"` 都可能，
   靠"值 ≤1 就当小数"去猜会在真值是 0.5% 时放大一百倍。
3. **问"某校某专业的录取概率"时，必须先有用户分数**；没有分数时正确的回答是
   "需要先知道你的分数/位次"，而不是"概率 0"或"无法回答"。

## 六、章程与规则（表在，端点未定位）

`z_school_admission_rule`、`z_volunteer_policy`、`z_response_policy`、
`z_data_policy`、`z_select_subject_policy`、`z_pre_batch_policy`。

**只做了表级定位，没有核到字段与查询路径**——B3 的章程一项仍未被解决。

## 七、位次与省控线

`z_score_position`（位次换算）、`pr_province_score_line`（省控线）、
`z_abnormal_score` / `pr_abnormal_school_score_info`（异常分数）。
位次是"用分数换算"的，所以它同样**依赖分数**，但换算是一次性的、与院校无关。

## 八、稳定取数的三条原则（汇总）

1. **用 ID，不用名字**：解析一次，之后全程 ID。
2. **口径显式**：`PREDICT`/`VOLUNTEER` 从调用方传入，不由表名或年份推断。
3. **年份口径透传上游**：`PlanDisplayYearUtil` 才是权威（预测年=数据年−1，
   正式年=数据年；已发布省批次命中 Apollo 配置时预测也用数据年）。
   zhiyuan 自己算一遍必然与上游不一致。

## 九、未核实（不得当作已知）

1. `RemoteData<String,String>`（`area`/`batch`/`dataType` 的包装）线上序列化形状；
2. H5 端点经网关对外时的完整前缀；
3. `dataLevel` / `dataType` 的取值域（代码里是 String，没有枚举约束）；
4. 上游计划/录取表有没有 `publishedAt` / `sourceUrl` 这类发布元数据；
5. 章程五张表的字段与取数路径；
6. 所有这些表**没有查过真实 DDL**（索引、软删策略、数据量级）；
7. 上游端点是否需要网关层鉴权（H5 标注免 token，但网关可能另有要求）。
