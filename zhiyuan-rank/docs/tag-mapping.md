# Rank 标签映射约定

## 1. 目标

本文档约束 `gaokao-volunteer-rank-service` 中“打分原始标签”和外部系统统一标签体系之间的边界。

rank 服务当前仍保留历史实现标签：

- `tag_info / negative_tag_info`
- `city_info / negative_city_info`
- `major_intent / negative_major_intent`
- `school_intent / negative_school_intent`
- `tag_major.json / tag_major_02.json`

这些字段仍可继续作为 rank 内部打分输入存在，但不应再被视为 frontend / backend / agent 的统一语义。

统一标签体系由 backend 负责对外收口。

补充约束：

- rank 不作为院校/专业主数据源
- `schoolId / majorId / categoryId / subCategoryId` 的主语义定义，以 backend 文档 [entity-catalog-governance.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/entity-catalog-governance.md) 为准
- `schoolUnitCode / majorUnitCode` 只允许作为展示或导出 code，不得替代主键

## 2. 当前 rank 的原始标签来源

### 2.1 院校侧

`services/recommendation.py` 当前会从院校画像和院校字典中读取：

- 省份 / 城市
- `category`
- `nature`
- `tag`
- `postgraduate`

并将这类信息参与院校分数修正。

这些字段本质上仍是“院校原始属性”或“院校原始标签”，并不是统一标签域。

### 2.2 专业侧

`services/recommendation.py` 当前会从：

- `majorId`
- `subCategoryId`
- `tag_major.json`
- `tag_major_02.json`

中判断某专业或专业大类是否命中某个历史标签，再参与专业分数修正。

这里的 `subCategoryId` 本质上对应“专业大类（level2）”。

## 3. 与统一标签体系的关系

标准标签域如下：

- `region.school_province`
- `region.school_city`
- `school.category`
- `school.nature`
- `school.feature`
- `school.level`
- `major.discipline`
- `major.category`
- `admission.type`
- `constraint.limit`

rank 不直接产出这些标准标签对象。

rank 当前职责是：

- 读取画像与原始标签
- 基于原始标签做推荐分修正
- 返回可供 backend 继续加工的学校 / 专业 / 分数结果

backend 当前职责是：

- 把 rank 原始学校属性映射到 `school.*`
- 把 rank 的 `categoryId / subCategoryId` 和专业扩展数据映射到 `major.discipline / major.category`
- 把 rank 暴露出来的历史招生类型、限报信息映射到 `admission.type / constraint.limit`
- 向 frontend / agent 输出统一筛选枚举与统一查询字段

专业层级统一映射表：

| 语义层级 | 中文含义 | rank 字段 | 统一标签域 | 对外筛选兼容字段 |
| --- | --- | --- | --- | --- |
| level1 | 专业门类 | `categoryId` | `major.discipline` | `majorTags` |
| level2 | 专业大类 | `subCategoryId` | `major.category` | `majorKeywords` |
| level3 | 具体专业 | `majorId` | 暂无独立标准标签域 | 暂无；仅允许兼容兜底 |

## 4. 映射原则

### 4.1 地域

- rank 内部 `province_code / city_code / school 所在地`
  - 对应统一标签 `region.school_province / region.school_city`
- 不允许把地域语义继续混入 `school.tag`

### 4.2 院校

- `category`
  - 对应 `school.category`
- `nature`
  - 对应 `school.nature`
- `tag`、`postgraduate` 等院校特征字段
  - 由 backend 进一步拆分到 `school.feature / school.level`

### 4.3 专业

- `majorId`
  - 对应具体专业
- `categoryId`
  - 对应 `major.discipline`
- `subCategoryId`
  - 对应 `major.category`
- 若需一级门类
  - 应通过 backend 的专业补充数据再映射到 `major.discipline`

### 4.4 历史 tag 字典

- `tag_major.json / tag_major_02.json`
  - 仍可作为 rank 的内部打分 tag 字典使用
  - 不应直接作为前端筛选枚举暴露
  - 其中能稳定映射到统一标签的部分，应由 backend 二次归并后再对外输出

## 5. 对接约束

后续若 rank 新增标签能力，必须满足：

1. 先定义它是“内部打分标签”还是“统一标签候选源”。
2. 若只是内部打分标签，不得直接透传给 frontend / agent。
3. 若希望变成统一标签，必须先在 backend 补上映射规则与枚举治理。
4. `major.category` 相关语义优先使用 `subCategoryId` 及其映射，不再新增新的自由命名。
5. `schoolKeywords` 不属于 rank 标签体系，始终只表示具体院校名，由 backend / frontend 侧单独维护。
6. `majorId = 0` 仅表示当前样本没有三级专业粒度，属于历史兼容值，后续不得继续扩散为新的运行时标准语义。

## 6. 后续统一接入方式

当前 rank 先不直接改成跨模块读取 backend 文件。

推荐后续接入顺序：

1. backend 固定统一主键语义与标签映射规则
2. catalog build 产出 rank 专用字典生成物
3. rank 继续从本仓库本地 `dict/` 目录加载，但这些文件来源改为统一生成链路
4. 对 `majorId=0 / subCategoryId 非法值 / schoolId 缺失` 增加启动校验和 CI 回归

这样 rank 仍保留现有启动和运行方式，但不会继续把自己的静态字典当成独立主数据源。
