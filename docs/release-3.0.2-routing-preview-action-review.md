# Release 3.0.2 Routing / Preview / Action / Review

本文记录当前对话里「路由 -> 预览 -> 确认执行 -> 审查/复审」的真实链路，重点说明：

- 用户一句话是怎么被分到查看、分析、预览、执行这些分支的。
- 预览内容是怎么生成的，哪些内容来自后端事实，哪些只是回复包装。
- 审查、调整、补偿、重排之间现在怎么串联。
- 现阶段还保留了哪些兼容路径和技术债。

本文不展开 UI 细节，只描述 Agent / 后端主链路。

## 1. 当前主链路

当前运行主路径是：

```text
ChatAgent -> plan_next_action -> execute_plan_action
```

其中：

- `ChatAgent` 只负责注册可用工具，不直接决定动作。
- `plan_next_action` 负责把用户意图归一成一个可执行的 `PlanActionPlan`。
- `execute_plan_action` 负责真正返回预览、执行结果或只读分析结果。

### 1.1 关键入口

- [chat_agent.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/chat_agent.py:81>)：注册 `plan_next_action`、`execute_plan_action` 等规划工具。
- [tool_dispatch_rules.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/instructions/tool_dispatch_rules.py:41>)：约束“先看状态、先预览、再确认”的对话规则。
- [service.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/service.py:1569>)：加载历史、构建 `ConversationPhase`、处理短确认、触发直接执行。
- [conversation_phase.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/models/conversation_phase.py:84>)：统一的阶段与 pending 模型。
- [state_sync.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/sync/state_sync.py:59>)：pending 失效、版本漂移和执行前拦截。
- [plan_orchestration_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_orchestration_tool.py:357>)：把用户意图整理成 `PlanActionPlan`。
- [plan_execution_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_execution_tool.py:1766>)：把 `PlanActionPlan` 落成预览、分析或实际动作。

### 1.2 主链路分支

| 场景 | 当前路由 | 结果 |
| --- | --- | --- |
| 看方案、看候选、看状态 | `plan_next_action(action_family="query_state/query_candidates/query_ordered")` -> `execute_plan_action` | 先返回当前状态，再决定后续动作 |
| 方案分析 | `plan_next_action(action_family="analyze_adjustment")` -> `execute_plan_action` | 只读分析，不改方案 |
| 审查 | `plan_next_action(action_family="review_plan")` -> `execute_plan_action` | 只读审查，产出问题摘要 |
| 补偿预览 | `plan_next_action(action_family="preview_compensation")` -> `execute_plan_action` | 只读预览，确认后再应用 |
| 移动、删除、排序、补入 | 先预览，再确认，再 apply | 先解释影响，再实际改动 |
| 院校专业组移动/删除 | `move_ordered_unit/remove_ordered_unit` | 按专业组顺序解释，不按单条志愿顺序解释 |

## 2. 路由是怎么决定的

### 2.1 对话层规则

`tool_dispatch_rules.py` 现在已经把主规则说得很清楚：

- “方案有了么 / 现在方案怎么样” 这类问题，直接走 `plan_next_action(action_family="query_state")`。
- 要改方案内容时，不要先做长查询，先进入预览。
- 高副作用动作必须先 preview，再等确认。
- 院校专业组模式下，如果用户说的是“这一组 / 整组”，就应规划成 `move_ordered_unit` 或 `remove_ordered_unit`，不能打散成单条志愿。

### 2.2 计划编排层

`plan_next_action` 做的事情主要有四步：

1. 读取当前上下文、候选、方案摘要和审查问题。
2. 根据用户目标决定 `action_family`，并在必要时重写成更合适的动作。
3. 生成 `PlanActionPlan`，里面包含：
   - `stage`
   - `action_family`
   - `atomic_actions`
   - `preview_summary`
   - `missing_inputs`
   - `review_issue_target`
4. 明确这次动作是否需要确认，以及执行后是否要重新审查。

### 2.3 现在还保留的兼容路径

- `conversation_phase.pending` 是当前唯一的主来源。
- 旧的 `pending_plan_action` / `pending_intent_change` 仍保留，只是兼容旧会话。
- `ActionResolver` 现在存在，但还没有接入主路径。
- `planning_router_tool.py` 只是历史兼容壳，不是新能力入口。

相关代码：

- [context.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/context.py:135>)
- [action_resolver.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/resolver/action_resolver.py:147>)
- [planning_router_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/planning_router_tool.py:1>)

## 3. 预览内容是怎么生成的

### 3.1 预览不是纯聊天话术

当前预览尽量不是大模型自由发挥，而是由两类信息拼起来：

- 后端事实：当前方案、候选、审查结果、补偿建议、专业组顺序。
- 编排层语义：这次动作的目标、影响范围、确认提示。

也就是说，预览内容的核心是 `facts` 和后端状态，不是凭空编造一句“我会帮你调整”。

### 3.2 专业组移动 / 删除的预览

`move_ordered_unit` 和 `remove_ordered_unit` 的预览，都会先读后端 `orderedPlanState.units`，再按“专业组顺序”解释：

- 第几个指的是第几个专业组，不是第几条单条志愿。
- 会带出源专业组名称、目标位置、组内专业数。
- 回复时只保留这些关键信息，不再补“前 N 条志愿概况”，避免把专业组位置和单志愿位置混掉。

对应实现：

- [plan_execution_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_execution_tool.py:246>)
- [tool_dispatch_rules.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/instructions/tool_dispatch_rules.py:55>)

### 3.3 其他变更类预览

`add_units`、`remove_units`、`move_unit`、`replace_units`、`sort_ordered_plan` 这类动作，预览层会给出：

- 会改什么。
- 改完后会不会触发重新审查。
- 用户确认后才会真正执行。

`sort_ordered_plan` 的预览会明确说明：

- 这次排序会实际改变方案顺序和导出顺序。
- 排序后审查状态会变成待重新审查。

对应实现：

- [plan_orchestration_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_orchestration_tool.py:527>)
- [plan_execution_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_execution_tool.py:1766>)

### 3.4 短确认怎么走

如果上一轮已经生成了可复用的 pending，用户只回“确认 / 可以 / 好的 / 执行”这类短句时：

- `service.py` 会直接识别当前 pending。
- 不会重新绕一遍长链路。
- 会直接把 pending payload 交给 `execute_plan_action`。

但如果当前 pending 已经过期、版本漂移了，`PlanningStateSync` 会先拦住，要求重新读取当前方案后再确认。

相关代码：

- [service.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/service.py:1712>)
- [state_sync.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/sync/state_sync.py:125>)

## 4. 审查、分析、调整、补偿怎么串

### 4.1 审查问题如何映射到动作

`review_issue_registry.py` 负责把审查问题映射成默认动作。现在的大方向是：

| 问题类型 | 默认动作 | 典型问题 |
| --- | --- | --- |
| 条目移除类 | `remove_units` / `replace_units` | 高收费、中外合作、限报条件、特殊类型招生 |
| 结构分析类 | `analyze_adjustment` | 概率倒挂、梯度断层、冲稳保配比、边缘分、组内安全垫不足 |
| 信息提示类 | `review_plan` 或不触发变更 | 招生计划更新、调剂风险提示 |

这意味着：

- 审查不是直接改方案。
- 审查先把问题归类，再决定是分析、补齐，还是移除。

对应代码：

- [review_issue_registry.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/review_issue_registry.py:20>)
- [plan_orchestration_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_orchestration_tool.py:418>)

### 4.2 `review_plan`

`review_plan` 是纯读取：

- 调审查接口。
- 再读当前规划状态。
- 拼出 `facts` 和 `review_summary`。

它不直接改方案，只告诉用户当前审查结果是什么。

对应代码：

- [analysis_handlers.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/analysis_handlers.py:227>)

### 4.3 `analyze_adjustment`

`analyze_adjustment` 也是纯读取：

- 调调整分析接口。
- 再读当前规划状态。
- 生成结构性问题的事实摘要。

它的作用是回答“当前方案结构哪里不平衡、为什么需要动”，不是直接执行改动。

对应代码：

- [analysis_handlers.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/analysis_handlers.py:263>)

### 4.4 `preview_compensation`

`preview_compensation` 走补偿预览接口：

- 先看有哪些可安全补齐的候选。
- 再生成预览摘要。
- 只有用户确认后，才会进入 `apply_compensation`。

`apply_compensation` 真正执行后，会刷新 `draft / ordered / review`，也就是补齐后方案、排序和审查一起更新。

对应代码：

- [compensation_handlers.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/compensation_handlers.py:169>)
- [compensation_handlers.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/compensation_handlers.py:198>)

### 4.5 审查后的复审链路

只要是会改动方案顺序或内容的动作，执行成功后都会触发重新审查的语义：

- `sort_ordered_plan`
- `move_ordered_unit`
- `remove_ordered_unit`
- `move_unit`
- `remove_units`
- `replace_units`
- `apply_compensation`

也就是说：

- 改动前先预览。
- 改动后进入待重新审查。
- 后续审查结果可能再次驱动 `analyze_adjustment` 或 `preview_compensation`。

对应代码：

- [plan_execution_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_execution_tool.py:2055>)
- [plan_execution_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_execution_tool.py:2197>)

## 5. 当前兼容边界和风险

### 5.1 旧 pending 还没完全退场

现在是兼容期：

- `conversation_phase.pending` 已经是主来源。
- `pending_plan_action` 和 `pending_intent_change` 还在，只是 fallback。

这意味着：

- 功能上已经能跑。
- 但如果不同步，仍可能出现确认错位风险。

### 5.2 预览依赖后端真实状态

尤其是专业组移动/删除这类预览：

- 必须先读后端 `orderedPlanState.units`。
- 如果后端状态拿不到，预览就会退化成 error。

这不是“空话术”，而是链路设计使然。

### 5.3 只有部分动作已迁入 handler registry

当前 `handlers/registry.py` 说明得很直白：

- 只有 query handlers 已迁入。
- 其他动作仍会 fallback 到旧 `_execute_plan_action_model`。

这说明迁移还在进行中，不能把 `ActionResolver` 或 `handler registry` 当成已经完全统一的最终态。

### 5.4 需要继续补的验证

当前还应继续补这些场景：

- 专业 + 大学模式的 preview / apply 回归。
- 院校专业组模式的 preview / apply 回归。
- 专业组移动 / 删除时，专业组顺序和单志愿顺序不要混淆。
- 版本漂移、pending 过期、短确认直执行的边界。
- 后端不可达时的预览退化路径。

## 6. 代码锚点

- [chat_agent.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/chat_agent.py:81>)
- [tool_dispatch_rules.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/instructions/tool_dispatch_rules.py:41>)
- [context.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/agent/context.py:135>)
- [conversation_phase.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/models/conversation_phase.py:84>)
- [service.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/service.py:1569>)
- [state_sync.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/sync/state_sync.py:59>)
- [plan_orchestration_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_orchestration_tool.py:357>)
- [plan_execution_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/plan_execution_tool.py:1766>)
- [review_issue_registry.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/review_issue_registry.py:20>)
- [analysis_handlers.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/analysis_handlers.py:227>)
- [compensation_handlers.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/compensation_handlers.py:169>)
- [handlers/registry.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/handlers/registry.py:1>)
- [planning_router_tool.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/tools/planning_router_tool.py:1>)
- [action_resolver.py](</Users/baiyang/git/zhiyuan/zhiyuan-agent/app/resolver/action_resolver.py:147>)

## 7. 本次补充验证

### 7.1 已通过的验证

#### 7.1.1 阶段、pending 和短确认链路

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/models/test_conversation_phase.py \
  tests/unit/test_planning_router_tool.py \
  tests/unit/test_chat_service_history_persistence.py \
  -k 'pending or confirmation or preview or history_persistence' -q
```

结果：

- 135 passed, 23 deselected
- 说明 `ConversationPhase`、短确认复用、history 里的 pending 恢复和路由壳逻辑保持稳定。

#### 7.1.2 审查、分析、补偿、排序和旧逻辑对齐

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/regression/test_execution_preview.py \
  tests/regression/test_execution_apply.py \
  tests/regression/test_normalize_action.py \
  tests/regression/test_determine_stage.py \
  tests/integration/test_resolver_vs_legacy.py -q
```

结果：

- 584 passed
- 说明审查、分析、补偿、排序、移动、删除、重排和旧逻辑对齐相关回归整体保持通过。

#### 7.1.3 真实对话场景回归

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_dialog_scenario_stability.py tests/unit/test_mainline_dialog_scenarios.py -q
```

结果：

- 50 passed
- 说明跨轮对话、预览、确认和状态承接在当前本地服务下保持稳定。

### 7.2 已修复的预览分支问题

本次补充验证里，曾经出现过 `remove_units` / `move_unit` 的泛化预览回退到 `error` 的情况。根因是：

- 预览分支把“没有显式引用”的 generic fallback 也当成了需要报错的删除/移动请求。

已调整为：

- 只有真的带了引用，或者属于审查问题驱动的整批移除，才进入专用预览分支。
- 空引用的泛化场景回到通用 `preview_only`，不再误报错。
- 审查问题驱动的整批移除仍保留专用预览，不受影响。

## 8. 结论

当前这条路由 / 预览 / 确认 / 审查链路的主逻辑已通过本地回归验证；当前剩余风险主要还是后端真实状态依赖、兼容期 pending 双轨并存，以及后续还需继续补的联调场景覆盖。
