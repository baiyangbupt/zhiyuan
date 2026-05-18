# Release 3.0.1 Current State And Optimization Roadmap

本文基于 `docs/release-3.0.0-review-claude.md`、`docs/release-3.0.0-backlog.md`、`docs/release-3.0.1-stability-plan.md` 和 `docs/release-3.0.1-implementation-design.md`，整理当前实现状态、已知问题和后续优化优先级。

定位：

- `release-3.0.1-stability-plan.md` 仍是 3.0.1 范围和优先级的主文档。
- `release-3.0.1-implementation-design.md` 仍是已确认事项的落地设计。
- 本文用于承接 review 中暴露出的系统性问题，避免把产品稳定修和 Agent 架构重构混在同一个 P0 清单里。

## 1. 当前实现状态

### 1.1 工作台和方案能力

已完成或已纳入 3.0.1 主设计：

- 用户侧收敛“草稿”概念，前端和 Agent 统一使用“方案 / 当前方案 / 已加入方案”。
- 方案页补齐排序、审查、导出、历史分数、目标位置移动、专业组组级移动/删除等核心能力。
- 方案排序支持录取率、院校层次、推荐系数三类维度，并按实际顺序改写方案，排序后审查进入待重新审查。
- 导出链路已补充历史 ID 兼容解析，解决迁移方案中 `volunteerId` 第三段不一致导致 Excel 明细为空的问题。
- 候选筛选项已向后端结构化来源收口，地域通过 `regionTree` 解决“其他城市”误归类；专业筛选移除“意向专业类”等推荐解释标签。
- 专业+大学和院校专业组两种模式均作为回归要求，特别关注 unit 级移动/删除、历史分数展示、导出和排序。

仍需继续验证：

- 新建 `major` 和 `majorGroup` 会话完整链路，包括初始化方案、排序、移动、审查、导出。
- 历史迁移 `_final`、`_temp`、无后缀文件选择逻辑与导出回填。
- 用户调整后 `reviewStatus=stale`、旧审查风险提示隐藏、导出状态过期。
- 行为事件是否覆盖添加、删除、移动、组级操作、排序应用和导出。

### 1.2 Agent 和对话驱动

当前已经完成的收口方向：

- `ChatAgent` 面向模型的 Plan 主链路收敛为 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。
- `planning_router_tool` 已定位为 deprecated compatibility wrapper，不作为新能力入口。
- `planning_workflow_tool` 仍是内部 helper 集合，被多个 handler/tool 复用，不能直接删除；后续需要拆分。
- 对话触发排序新增 `sort_ordered_plan`，与前端排序能力对齐。
- `pin_unit / unpin_unit / lock_draft` 不再作为 3.0.1 用户可触发能力；用户要求固定/锁定时转为解释和替代操作建议。
- Explore / Intent / Plan 的边界已明确：职业路径探索走 `analyze_current_career_direction`，职业偏好写入走 `preview_current_career_intent_confirmation` 后等待确认。
- 对话驱动的专业组 unit 级操作已补入 Agent 动作模型和执行链路，支持 `move_ordered_unit / remove_ordered_unit`。
- 已新增最小结构化日志，覆盖 conversation turn、plan action 和 intent state 三类事件。
- Agent examples 已补齐首批 3.0.1 场景，覆盖 career explore、career intent、plan sort、unit move/remove、no draft wording。

当前主要遗留：

- 仍存在旧指令、旧 skill 描述、旧 changelog 语言残留，容易让维护者误解哪个入口实际生效。
- `planning_workflow_tool` 作为内部 helper 过大；本轮已清理一批旧 patch 点，但模块边界仍需要后续拆分。
- Plan action 的 mutation handlers 尚未完全迁入统一 registry，部分动作仍在旧执行路径中。
- `tests/unit/test_plan_execution_tool.py` 历史 fixture 债务已完成首轮清理，当前全量 62 条通过。
- 旧 router/workflow 兼容测试已同步到 3.0.1 语言和当前 handler patch 点，避免本地单测误连 backend；`test_planning_router_tool* / test_planning_plan_scenarios_sync / test_planning_workflow_tool` 共 72 条通过。
- Agent 主链路 + router/workflow 兼容集合当前共 387 条通过；后续重点转向真实 websocket regression。
- 本地真实 websocket smoke 首轮发现 `session=17` 输入“看看现在的方案”在百家平台 `kimi-k2.6` 下 180 秒内未收到结束消息。切到 SiliconFlow 后可返回，但完整链路约 38.3 秒，其中后端状态读取和 `query_state` 工具均在 1 秒以内，主要耗时来自 4 次 LLM 往返和约 4 万 input tokens。
- 当前低风险优化方向：不直接绕过大模型，也不新增正常路由字符串短路；先通过提示词、工具 schema 和 examples 引导方案现状查询稳定收敛为 `query_state`，并避免重复 `collect_plan_context_inputs`，减少 LLM 往返次数。
- 提示词收敛后，`看看现在的方案` 诊断链路已从 `collect -> plan_next -> execute -> final` 收敛为 `plan_next -> execute(query_state) -> final`；SiliconFlow 下单轮耗时约 `14s` 量级，LLM 请求数减少到 `3` 次左右。后端和工具仍在 1 秒以内。
- 已新增真实 websocket smoke 用例 `zhiyuan-agent/examples/dialog_regression_301_agent_smoke_cases.json`，覆盖方案现状、审查、排序确认、专业组移动确认，并通过 runner 输出 `elapsedMs / primaryMessages / followupMessages`，用于同步验证效果和性能。
- 已移除 plan correctness examples 中旧 `pin -> verify` 正向用例，保留 `pin_disabled` 作为 3.0.1 唯一锁定验证口径，避免回归用例和产品策略冲突。
- 真实 smoke 首轮把专业组 fixture 从 `session=35` 调整为 `session=16`：`35` 存在历史 pending intent 干扰，排序/专业组操作不适合作为稳定样本。
- 真实 smoke 暴露排序确认状态不一致问题：执行层只认 `{code: 0}`，未兼容 `{success: true}`，导致后端执行成功但回复“排序失败”，同时仍发送 ordered 刷新。当前已修正为统一成功判定；失败时不标记 `applied`，也不发送 workspace refresh。
- 执行层修复后复跑真实 smoke：方案现状、审查、排序确认和专业组移动确认已通过，排序/移动确认后均返回 `ordered` 工作区刷新。
- 已完成首轮结构收口：未确认高副作用动作不能被模型单独推入 `apply`；专业组位置引用允许在 preview 阶段先保留为自然位置，由执行层解析真实 unitId；测试中废弃的 service `get_planning_state` patch 和独立 `review` workspace card 断言已清理。
- 专业组删除已通过真实 websocket 复测：`删除第5个专业组 -> 确认` 走 `remove_ordered_unit preview/apply`，不会把组内专业打散。
- 专业模式学校+专业自然引用已通过真实 websocket 复测：`把哈尔滨理工大学的人力资源管理改到第4位 -> 确认` 走 `move_unit preview/apply`；`去掉山东英才学院的国际商务 -> 确认` 走 `remove_units preview/apply`，不再先调用 `query_volunteer_plan`。
- 候选加入自然引用已补执行层防重：如果目标学校+专业或简称已经在当前方案中，返回 `no_change` 并提示无需重复加入，不调用后端加入接口、不触发复审、不发送无变化工作台卡片。
- 专业组移动/删除预览文案继续收口：工具提示和 style guard 会避免输出“当前前 N 位概况”等单条志愿列表，防止用户把专业组位置和单条志愿位置混淆。

### 1.3 Explore / Intent / Career

当前链路：

```text
用户探索职业方向
  -> ChatAgent 识别 Explore + career
  -> analyze_current_career_direction
  -> resolve_career_direction_slots / generic direction analysis
  -> 读取学生、方案、候选事实
  -> 只读分析，不写 pending intent

用户明确表达后续偏好
  -> preview_current_career_intent_confirmation
  -> 写入待确认 cache
  -> 用户下一轮确认
  -> update_volunteer_intent_state(confirm)
```

现状判断：

- 运行时链路还在，并且不是旧的 skill-only career chat。
- Explore 阶段有只读保护，`persist_cache=false` 路径可避免“体制内适不适合我”被误写入偏好。
- Intent 确认有 `pending_intent_change` 和确认话术保护，首轮表达不应同轮直接生效。

需要补强：

- 文档中仍有“Career 分析：`skills/career_path_chat`”这类旧表述，应改成“skill 负责语义说明，运行时入口是 `analyze_current_career_direction`”。
- 端到端 examples 应增加泛方向、多职业方向对比、负向职业 intent、确认后方案承接四类 case。

## 2. 系统性问题

### 2.1 Model-first 原则和关键词兜底并存

`release-3.0.0-review-claude.md` 指出当前存在三层关键词/规则兜底：

- service 层确认、基础方案状态、pending intent 的快速短语匹配。
- `plan_next_action` 内部仍有较多规则化 action routing。
- 最终回复还有多层 post-processing 文本清理和术语替换。

这类兜底短期有利于生产稳定，但会带来三个问题：

- 用户口语、错别字、方言、多指令表达容易漏匹配。
- prompt、规则和后处理三套逻辑同时维护，新增能力成本高。
- 后处理会掩盖模型回复质量问题，难以用数据持续优化 prompt。

3.0.1 处理建议：

- 不在稳定版中一次性删除这些兜底。
- 先补结构化日志，记录 routing path、post-processing 是否修改、tool 调用耗时和失败原因。
- 后续小步替换确认检测和 action classification，而不是直接重写整个 Agent。

### 2.2 Pending 状态双系统

现状：

- `RequestContext` 同时保留旧 `pending_plan_action` 和新 `conversation_phase`。
- service 层仍会从 message history 推导 pending 状态。

风险：

- 多轮确认在长历史、重复工具结果、用户切换话题时容易误判。
- 每轮扫描历史有性能和复杂度成本。

优化方向：

- 短期保留兼容，但新增 pending 必须优先写结构化 phase。
- 将从历史扫描推导 pending 降级为兼容兜底。
- 后续删除 deprecated pending 字段前，需要用真实对话回归覆盖 preview -> confirm -> apply。

### 2.3 内存级 preview 缓存不适合多 worker

现状：

- 方案执行 preview 结果仍有模块级近期结果缓存。

风险：

- 如果生产 Agent 多 worker 或非粘性会话，preview 和 confirm 落到不同进程会找不到 payload。

优化方向：

- 生产部署先确认 Agent 是否单 worker 或 session sticky。
- 若要多 worker，preview payload 必须迁移到 Redis、数据库或已有会话状态存储。

### 2.4 Tool 返回和用户话术不统一

现状：

- 有的 tool 返回 JSON，有的返回自然语言，有的混合结构和文本。
- 部分历史工具仍带“草稿、排序区、画像、内部 action”等术语风险。

风险：

- 模型难以稳定组织回复。
- service 层不得不继续做文本清理。

优化方向：

- 新增或改造工具优先使用统一信封：`status / summary / details / nextOptions / internalNotes`。
- 用户可见术语在 tool 源头修正，post-processing 只保留安全清理，不承担主表达。

### 2.5 Handler 和 workflow 模块边界不清

现状：

- query handlers 已有 registry 方向。
- mutation、generate、review、compensation 仍部分依赖旧 monolith 或 `planning_workflow_tool` helper。

风险：

- 新能力容易接错入口。
- 单测 patch 点不稳定，容易出现测试绕过实际调用路径或误连本地 backend。

优化方向：

- 先拆分 `planning_workflow_tool` 为内部 helper 模块，再逐步迁移 handlers。
- 每迁移一类 action，就补一组主链路测试：preview、confirm、workspace refresh、review stale。

### 2.6 数据闭环不足

3.0.1 已计划记录方案操作和导出行为，但 Agent 侧仍缺少完整对话质量数据。

需要补充的最小日志：

- 每轮对话：session、turn、scene、routing path、pending type。
- 模型调用：provider、model、latency、status、errorType、token 用量。
- 工具调用：tool name、action family、duration、success、errorType。
- 输出质量：是否触发 post-processing、是否含内部术语、是否需要 retry。
- 用户反馈：preview 后确认/拒绝、导出、重复追问、手动调整。

## 3. 优先级建议

### P0：3.0.1 稳定版继续收口

这些事项直接影响用户体验、数据正确性或发布准入：

1. 继续完成工作台 P0/P1 回归：导出、空候选、审查状态、排序、移动、组级操作、历史分数。
2. 补齐专业+大学和院校专业组两种模式的端到端样例。
3. Agent 用户话术继续去“草稿/排序区/画像”，确认卡和 pending 回复统一到“方案/后续报考参考”。
4. 对话排序、审查、移动、删除、补齐等高副作用动作确认边界必须稳定。
5. 文档修正旧 career chat、router、workflow 的入口描述，避免后续误用旧路径。

### P1：3.0.1 后续小版本可做

这些事项有明显收益，但不应阻塞当前稳定版发布：

1. 把 confirmation detection 从纯短语匹配逐步替换成轻量分类器或结构化判定。
2. 继续扩充 LLM benchmark 的真实端到端 case，覆盖更多长会话、异常候选和双模式方案编辑。
3. 给 `sort_ordered_plan / move_unit / remove_units / review_plan / apply_compensation` 补齐主链路 regression examples。
4. 梳理 ActionResolver 与 `plan_next_action` 的边界，决定后续 structured planner 切换节奏。
5. 将 `planning_workflow_tool` 拆成内部 helper 模块，继续迁移剩余旧测试 patch 点。
6. 用真实 websocket regression 固化 `review_plan / apply_compensation / unit move/remove` 的端到端表现。

### P2：架构优化和长期能力

这些事项需要更完整设计和灰度验证：

1. `plan_next_action` 从规则路由逐步升级为 LLM structured planner + deterministic guardrails。
2. post-processing 从“改写回复”收敛到“安全过滤 + 质量评估 + 必要时 retry”。
3. preview payload 从进程内缓存迁移到共享存储，支持多 worker。
4. 完成 `ConversationPhase` 迁移，删除旧 pending 推导。
5. 建立 response quality evaluator 和人工标注回归集。
6. 基于操作事件、导出事件和对话日志做策略/算法优化闭环。

## 4. 建议下一步

短期建议按以下顺序推进：

1. 先把 3.0.1 当前已实现内容做一次全链路验证，尤其是 `major / majorGroup` 双模式。
2. 用真实 websocket regression 验证 plan sort、unit move/remove、review/apply_compensation 的 preview -> confirm -> apply。
3. 先把“方案现状查询”收敛为 `query_state`：提示词不再要求单独先调 `collect_plan_context_inputs`；如果只是多一次调用，暂不通过字符串规则强行纠偏。
4. 高副作用 preview pending 形成机制已完成首轮收口：`plan_next_action(preview)` 可直接形成 pending，`query_state` 等只读动作不会清掉待确认变更；后续继续扩充更多 action 的真实回归。
5. 专业组 unit action 和专业模式自然引用已完成首轮真实验证；下一步继续补 `review_plan / apply_compensation` 的真实 websocket preview -> confirm -> apply 覆盖。
6. 继续补 websocket 对话链路分段耗时和结果日志，稳定观测 LLM 请求次数、token 数、工具耗时和最终发送耗时。
7. 再评估是否引入轻量分类器替代 service 层确认短语匹配。
8. 继续拆分 `planning_workflow_tool`，把 formatter/state/mutation/review/compensation helper 从 monolith 中拆出来。
9. 继续检查用户可见文案，避免“草稿/排序区/画像/action”等内部词从老工具 fallback 泄露，特别关注专业组预览和补齐建议类回复。

下一批 Agent 优化的详细实施设计见 `docs/release-3.0.1-agent-optimization-design.md`。该文档确认后再进入代码实现。

## 5. 当前不建议立即做的事

- 不建议在 3.0.1 稳定收口阶段直接删除所有关键词兜底。
- 不建议一次性重写 `plan_next_action` 和 action resolver。
- 不建议直接删除 `planning_workflow_tool`。
- 不建议在没有共享 preview 状态设计前开启多 worker Agent。
- 不建议把行为反馈立即用于自动改变推荐策略，先完成记录和可追溯查询。
