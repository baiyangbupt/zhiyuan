# 规划状态统一设计概览

## 定位

本文档只保留最短概览，完整方案见：

- [planning_state_full_design.md](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/planning_state_full_design.md)
- [planning_agentize_design.md](/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/planning_agentize_design.md)

## 目标

把现有“自动生成方案 + 意向调权”的模式升级为“候选池 + 草稿 + 排序 + 审查 + 补偿”的人机协同模式。

## 核心状态

统一状态以 `planningState` 为中心，包含：

- `profileState`
- `constraintState`
- `candidatePoolState`
- `draftPlanState`
- `orderedPlanState`
- `reviewState`
- `pendingActions`
- `operationLog`

## 关键变化

- 将优势学科、未来发展、兴趣性格、家庭情况统一纳入画像体系
- 将用户手动选取和排序操作沉淀为可追踪状态
- 将风险管理和数量校验纳入审查与补偿链路
- 将 agent 从“黑盒出方案”升级为“围绕规划状态编排动作”

## 当前落地进度

backend 已完成：

- `planningState` 持久化骨架
- 画像更新
- 派生偏好
- 候选池
- 草稿
- 排序

下一步重点：

- `reviewState`
- 数量校验
- 风险规则配置化
- 自动补偿
