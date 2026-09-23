# 招生数据的身份层级与筛选：准确数据如何定义

> 日期：2026-09-21。依据两类证据，**分开标注**：
> - **源码事实**：上游仓库 `/root/dev/hl-wish-server`（`xiaowo-ci` / `xiaowo-cms`）与页面端仓库（`school-major-library` / `zy-pc-react` / `hl-ambition-h5` / `zy-m-web`）的控制器、mapper、实体。
> - **真机实测**：对 `https://www.gaotuzhiyuan.com/hl-wish/ci/...` 的真实调用（浙江/山东/江苏/河北四省，2024–2026）。
>
> 凡只有源码、没有真机样本的，标「源码未体现/未验证」。

## 一、一句话

**录取数据按「招生单元」组织，专业是行的属性而不是筛选层；页面端筛选级联止于招生单元。**
`schoolUnitId` 就是"专业组"，而"专业类"只在志愿填报页的「筛选专业」里作为一层出现。

## 二、五个身份，各自的取值口径

| 层 | 字段 | 上游表 | 取值形态（实测） |
|---|---|---|---|
| 省 | `areaId` | — | 六位码：浙江 330000、江苏 320000 |
| 年 | `year` | `z_*.year` | 招生计划年（**不是**录取年），字符串 |
| 科类 | `subject` | `z_*.subject` | 枚举 `SubjectType{N:综合, WL:物理, LS:历史, W:文科, L:理科}` |
| 批次 | `batch` | `z_batch_data.batch` + 字典 `BATCH` | **地区相关**：浙江 17/18、江苏/河北 01 |
| **招生单元 / 专业组** | `schoolUnitId` | `z_school_unit.id` | 浙江=学校级；江苏=`310107`＝"北京大学07专业组"；山东=A001 |
| 专业 | `majorId` | `z_major.id` | 标准专业 id；**`0` 是"大类招生"哨兵** |
| 门类 / 大类 | `category_id` / `sub_category_id` | `z_major_category.id`（自关联 `parent_id`） | 行的属性，不是筛选层 |

源码依据：`SubjectType.java:31-53`、`SchoolFilterResponse.java:30-37`、`ZSchoolUnit.java:59-107`、
`Major.java:83-98`、`MajorCategoryMapper.xml:38-43`。

### 「专业组」= `schoolUnitId`，不是另一张表

- 页面上这一层叫**「招生方向」**（`SchoolFilterResponse.java:30-37` 的 `@ApiModelProperty`、页面弹窗标题 `title="招生方向"`）。
- 「以专业组为维度」= `ZytbTypeEnum.OTON` / `OTONWL`（1 院校 + 多专业），由**每省配置**的 `z_response_policy.type` 决定，**不是**由高考模式枚举（`AreaPolicyEnum` 在 ci/cms 里零引用）。
- 组代码载体是 `z_school_unit.school_code`，格式 `院校代码-组代码`（页面 `schoolUnitCode.split('-')` 拆开展示）；
  **服务端未找到生成该格式的代码**——来自导入源数据，未验证。

## 三、页面端实际怎么筛（两条链，都不含"专业类"层）

### 3.1 院校库 / 专业库（分数线、招生计划 tab）：**五层级联**

```
省 → 年 → 科类 → 批次 → 招生方向(=schoolUnitId，叶子)
```

- 前端：`school-major-library/.../scoreLine/components/selectGroup/index.tsx:177-195`，
  提交参数只到 `schoolUnitId`（`:52-57`、`:137-142`），类型 `IFormValue{year,subject,batch,schoolUnitId}`。
- 端点：`GET /h5/school/noToken/{schoolScoreFilterList|majorScoreFilterList|planMajorFilterList}?schoolId&areaId`
  （`SchoolH5Controller.java:148/167/184`）→ 返回 4 层树。
- 树怎么造的：`BusinessUtil.java:70-80` 三层 `groupingBy`（年 → 科类 → 批次）+ 叶子 `schoolUnitId`
  （`:62-64`）；SQL `GROUP BY a.year, a.subject, a.batch, a.school_unit_id`
  （`PlanMajorDataMapper.xml:88-109`、`EnrollMajorDataMapper.xml:81-102`、`EnrollSchoolDataMapper.xml:75-96`）。
- 返回 DTO **没有专业/门类字段**：`SchoolFilterResponse{year, subject, batch, batchTitle, schoolUnitId, schoolCode, schoolUnitTitle}`。

**实测四个省的树（真机）**：

```
浙江 N  → 17 第一段 → 1 个单元：北京大学("双一流"…)(北京)[1103]
山东 N  → 17 第一段 → 2 个单元：北京大学(A001)[A001] / 北京大学(A001)(高校专项计划)
江苏 WL → 01 本科批 → 北京大学07专业组[310107]      LS → 04专业组[310104]
河北 物理 → 本科批 01 → 北京大学(公办)[0080]
```

### 3.2 志愿填报页：省（会员资料）→ 科类 → 批次，然后是多维筛选

- 端点：`GET /h5/batchData/anno/batchListByPolicyV2?areaId&subject&score&onlyCurrentBatch`（`BatchDataH5Controller.java:62-74`）。
- **「专业类」这一层只在这里出现**：`POST /h5/major/noToken/tree` 返回 **门类 → 大类 → 专业** 三层树
  （`MajorH5Controller.java:71-76`、`MajorCategoryMapper.xml:38-43`），提交形态是 `{subId(大类), majorIdList(专业)}`
  （`MajorFilterDTO.java:18-31`、页面 `majorFilter/index.tsx:79,89-92`）。
- 落到 SQL 时 **`major_id = 0` 是"大类招生"哨兵**：
  `prepareMajor.major_id IN (…) OR prepareMajor.sub_category_id = #{subId} AND prepareMajor.major_id = 0`
  （`PrepareMapper.xml:207-224`）。判定函数见 `PreRelationMajorServiceImpl.java:603-612`。

## 四、录取数据（分数线）：三种查询模式（真机实测）

`POST /ci_feign/volunteer/querySchoolMajorScoreLine`，入参
`EnrollDataRequest{areaId, batch, schoolId, subjectType, year, majorId?}`（`VolunteerFacadeController.java:162`）。
分发逻辑：**`majorId` 有值走专业级表、无值走院校级表**（`EnrollDataServiceImpl.java:42-66`）。

江苏 · 北大 · 物理 · 本科批 2025：

| `majorId` | 返回 | 层 | 分数 |
|---|---|---|---|
| **不传** | 1 行，`name = "北京大学05专业组"` | **院校/单元级**（`z_enroll_school_data`） | **minScore 686 / minPos 126** ✓ |
| **`"0"`** | **81 行**（工科试验班类/物理学类/地质学类…） | 专业级 · **大类招生行** | 全 0 |
| **`"473"`** | 5 行，天文学 **2025/2023/2021**（跨年序列） | 专业级 · 具体专业 | 全 0 |

三条结论：

1. **"某专业组多少分"可查**——走"不传 `majorId`"，行的 `name` 就是招生单元名。
2. **专业级行存在，但分数列在该省恒为 0**：上游对该省只公布到专业组/单元投档线。
   所以"专业级录取分查不到"**不是我们没接，是数据口径如此**。
3. **专业级查询会回多年序列**（请求 2025 返回 2023/2021），做对比时口径要显式钉死年份。

专业级行的字段比院校级多两个身份回显：`schoolName` 与 `majorId`；两边都有 `selectInfo`（选考要求）。

## 五、`majorId = 0` 才是我们看到的"缺失"的真身

北大在**浙江**2026 第一段的计划行：`majorId="0"` —— 不是缺数据，是**按大类招生**（该省单元是学校级，
专业以试验班形态出现）。同校在**江苏**07 专业组里，17 条计划中 16 条 `majorId="0"`、
只有 `37 天文学 majorId="473"` 是具体专业。这与 `z_plan_major_data.major_id = 0` 的哨兵语义一致。

## 六、我们这边对不上的地方（源码 + 实测）

| # | 现状 | 影响 |
|---|---|---|
| 1 | **`admission.check_eligibility` 曾经恒"通过"**：agent 把 `majorId` 塞进 `majors["level2"]`，而 Java `PlanValidationService` 只读 `level3` → 空循环 → `return true` | **fail-open**：对任何专业都说"选科要求都满足"。已修（落到 level3 + 缺参拒绝） |
| 2 | **布尔结论说不出"不合格"**：`_admission_envelope` 把 `bool` 判成"后端没返回结构化数据" → 模型只收到 `insufficient_data` | 合格/不合格都读不到。已修（包成 `{"eligible": bool}`） |
| 3 | `CatalogService.java:283` 硬编码 `schoolUnitCode = null`，`school_info.csv` 也没有省院校代码列 | 目录回答不了"某校在我省的院校代码/专业组"。**已由新工具 `catalog.list_admission_units` 补上**（它给 `schoolUnitCode`） |
| 4 | 目录 id 来自**本地夹具**（`bizdata/*.json|csv|xlsx`），与上游同源但**无任何校验**（抓包交叉验证：majorId 490/493 命中、subCategoryId 有越界值与跨级值 `172`） | 夹具漂移会静默出错 |
| 5 | `volunteerModel` 靠**排除法**判定（只有 `OTOO`/`OTOOWL` 是 major，其余落 majorGroup），`OTOWL` 是死常量 | 新增策略码会静默变 majorGroup |
| 6 | agent 的 fact 契约要求 `major_group` 时必须有 `group_code`，而 Java 侧 `groupCode` **从未被赋值** | 悬空字段 |
| 7 | 候选池筛选是**文本 contains**，不是 id 等值；"专业类"被塞进 `majorKeywords`；`isMajorFiltered` 等 id 过滤是**死代码** | "按专业类筛"实际按名字匹配 |
| 8 | `PlanMajorDataRes` **不回显** `schoolUnitId`/`categoryId`/`subCategoryId` | 无法自证某行计划属于哪个单元（调用方自己知道入参，但响应不可自证） |
| 9 | 计划端点 `subject` 用**中文**会**静默返回空**（实测江苏传"物理" 0 行、传 `WL` 17 行）；批次名同理 | 与批次码同一类坑：上游不报错，只返回空 |

## 七、仍未查清（需真机或 DB）

1. 录取表的**物理分表**（`z_data_policy.split_table` 无消费代码，但 docs 里出现 `z_enroll_school_data_620000`）。
2. `school_code` 的 `院校代码-组代码` 格式由谁生成（服务端无拼接代码）。
3. 3+3 省份在 `z_response_policy` 里实际配成哪个 `ZytbType`（源码无专门分支）。
4. `EnrollMajorDataMapper.xml:70` 的 `AND a.subject = #{subject}`（传枚举对象）与其它 mapper 的
   `#{subject.code}` 是否等价（依赖 TypeHandler 注册）——**实测江苏按 `WL` 查得到，说明这条通**，但等价性未证。
