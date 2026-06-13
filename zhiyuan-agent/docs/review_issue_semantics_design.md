# Review Issue 语义设计

更新时间：2026-04-30

## 1. 背景

当前主线验证里，`review -> follow-up action -> confirm -> apply` 这条链已经能跑通，但在“先处理高收费 / 中外合作”这类 follow-up 上暴露出一个更底层的问题：

- backend 的 `reviewState.checks[]` 其实已经给了结构化问题对象
- agent 侧在对话里主要保留了“问题摘要 + 典型涉及样例”
- 模型后续承接“先处理这个问题”时，容易把“样例”当成“作用范围”
- 执行层目前又只能靠少量关键词反推 broad issue

所以现在的问题不是“高收费”这个 case 本身，而是：

**系统里缺少稳定的一等概念：`review issue`。**

没有这个概念时，模型看到的是几条样例，执行层看到的是几段自然语言，最后只能靠 prompt 和局部兜底拼起来。这种结构遇到别的审查问题时还会继续失真。

## 2. 当前问题定义

### 2.1 backend 已经有结构化问题对象

来源：

- backend `PlanningStateService`
- DTO: `ReviewCheckDTO`

当前字段包括：

- `code`
- `level`
- `passed`
- `summary`
- `detail`
- `suggestedAction`
- `affectedUnitIds`
- `affectedVolunteerIds`
- `suggestedCompensations`

也就是说，backend 语义上表达的是：

- 这是哪个问题
- 问题级别是什么
- 影响的是哪些组 / 哪些志愿
- 推荐怎么处理

这本身已经不是“文本提醒”，而是“结构化问题”。

### 2.2 agent 侧把问题压成了“摘要 + 样例”

当前 agent 侧存在两套产物：

1. 面向用户解释的样例
   - `planning_workflow_tool._collect_issue_hit_plan_examples`
   - 产出 `issue_hit_plan_examples / review_issue_hit_plan_examples`
2. 新增但还没有贯通的结构化问题范围
   - `app/tools/review_issue_registry.py`
   - `build_review_issue_scopes(...)`

第一套东西适合解释，不适合做动作规划；第二套东西才接近真正需要的对象，但还没有进入主链。

### 2.3 当前主链在哪一步失真

失真主要发生在三处：

1. `plan_context_tool`
   - 当前 `PlanContextInputs` 里没有 `review_issues`
   - 模型拿到的是风险数、提醒数、偏好摘要、relation lines
   - 没拿到“当前有哪些可操作的审查问题”

2. `review_plan / analyze_adjustment` 的 follow-up
   - 当前会把“典型涉及项”写进摘要或 facts
   - 这些本来只是示例
   - 但模型下一轮容易把它们误当成完整操作范围

3. `plan_execution_tool`
   - 现在 broad issue 的 scope 扩展只靠 `_review_issue_code_from_goal(...)`
   - 目前只识别 `high_tuition / cooperative_program`
   - 这本质上还是关键词补丁，不是语义层定义

### 2.4 真实联调里暴露出的症状

以 `session 69` 为例：

- `帮我审查一下当前方案`
- `先处理高收费`

模型实际规划成了：

- `action_family = replace_units`
- `volunteer_ids = [两个样例]`

这说明当前系统默认理解的是：

- “高收费” = 审查回复里看到的两条样例

而不是：

- “高收费” = 当前 review 里 `code=high_tuition` 的问题对象，其作用范围是全部 `affectedVolunteerIds`

## 3. 设计目标

本设计的目标不是把主链改成规则机，而是把 `model + skill + tool` 之间的语义边界压清楚。

目标：

1. `review issue` 成为一等结构，而不是摘要副产物
2. 模型规划动作时针对“问题对象”，不是针对“问题样例”
3. 样例只用于解释，不再隐式代表作用范围
4. 执行层不再靠个别关键词反推 broad issue
5. 新增 review code 时，默认能落到稳定语义路径，而不是继续加 prompt 例子

非目标：

1. 不把 Explore / Intent / Plan 主路由前移到 service 正则
2. 不用硬编码短语覆盖所有问法
3. 不把模型回复写死成固定模板

## 4. 核心概念

### 4.1 Review Issue

建议把当前审查问题标准化为一个明确对象：

```json
{
  "code": "high_tuition",
  "label": "高收费",
  "level": "warn",
  "summary": "当前方案包含高收费专业",
  "detail": "检测到学费超过 2w/学年的专业...",
  "scope_kind": "item_removal",
  "default_action_family": "remove_units",
  "supported_action_families": ["remove_units", "replace_units"],
  "affected_unit_count": 13,
  "affected_volunteer_count": 44,
  "affected_unit_ids": ["..."],
  "affected_volunteer_ids": ["..."],
  "sample_items": ["北京城市学院(04)-护理学@14", "武昌理工学院(02)-智能科学与技术(华为精英班)@24"],
  "suggested_action": "建议结合家庭经济状况确认是否保留相关志愿。",
  "source": "reviewState.checks",
  "scope_fingerprint": "..."
}
```

其中最关键的是：

- `scope_kind`
- `default_action_family`
- `affected_*`
- `sample_items`

这里必须明确：

- `affected_*` 才是实际作用范围
- `sample_items` 只是解释样例

### 4.2 Review Sample

样例单独定义为：

- 仅用于用户解释
- 仅用于帮助模型在回答里举例
- 不应单独承担动作 scope

只有用户显式说：

- “就处理刚才那两个”
- “把北京城市学院那个去掉”
- “先动第14个”

这类明确 narrowing，样例或显示引用才可以变成局部 scope。

### 4.3 Review Issue Scope Kind

当前 backend 的 review code 可以先抽成三类：

1. `item_removal`
   - 问题落在受影响条目本身
   - 默认处理路径是移除、替换、缩小范围

2. `structural`
   - 受影响条目只是问题上下文
   - 不能直接把这些条目删掉当作“已处理问题”
   - 默认处理路径是分析调整、补齐、重排、局部补稳

3. `informational`
   - 问题本身不对应直接 mutation
   - 只提示，不直接删改

## 5. 当前 review code 的语义分类

基于 backend 当前 `PlanningStateService` 的 review code，建议先统一成下面这张表：

| code | 含义 | scope_kind | broad follow-up 默认路径 |
| --- | --- | --- | --- |
| `high_tuition` | 高收费 | `item_removal` | `remove_units` |
| `cooperative_program` | 中外合作办学 | `item_removal` | `remove_units` |
| `admission_limit` | 限报条件 | `item_removal` | `remove_units` |
| `special_enrollment` | 特殊类型招生 | `item_removal` | `remove_units` |
| `probability_inversion` | 概率倒挂 | `structural` | `analyze_adjustment` |
| `probability_gap` | 梯度断层 | `structural` | `analyze_adjustment` |
| `ratio_distribution` | 冲稳保配比问题 | `structural` | `analyze_adjustment` |
| `safety_guard` | 本省保底不足 | `structural` | `preview_fix_proposal` |
| `count_validation` | 数量缺口 | `structural` | `preview_fix_proposal` |
| `edge_score` | 边缘分风险 | `structural` | `analyze_adjustment` |
| `major_group_safety_intent_alignment` | 非意向托底 | `structural` | `analyze_adjustment` |
| `group_inner_safety_guard` | 组内安全垫不足 | `structural` | `analyze_adjustment` |
| `plan_update_notice` | 招生计划更新提示 | `informational` | 解释即可 |
| `adjustment_notice` | 调剂风险提示 | `informational` | 解释即可 |

这张表的意义是：

- 以后新增 case，先归类，再决定处理路径
- 不再从“高收费 / 中外合作”这种例子倒推系统行为

## 6. 分层职责

### 6.1 backend

backend 继续作为问题发现和 `affected ids` 的 source of truth。

agent 不应该重新发明一套“哪些条目算高收费 / 哪些算中外合作”的判定规则。agent 只做两件事：

1. 读取 backend review 结果
2. 解释这些结果在当前对话动作里的语义

### 6.2 `review_issue_registry.py`

这个文件应该成为 agent 侧的“问题语义注册表”，职责是：

- code -> label
- code -> `scope_kind`
- code -> `default_action_family`
- code -> `supported_action_families`
- code / alias / summary 与当前 issue 的匹配辅助

它不应该只是“给两个例子做 alias 匹配”的地方，而应该承载：

- 问题分类
- 默认动作能力
- broad follow-up 的语义入口

### 6.3 `planning_workflow_tool.py`

这里继续保留：

- `issue_hit_plan_examples`
- `review_issue_hit_plan_examples`

但角色要明确收窄为：

- 面向用户解释的 facts
- 面向模型组织回复的例子

不要再让这两个 fields 承担“动作 scope”的含义。

### 6.4 `plan_context_tool.py`

这里需要把 `review_issues` 变成 `PlanContextInputs` 的正式字段。

建议新增：

- `review_issues`
- `review_issue_summary_lines`

这样 `collect_plan_context_inputs` 返回的不再只是：

- 风险数
- 提醒数
- 偏好摘要

还包括：

- 当前有哪些 active review issue
- 每个 issue 的类型、默认动作、影响范围

### 6.5 skill / prompt

skill 层不负责做 scope 计算，但要明确告诉模型：

1. 当用户 follow-up 一个 review issue 时，优先承接“问题对象”
2. broad 问法默认指向整批 issue scope，不指向样例
3. 样例只用于说明，不用于默认缩窄范围
4. 如果 issue 是 structural，就不要把 affected items 当成删除清单

换句话说，skill 层负责提供：

- 判断框架
- 负例边界
- broad vs narrow 的说明

但不负责替代 execution 的安全边界。

### 6.6 `plan_orchestration_models.py`

当前 `PlanAtomicAction` 只有：

- `action_type`
- `volunteer_ids`
- `target_position`
- `filters`
- `reason`

这不足以表达“当前动作是针对哪个 review issue”的语义。

建议新增一个显式 target 结构，例如：

```json
{
  "review_issue_target": {
    "code": "high_tuition",
    "scope_mode": "full_issue",
    "scope_fingerprint": "...",
    "narrowed_refs": [],
    "narrowed_filters": {}
  }
}
```

至少需要表达三件事：

1. 目标问题是哪个 code
2. 当前是整批 scope 还是 narrowed scope
3. preview 时看到的问题范围和 apply 时要执行的是不是同一批

`scope_mode` 可以先定义为：

- `full_issue`
- `narrowed_issue`
- `explicit_items`

含义分别是：

- `full_issue`：当前 review 里这个问题的完整影响范围
- `narrowed_issue`：当前问题的子范围，需和学校 / 位置 / 专业组等交集计算
- `explicit_items`：用户明确点名的若干条志愿

### 6.7 `plan_orchestration_tool.py`

`plan_next_action` 的职责不应该只是拼 preview 文案，而应该能承接 `review_issues` 做语义规划。

建议规则：

1. broad 跟进某个 `item_removal` issue
   - 默认 `remove_units`
   - 目标是 `review_issue_target.full_issue`

2. broad 跟进某个 `structural` issue
   - 默认走该 issue 的 `default_action_family`
   - 不生成 sample-based remove / replace

3. 只有当用户显式说出“换成 / 补回 / 保持总数 / 换成北京的 / 换成更稳的”
   - 才规划 `replace_units`
   - 且应带 `review_issue_target`

4. 如果用户明确限定：
   - 学校
   - 专业组
   - 位置
   - “刚才那两个”

   则 scope 从 `full_issue` 变成 `narrowed_issue` 或 `explicit_items`

### 6.8 `plan_execution_tool.py`

执行层应该基于 `review_issue_target` 解 scope，而不是基于自然语言反推。

执行顺序建议是：

1. 解析 `review_issue_target`
2. 用当前 review state 找到对应 issue
3. 根据 `scope_mode` 解出 `effective_ids`
4. 校验 action 与 issue 能力是否一致
5. 生成 preview / apply

这里需要两个明确边界：

#### A. broad item_removal issue

例如：

- 高收费
- 中外合作
- 限报条件
- 特殊类型招生

如果当前 action 是：

- `remove_units`

则 preview / apply 应直接基于 `affectedVolunteerIds` 或 issue 子范围解出真实作用范围。

如果当前 action 是：

- `replace_units`

则只有在用户明确表达了 replacement intent 时才继续。

否则不应该静默把 broad remove 变成 broad replace。

#### B. structural issue

例如：

- 梯度断层
- 数量缺口
- 本省保底不足
- 非意向托底

这类 issue 即使带 `affectedVolunteerIds`，也不能直接把这些 ids 当成“删掉就算处理完”。

执行层遇到这类 issue 时应：

- 优先转到 `analyze_adjustment` 或 `preview_fix_proposal`
- 或返回明确 preview，说明这是结构问题，不是直接删除清单

### 6.9 service pending confirm

service 层可以继续做“确认复用 pending payload”，但不应该承担 issue 语义判断。

它只需要保证：

- preview 留下的 payload 结构完整
- apply 复用的是同一个 payload
- 如果 scope fingerprint 已经失效，要求重新预览

## 7. 推荐的数据流

### 7.1 review / analyze 阶段

1. backend 返回 `reviewState.checks[]`
2. agent 规范化成 `review_issues[]`
3. `review_plan` / `analyze_adjustment` 的 facts 里可以继续带样例
4. `collect_plan_context_inputs` 同时输出 `review_issues`

### 7.2 follow-up 承接阶段

用户说：

- “先处理高收费”
- “把中外合作先去掉”
- “数量不足怎么补”
- “先处理非意向托底”

模型应优先做：

1. 从当前 `review_issues` 找命中的 issue
2. 根据 `scope_kind` 和 `default_action_family` 规划 action
3. 把“issue target”写入 payload

而不是：

1. 从上一轮回复里抓两条样例
2. 直接拼成 `volunteer_ids`

### 7.3 preview 阶段

preview 需要把“作用范围”讲清楚：

- item_removal issue：明确共涉及多少组、多少条志愿
- structural issue：明确这是结构问题，下一步是看调整建议还是补齐建议

这一步不要求模型固定模板，但要求它引用的是结构化 scope，不是 sample scope。

### 7.4 apply 阶段

apply 用 payload 里的 `review_issue_target` 解 scope。

如果 preview 和 apply 之间 issue scope 已变化：

- 要么校验失败并要求重新预览
- 要么显式提示当前问题范围已变化，避免 silent drift

### 7.5 post-review 阶段

执行完成后：

- rerun review
- 用新 review state 重新生成 `review_issues`
- 后续 follow-up 基于新的问题对象继续走

## 8. broad / narrow 语义规则

### 8.1 broad

以下表达默认是 broad issue：

- “先处理高收费”
- “把中外合作去掉”
- “数量不足怎么补”
- “先处理非意向托底”

它们指向的是：

- 当前 active review issue

不是：

- 回复里举出来的两个示例

### 8.2 narrow

以下表达默认是 narrowing：

- “先处理北京城市学院那个高收费”
- “只动第14个那个”
- “刚才那两个先去掉”
- “先处理湖北工程学院01组里这个问题”

这时作用范围才应收窄。

### 8.3 item_removal 与 replace 的边界

默认关系：

- broad `item_removal` follow-up -> `remove_units`

只有满足下列条件之一，才优先 `replace_units`：

1. 用户明确说“换成”
2. 用户明确说“补回去”
3. 用户明确说“保持总数”
4. 用户给了新的筛选范围

否则就算执行后会出现数量缺口，也应该走：

- 先移出
- 再根据新状态进入 `preview_fix_proposal` 或后续替换

## 9. 样例字段的定位

当前的：

- `issue_hit_plan_examples`
- `review_issue_hit_plan_examples`
- `sample_items`

都应该降级为同一类用途：

- 解释
- 展示
- 引用

不应再承担：

- broad issue 的真实 scope
- broad action 的默认目标

可以理解为：

- `review issue` 是动作对象
- `sample items` 是说明材料

## 10. 主线验证场景补充

这层设计落地后，主线至少应补以下 case：

### item_removal

1. `帮我审查一下当前方案 -> 先处理高收费 -> 确认`
2. `帮我审查一下当前方案 -> 先处理中外合作 -> 确认`
3. `帮我审查一下当前方案 -> 先处理限报条件 -> 确认`
4. `帮我审查一下当前方案 -> 先处理特殊类型招生 -> 确认`
5. `帮我审查一下当前方案 -> 先把刚才那两个高收费去掉 -> 确认`
6. `帮我审查一下当前方案 -> 把中外合作换成北京的 -> 确认`

### structural

1. `帮我审查一下当前方案 -> 数量不足怎么补`
2. `帮我审查一下当前方案 -> 先处理本省保底不足`
3. `帮我审查一下当前方案 -> 先处理梯度断层`
4. `帮我审查一下当前方案 -> 先处理非意向托底`
5. `帮我审查一下当前方案 -> 先处理组内安全垫不足`

### informational

1. `帮我审查一下当前方案 -> 这个招生计划更新提示是什么意思`
2. `帮我审查一下当前方案 -> 调剂风险提示主要影响什么`

重点验证的不是回复措辞，而是：

- 目标 issue 是否识别正确
- broad / narrow scope 是否正确
- 规划 action 是否符合 issue capability
- apply 是否作用在正确范围

## 11. 实现顺序建议

建议实现顺序是：

1. 先把 `review_issues` 接进 `PlanContextInputs`
2. 再给 `PlanAtomicAction` 增加 `review_issue_target`
3. 再改 `plan_next_action` 的 broad issue 规划逻辑
4. 最后把 `plan_execution_tool` 从“关键词反推”切到“target 解 scope”

这样做的原因是：

- 先把问题对象显式化
- 再让 planner 能表达它
- 最后再让 execution 按这个对象执行

如果顺序反过来，只会继续在执行层做更多例子补丁。

## 12. 结论

“高收费 / 中外合作”不是特殊业务，而只是第一批暴露出问题的 `review issue` 样本。

真正要修的是下面这条语义链：

```text
reviewState.checks
  -> review issue object
  -> plan context
  -> action target
  -> preview scope
  -> apply scope
  -> post-review
```

只要这条链没有显式对象，系统就会反复在：

- 问题摘要
- 问题样例
- 动作范围
- 执行目标

这几层之间来回混淆。

接下来的实现应围绕“问题对象化”推进，而不是继续为单个关键词补 prompt 或补执行分支。
