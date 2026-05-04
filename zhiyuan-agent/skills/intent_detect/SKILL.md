---
name: intent-detect
description: 处理用户对志愿方案的调整意向，包括增加/排除学校、专业、地域偏好，需要校验合法性后生成变更预览供用户确认；支持逐项勾选的局部采纳。若识别到方案查询意图则应转交给 plan-query skill。
---

# 意向调整技能

## 目标
本技能用于处理用户对**报考意向与偏好**的调整，包括：
- 增加偏好学校、专业、地域
- 排除不想要的学校、专业、地域
- 调整正面/负面意向

本技能只处理**意向层面的识别、抽取和确认**，不直接操作志愿表中的具体行。

不属于本技能的典型问法：
- “电子信息工程适合我吗”
- “网络与新媒体值不值得继续看”
- “北京的机会多一点吗”
- “体制内适不适合我”

这些都还是 Explore，不是 Intent。它们应转交给 `explore-chat` skill 或对应 Explore 工具，不要直接进入意向确认链。

采纳后的直接影响是：

- 更新推荐系数
- 更新专家优选组合
- 更新默认推荐顺序倾向

不会因为采纳意向而直接视为“当前方案已经变化”。

## 工具调用流程

下面是推荐编排，不是固定规则。你需要根据用户语义、上下文、是否存在副作用来决定实际工具组合。

### 1. 必要时先校验
- 如果涉及新增专业，先调用 `validate_major_subjects` 校验选科兼容性
- 如果涉及新增学校、专业或地域，可调用 `validate_plan_params` 校验在当前分数范围内是否可行
- 如果校验不通过，先解释原因并引导用户调整，不要直接落状态

### 2. 先拿分析数据，再决定怎么回复
- 优先调用 `analyze_volunteer_intent_change`
- 它只返回结构化分析数据，不直接替你生成最终用户文案
- 它不应用于“适不适合我 / 值不值得继续看 / 先看看”这类只读探索问题；这类问题应停留在 Explore
- 你需要基于这些数据，结合当前对话语境，自然地向用户解释：
  - 识别到了哪些偏好/要求
  - 当前方案和候选里有什么关联
  - 哪些是新增、哪些本来就已存在
  - 下一步是继续分析，还是等待用户确认生效

### 3. 生成确认分析，等待用户选择或确认
- 校验通过后，继续使用 `analyze_volunteer_intent_change`
- 将用户意图整理为对应的参数格式传入
- 由模型基于返回的结构化分析数据，自然生成确认说明或分析说明
- 如果用户只是刚表达一句明确态度，还不值得你手动组装完整结构，可优先调用 `preview_current_intent_confirmation`
- `preview_current_intent_confirmation` 属于面向 agent 的预览入口；底层仍是围绕 `analyze_volunteer_intent_change` 做确认分析

如果用户只是刚表达一个新的偏好/要求，还在“先看一下”“先分析一下”的阶段，
优先调用 `preview_current_intent_confirmation` 生成基于当前句子的确认预览，
不要直接口头记忆，也不要先自己总结成最终结论。

但如果用户句子本身是在问适配度，例如“电子信息工程适合我吗”“这个方向值不值得继续看”，
不要因为里面出现了专业名或方向词，就误进 `preview_current_intent_confirmation` 或 `analyze_volunteer_intent_change`。

### 4. 等待用户确认
用户有两种确认方式：

**方式A：通过前端已有交互勾选（推荐）**
- 用户在 `intentDetectSelectPopup / intentConfirmPopup` 卡片中勾选想要的项目，点击【采纳】
- 前端发送结构化确认消息，系统自动处理选中的子集
- 无需 Agent 参与，直接更新画像

**方式B：通过对话确认**
- 用户在对话中回复确认或拒绝
- 用户确认（如"确认"、"好的"、"可以"） → 调用 `update_volunteer_intent_state(action="confirm")`
- 用户拒绝（如"不要"、"取消"、"算了"） → 调用 `update_volunteer_intent_state(action="reject")`

## 可用工具

### validate_major_subjects
- **用途**：校验专业与学生选科的兼容性
- **参数**：`major_names`（三级专业名称列表）
- **使用场景**：用户要新增专业偏好时，先校验选科是否允许

### validate_plan_params
- **用途**：校验方案参数是否在学生分数范围内
- **参数**：`major_names`、`school_names`、`province_names`、`city_names`（均可选）
- **使用场景**：校验新增的学校/专业/地域在当前分数下是否可行

### analyze_volunteer_intent_change
- **用途**：只分析意向变化，返回结构化数据，不直接执行更新
- **参数**：
  - `major_intents`: `{"level1":[], "level2":[], "level3":[], "negative_level1":[], "negative_level2":[], "negative_level3":[]}`
  - `school_intents`: `{"colleges":[], "negative_colleges":[]}`
  - `city_intents`: `{"province":[], "city":[], "negative_province":[], "negative_city":[]}`
  - `career_intents`: `{"positive":[], "negative":[]}`
  - `edit_flag`（可选）: `add | delete | move | replace`
  - `analysis_stage`（可选）: `confirmed | interest`
  - `recovery_scope`（可选）: 当模型已判断是某一类意向，但暂未组装结构化参数时使用
  - `confirm_enabled`（可选）: 是否进入确认链路
  - `intent_mode`（可选）: `preference | constraint`
- **返回**：JSON 字符串，包含识别项、已有项、关联分析、阶段、偏好/要求模式等事实数据

### update_volunteer_intent_state
- **用途**：统一管理意向状态更新动作
- **参数**：
  - `action`: `confirm | reject | apply_selected`
  - `merged`（可选）: 已合并的意向结构，`apply_selected` 时使用
  - `intent_mode`（可选）: `preference | constraint`
- **返回**：JSON 字符串，包含是否生效、候选过滤信息、数量信息、消息码与兼容消息等

### preview_current_intent_confirmation
- **用途**：直接基于当前这句话生成确认预览
- **参数**：
  - `intent_mode`: `"preference"` 或 `"constraint"`
  - `recovery_scope`（可选）: 当你已明确这是某一类意向，但不想手动组装结构化参数时使用
- **使用场景**：用户说“更想去北京”“不去上海”“只看北京”“不要中外合作”这类明确表态，但还没正式确认采纳
- **说明**：这是便捷入口，适合对话层直接承接；不要把它理解成最终答复生成器
- **不要用于**： “适合我吗 / 值不值得继续看 / 我先了解下” 这类 Explore 问句

## 前提条件
- 用户已有志愿方案（已生成志愿方案）
- 如果用户尚未生成方案，引导其先完善信息并生成方案

## 输出风格
- 使用专业高考志愿规划师的口吻
- 校验不通过时给出具体原因和替代建议
- 预览时清晰展示哪些是新增、哪些已存在
- 确认/拒绝后给出明确的后续引导
- 不要机械复读工具原文；工具提供事实，最终答复由模型结合上下文组织
