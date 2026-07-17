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
- `skills/career_path_chat/SKILL.md`

它们负责：

- 给模型解释每层的语义边界
- 明确什么问题属于当前 skill
- 明确什么问题不属于当前 skill
- 指导优先调用哪类高层工具

skill 不直接执行状态，也不应该替代 tool 的安全边界。

说明：

- `skills/career_path_chat/SKILL.md` 是 `Explore + career` 的语义说明层。
- 4.0 direct 职业路径探索运行时走 `explore_topic(topic_type="career")`。
- 用户明确表达职业方向报考要求时，运行时走 `preview_intent_change` 生成统一待确认预览，再等用户采纳后由确认链路生效。

### 3.3 Tool 层

#### Explore

4.0 direct 当前高层 Explore 入口：

- `app/zhiyuan_agent/tools.py::explore_topic`
- `app/zhiyuan_agent/tools.py::compare_entities`
- `app/zhiyuan_agent/tools.py::answer_policy`
- `app/zhiyuan_agent/tools.py::query_plan`
- `app/zhiyuan_agent/tools.py::review_plan`

#### Intent

4.0 direct 当前报考要求入口：

- `app/zhiyuan_agent/tools.py::preview_intent_change`
- `app/zhiyuan_agent/tools.py::confirm_pending`

底层仍保留：

- `app/tools/intent_state_tool.py`：执行确认后的报考要求应用与状态同步。
- `app/tools/intent_response_tool.py`：结构化结果解析与渲染。
- `app/tools/intent_relation_tool.py`：报考要求与当前方案关系分析。

其中：

- 主 agent 不再暴露 `preview_current_*` 或 `analyze_current_*` wrapper。
- 用户明确表达要/不要/只看时，由 `preview_intent_change` 生成待确认预览。
- 用户采纳后通过 `confirm_pending` 执行，底层再调用 `apply_selected_intents`。

#### Plan

4.0 direct 当前方案入口：

- `app/zhiyuan_agent/tools.py::query_plan`
- `app/zhiyuan_agent/tools.py::review_plan`
- `app/zhiyuan_agent/tools.py::preview_plan_action`
- `app/zhiyuan_agent/tools.py::confirm_pending`

其中：

- 查询、审查和方案调整预览都由 4.0 direct 工具直接承接。
- 方案调整只生成待确认预览，不直接修改当前方案。
- 用户采纳后由 `confirm_pending` 执行结构化 `action_family + atomic_actions` payload。

## 4. 当前结构状态

当前普通会话已收敛到 `ZhiyuanAgent` direct 链路：

- System prompt 与主编排规则集中在 `app/zhiyuan_agent/prompt.py`。
- 主 agent 可见工具为 `read_state`、`answer_policy`、`compare_entities`、`explore_topic`、`preview_intent_change`、`preview_plan_action`、`query_plan`、`review_plan`、`confirm_pending`。
- 旧 `ChatAgent`、旧 `intent_preview_tool.py` wrapper、旧 `planning_workflow_tool.py`、旧 `plan_execution_tool.py`、旧 `plan_query_tool.py` 均不再作为运行时入口。
- Skill 文档只保留语义边界说明，不再作为 4.0 direct 主链路的提示词来源。

## 5. 当前剩余风险

当前剩余风险集中在模型语义判断和结构化 payload 质量：

- 口语化、指代性、多诉求混合表达仍需要通过 prompt/schema 和真实回归持续校准。
- `intent_state_tool` 仍是确认后的底层应用能力，需要继续验证与 4.0 pending/confirm 协议一致。
- `explore_followup_tool` 仍服务前端 actionType 兼容，只允许从 active pending 读取来源；`plan_analyze` 分支只委托 4.0 `query_plan` 做只读承接，不得回到旧 plan chain。
- 历史文档和旧 changelog 中仍可能出现 3.x 工具名，只作为历史记录，不应作为当前实现入口。

## 6. 建议的下一步优化方向

### 6.1 继续补 prompt / schema / 回归

下一步重点仍是提高模型在 4.0 高层工具之间的选择稳定性：

- Explore 题稳定走 `explore_topic` / `compare_entities` / `answer_policy`。
- Intent 题稳定走 `preview_intent_change`。
- Plan 查询、审查、调整稳定走 `query_plan` / `review_plan` / `preview_plan_action`。

这类工作应落在 `prompt.py`、工具 schema、结构化 payload 校验和真实对话回归里，不重新引入 service 层中文字符串分流。

### 6.2 继续清理旧说明和资产

- 当前质量门禁和 hard-cut audit 已覆盖主链路旧入口防回退。
- 后续继续清理非 gate 的历史说明、旧样例和不再执行的兼容分支。
- 清理时优先删除不可达旧代码，不保留需要长期维护的并行实现。
