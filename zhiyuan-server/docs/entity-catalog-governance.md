# 院校专业主数据与编码治理

## 1. 目标

本文档统一 `assistant-backend / agent / rank / frontend` 四侧对“院校、专业、地域”主数据与编码字段的使用边界，避免再次出现：

- 多套静态字典并行维护
- 同一语义在不同服务用不同字段
- `name / id / code` 混用
- `majorId = 0` 这类历史兼容值在新链路中被误当作标准三级专业

本文档与以下文档互补：

- [tag-governance.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/tag-governance.md)
- [catalog-api-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-api-contract.md)
- [catalog-build-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-build-contract.md)
- [catalog-implementation-design.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-implementation-design.md)
- [major-filter-mapping.md](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/major-filter-mapping.md)
- [tag-mapping.md](/Users/baiyang/git/zhiyuan/gaokao-volunteer-rank-service/docs/tag-mapping.md)

## 2. 当前主数据来源盘点

### 2.1 assistant-backend

当前 backend 是离高途原始志愿结果最近的一层，已持有以下主数据与扩展数据：

- 专业层级主数据
  - `src/main/resources/bizdata/major_bachelor.json`
  - `src/main/resources/bizdata/major_associate.json`
  - 加载器：[MajorMappingManager.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/manager/MajorMappingManager.java)
- 专业扩展数据
  - `src/main/resources/bizdata/major_extra_data.csv`
  - 加载器：[MajorExtraDataManager.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/manager/MajorExtraDataManager.java)
- 院校主数据
  - `src/main/resources/bizdata/school_info.csv`
  - 加载器：[SchoolManager.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/manager/SchoolManager.java)
- 省市主数据
  - `src/main/resources/bizdata/province_city.json`
  - 加载器：`ProvinceCityManager`

运行时候选、方案与筛选链路，主要直接消费高途返回的：

- `schoolId`
- `schoolUnitCode`
- `majorId`
- `majorUnitCode`
- `categoryId`
- `subCategoryId`

并在 [PlanningStateService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java) 中补充：

- `major.discipline` <- `categoryId`
- `major.category` <- `subCategoryId`

### 2.2 gaotu-zy-agent-v3

agent 当前仍持有一套本地静态映射副本：

- `data/option/major_bachelor.json`
- `data/option/major_associate.json`
- `data/option/school_bachelor.csv`
- `data/option/school_associate.csv`
- `data/option/province_city.json`

主要消费入口：

- [major_data.py](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/app/data/major_data.py)
- [code_enrichment.py](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/app/util/code_enrichment.py)

当前 agent 会把名称转成编码后再供旧链路使用：

- 专业
  - `level1 -> level1_code`
  - `level2 -> level2_code`
  - `level3 -> level3_code`
- 院校
  - `values -> values_code`
- 地域
  - `province -> province_code`
  - `city -> city_code`

这些 code 目前主要被以下链路使用：

- rank-service 调用
- 选科/参数校验
- 分数线查询

补充说明：

- 当前这一层先不改运行时文件加载点
- 后续统一应通过接口层、共享生成物或发布链路来收敛“名称能否识别、识别成哪个 `id/code`”的主口径
- 不建议直接让 agent 在部署时跨模块读取 backend 仓库内文件

### 2.3 gaokao-volunteer-rank-service

rank 当前不是直接消费 backend 主数据，而是单独加载自己的静态文件：

- `services/dict/data_major.xlsx`
- `services/dict/data_school.xlsx`
- `services/dict/data_major_02.xlsx`
- `services/dict/data_school_02.xlsx`
- `services/dict/tag_major.json`
- `services/dict/tag_major_02.json`
- 以及评估/学位/特色等辅助表

加载器：

- [data_loader.py](/Users/baiyang/git/zhiyuan/gaokao-volunteer-rank-service/services/data_loader.py)

计算时直接依赖：

- `schoolId`
- `majorId`
- `subCategoryId`
- `province_code`
- `city_code`

关键历史兼容逻辑：

- [recommendation.py](/Users/baiyang/git/zhiyuan/gaokao-volunteer-rank-service/services/recommendation.py) 中，`majorId == '0'` 时会回退使用 `subCategoryId`

这说明 rank 内部仍把“具体专业志愿”和“仅专业大类粒度志愿”混在一个评分通道里。

### 2.4 frontend

frontend 不直接维护专业/院校编码映射表做业务计算，但会消费并展示：

- `schoolId / schoolUnitCode`
- `majorId / majorUnitCode`
- `categoryId / subCategoryId`
- `majorCategory / majorDiscipline`

当前前端专业门类/大类树仍有一层本地展示映射：

- [majorCategoryMap.ts](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetailV2/WorkspacePanel/majorCategoryMap.ts)

它只应该是“展示层兜底映射”，不应成为运行时主语义来源。

## 3. 统一主键口径

### 3.1 院校

- 主键：`schoolId`
- 展示代码：`schoolUnitCode`

约束：

- `schoolId` 是跨 backend / agent / rank 的唯一院校主键
- `schoolUnitCode` 只用于展示、导出、对账
- 禁止使用 `schoolUnitCode` 替代 `schoolId` 做业务主键

### 3.2 专业

- 具体专业主键：`majorId`
- 专业门类主键：`categoryId`
- 专业大类主键：`subCategoryId`
- 展示代码：`majorUnitCode`

约束：

- `majorId` 对应三级专业
- `categoryId` 对应一级门类
- `subCategoryId` 对应二级大类
- `majorUnitCode` 只作为招生展示代码，不参与跨服务主键语义

### 3.3 地域

- 省份主键：行政区划 `province_code`
- 城市主键：行政区划 `city_code`

约束：

- 对话、筛选、排序都应通过标准省市 code 流转
- 不允许用“院校标签里恰好带了某地名”替代地域主键

## 4. 标准标签域与编码字段的关系

| 语义 | 主键字段 | 标准标签域 | 说明 |
| --- | --- | --- | --- |
| 院校所在省 | `province_code` | `region.school_province` | 省级地域 |
| 院校所在市 | `city_code` | `region.school_city` | 市级地域 |
| 院校分类 | school 原始属性 | `school.category` | 综合、理工等 |
| 院校性质 | school 原始属性 | `school.nature` | 公办、民办等 |
| 专业门类 | `categoryId` | `major.discipline` | 对应旧 `level1` |
| 专业大类 | `subCategoryId` | `major.category` | 对应旧 `level2` |
| 具体专业 | `majorId` | `major.name` | 对应旧 `level3` |

兼容期约束：

- `majorKeywords` 仅承接 `major.category`
- `majorTags` 不应再继续承担 `major.category` 的标准枚举语义
- `majorId == 0` 只表示“当前志愿没有三级专业粒度”，不能视为正常 `major.name`

## 5. 各服务职责收口

### 5.1 backend

backend 作为唯一主数据收口层，负责：

- 加载专业/院校/地域主数据
- 提供 `name <-> id/code <-> 标准标签域` 映射
- 把高途返回的原始 `categoryId/subCategoryId` 映射为统一标签语义
- 对 frontend / agent 输出统一的筛选树与查询字段

backend 不应再把“是否存在某名称映射”这件事下放给 agent 本地字典判断。

### 5.2 agent

agent 负责：

- 抽取用户表达的名称语义
- 持有标准意图对象
- 在需要 code/id 时调用 backend 的映射能力

agent 不再作为主数据源，不应继续用本地 csv/json 副本决定：

- 某个专业/院校是否存在
- 某个名称对应哪个唯一编码

本地副本只允许：

- 离线测试
- prompt 展示层辅助
- backend 映射不可用时的临时兜底

当前阶段说明：

- 已完成：统一主键语义、字段边界、现状差异和治理方向的系统设计与文档化
- 未完成：agent / rank / frontend 仍各自加载自己的静态文件；后续需要继续推进接口层、共享生成物或统一发布链路

### 5.3 rank

rank 负责：

- 消费标准化后的 `schoolId / majorId / subCategoryId / province_code / city_code`
- 基于原始属性与历史 tag 计算分数修正

rank 不负责：

- 对外定义统一标签语义
- 对外定义名称与编码映射规范

rank 当前仍可保留内部 `tag_major.json / tag_major_02.json`，但应视为内部打分字典，而不是统一对外主数据。

### 5.4 frontend

frontend 负责：

- 消费 backend 输出的结构化筛选树
- 展示标签与编码对应关系

frontend 不负责：

- 自行定义专业/院校主数据
- 自行通过本地静态映射决定运行时编码语义

## 6. 当前差异事实

基于当前仓库静态文件核对，现状如下：

### 6.1 backend 与 agent

- `major_bachelor.json`
  - 结构一致
- `major_associate.json`
  - 结构一致
- `province_city.json`
  - 内容一致
- 学校字典
  - backend `school_info.csv` 共 3002 条
  - agent `school_bachelor.csv + school_associate.csv` 合并后共 3024 条
  - backend 无缺失项，但 agent 额外多出 22 条

结论：

- 专业与地域主数据当前基本同源
- 学校主数据当前不是完全同源，agent 持有一个比 backend 更大的并集副本

### 6.2 rank 与 backend

当前 rank 暴露出的 `volunteerinfo_major.json / volunteerinfo_majorgroup.json` 中：

- `schoolId`
  - 均可在 backend `school_info.csv` 中找到
- `majorId`
  - 非 `0` 的值均可在 backend 专业主数据中找到
- `categoryId / subCategoryId`
  - 存在历史兼容值 `0`
  - `majorgroup` 数据中还出现了 `subCategoryId = 172`，backend 当前主数据中不存在

结论：

- rank 与 backend 在主业务 ID 上大体兼容
- 但仍有历史兼容值与孤立类别 ID，需要显式治理，不能继续靠隐式兜底

## 7. 迁移策略

### Phase 1：治理与校验

- 固化本文件
- 增加自动检查脚本，持续校验 backend / agent / rank 数据一致性
- 将“主键字段”“展示 code”“历史兼容值”写入文档与 changelog

### Phase 2：统一生成链路 / 接口层设计

这一阶段的目标不是直接改掉各模块的文件加载点，而是先把“谁产出、谁发布、谁消费、谁校验”设计稳定。

推荐采用两层方案并行：

1. 统一语义主源层
2. 各模块本地消费层

其中：

- backend 继续作为统一语义主源
- agent / rank / frontend 继续保留各自本地文件加载逻辑
- 但这些本地文件的内容，不应再长期靠人工各改各的，而应来自同一套生成与发布链路

### Phase 2.1：共享生成物

建议新增一套“catalog build”生成链路，输入为 backend 当前主数据：

- `major_bachelor.json`
- `major_associate.json`
- `school_info.csv`
- `province_city.json`
- `major_extra_data.csv`

输出为按消费方裁剪后的标准生成物，例如：

- `catalog_major_agent_bachelor.json`
- `catalog_major_agent_associate.json`
- `catalog_school_agent_bachelor.csv`
- `catalog_school_agent_associate.csv`
- `catalog_province_city.json`
- `catalog_rank_school.xlsx`
- `catalog_rank_major.xlsx`
- `catalog_frontend_major_tree.json`
- `catalog_frontend_region_tree.json`

约束：

- 各模块仍从自己的目录加载本地文件
- 但这些本地文件应改为“由统一生成链路产出并同步”的发布产物
- 不再允许 agent / rank / frontend 分别手工维护语义相同但内容漂移的副本

建议生成物按“统一元数据 + 业务数据”两层组织。

统一元数据建议固定为：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "generatedAt": "2026-04-24T12:00:00+08:00",
  "sourceCommit": "backend-git-sha",
  "sourceFiles": [
    "major_bachelor.json",
    "major_associate.json",
    "school_info.csv",
    "province_city.json",
    "major_extra_data.csv"
  ]
}
```

各消费方生成物的最小 schema 建议如下。

agent 专业树：

```json
{
  "meta": {},
  "data": [
    {
      "id": "categoryId",
      "label": "工学",
      "children": [
        {
          "id": "subCategoryId",
          "label": "计算机类",
          "children": [
            {
              "id": "majorId",
              "label": "计算机科学与技术",
              "majorCode": "080901"
            }
          ]
        }
      ]
    }
  ]
}
```

agent 院校表：

```csv
标准院校id,标准院校名称,院校省份,院校城市,学校隶属,学校类型,学校标签,公办民办,本科专科
1,北京大学,北京,海淀,教育部,综合,985、211,公办,本科
```

rank 专业字典：

- 必须至少包含 `majorId / subCategoryId / categoryId / name / educationLevel`
- 对 `majorId=0` 的历史兼容样本，应额外显式标记 `granularity=category`

frontend 筛选树：

```json
{
  "meta": {},
  "major": {
    "disciplines": [
      {
        "id": "categoryId",
        "label": "工学",
        "children": [
          {
            "id": "subCategoryId",
            "label": "计算机类"
          }
        ]
      }
    ]
  },
  "region": {
    "provinces": [
      {
        "id": "province_code",
        "label": "北京",
        "children": [
          {
            "id": "city_code",
            "label": "海淀"
          }
        ]
      }
    ]
  }
}
```

约束：

- 生成物中的 `id` 一律使用统一主键，不得混入展示 code
- 展示 code 若需要保留，必须单独以 `schoolUnitCode / majorUnitCode` 命名
- 任一消费方生成物都必须带 `meta.catalogVersion`

### Phase 2.2：接口层

对于不适合靠静态生成物解决的“名称 -> 统一主键 / 标准标签域”问题，建议由 backend 提供内网接口，而不是继续分散在各端本地字典里判断。

详细协议见：

- [catalog-api-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-api-contract.md)
- [catalog-build-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-build-contract.md)

建议接口按能力拆分：

- 实体精确映射
  - `schoolName -> schoolId`
  - `majorName(level3) -> majorId + subCategoryId + categoryId`
  - `majorCategoryName(level2) -> subCategoryId + categoryId`
  - `majorDisciplineName(level1) -> categoryId`
  - `provinceName -> province_code`
  - `cityName -> city_code`
- 实体模糊检索
  - `school keyword -> school candidates`
  - `major keyword -> major candidates`
- 标签树 / 筛选树查询
  - `major.discipline -> major.category tree`
  - `province -> city tree`
  - `school tags / admission.type / constraint.limit` 枚举树

约束：

- 接口层只负责“统一语义判定与映射”
- 各模块本地文件仍负责高频运行时读取和离线启动
- 因此接口层不是为了替换所有本地静态文件，而是为了收口最容易漂移的映射逻辑

建议把接口再拆成三类：`lookup / search / tree`。

#### 现有可复用接口

专业：

- `/gaotu-assistant-bot/inner/major/getMajorInfo?majorId=`
- `/gaotu-assistant-bot/inner/major/getThirdLevelIdAndSecondLevelId?thirdLevelName=`
- `/gaotu-assistant-bot/inner/major/getMajorProfile?id=|name=`
- `/gaotu-assistant-bot/inner/major-category/getMajorCategoryProfile?id=|name=`

院校：

- `/gaotu-assistant-bot/inner/school/id?schoolId=`
- `/gaotu-assistant-bot/inner/school/name?schoolName=`
- `/gaotu-assistant-bot/inner/school/search/name?schoolName=`
- `/gaotu-assistant-bot/inner/school/getSchoolProfileByName?name=`

地域：

- `/gaotu-assistant-bot/inner/province-city/province/id`
- `/gaotu-assistant-bot/inner/province-city/province/name`
- `/gaotu-assistant-bot/inner/province-city/city/id`
- `/gaotu-assistant-bot/inner/province-city/city/name`
- `/gaotu-assistant-bot/inner/province-city/cities/province-name`

筛选树：

- `/gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/filter-options`

#### 缺口接口

当前还缺少统一、稳定、可直接给 agent/rank/frontend 使用的最小映射接口，建议补以下接口。

1. 精确 lookup

`GET /gaotu-assistant-bot/inner/catalog/lookup/school?name=北京大学`

返回：

```json
{
  "schoolId": "1",
  "schoolName": "北京大学",
  "schoolUnitCode": "10001"
}
```

`GET /gaotu-assistant-bot/inner/catalog/lookup/major?name=计算机科学与技术&educationLevel=本科`

返回：

```json
{
  "majorId": "574",
  "majorName": "计算机科学与技术",
  "subCategoryId": "39",
  "subCategoryName": "计算机类",
  "categoryId": "7",
  "categoryName": "工学"
}
```

`GET /gaotu-assistant-bot/inner/catalog/lookup/major-category?name=计算机类&educationLevel=本科`

`GET /gaotu-assistant-bot/inner/catalog/lookup/major-discipline?name=工学&educationLevel=本科`

`GET /gaotu-assistant-bot/inner/catalog/lookup/province?name=北京`

`GET /gaotu-assistant-bot/inner/catalog/lookup/city?name=海淀`

2. search

`GET /gaotu-assistant-bot/inner/catalog/search/school?keyword=北京`

`GET /gaotu-assistant-bot/inner/catalog/search/major?keyword=计算机&educationLevel=本科`

要求：

- search 返回候选列表，不直接做唯一判定
- 列表元素必须带统一主键
- 必须区分 `exact / alias / fuzzy` 命中类型

3. tree

`GET /gaotu-assistant-bot/inner/catalog/tree/major?educationLevel=本科`

`GET /gaotu-assistant-bot/inner/catalog/tree/region`

`GET /gaotu-assistant-bot/inner/catalog/tree/filter-tags`

要求：

- tree 接口返回结构化树，不再依赖前端自行拼接门类/大类父子关系
- `filter-tags` 统一返回 `school.* / major.* / admission.type / constraint.limit`

#### 接口返回约束

所有 catalog 接口都应满足：

- 统一返回主键，不返回仅展示用 code 作为唯一标识
- 携带 `catalogVersion`
- 对不存在结果显式返回空，不允许模糊兜底成别的层级
- 对多命中结果必须区分：
  - 无结果
  - 唯一结果
  - 多候选结果

### Phase 2.3：发布链路

建议把“共享生成物”纳入统一发布链路，最小要求：

1. backend 主数据更新后，触发 catalog build
2. catalog build 产出各消费方版本化文件
3. agent / rank / frontend 通过发布脚本或子仓同步机制接入对应版本
4. CI 校验生成物版本与消费方仓库中的本地副本是否一致

建议增加版本元数据：

- `catalogVersion`
- `generatedAt`
- `sourceCommit`
- `schemaVersion`

这样可以在运行时和联调时快速确认：

- 当前各服务是否使用同一批主数据
- 某个问题到底是“算法问题”还是“主数据版本不一致”

### Phase 2.4：校验链路

后续校验不应只看“文件是否存在”，而应分成三层：

1. 结构校验
2. 语义校验
3. 样本回归

结构校验：

- 字段是否齐全
- 主键是否唯一
- 层级关系是否闭合

语义校验：

- `level1/level2/level3` 是否仍分别对应 `categoryId/subCategoryId/majorId`
- `majorKeywords` 是否只承接 `major.category`
- `schoolId / majorId / province_code / city_code` 是否都能在统一主数据中找到

样本回归：

- 用固定样本校验前端筛选、agent 对话筛选、rank 打分输入、backend 候选筛选是否仍给出同一口径

### Phase 2.5：各模块接入清单

agent：

- 第一优先级
  - `code_enrichment`
  - `student_info_mappings`
  - 对话侧专业/院校/地域名称抽取后的 code 补全
- 第二优先级
  - `plan_validation_tool`
  - `score_query_tool`
  - 与标签筛选直接相关的 query tool
- 暂缓
  - prompt 展示层用到的本地专业树/院校列表

rank：

- 第一优先级
  - `schoolId / majorId / subCategoryId / province_code / city_code` 输入校验
  - `majorId=0` 显式粒度语义
- 第二优先级
  - `dict/` 目录改为统一生成物同步
  - 启动时比对 `catalogVersion`
- 暂缓
  - 内部打分标签字典重构

frontend：

- 第一优先级
  - 专业门类/大类树
  - 地域树
  - 筛选枚举来源
- 第二优先级
  - 本地展示兜底映射清退
  - 根据 `catalogVersion` 做前后端联调检查
- 暂缓
  - 仅用于展示的 label 文案优化

### Phase 3：agent 去本地生产映射

在 Phase 2 的接口层与生成链路稳定后，再推进：

- agent 的 `code_enrichment` 改为优先调用 backend 映射接口
- 本地 `major_*.json / school_*.csv / province_city.json` 改为测试/兜底用途

### Phase 4：rank 输入显式标准化

- rank 继续只消费标准 ID
- `majorId = 0` 改为显式“专业大类粒度”语义，不再隐式重写
- 对 `subCategoryId` 的非法值建立启动校验和回归测试

### Phase 5：frontend 完全消费 backend schema

- 前端不再依赖本地 `majorCategoryMap` 充当运行时主语义
- 专业门类/大类树只展示 backend 输出

## 8. 执行约束

后续所有新逻辑必须满足：

1. 先定义语义属于 `name / id / code / tag` 中哪一层。
2. 运行时主键只允许使用：
   - `schoolId`
   - `majorId`
   - `categoryId`
   - `subCategoryId`
   - `province_code`
   - `city_code`
3. `schoolUnitCode / majorUnitCode` 只允许用于展示、导出、对账。
4. 任何服务若新增本地字典副本，必须先说明其与 backend 主数据的同步策略。
5. 对外统一标签与筛选语义仍以 backend 为唯一收口层。
