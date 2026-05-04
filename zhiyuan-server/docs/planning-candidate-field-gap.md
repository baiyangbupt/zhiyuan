# Planning Candidate Field Gap

## 1. 背景

当前 `planning candidate-pool` 已可支撑：

- 候选查询
- 草稿选取
- 排序生成
- 审查

但前端 `sessionDetailV2` 若要真正复用旧版志愿表展示颗粒度，还缺少一批结构化字段。

当前 DTO：

- [`CandidateItemDTO.java`](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/model/dto/planning/CandidateItemDTO.java)

## 2. 当前 DTO 已有字段

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

这些字段已能直接支撑 `sessionDetailV2` 候选区的院校头部与专业行展示。

## 3. 当前剩余缺口

### 3.1 结构层缺口

当前最大缺口已经不是字段，而是返回结构：

- 仍然只返回 flat `CandidateItemDTO`
- 前端仍需自行按 `planSchoolDataId/schoolId` 聚合院校
- 还没有 group 级 `school/group -> majors[]` 查询结果

### 3.2 深层展示缺口

如果后续要完整回迁旧版表格式展示，还可以继续补：

- 更明确的 `strongMajors`
- group 级聚合后的院校摘要字段
- 专业表格专用的结构化视图 DTO

### 3.3 结构层缺口
建议后续增加 group 结构，避免前端继续做聚合。

## 4. 当前 queryCandidatePool 的排序支持边界

实现位置：

- [`PlanningStateService.java:200`](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java:200)
- [`PlanningStateService.java:645`](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/PlanningStateService.java:645)

当前原生支持字段：

- `finalScore`
- `admissionRatio`
- `rankInTier`
- `tuitionPerYear`
- `hotIndex`
- `salaryAvg`
- `schoolRank`

本轮已经把候选区需要的核心排序字段补到 comparator，可直接被前端透出使用。

## 5. 推荐落地顺序

### Phase 1: 已完成

扩展 `CandidateItemDTO`，补齐院校头部与专业行展示所需字段，并把 `hotIndex/salaryAvg/schoolRank` 等排序字段显式化。

### Phase 2

增加 group 级查询结果，减少前端聚合逻辑。

### Phase 3

如需完整回迁旧版表格，再追加专用视图 DTO 或 group 级结果里的专业表格字段。

## 6. 结论

如果目标只是“候选可看可选且信息基本齐全”，当前 DTO 已经够用。  
如果目标是“无损迁移旧版志愿展示结构”，后续重点应该转向 group 级结果，而不是继续堆 flat item 字段。
