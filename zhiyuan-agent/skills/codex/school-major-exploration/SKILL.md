---
name: school-major-exploration
description: Use when a user wants to compare schools, majors, locations, training paths, or trade-offs before asking for admission recommendations.
version: 1.0.0
---

# School and Major Exploration

## 适用条件

- 用户希望了解院校、专业、培养方向、城市或就业取舍。
- 用户已有明确或可解析的院校/专业名称，但还没有要求基于成绩生成候选。

## 不适用条件

- 需要历年录取事实、招生计划或选科资格判断时，转交 `admission-fact-analysis`。
- 用户要求按个人分数排序候选或构建志愿表时，转交后续 Skill。

## 前置状态

- Snapshot 中存在当前用户会话和 planning stage。
- 目标实体先通过 `entity.resolve` 唯一解析；不接受模型自行拼接 entity ID。
- 已知偏好只作为探索维度，不自动升级为硬约束。

## 允许能力

- `entity.resolve`
- `catalog.search_schools`、`catalog.get_school`
- `catalog.search_majors`、`catalog.get_major`
- 仅只读；禁止 profile、plan、recommendation 写操作。

## 标准步骤

1. 解析并确认用户指向的学校、校区、专业或专业类。
2. 查询最小必要的院校/专业资料，不为填充回答而遍历大量结果。
3. 从培养内容、学科特色、城市、费用和发展路径等维度进行对比。
4. 明确事实、解释和规划师经验的边界，询问用户最在意的维度。
5. 若用户转向“我能不能上/怎么填”，停止探索并交给录取事实或候选 Skill。

## Evidence 要求

- 学校和专业名称、层次、培养信息必须来自目录工具的标准实体和 Evidence。
- 搜索无结果返回 `not_found`，歧义返回 `needs_clarification`；不以相似名称替代。
- 任何时效性招生数字必须改用 `admission-fact-analysis` 查询。

## 单轮调用预算

- 最多 4 次读取调用，其中实体解析最多 2 次；同参数只调用一次。
- 优先批量搜索和单次详情查询，避免 N+1。

## 停止条件

- 实体仍有多个候选、用户偏好无法区分，或资料覆盖不足时先澄清。
- 不输出录取率、冲稳保标签或最终志愿顺序。

## 输出结构

- `responseType=fact` 时逐条绑定 `evidenceRefs`。
- 结构化比较使用 `artifactRefs`，包含实体 ID、比较维度和 limitations。
- 末尾给出一个明确的下一步问题，不代替用户做未经确认的价值判断。

## 降级策略

- 目录服务暂时不可用时返回 `recoverable.error`，保留已确认实体，不使用模型记忆补齐。
- 版本过期时刷新 Snapshot 后重查；禁止使用旧结果覆盖新状态。
