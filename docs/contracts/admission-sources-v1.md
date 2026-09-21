# 年度招生计划与招生章程：来源调查

> 日期：2026-09-21。**v2：上一版的结论是错的，已更正。**
> 依据：上游仓库 `../hl-wish-server`（`xiaowo-ci` / `xiaowo-report` / `xiaowo-cms`）的实体与控制器代码。

## 〇、上一版错在哪

v1 只查了**本仓**（zhiyuan-server）的上游客户端清单，看到没有 plan/policy 接口，
就下了"没有来源、走受控导入"的结论。

**错在这里**：本仓没接 ≠ 上游没有。上游仓库里两张计划表、一批章程表都在，
而且有现成的免 token 查询端点。教训与 P1a 那次同型——**只看消费侧，
看不到生产侧有什么**。

## 一、招生计划：存储

两张表（MyBatis-Plus 实体，`xiaowo-ci-entity`）：

| 表 | 实体 | 粒度 |
|---|---|---|
| `z_plan_school_data` | `PlanSchoolData` | 学校/招生单元级 |
| `z_plan_major_data` | `PlanMajorData` | 专业级 |

`z_plan_major_data` 的关键字段（注释见源码）：

| 字段 | 含义 | 对应 B3 合同 |
|---|---|---|
| `year` | 招生年度 | `admissionYear` |
| `area` | 投放省份（`RemoteData<String,String>`） | `areaId` |
| `batch` | 批次（`RemoteData`） | `batch` |
| `schoolId` / `schoolUnitId` / `schoolUnitBaseId` | 学校与招生单元身份 | `schoolId` / 组身份 |
| `majorId` / `majorPlanCode` | 专业与**计划代码** | `majorId` / 组内专业身份 |
| `planNum` | 名额 | `planCount` |
| `planDuration` | 学制 | `durationYears` |
| `planMoney` | 学费 | `tuitionPerYear` |
| `subjectPolicy` / `selectLevelOne` / `selectLevelTwo` / `selectInfo` | 选科条件 | `subjectRequirements` |
| `subject` | 科类 | — |
| `type` / `dataType` / `dataGrade` | 数据种类/年级 | — |
| `isDeleted` | 软删 | — |

**B3 合同里的字段这里几乎都有**，缺的是 `publishedAt` / `sourceUrl` 这类
**发布元数据**——上游表里有没有，下面第五节写清。

## 二、招生计划：怎么取

已有业务端点，全部免 token：

| 端点 | 用途 |
|---|---|
| `POST /h5/school/noToken/planMajorDataList` | **招生计划数据列表**（主路径） |
| `GET /h5/school/noToken/planMajorFilterList` | 招生计划筛选条件（年份/地区/批次） |
| `POST /school/planMajorDataList` | 同一实现的带 `@Sign` 版本 |

请求体 `PlanMajorDataRequest`：

```json
{"schoolId": "...", "areaId": "...", "year": "...", "subject": "...", "batch": "...", "schoolUnitId": "..."}
```

响应 `List<PlanMajorDataResponse>`：

```json
[{"key": 1, "majorPlanCode": "...", "majorSubtitle": "...", "batch": {...},
  "selectInfo": "...", "planNum": 20, "planDuration": "4", "planMoney": "6000",
  "majorId": "..."}]
```

对应服务方法 `PlanMajorDataService.findPlanMajorDataList(request)`；同模块还有
`listByYearListAndAreaIdAndType(...)`（供内部算法用）与
`PlanSchoolDataService`（学校级）。

**接入方式**：与现有 `querySchoolMajorScoreLine` 同一形状——zhiyuan-server 在
`GaotuClient` 上新增一个方法，走上面的 H5 端点，`year` 取上游的展示年口径。

## 三、年份口径（比"取最大年份"复杂）

上游 `PlanDisplayYearUtil` 才是权威规则：

- **`PREDICT`（预测填报）**：展示年 = 数据年 − 1；
- **`VOLUNTEER`（正式填报）**：展示年 = 数据年本身；
- 例外：当 `areaId + batch` 命中 Apollo 配置
  `hl.ci.volunteer.program.plan.publish.areaId.batch.config`（即该省批次**已发布**
  招生计划）时，`PREDICT` 也用数据年本身。

所以"最近已发布年份"不是"表里最大的 year"，而是**由配置声明的发布状态**决定的。
zhiyuan 侧自己算一遍必然与上游不一致——应当把口径透传给上游，或直接复用上游逻辑。

## 四、招生章程：存储与取数

### 4.1 只有一张表是章程（先前的归类是错的）

v1 把五张 `*_policy` 表当成一类，实际它们**用途完全不同**：

| 表 | 实际是什么 |
|---|---|
| **`z_school_admission_rule`** | **招生章程**：`schoolId`、`schoolName`、`admissionRule`(全文)、`year` |
| `z_volunteer_policy` | 志愿**算法策略**（`baseYear`、`weight`、`n0Add/n0Sub…n4Add`）——冲稳保的权重参数 |
| `z_response_policy` | **展示策略**（`detailShow`、`areaIds`、`dataLevel`、`tenant`） |
| `z_data_policy` | **数据表管理**（`tableName`、`splitTable`、`expUploadTime`） |
| `z_select_subject_policy` | **选科政策**（`subjectIds`、`firstNum/secondNum/maxNum`、`areaIds`、`year`） |

后四张是配置，不是可引用的章程条文。`z_select_subject_policy` 与资格判断相关，
但它给的是"选科数量要求"这类**规则参数**，不是"原文条款"。

### 4.2 取数端点

```
GET /school/noToken/getSchoolRule?schoolId=<Long>
→ R<SchoolRuleResponse>{ title, content }
```

上游实现 `SchoolServiceImpl.getSchoolRule(schoolId)`：

```java
SchoolAdmissionRule rule = admissionRuleMapper.selectBySchoolId(schoolId);
if (rule == null) { year = admissionRuleMapper.selectYear(); content = defaultSchoolRuleContent; }
else { year = rule.getYear(); content = rule.getAdmissionRule(); }
title = year + schoolRuleTitle;
```

### 4.3 接这条端点必须处理的两件事（否则会引用错东西）

1. **默认文案不是该校章程。** 该校没有规则时回的是 `defaultSchoolRuleContent`
   （一段通用文案），而**响应里没有标志位**区分这两种情况。
   直接把 content 当"该校章程原文"引用是错的——B3 要求"以原文条款为依据"，
   通用文案没有原文可依据。
   **接法**：zhiyuan 侧调用前先用别的方式确认该校确有规则，或把
   `content == defaultSchoolRuleContent` 判为"无章程"。两种都要与上游对齐口径。
2. **年份是"全局规则年"而非该校的年份。** 缺失时 `selectYear()` 取的是通用年份，
   不代表该校该年有章程。所以 title 里的年份**不能**当作"这是哪一年的章程"。

`z_school_admission_rule` 表里确实有 `year` 列，但端点没有把它与
"是否命中该校"分开返回——这是这条链路目前的形状限制。

## 五、还没核实的（不得当作已知）

1. **`publishedAt` / `sourceUrl` 从哪来**：上游计划表里有没有发布日与官方出处？
   没有的话，"这是哪一年哪份文件"就答不出来——而那是学生要核对的东西。
2. **`RemoteData<String,String>` 的实际序列化形状**：`area`/`batch`/`dataType`
   都是这个包装类型，线上返回的是什么（id+name？还是嵌套对象？）没有样本。
3. **网关前缀**：本仓现有上游路径都是 `/hl-wish/ci/...`，而 H5 端点在
   `xiaowo-ci` 的 `/h5/school/...` 下。两者经同一个网关对外时的完整前缀
   需要一次真实调用确认。
4. **章程端点的默认文案与年份语义**：`defaultSchoolRuleContent` 的实际内容、
   `selectYear()` 的取值来源，都没有核；这直接决定"这条 content 能不能当原文引用"。
5. **上游是否有 `@Sign` 之外的其他门槛**（H5 端点标注免 token，但网关层可能另有要求）。

## 六、对本仓 B3 的影响

- 年度招生计划从 `blocked_data_source` 改为**可接**：走
  `POST /h5/school/noToken/planMajorDataList`，在 `GaotuClient` 加一个方法即可，
  与现有取数同一形状。
- **不要**在 zhiyuan 侧重算展示年：口径在上游 `PlanDisplayYearUtil`，
  自己算一遍会与上游不一致（这正是"两处实现同一个规则"的典型代价）。
- 受控导入模式（`scripts/import_admission_catalog.py`）降级为**兜底**：
  适用于上游确实没有、或需要离线快照的场景，不再是主路径。
- 章程已定位到表与端点（`GET /school/noToken/getSchoolRule`），但**默认文案与
  年份语义未核**，接之前必须先解决 4.3。

## 七、证据边界

- 以上全部来自**上游源码**，没有对上游发起任何真实调用：字段名与端点是
  代码事实，"线上真的这么返回"未验证。
- 表结构来自实体注解，**没有**查过真实 DDL（索引、字符集、软删策略）。
