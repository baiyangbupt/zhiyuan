# sessionDetailV2 方案导出设计

## 目标

恢复 `sessionDetailV2` 的“方案导出”能力，但语义切换到新工作台：

- 只导出当前 `orderedPlanState`
- 不重新走老版推荐链路
- 不导出候选、草稿、老版“候补志愿”
- Excel 模板、字段结构、文件名规则尽量保持老版一致

## 数据来源

导出链路的输入分为三层：

1. `CreateSessionReq userScoreDetail`
用于文件名、顶部省份/分数/选科信息

2. `PlanningStateDTO.orderedPlanState`
用于确定当前方案顺序与导出范围

3. `PlanningStateDTO.candidatePoolState.items`
用于回填老版 Excel 所需的字段：
- `schoolUnitCode`
- `schoolLevel`
- `schoolCategory`
- `schoolNature`
- `schoolRank`
- `planNum`
- `duration`
- `mustSubjects`
- `majorHistoryScores`

## 模式判定

通过 `candidatePoolState.volunteerModel` 判断：

- `major`: 专业+大学模式
- `majorGroup`: 院校专业组模式

## 映射策略

### 专业+大学模式

- 以当前 `orderedPlanState.items` 为顺序来源
- 按学校聚合为 Excel 的一个学校单元
- 同校多专业在 Excel 中纵向展开

### 院校专业组模式

- 优先使用 `orderedPlanState.units`
- 一个 `OrderedUnitDTO` 对应 Excel 的一个导出单元
- `unit.majorItems` 作为组内专业展开顺序
- 每个专业再通过 `volunteerId -> CandidateItemDTO` 回填计划数、学费、学制、选科、历史数据

## 代码落点

- controller: `PlanningStateController#exportOrderedPlan`
- service: `PlanningStateService#exportOrderedPlan`
- builder: `PlanningExcelExportBuilder`
- excel generator: 继续复用 `ExcelUtil.generateVolunteerExcel`

## 输出约定

- 文件名：`省份_分数_选科_yyyyMMdd.xlsx`
- sheet 结构保持老版三层表头
- 专业组模式继续保留“专业录取概率”列
- 第一阶段不新增推荐系数、专业热度、就业表现等新列

## 测试重点

- 专业+大学模式：按学校聚合、顺序与 `orderedPlanState` 一致
- 专业组模式：按 `OrderedUnitDTO` 聚合、组内专业顺序正确
- 院校代码来源于 `CandidateItemDTO.schoolUnitCode`
- 空方案时直接报错，不生成空 Excel
