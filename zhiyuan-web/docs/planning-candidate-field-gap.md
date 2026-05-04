# Planning Candidate Field Gap

## 1. 目的

本文件用于梳理：

- 旧版 [`Volunteer`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/pageComponents/sessionDetail/Volunteer/index.tsx) 展示真正依赖的字段
- 当前 `planning candidate` 返回的字段
- 前端可临时还原的内容
- 必须补到 backend / rank 才能无损迁移的字段

## 2. 当前两套数据来源

### 2.1 旧版志愿展示

旧版核心接口：

- [`getVolunteerRecommendListApi`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/service/apis/sessionDetail.ts)

旧版展示结构是：

- `冲 / 稳 / 保`
- 每个区间下是院校或院校专业组
- 每个院校下有 `majors[]`
- 专业表格里展示多年历史录取数据、计划数、录取率等

### 2.2 新版 planning 候选池

当前核心接口：

- [`queryPlanningCandidatePoolApi`](/Users/baiyang/git/zhiyuan/gaokao-volunteer-pc/src/service/apis/sessionDetail.ts)

后端 DTO：

- [`CandidateItemDTO.java`](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/model/dto/planning/CandidateItemDTO.java)

当前返回是“平铺专业项”，不是旧版那种完整院校结构。

## 3. 当前 planning candidate 已有字段

当前 planning candidate 原生字段：

- `volunteerId`
- `tier`
- `subTier`
- `schoolId`
- `schoolName`
- `provinceName`
- `cityName`
- `majorId`
- `majorName`
- `tuitionPerYear`
- `baseScore`
- `intentScore`
- `finalScore`
- `admissionRatio`
- `rankInTier`
- `mustSubjects`
- `reasonCodes`
- `riskFlags`
- `planSchoolDataId`
- `schoolBatch`
- `schoolLevel`
- `schoolNature`
- `schoolCategory`
- `schoolRank`
- `schoolEnrollRatio`
- `baoyanRatio`
- `upgradeRatio`
- `masterCount`
- `doctorCount`
- `preferred`
- `majorCode`
- `majorLevel`
- `planNum`
- `duration`
- `hotIndex`
- `salaryAvg`
- `schoolRankTags`
- `schoolBasicTags`
- `schoolPopupTags`
- `majorRankTags`
- `majorPlanTags`
- `schoolHistoryScores`
- `majorHistoryScores`

这些字段足以支撑：

- 候选池筛选
- 候选排序
- 草稿加入
- 基础院校/专业展示
- 推荐系数、录取率、学费、选科要求等轻量信息

## 4. 当前仍未完全对齐旧版的部分

当前已经补齐了院校头部与专业行展示的主体字段，但仍有两类缺口：

### 4.1 结构层缺口

- 当前仍是 flat item 返回
- 前端仍需自行按 `tier + planSchoolDataId/schoolId` 聚合
- 还没有真正的 group 级 `school -> majors[]` 返回结构

### 4.2 旧版深层展示缺口

旧版还有一些深层展示或解释信息未在 V2 中完全展开使用，例如：

- `school_name`
- `school_rank`
- `basicTagList`
- `rankTagList`
- `history_score_list`
- `enroll_ratio`
- `baoyan_ratio`
- `strong_major`
- `master_count`
- `doctor_count`
- `popTagList`

专业表格深层能力仍未完全迁移：

- `major_name`
- `majorUnitCode`
- `enroll_ratio`
- `level`
- `must_subject`
- `rankTagList`
- `planTagList`
- `history_score_list`

旧版整体结构依赖字段：

- `baseData.volunteerModel`
- `baseData.volunteerCount.majorCount`
- `baseData.three_target_count_map`
- `sprints / safes / protects`
- 每个院校下的 `majors[]`

也就是说，当前已经不再是“字段没有”，而是“V2 暂未把这些深层字段全部渲染成旧版表格样式”。

## 5. 当前前端剩余的临时还原

V2 当前仍有少量过渡逻辑：

- 用 `tier + planSchoolDataId/schoolId` 聚合成院校折叠结构
- 当后端未给显式 `hotIndex/salaryAvg` 时，仍可从 `riskFlags/reasonCodes` 做兜底解析

相比之前，这部分已经缩小到“聚合结构与兜底解析”，不再是大面积字段猜测。

## 6. 后端当前原生支持的 candidate 排序字段

后端实现：

- [`PlanningStateService.java:200`](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java:200)
- [`PlanningStateService.java:645`](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java:645)

当前 backend 已原生支持：

- `finalScore`
- `admissionRatio`
- `rankInTier`
- `tuitionPerYear`
- `hotIndex`
- `salaryAvg`
- `schoolRank`

前端当前可直接把这些字段作为真实排序能力暴露给用户。

## 7. 建议的补齐优先级

### Phase 1: 已完成

已补充到 planning candidate：

- `schoolRank`
- `basicTags`
- `rankTags`
- `popTags`
- `historyScores`
- `enrollRatio`
- `baoyanRatio`
- `masterCount`
- `doctorCount`
- `majorUnitCode`
- `level`
- `planTags`
- `rankTags`
- `historyScores`
- `duration`
- `hotIndex`
- `salaryAvg`

当前已经足够支撑 V2 候选卡片按旧版颗粒度做“院校头 + 专业行”展示。

### Phase 2: 继续做结构升级

建议 backend 后续直接返回 group 级结构，减少前端聚合。

### Phase 3: 再决定是否迁回旧版表格式内容

建议后端不再只返回 flat candidate item，而是支持：

- `tier`
- `school/group`
- `majors[]`

这样前端不需要继续用 `schoolName` 做脆弱聚合。

## 8. 结论

当前 V2 已经可以：

- 复用 planning 接口做基础候选展示与选择
- 用真实结构化字段组织候选列表
- 展示院校标签、院校排名、保研率、硕博点、专业代码、学制、计划数、历史分数等信息所需的数据底座
- 支持基于 `录取率 / 推荐系数 / 区间位次 / 院校排名 / 专业热度 / 就业表现 / 学费` 的真实排序

但如果目标是“无损迁移旧版整套折叠表格和 group 结构”，仍然需要 backend 继续补 group 级返回。  
当前阶段已经从“字段缺失”推进到“结构与展现形式待继续升级”。
