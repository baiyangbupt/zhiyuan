# 标签统一治理约定

## 1. 目标

本文件用于统一 `gaokao-volunteer-rank-service`、`gaotu-assistant-backend`、`gaotu-zy-agent-v3`、`gaokao-volunteer-pc`
在“标签”上的职责边界、字段口径、枚举来源与演进方式。

目标不是把所有标签都放进一个大列表，而是建立一套稳定约定，保证：

- rank 用同一套标签语义做打分
- backend 用同一套标签语义做筛选和返回
- agent 用同一套标签语义做意图识别和工作台联动
- frontend 用同一套标签语义展示和筛选

只有在这套约定稳定后，`sessionDetail` 才适合正式切到 `sessionDetailV2`。

## 2. 目标标签体系

系统后续应统一到以下标准标签体系。这里的“标签”指可被 frontend 展示筛选、agent 识别、backend 映射、rank 打分复用的标准语义单元。

### 2.1 地域标签

- `region.school_province`
  - 院校所在省
  - 例如：`北京`、`浙江`、`广东`
- `region.school_city`
  - 院校所在城市
  - 例如：`杭州`、`温州`、`广州`

约束：

- `school_province` 是首要地域筛选维度
- `school_city` 必须进入统一标签体系，但是否首版直接进入前端显式筛选，可按产品复杂度灰度
- 院校地域属性不得再混入 `schoolTags`

### 2.2 院校标签

- `school.category`
  - 综合、理工、师范、财经、政法、医药、语言、农林、民族、体育、艺术、军事
- `school.nature`
  - 公办、民办、中外合作
- `school.feature`
  - 教育部直属、中央部委、省会城市
- `school.level`
  - 本科、专科、985、211、双一流、强基、保研、国重点、省重点、双高计划、国家级示范、国家级骨干、职业本科

### 2.3 专业标签

- `major.discipline`
  - 专业门类，对应 `level1`
- `major.category`
  - 专业大类，对应 `level2`

专业层级与运行时字段统一映射表：

| 语义层级 | 中文含义 | 旧画像字段 | rank / 推荐结果字段 | 统一标签域 | 候选筛选兼容字段 |
| --- | --- | --- | --- | --- | --- |
| level1 | 专业门类 | `level1` | `categoryId` | `major.discipline` | `majorTags` |
| level2 | 专业大类 | `level2` | `subCategoryId` | `major.category` | `majorKeywords` |
| level3 | 具体专业 | `level3` | `majorId` | 暂无独立标准标签域 | 暂无；仅允许兼容兜底 |

要求：

- `专业门类` 和 `专业大类` 都必须展开进统一标签体系
- 不能继续仅以“majorKeywords”这类模糊名字在运行时隐含存在

### 2.4 招生与限制标签

- `admission.type`
  - 普通类、中外合作办学、地方专项、国家专项、特色计划、少数民族、预科、定向、试（实）验班、师范专业、首年招生
- `constraint.limit`
  - 色盲色弱、语种要求、单科成绩、性别要求

说明：

- `中外合作` 相关语义需要拆清
  - 院校性质侧落到 `school.nature=中外合作`
  - 招生类型侧落到 `admission.type=中外合作办学`
- `constraint.limit` 用于表达候选筛选、约束确认和 review 共用的限制项语义

## 3. 标签分层

系统内的标签必须先按“作用对象”和“作用方式”拆开。

### 3.1 按作用对象分

- `school tags`
  - 描述院校/院校专业组属性
  - 例如：`公办`、`双一流`、`理工院校`
- `major tags`
  - 描述专业/专业大类属性
  - 例如：`计算机`、`师范`、`医学`

禁止继续使用无归属的通用 `tags` 作为运行时接口字段。

### 3.2 按作用方式分

- `display tags`
  - 只用于展示说明
  - 不参与筛选枚举，不直接参与意图识别
- `filter tags`
  - 可进入候选面板筛选
  - 必须是稳定、枚举型、离散值
- `score tags`
  - rank 可用于正负向加减分
  - 需要可映射到用户意向或画像
- `risk tags`
  - 用于审查、补偿和风险解释
  - 不应直接混入候选筛选枚举

同一个标签可以同时属于多个层，但必须显式声明，而不能默认“所有标签都能筛、都能打分、都能识别”。

## 4. 旧命名兼容映射

现网多处仍在使用旧语义或旧命名。切换到标准标签体系时，不能直接删除旧字段，必须先经过映射层收口。

### 4.1 major 旧命名

- `categoryId`
  - 对应一级专业分类
  - 统一映射到 `major.discipline`
- `subCategoryId`
  - 对应二级专业分类
  - 统一映射到 `major.category`
- `major.category`
  - 旧语义中通常指“专业门类”
  - 统一映射到 `major.discipline`
- `major.subcategory`
  - 旧语义中通常指“专业大类”
  - 统一映射到 `major.category`
- `level1`
  - 统一映射到 `major.discipline`
- `level2`
  - 统一映射到 `major.category`

说明：

- 当前前端初始采集里的 `preferredMajors.majorSubName`，本质上是 `level2`，也就是“专业大类”
- 因此现阶段运行时 `majorKeywords` 实际承接的是“专业大类”，不是自由关键词
- 文档和映射表必须显式记录这件事，避免后续再把“专业大类”误当成模糊检索词

### 4.2 school 旧命名

- `provinceName`
  - 统一映射到 `region.school_province`
- `cityName`
  - 统一映射到 `region.school_city`
- `schoolCategory`
  - 映射到 `school.category`
- `schoolNature`
  - 映射到 `school.nature`
- `schoolLevel`
  - 映射到 `school.level`
- `schoolBasicTags / schoolRankTags / schoolPopupTags`
  - 作为候选原始标签来源，需要二次映射到标准院校标签

### 4.3 兼容期规则

- 标准标签是统一主语义
- 旧命名只作为兼容输入存在
- frontend、backend、agent、rank 在内部处理前都必须先把旧字段映射到标准标签
- 不允许新逻辑继续直接扩展旧命名

## 5. 统一字段口径

### 5.1 候选查询接口

`candidate-pool/query` 统一只接受以下标签字段：

- `schoolTags`
- `negativeSchoolTags`
- `majorTags`
- `negativeMajorTags`

并继续保留：

- `provinceNames`
- `negativeProvinceNames`
- `cityNames`
- `negativeCityNames`
- `schoolKeywords`
- `negativeSchoolKeywords`
- `majorKeywords`
- `negativeMajorKeywords`
- `tiers`

禁止再新增或继续透传以下旧字段：

- `tags`
- `negativeTags`

补充约定：

- `provinceNames / negativeProvinceNames`
  - 只表示院校所在省
- `cityNames / negativeCityNames`
  - 只表示院校所在城市
- `schoolKeywords / negativeSchoolKeywords`
  - 只允许表示“具体院校名”
  - 不允许承接公办、民办、中外合作、双一流这类属性
- `majorKeywords / negativeMajorKeywords`
  - 在兼容期内仅承接“专业大类（level2）”
  - 当前运行时实现里，这个字段名虽然叫 `keywords`，但在候选筛选语义上应视为“专业大类枚举值通道”，不是自由文本搜索词
  - `candidate-pool/filter-options.groups` 中的 `major.category` 也必须映射到该字段，保证前端默认意向、显式筛选与查询入参一致
  - `candidate-pool/filter-options` 顶层也必须显式返回 `majorKeywords`，不能只放在 `groups` 里让 frontend 从候选项回退猜测
  - 后续应被标准标签 `major.category` 替代
- `schoolTags / negativeSchoolTags`
  - 承接标准院校标签
- `majorTags / negativeMajorTags`
  - 承接标准专业标签
  - 当前兼容实现中仍会混入 `major.discipline` 等稳定枚举值，因此 frontend/agent 在消费时必须显式按组别区分，不能把它直接当成“剩余专业标签全集”

当前实现风险：

- `majorKeywords`
  - 运行时字段名是 `keywords`
  - frontend 展示和 agent 映射口径上承接的是 `专业大类（level2）`
  - backend 匹配实现中仍兼容命中 `majorName / major.category / major.discipline`
- `majorTags`
  - frontend 展示上同时承接 `专业门类` 与 `专业标签`
  - backend 匹配实现里还会混入 `majorRankTags / majorPlanTags / constraint tags`

因此当前不能把字段名直接等同于真实业务语义，新增逻辑时必须先看“标准标签域 -> 运行时兼容字段”的映射，而不是只看字段名。

### 5.2 候选返回字段

backend 返回给前端的候选字段口径保持为：

- `schoolBasicTags`
- `schoolRankTags`
- `schoolPopupTags`
- `majorRankTags`
- `majorPlanTags`
- `provinceName`
- `cityName`

这些字段的职责分别是：

- `schoolBasicTags`
  - 院校基础属性展示
  - 其中一部分可映射到 `schoolTags`
- `schoolRankTags`
  - 与院校层次、升学、保研等相关的展示/筛选/打分标签
- `schoolPopupTags`
  - 更偏展示补充，不默认进入筛选枚举
- `majorRankTags`
  - 专业属性与方向标签
  - 一部分可映射到 `majorTags`
- `majorPlanTags`
  - 计划、培养、选科等标签
  - 仅其中离散且稳定的部分可进入 `majorTags`
- `provinceName`
  - 候选院校所在省，统一映射到 `region.school_province`
- `cityName`
  - 候选院校所在城市，统一映射到 `region.school_city`

## 6. 跨模块映射表

以下映射表用于约束“前端采集 / agent 抽取 / backend 运行时字段 / rank 打分标签”最终都回到同一套标准标签。

### 6.1 frontend 采集 -> 标准标签

- 意向地域（省）
  - `region.school_province`
- 意向地域（市，若后续采）
  - `region.school_city`
- 意向专业门类（level1）
  - `major.discipline`
- 意向专业大类（level2）
  - `major.category`
- 不接受中外合作
  - 排除 `school.nature=中外合作`
  - 必要时同时排除 `admission.type=中外合作办学`

### 6.2 agent 抽取 -> 标准标签

- “不去北京”
  - `region.school_province=北京`, polarity=`exclude`
- “不想去温州”
  - `region.school_city=温州`, polarity=`exclude`
- “想学工科”
  - `major.discipline=工学`, polarity=`include`
- “想报计算机类”
  - `major.category=计算机类`, polarity=`include`
- “不接受中外合作”
  - `school.nature=中外合作`, polarity=`exclude`
  - 必要时补 `admission.type=中外合作办学`, polarity=`exclude`

### 6.3 backend 运行时字段 -> 标准标签

- `CandidateItemDTO.provinceName`
  - `region.school_province`
- `CandidateItemDTO.cityName`
  - `region.school_city`
- `CandidateItemDTO.schoolCategory`
  - `school.category`
- `CandidateItemDTO.schoolNature`
  - `school.nature`
- `CandidateItemDTO.schoolLevel`
  - `school.level`
- `CandidateItemDTO.schoolBasicTags / schoolRankTags / schoolPopupTags`
  - 映射到标准院校标签
- `CandidateItemDTO.majorRankTags / majorPlanTags`
  - 映射到标准专业标签或招生/限制标签
- `ExplicitProfileDTO.positiveMajors / negativeMajors`
  - 兼容期视作 `major.category`
- `ExplicitProfileDTO.positiveSchools / negativeSchools`
  - 兼容期仅允许表示具体院校名
- `ExplicitProfileDTO.positiveRegions / negativeRegions`
  - 兼容期视作 `region.school_province`

### 6.4 rank 原始标签 -> 标准标签

- rank 内部院校层标签
  - 映射到 `school.category / school.nature / school.feature / school.level`
- rank 内部专业层标签
  - 映射到 `major.discipline / major.category`
- rank 内部特殊项目标签
  - 映射到 `admission.type`
- rank 内部限报与风险标签
  - 映射到 `constraint.limit` 或 review/risk 体系

要求：

- rank 不得直接把原始标签字典暴露给 frontend 或 agent
- 必须先经过 backend 的标准标签映射层

## 7. 标签主数据治理

### 7.1 单一主源

标签枚举必须有唯一主源，推荐由 backend 维护“可供筛选和识别的标准标签词表”。

原因：

- rank 的原始标签字典更偏打分实现，不适合直接暴露给前端
- agent 需要的是可识别、可解释、可枚举的标准词表
- frontend 需要的是稳定、去噪、可展示的枚举结果

### 7.2 主数据至少包含的字段

每个标准标签至少应包含：

- `tagCode`
  - 稳定编码，跨服务引用优先用它
- `tagName`
  - 用户可见名称
- `tagDomain`
  - `region` / `school` / `major` / `admission` / `constraint`
- `tagCategory`
  - 例如：`school_province` / `school_city` / `nature` / `level` / `category` / `discipline` / `type` / `limit`
- `enabledForFilter`
- `enabledForScore`
- `enabledForIntent`
- `enabledForDisplay`
- `aliases`
  - agent 意图识别可用的同义表达
- `version`

在标准标签主数据没落地前，运行时最少也要保证 backend `candidate-pool/filter-options` 的返回结果是唯一可信来源。

## 8. 前端筛选交互约定

候选筛选区必须围绕统一标签体系做显式交互，不允许再出现“隐藏生效的默认筛选”。

### 8.1 下拉项结构

- 每行一个标准标签
- 左侧显示标签名称
- 右侧显示 `筛选 | 排除`
- `筛选` 与 `排除` 为互斥态
- 再次点击当前高亮态可取消

### 8.2 生效状态

- 所有当前生效的筛选都必须显式展示
- 包括初始化从画像、agent 意图确认、前端采集同步来的默认项
- 不允许只在 query 参数里保留，而界面上不可见

### 8.3 filter-options 职责

- frontend 只消费 backend 提供的统一 `filter-options`
- 地域、院校标签、专业标签、招生类型、限报要求都应由 backend 统一管理和返回
- frontend 不从当前已加载候选中自行拼装“地域标签”或“院校地域属性”

## 9. 各系统职责

### 9.1 rank

rank 负责：

- 维护底层打分所需的标签映射和权重规则
- 将原始标签映射到标准标签编码
- 不直接决定 frontend 展示枚举

rank 不负责：

- 直接给前端输出筛选枚举
- 直接给 agent 暴露原始字典文件

### 9.2 backend

backend 负责：

- 维护标准标签主数据或其运行时镜像
- 把 rank / 原始数据中的标签映射为统一字段
- 决定哪些标签可以进入 `filter-options`
- 提供前端筛选枚举接口
- 为 agent 提供统一查询协议

### 9.3 agent

agent 负责：

- 基于标准标签或 backend 返回枚举做意图识别
- 在 `planningWorkspaceAction.candidateFilters` 中只下发统一字段
- 不再直接使用旧 `tags/negativeTags`

agent 不应：

- 自己维护另一套无版本的标签常量
- 将“展示标签”直接当成“筛选标签”

### 9.4 frontend

frontend 负责：

- 消费 backend 返回的筛选枚举
- 只用统一字段提交候选筛选
- 展示标签时区分“展示标签”和“筛选标签”

frontend 不应：

- 从当前已加载候选结果中自行反推完整标签枚举
- 自己拼出新的标签语义字段

## 10. 过滤、打分、识别的统一规则

### 10.1 过滤

- 候选筛选只允许使用标准化后的地域/院校/专业/招生/限制标签
- 不同属性间做 `且`
- 同属性内部做 `或`

### 10.2 打分

- rank 使用的正负向标签应优先映射到标准标签编码
- 若某条标签只存在于 rank 内部实现，且不适合暴露到前台，则不得直接进入筛选枚举

### 10.3 意图识别

- agent 对“公办”“双一流”“师范”“计算机”“不去北京”“不接受中外合作”等离散表达的识别，应优先落到标准标签
- 对“学费低”“好就业”“录取率高”这类数值或连续概念，优先落到排序、约束或解释层，不直接伪装成标签枚举

## 11. 允许进入筛选枚举的标签标准

只有满足以下条件的标签才能进入 `candidate-pool/filter-options`：

- 含义稳定
- 粒度离散
- 跨服务可复用
- 用户容易理解
- 不依赖数值阈值解释

以下信息默认不进入枚举：

- 排名
- 录取率
- 学费金额
- 计划数
- 位次
- 保研率
- 升学率
- 就业薪资

这些字段统一走排序、范围过滤或解释，不走标签枚举。

## 12. 页面切换前置条件

在正式把默认入口从 `sessionDetail` 切到 `sessionDetailV2` 前，至少要满足：

1. frontend 提交候选筛选时不再使用 `tags/negativeTags`
2. agent `planningWorkspaceAction.candidateFilters` 不再使用 `tags/negativeTags`
3. agent 查询候选总量与候选列表接口字段和 backend 完全一致
4. backend `filter-options` 成为前端筛选枚举唯一来源
5. rank 参与打分的关键标签已完成到标准标签的映射说明

## 13. 当前落地建议

建议按以下顺序推进：

1. 先冻结标准标签体系和旧命名兼容映射，不再新增游离标签语义
2. backend 增加标准标签映射说明，明确候选返回字段如何映射到标准标签
3. 调整 frontend / agent / rank 到统一映射表
4. 将 `filter-options` 扩展为统一输出地域、院校、专业、招生类型、限制项的显式筛选枚举
5. 再做 `sessionDetail -> sessionDetailV2` 默认入口切换
