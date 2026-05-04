# 现有推荐与分层链路梳理

## 1. 文档目的

本文档用于梳理当前系统中与志愿推荐直接相关的既有实现，作为后续拆分：

- 基础候选池
- 专家推荐覆盖层
- 工作台筛选状态层

的设计依据。

本文只描述当前实现和既有经验规则，不直接引入目标态改造方案。

相关文档：

- [planning-state-roadmap.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/planning-state-roadmap.md)
- [planning_state_full_design.md](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/planning_state_full_design.md)

## 2. 当前主链路

当前 backend 推荐主链如下：

1. 读取用户成绩、用户画像、全量志愿数据。
2. 合并画像，得到当前推荐使用的 `userFinalProfileData`。
3. 根据成绩信息、身体限制、学费、专项计划、用户画像构造筛选条件。
4. 对全量志愿做过滤。
5. 按录取率将志愿先划分到九宫格区间。
6. 对每个小区间调用 rank 服务做专家打分排序。
7. 将九宫格合并为冲稳保三大区间，并按目标数量截取。
8. 在每个大区间内部按 `volunteer_score` 排名，标记“专家优选组合”。

对应代码：

- 数据准备与主流程：
  [VolunteerBizService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerBizService.java)
- 画像整理：
  [VolunteerUtils.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerUtils.java)
- 条件过滤：
  [VolunteerFilterChain.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerFilterChain.java)
- 区间划分：
  [VolunteerIntervalService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/volunteer/VolunteerIntervalService.java)
- 分区间排序与合并：
  [VolunteerSorterAndMerger.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerSorterAndMerger.java)
- 优选标记：
  [VolunteerResponseBuilder.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerResponseBuilder.java)
- rank 打分：
  [recommendation.py](/Users/baiyang/git/zhiyuan/gaokao-volunteer-rank-service/services/recommendation.py)

## 3. 当前候选生成逻辑

### 3.1 当前候选并不是纯基础池

当前候选池生成时，`VolunteerFilterChain` 已经把以下信息直接作为过滤条件：

- 正向省份、城市
- 负向省份、城市
- 正向院校、负向院校
- 正向专业、负向专业
- 选科
- 色盲色弱
- 少数民族
- 专项计划
- 学费区间

这意味着当前实现中：

- 用户软意向会直接影响候选成员
- 候选池、专家推荐、工作台筛选状态尚未分层

对应代码：

- [VolunteerFilterChain.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerFilterChain.java#L19)

### 3.2 当前画像的作用位置

当前画像在推荐链路中至少影响两层：

1. 候选过滤层
2. rank 打分层

其中第二层已经具备成熟的提权和降权规则，后续若要拆分“候选基础层”和“专家推荐覆盖层”，rank 侧逻辑可以继续复用。

## 4. 冲稳保区间分层逻辑

### 4.1 三大区间

当前三大区间按录取率划分：

- 冲：1 - 50
- 稳：51 - 70
- 保：71 - 100

对应代码：

- [VolunteerIntervalService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/volunteer/VolunteerIntervalService.java#L74)

### 4.2 九宫格细分

当前九宫格细分规则为：

- 冲1：1 - 10
- 冲2：11 - 34
- 冲3：35 - 50
- 稳1：51 - 56
- 稳2：57 - 62
- 稳3：63 - 70
- 保1：71 - 86
- 保2：87 - 98
- 保3：99 - 100

说明：

- 划分基准是 `schoolEnrollRatio`
- 不是按 `volunteer_score` 分层
- `volunteer_score` 只决定每个区间内部谁更值得优先推荐

对应代码：

- [VolunteerIntervalService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/volunteer/VolunteerIntervalService.java#L37)

## 5. 冲稳保目标数量逻辑

当前目标数量由总志愿数和策略型共同决定。

### 5.1 三大区间比例

- 激进型 `aggressive`：4:3:3
- 稳妥型 `cautious`：3:3:4
- 保守型 `traditional`：2:4:4

例如总数 45 时：

- 激进型：18 / 13 / 14
- 稳妥型：13 / 13 / 19
- 保守型：9 / 18 / 18

### 5.2 九宫格内部比例

- 冲：20% / 48% / 32%
- 稳：30% / 30% / 40%
- 保：53.3% / 40% / 剩余

对应代码：

- [VolunteerIntervalService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/volunteer/VolunteerIntervalService.java#L111)

## 6. 专家打分结构

### 6.1 总体结构

rank 当前采用“院校分 + 专业分”的双层打分结构。

关键字段：

- `college_score_old`
- `college_score_new`
- `major_score`
- `major_score_new`
- `major_score_final`
- `volunteer_score`
- `score_final`

总体原则：

- 先算院校分
- 再算专业分
- 再通过调和平均形成最终志愿得分
- 强调“不能有短板”

### 6.2 院校侧提权和降权

当前院校分会被以下因素影响：

- 正向院校、负向院校
- 正向城市、负向城市
- 正向省份、负向省份
- 院校层次标签
- 院校类型标签
- 院校性质标签
- 保研、硕博点等标签
- 无任何院校意向时的统一减分

说明：

- 这部分是典型的专家推荐层逻辑
- 更适合后续作为候选池之上的推荐覆盖层复用

对应代码：

- [recommendation.py](/Users/baiyang/git/zhiyuan/gaokao-volunteer-rank-service/services/recommendation.py#L512)

### 6.3 专业侧提权和降权

当前专业分会被以下因素影响：

- 正向专业、负向专业
- 正向专业类、负向专业类
- 专业标签偏好
- 学科评估
- 特色专业
- 硕博点
- 学费标签
- 无任何专业意向时的统一减分

对应代码：

- [recommendation.py](/Users/baiyang/git/zhiyuan/gaokao-volunteer-rank-service/services/recommendation.py#L704)

## 7. 两种志愿模式的差异

### 7.1 专业+大学模式

当前 `VolunteerDataTransformService` 在专业+大学模式下的处理方式：

- 一个 `VolunteerSchoolGroup` 代表一个学校容器
- `majorList` 中的每个专业都是独立的实际可填报项
- 专业录取率取外层 `SchoolDetail` 的录取率
- school 负责院校公共属性，major 负责专业级排序和展示

对应代码：

- [VolunteerDataTransformService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/volunteer/VolunteerDataTransformService.java#L78)

rank 侧表现为：

- school 提供院校基座分
- 每个专业有独立的 `score_final`
- 页面最终更接近“同一学校下挂多个专业”

### 7.2 院校专业组模式

当前院校专业组模式下：

- 一个 `VolunteerSchoolGroup` 代表一个专业组填报单元
- `majorList` 表示组内专业
- 专业录取率来自 `MajorVO`
- 实际填报单元是专业组，不是单个专业

对应代码：

- [VolunteerDataTransformService.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/volunteer/VolunteerDataTransformService.java#L88)

rank 侧表现为：

- 先算专业组整体 `volunteer_score`
- 再保留组内专业的专业分和排序信息
- 冲稳保分层以专业组为单位，不以组内专业为单位

## 8. 专业组内部选择规则

当前 backend 在专业组模式下对组内专业列表有一层截断和保底逻辑。

规则如下：

1. 若组内专业数小于等于目标专业数，不处理。
2. 若组内专业数大于目标专业数，先取排序后的前 `targetMajorCount` 个专业。
3. 截取后要保证至少存在一个专业，其录取率不低于专业组整体录取率。
4. 若不满足，则从后续专业中寻找符合条件的专业，替换掉当前截取结果中的最后一个。

这条规则的含义是：

- 组内不能全部是偏冲专业
- 至少保留一个更贴近专业组整体录取概率的保底专业

对应代码：

- [VolunteerSorterAndMerger.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerSorterAndMerger.java#L329)

## 9. 组内专业数语义

当前 `majorGroup` 模式下，`requiredMajorCount` 只保留老版本语义：

- 它表示“每个已选专业组最多展示/保留多少个主选专业”
- 若组内天然专业数少于这个值，属于正常现象
- 这类情况不会触发 `review` 风险、`planAdjustment` 建议，也不会作为初始方案优劣比较条件

说明：

- `majorGroup` 模式的主计数口径始终是“专业组数量”
- 组内专业数不足不代表方案错误，只代表该专业组上游可选专业本来就少
- 当前仍保留组内安全垫约束：若可选专业里存在 `admissionRatio > schoolEnrollRatio` 的专业，主选专业里应尽量保留至少 1 个

## 10. 专家优选组合当前的标记方式

当前“专家优选组合”并不是 rank 直接返回的固定标签，而是 backend 返回层二次计算得到。

规则：

1. 在每个冲稳保区间内，按 `volunteer_score` 降序重新排名。
2. 在该区间目标水位线以内的志愿，标记为 `is_preferred = true`。

这意味着：

- “专家优选组合”是区间内的优先推荐集合
- 它依赖区间目标数，也依赖区间内的推荐分排序
- 该标记天然适合作为专家推荐覆盖层的一部分

对应代码：

- [VolunteerResponseBuilder.java](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/VolunteerResponseBuilder.java#L128)

## 11. 当前结构性问题

从当前实现看，至少有三层语义尚未拆开：

1. 基础候选空间
2. 专家推荐系数与专家优选组合
3. 工作台上的临时筛选、排序和标签状态

当前问题主要在于：

- 用户软意向会直接进入候选过滤层
- 候选池、推荐层、前端筛选状态之间缺少清晰边界
- 用户表达“想去哪里”“不想去哪里”“想看哪些标签”时，系统容易把“推荐变化”误实现成“候选成员变化”

## 12. 后续改造的设计启示

基于现状实现，后续建议明确拆分为三层：

### 12.1 基础候选池

只受硬约束影响，例如：

- 分数和位次
- 省份与批次
- 志愿模式
- 选科要求
- 身体限制
- 专项计划
- 学费等硬约束

### 12.2 专家推荐覆盖层

在既有候选池上重算：

- `college_score_new`
- `major_score_new`
- `volunteer_score`
- `is_preferred`
- 推荐理由标签

### 12.3 工作台筛选状态层

只影响当前页面展示和用户操作上下文，例如：

- 当前区间 tab
- 标签筛选条件
- 自定义排序字段
- 升降序

不应直接回写候选池基础成员。
