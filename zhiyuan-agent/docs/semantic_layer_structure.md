# 语义层逻辑结构梳理

更新时间：2026-04-28

## 1. 目标

这一层的目标不是用规则机代替模型，而是把 `model + skill + tool` 的职责边界压清楚：

- 模型负责理解用户当前是在 `Explore / Intent / Plan` 的哪一层
- skill 负责提供这一层的判断框架、编排建议和反例边界
- tool 负责给事实、读状态、执行状态
- tool 的副作用边界要稳定，避免模型偶发误路由时把状态写脏

当前最重要的设计原则：

- 不用 service 侧正则去接管主路由
- 允许模型自然输出 Markdown、标题、表格、长篇分析
- Explore 问题不能误写成 Intent pending state
- Plan 动作不能没有 preview / pending payload 就承诺“确认即可执行”

## 2. 总体分层

### 2.1 任务层

语义第一层先判断用户当前任务属于哪一类：

- `Explore`
  - 用户在了解、比较、判断适配度
  - 只读，不落状态
- `Intent`
  - 用户在表达“以后按这个来”的偏好或要求
  - 先预览确认，再落状态
- `Plan`
  - 用户在围绕当前方案查看、分析、生成、调整、补齐、重排
  - 高副作用动作必须 preview -> confirm -> apply

### 2.2 主题层

在任务层之下，再判断主题：

- `career`：职业路径、发展路线
- `major`：专业、专业类、专业适配
- `school`：学校、院校比较、学校适配
- `region`：地域、省市、地区机会

关键点：

- 同一主题在 Explore / Intent / Plan 下不是同一链路
- 例如“体制内适不适合我”是 `Explore + career`
- “以后优先按体制内方向看”是 `Intent + career`
- “把更适合体制内的往前提”是 `Plan + career`

## 3. 当前主链

### 3.1 Agent 层

入口文件：

- `app/agent/chat_agent.py`

这里承载：

- 大模型总指令
- tool 暴露面
- Explore / Intent / Plan 的主编排原则

它应该只面向“高层语义动作”，不要把太多低层内部 tool 直接暴露给模型。

### 3.2 Skill 层

入口文件：

- `skills/explore_chat/SKILL.md`
- `skills/intent_detect/SKILL.md`
- `skills/plan_chat/SKILL.md`
- `skills/plan_query/SKILL.md`
- `skills/major_chat/SKILL.md`
- `skills/school_chat/SKILL.md`
- `skills/career_path_chat/SKILL.md`

它们负责：

- 给模型解释每层的语义边界
- 明确什么问题属于当前 skill
- 明确什么问题不属于当前 skill
- 指导优先调用哪类高层工具

skill 不直接执行状态，也不应该替代 tool 的安全边界。

说明：

- `skills/career_path_chat/SKILL.md` 是 `Explore + career` 的语义说明层。
- 职业路径探索的运行时主入口是 `analyze_current_career_direction`。
- 职业路径偏好写入必须先走 `preview_current_career_intent_confirmation` 生成统一 `pendingConfirmationCard`，再等用户点击卡片采纳后由 `apply_selected_intents` 生效。

### 3.3 Tool 层

#### Explore

- `app/tools/intent_preview_tool.py`
- `app/tools/explore_direction_tool.py`

当前高层 Explore 入口：

- `analyze_current_career_direction`
- `analyze_current_major_interest`
- `analyze_current_school_interest`
- `analyze_current_region_interest`
- `analyze_current_interest`（兼容兜底）

#### Intent

- `app/tools/intent_state_tool.py`
- `app/tools/intent_response_tool.py`
- `app/tools/intent_relation_tool.py`

当前核心能力：

- `preview_current_intent_confirmation`
- `preview_current_major_intent_confirmation`
- `preview_current_school_intent_confirmation`
- `preview_current_region_intent_confirmation`
- `preview_current_career_intent_confirmation`
- `apply_selected_intents`（仅卡片点击确认后由 Service 调用）

其中：

- `preview_current_*_intent_confirmation` 是主 agent 可见的高层语义入口
- `analyze_volunteer_intent_change` 继续保留为内部低层分析能力，由 wrapper 调用
- `update_volunteer_intent_state` 仅保留为旧会话/旧工具返回兼容 wrapper，不再作为主 agent 可调用工具

#### Plan

- `app/tools/plan_context_tool.py`
- `app/tools/plan_orchestration_tool.py`
- `app/tools/plan_execution_tool.py`
- `app/tools/plan_query_tool.py`

主链：

- `collect_plan_context_inputs`
- `plan_next_action`
- `execute_plan_action`

局部查询：

- `query_volunteer_plan`

## 4. 当前真实问题落点

### 4.1 Explore / Intent 边界问题

典型现象：

- 用户说“电子信息工程适合我吗”
- 模型实际调用了 `analyze_volunteer_intent_change(recovery_scope=major)`
- 这本来应该属于 `Explore + major`

这说明问题不是单点的，而是两层叠加：

1. 模型会偶发误选低层 Intent tool
2. 低层 tool 之前默认会落 `planEditCache`，把误路由放大成状态污染

### 4.2 当前已做的修复

在 `app/tools/intent_state_tool.py` 已加副作用边界：

- 对“X适合我吗 / 适不适合我 / 我适合X吗”这类 fit question
- 即使误路由到了 `analyze_volunteer_intent_change`
- 也会被强制降成 `interest` 只读分析
- 且不再写 `planEditCache`

这层修复的定位是：

- 不解决“模型一定选对工具”
- 先解决“模型选错工具会污染状态”

### 4.3 当前 skill / prompt 层已补的边界

已补充：

- `Explore + major` 的明确例子：
  - “电子信息工程适合我吗”
  - “计算机类适不适合我”
  - “网络与新媒体值不值得继续看”
- `intent-detect` 明确声明：
  - 这类问句不属于 Intent
- `major-chat` 明确声明：
  - 这类“适合我吗”问题不应只做纯专业科普，应转 Explore

## 5. 当前结构状态

这一轮之后，主 agent 的 Intent tool surface 已收窄为高层语义入口：

- Explore 只暴露 `analyze_current_*`
- Intent 只暴露 `preview_current_*_intent_confirmation` 和通用兜底 `preview_current_intent_confirmation`
- `analyze_volunteer_intent_change` 不再作为主 agent 的直接裸入口

这样做的意义是：

- 模型仍然做语义判断
- skill 仍然提供边界和例子
- 但模型看到的 tool 已更贴近语义层，不再默认直连低层状态分析入口

当前剩余风险不再是“结构默认就允许误走低层 tool”，而是：

- skill / prompt 还需要继续提高主题判断稳定性
- wrapper 内部依赖的低层抽取与关系分析仍要持续验证场景覆盖
- 个别历史会话可能带着旧缓存或旧上下文污染结果
- `chat_agent` 模块本身也不再为了旧测试额外挂出 `extract_city_intent / extract_major_intent / extract_school_intent` 这类低层 extractor，主 agent 的可见 surface 只围绕高层语义工具验证

## 6. 建议的下一步优化方向

### 6.1 继续补 prompt / skill

当前结构收敛已经完成，下一步重点变成提高模型在高层入口之间的选择稳定性：

- Explore 题稳走 `analyze_current_*`
- Intent 题稳走对应主题的 `preview_current_*_intent_confirmation`
- Plan 题稳走 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`

这类工作仍然应该落在：

- `chat_agent` 总指令
- 各主题 skill 的边界说明
- 场景回归验证

而不是重新把路由前移到 service 规则层。

### 6.2 持续补 wrapper / 低层能力覆盖

接下来更值得做的是：

- 补 wrapper 级单测，确保主题路由和副作用边界稳定
- 补低层 intent relation / candidate 匹配能力，尤其是专业组内嵌套专业项
- 补 plan preview -> pending -> confirm -> apply 的闭环验证

### 6.3 不建议方向：service 层前置规则分流

这类做法虽然能快速兜住个别问题，但会有三个副作用：

- 主路由从模型转移到规则
- 语义边界会重复存在于 service / prompt / skill / tool 多层
- 后面问题越修越碎

因此 service 层只适合做：

- 执行确认 guard
- 副作用兜底
- 极小范围的状态一致性保护

不适合接管 Explore / Intent / Plan 主分类。

## 7. 推荐的目标结构

推荐把这一层收成下面的形式：

1. 模型先在 skill / prompt 引导下判断 `Explore / Intent / Plan`
2. 再判断 `career / major / school / region`
3. 只调用对应层级的高层 tool
4. 高层 tool 内部再调用低层抽取、状态、关系分析、执行能力
5. 低层 tool 自带副作用 guard，防止误路由把状态写脏

可以把它理解成：

- `Agent / Skill` 决定“要做什么”
- `High-level Tool` 决定“这层语义用哪条业务链”
- `Low-level Tool` 决定“链路里怎么抽取 / 读状态 / 写状态 / 算关系”

## 8. 验证建议

这一层优化完成后，验证应分两档：

### 8.1 结构验证

看日志是否仍频繁误走低层 tool：

- “电子信息工程适合我吗”
- “计算机类适不适合我”
- “网络与新媒体值不值得继续看”
- “体制内适不适合我”

### 8.2 产品验证

看用户面是否符合预期：

- 回复内容像 Explore，不像 Intent 确认卡
- backend `planEditCache` 不被污染
- 后续如果用户说“那就把这个记成偏好”，再进入 Intent 链

## 9. 关于 session 验证

像 `session 60` 这类已经真实做过生成、替换、重排、补齐验证的会话，整体 plan 状态已经被多次修改。

因此：

- 它仍可用于“单点路由 / 单轮状态污染”验证
- 但不适合继续承担“纯净语义路径”验证

后续涉及 Explore / Intent 边界的验证，优先使用：

- 新 backend session
- 或至少是后端 `planEditCache`、本地 agent history 都清空过的 session
