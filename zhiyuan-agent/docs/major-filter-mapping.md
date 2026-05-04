# 专业层级与筛选字段映射

## 1. 目标

本文档固定 `gaotu-zy-agent-v3` 在意图抽取、画像更新、工作台联动时使用的专业层级口径，避免再次出现 `level1 / level2 / level3` 与 `majorTags / majorKeywords` 混用。

补充约束：

- agent 不再被视为专业/院校主数据源
- `data/option/*.json|*.csv` 当前仅可作为本地展示、测试或 backend 映射失败时的兜底副本
- 当前先不改 agent 运行时的文件加载点；后续统一应通过接口层、共享生成物或发布链路完成，而不是直接跨模块依赖 backend 仓库内文件
- 运行时名称到编码的最终收口语义，以 backend 文档 [entity-catalog-governance.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/entity-catalog-governance.md) 为准

## 2. 统一映射表

| 语义层级 | 中文含义 | 抽取结果字段 | rank / 推荐结果字段 | 统一标签域 | 候选筛选兼容字段 |
| --- | --- | --- | --- | --- | --- |
| level1 | 专业门类 | `level1 / negative_level1` | `categoryId` | `major.discipline` | `majorTags / negativeMajorTags` |
| level2 | 专业大类 | `level2 / negative_level2` | `subCategoryId` | `major.category` | `majorKeywords / negativeMajorKeywords` |
| level3 | 具体专业 | `level3 / negative_level3` | `majorId` | 暂无独立标准标签域 | 暂无；仅允许兼容兜底 |

## 3. 运行时约束

- `majorKeywords` 在当前链路中只承接 `major.category`
- `majorTags` 当前承接：
  - `major.discipline`
  - `admission.type`
  - `constraint.limit`
- `level1 / level2 / level3` 的 `*_code` 只表示与旧 rank / 校验链路兼容的编码透传，不应继续被视为 agent 本地定义的主键体系
- 统一设计目标中的返回口径固定为：
  - `level1_code -> categoryId`
  - `level2_code -> subCategoryId`
  - `level3_code -> majorId`
  - `college_info.values_code -> schoolId`
  - `city_info.province_code / city_code -> 行政区划 code`
- `level3` 不能再和 `level1 / level2` 一起无差别塞进 `majorKeywords`
- 如果用户表达的是“计算机类”“材料类”“教育学类”这类专业大类，应优先写入 `level2`，并联动到 `majorKeywords`
- 如果用户表达的是“工学”“医学”“法学”这类专业门类，应优先写入 `level1`，并联动到 `majorTags`
- 如果用户表达的是“软件工程”“临床医学”这类具体专业，当前只允许作为兼容兜底使用，不能冒充 `major.category`

## 4. 对话联动要求

- 硬约束联动候选区时：
  - `level1 -> majorTags`
  - `level2 -> majorKeywords`
  - `level3 -> 仅在缺失 level2 时兜底`
- 软意向更新画像时：
  - 仍保持 `level1 / level2 / level3` 原层级存储
  - 不得在 agent 内部把三层语义压平为一个“专业关键词”列表

## 5. 与旧命名的关系

- `major.category`
  - 旧语义里有时指“专业门类”
  - 在当前统一约定中一律禁止继续这样使用
- `major.subcategory`
  - 在当前统一约定中对应“专业大类”
- `planEdit`
  - 当前只保留兼容命名
  - 不应再附着旧的“直接改方案”语义

## 6. 后续统一落地方式

当前不建议直接把 agent 的运行时文件读取切到其他模块目录。

推荐顺序：

1. backend 固定统一主语义与映射接口
2. catalog build 产出 agent 可消费的标准生成物
3. agent 继续从本仓库本地文件加载，但这些文件改为“统一生成物同步结果”
4. `code_enrichment / intent 抽取 / 对话筛选` 中最容易漂移的“名称 -> id/code”映射，逐步改为调用 backend 接口层

这样可以同时满足：

- 部署时不跨模块依赖文件
- 本地离线能力仍保留
- 运行时语义不再长期漂移

## 7. 当前接入进展

当前第一批已接入 backend `catalog` 的入口：

- `app/util/code_enrichment.py`
  - 新增异步补码链路：
    - `get_major_codes_async`
    - `get_school_codes_async`
    - `get_province_codes_async`
    - `get_city_codes_async`
    - `add_codes_to_profile_async`
- `app/services/profile_manager.py`
  - 保存画像时改为调用异步补码链路
- `app/tools/intent_state_tool.py`
  - 在硬约束生效时，对 `candidateFilters` 做一次 catalog 归一化
- `app/tools/explore_followup_tool.py`
  - 在兴趣阶段的候选查询动作里，对 `candidateFilters` 做一次 catalog 归一化
- `app/tools/score_query_tool.py`
  - 学校 / 专业 / 省份补码改走异步链路
- `app/tools/plan_validation_tool.py`
  - 学校 / 专业 / 省市补码改走异步链路
- `app/tools/planning_router_tool.py`
  - 直接面向用户的 `candidate_query` 入参，在发给 backend 前也会做一次 catalog 归一化

当前策略：

- 对 agent 本地静态映射能精确命中的名称，仍直接使用本地结果
- 仅当本地映射缺失时，才调用 backend `catalog` lookup 做补码或名称归一化
- 因此现阶段仍满足：
  - 本地离线测试可跑
  - 运行时出现名称漂移时，agent 已有统一语义收口入口

当前归一化范围：

- `provinceNames / cityNames`
- `schoolKeywords`
- `majorKeywords`
- `majorTags`
- `schoolTags`

其中 `schoolTags` 当前通过 backend `catalog/tree/filter-tags` 的统一枚举树做白名单收口，避免路由层把任意自由文本直接当成标准院校标签下发。

## 8. studentinfo 与 batch/subject 的边界

- `app/data/student_info_mappings.py`
  - 负责构造 rank-service 需要的 `studentinfo` 结构
  - 其中 `subjectList[].value`、`strengthSubjectList[].subject` 是 rank-service 自身字段，不等同于高途查询接口的 `subjects` 编码
- `app/util/batch_subject_mapping.py`
  - 负责高途查询链路里的 `subjectType / batch / subjects` 解析
  - `encode_subjects()` 产出的字符串仅服务于查询接口，不应用来回填 `studentinfo.subjectList`

当前统一策略：

- 不合并两套下游字段结构
- 仅共享“省份感知的 `subjectType` 判定逻辑”
- 因此：
  - `studentinfo.subjectType.code` 现复用 `resolve_subject_type()`
  - `studentinfo.subjectList[].value` 仍保留 rank-service 自己的码表

这样做的原因：

- 避免把两条下游链路的不同协议强行揉成一套，造成隐性错误
- 同时把最容易漂移的“省份 + 选科 -> subjectType”判定收口为一套逻辑

## 9. 性能约束

当前 agent 接 catalog 的策略专门限制了额外时延：

- 本地静态映射精确命中时，不发 backend catalog 请求
- 仅当本地映射 miss 时，才触发 catalog lookup
- 单次补码/归一化中，对重复名称先去重，再并发查 miss 项
- `catalog/tree/filter-tags` 在 agent 进程内做缓存，避免每次筛选归一化都重复拉整棵标签树

这意味着当前新增 catalog 接入对性能的影响主要发生在：

- 用户输入了本地静态文件中没有的别名/新名称
- 或第一次进行 `schoolTags` 归一化时

正常稳定路径下，新增调用不会覆盖所有请求，只是补齐语义漂移时的兜底成本。

同样的策略也应用到 agent 的名称解析型工具：

- `major_compare_tool / school_compare_tool`
  - 先尝试本地标准名命中
  - 本地 miss 时，先用 catalog 做一次标准名归一化
  - 只有 catalog 仍未收口时，才继续走 fuzzy 候选和 LLM 二次判断

因此在“北大 / 计科 / 软工”这类常见别名场景下，当前链路通常能少一次 LLM 调用，直接降低响应时延。
