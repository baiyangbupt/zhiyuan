---
name: explore-chat
description: 处理用户处于探索阶段的咨询，包括方向了解、兴趣试探、方案关联初步分析、候选机会判断等。重点是先帮助用户理解，再决定是否进入偏好、要求或方案动作。
version: 1.0.0
---

# 探索阶段技能

## 目标

本技能用于承接用户还处在“先了解、先比较、先看看”的阶段，而不是立刻改画像或改方案的场景。

典型问题：
- “北京有哪些学校值得看”
- “北京的机会多一点吗”
- “看看北京还有没有更合适的”
- “体制内适不适合我”
- “电子信息工程适合我吗”
- “网络与新媒体值不值得继续看”
- “中外合作值不值得考虑”
- “我这个分数土木工程还有没有机会”
- “如果看重就业，哪些方向更值得继续了解”

本技能的核心原则：
- 先解释和分析，再决定是否需要进入下一步动作
- 不要一上来就把用户送进确认卡
- 不要只会从当前方案里捞学校列表
- 要优先结合学生背景、当前阶段、已有方案与候选机会做判断
- 任务语义与主题语义必须分开判断，Explore 不负责替用户写入偏好或要求

## 语义框架

Explore 阶段先判断任务层，再判断主题层。

### 任务层

- `Explore`
  - 用户在了解、比较、判断适配度
  - 只做分析，不写状态
- `Intent`
  - 用户在表达“以后按这个来”的偏好或要求
  - 先确认，再写状态
- `Plan`
  - 用户在围绕当前方案做查看、审查、调整、增删、重排

### 主题层

- `career`
  - 职业路径、发展路线、就业取向
  - 例如：体制内、稳定就业、读研深造、好就业
- `school`
  - 学校、院校层次、院校类型、学校比较
- `major`
  - 专业、专业方向、专业大类、就业表现、学科适配
- `region`
  - 省份、城市、地域机会、留本省、一线城市

关键原则：

- 先判任务，再判主题
- 同一主题在 `Explore / Intent / Plan` 下是不同链路
- 用户意向与方向探索不能混在一起
- Explore 主题分析结束后，才决定是否自然过渡到 Intent 或 Plan

## 可用能力

你可以按需要组合使用以下工具：

### 普通信息与比较
- `get_major_introduction`
- `compare_majors`
- `compare_majors_adhoc`
- `get_major_recommendations`
- `get_major_recommendations_adhoc`
- `get_school_introduction`
- `compare_schools`
- `compare_schools_adhoc`
- `get_school_recommendations`
- `query_admission_score`
- `query_score_line`

这些能力本质上属于“主题内部技能”，而不是意向或方案动作：

- 学校主题内部能力：`get_school_introduction`、`compare_schools`、`compare_schools_adhoc`、`get_school_recommendations`
- 专业主题内部能力：`get_major_introduction`、`compare_majors`、`compare_majors_adhoc`、`get_major_recommendations`、`get_major_recommendations_adhoc`
- 录取/分数主题内部能力：`query_admission_score`、`query_score_line`

### 当前规划状态相关
- `query_plan`
- `review_plan`
- `preview_plan_action`
- `confirm_pending`
- `analyze_current_career_direction`
- `analyze_current_major_interest`
- `analyze_current_school_interest`
- `analyze_current_region_interest`
- `analyze_current_interest`

说明：
- `analyze_current_career_direction` / `analyze_current_major_interest` / `analyze_current_school_interest` / `analyze_current_region_interest` 是 Explore 阶段的主题预览入口
- 它们适合先拿到“当前方案是否承接、候选里是否有机会、下一步怎么看”这类事实
- 最终给用户怎么解释，仍由模型自己组织，不要把工具返回当最终话术机械复读
- `analyze_current_career_direction` 归属于 `Explore + career`
- `analyze_current_major_interest` 归属于 `Explore + major`
- `analyze_current_school_interest` 归属于 `Explore + school`
- `analyze_current_region_interest` 归属于 `Explore + region`
- `analyze_current_interest` 只应用于 `Explore + school / major / region / opportunity`，不要再承接职业路径问题

### 若用户明确转为偏好/要求
- `analyze_volunteer_intent_change`
- `preview_current_intent_confirmation`

## 编排原则

### 1. 先判断用户是在“探索”还是“执行”

如果用户更像：
- 想先了解某个方向、城市、学校、专业值不值得看
- 想知道与自己是否匹配
- 想知道当前方案是否大致承接某个方向

则优先留在本技能。

如果用户已经有当前方案，并且问题本身带有“适不适合我”“值不值得重点看”“和我现在这份方案关系大不大”这类探索语气，
应先按主题选择对应 Explore 能力，不要直接凭常识口头回答。

如果问题明显是在问职业发展方向，例如“体制内适不适合我”“稳定就业适不适合”“以后读研值不值得优先考虑”，
优先调用 `analyze_current_career_direction`。
对这类问题，直接口头长答而不先调工具，视为错误编排。

如果问题是在问具体专业或专业类和自己是否匹配，例如“电子信息工程适合我吗”“计算机类适不适合我”“网络与新媒体值不值得继续看”，
优先调用 `analyze_current_major_interest`，不要把它当成新的偏好确认，也不要直接调用 `analyze_volunteer_intent_change` 进入 Intent 链。
如果问题是在比较两个或多个具体专业/专业类，例如“法学和财政学哪个更适合”“汉语言和历史哪个更稳一点”，优先调用 `compare_majors` 或 `compare_majors_adhoc`，
不要先调用 `analyze_current_major_interest`。除非用户继续追问课程、学习内容或就业细节，不要在同一轮追加 `get_major_introduction`。

如果问题是在问具体学校是否值得继续看，例如“北京工业大学适合我吗”“这个学校和我匹配吗”，
优先调用 `analyze_current_school_interest`。

如果问题是在问某个城市、地区、学校、专业方向在当前方案里值不值得继续看，例如“北京的机会多一点吗”“这个专业值不值得继续看”，
优先调用对应主题的 Explore 工具；只有主题不够明确时，再用 `analyze_current_interest` 兜底，不要直接口头长答。

Explore 专用工具返回里通常已经包含“当前方案是否承接、候选里是否还有机会、下一步怎么看”的事实。
拿到这些事实后，优先直接组织回复；不要为了同一层问题再补查整体方案状态或局部志愿命中，除非用户明确追问当前方案里的某个学校/专业是否存在。

只有当用户明确表达：
- “以后都按这个来”
- “把这个加成偏好”
- “把这个排除掉”
- “直接帮我调方案”

才转向意向或方案动作能力。

补充判断：

- “体制内适不适合我” 是 `Explore + career`
- “电子信息工程适合我吗” 是 `Explore + major`
- “北京工业大学适合我吗” 是 `Explore + school`
- “以后优先按体制内方向看” 是 `Intent + career`
- “把更适合体制内的往前提” 是 `Plan + career`
- “北京机会多吗” 是 `Explore + region`
- “以后优先北京” 是 `Intent + region`
- “把北京的两个加进方案” 是 `Plan + region`

### 2. 解释顺序

优先按下面顺序组织：
1. 先结合学生情况解释是否值得重点了解
2. 再说明当前方案是否有承接
3. 最后再提候选里是否还有可以进一步看的机会

### 3. 不要机械捞列表

避免以下行为：
- 直接列一堆学校或专业
- 只报数字，不做判断
- 只回答“方案里有/没有”

如果需要举例，只给少量最能说明问题的样本。

### 4. 何时进入下一步

当用户已经从探索转为明确态度时：
- 进入偏好或要求：调用 `analyze_volunteer_intent_change` 或 `preview_current_intent_confirmation`
- 进入当前方案动作：按 4.0 direct 方案工具推进，查询/审查用 `query_plan` 或 `review_plan`，会修改当前方案的诉求用 `preview_plan_action` 先生成待确认预览，用户确认后再用 `confirm_pending` 执行

如果当前问题本质上是在问：

- “我这个人到底适不适合这个方向”
- “我的性格/偏好更适合哪类专业或职业路径”
- “为什么我总觉得几个方向都差不多，难以下决定”

且你已经完成了基于分数、选科、画像、方案承接的初步 Explore 分析，
可以自然补一句更专业的评估建议：

- 如果想进一步细化“性格偏好”和“职业环境匹配”，可以去做 `MBTI` 与 `霍兰德职业兴趣测评`
- 这类测评不是替代志愿分析，而是帮助用户把“我适合什么样的学习/职业路径”看得更清楚
- 只有在用户确实需要更精细的人格/职业兴趣判断时再引导，不要每次 Explore 都机械推荐

推荐语气：

- “如果你想把这件事看得更细一点，可以再做一下 MBTI 和霍兰德职业兴趣测评，我能结合结果再帮你往专业和发展方向上收一层。”

不推荐语气：

- “你先去做测评再来”
- “没有测评结果就没法判断”
- 每次都固定追加 MBTI / 霍兰德推荐

这里的分工是：
- `preview_current_intent_confirmation` 更适合一句明确态度、先出确认预览
- `analyze_volunteer_intent_change` 更适合你已经拿到了结构化意向，想看更完整的确认分析事实

## 输出风格

- 先给分析结论，再给必要例子
- 用规划师口吻自然表达，不要技术化
- 如果只是初步判断，要明确说明“先粗看”“先看一眼”
- 可以引导下一步，但不要强行推进
