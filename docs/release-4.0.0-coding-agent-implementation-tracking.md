# Release 4.0.0 — Coding Agent Implementation Tracking

> 版本: v0.25 | 更新日期: 2026-07-02
> 关联文档:
> - [release-4.0.0-coding-agent-architecture-redesign.md](release-4.0.0-coding-agent-architecture-redesign.md)
> - [release-4.0.0-coding-agent-poc-plan.md](release-4.0.0-coding-agent-poc-plan.md)

## 1. 当前状态

Release 4.0 PoC 第一阶段已落地到 `zhiyuan-agent`，并完成真实 LLM、真实 service websocket shadow/direct 对比，以及确认后真实后端 action 验证。

当前状态：

| 模块 | 状态 | 说明 |
|------|------|------|
| 独立 `ZhiyuanAgent` PoC | 已落地 | 9 个工具、状态前置注入、`next_step` 终止信号、每轮 3 次工具上限 |
| service shadow 对比 | 已落地 | 默认关闭；开启后主链路照常执行，同时运行 PoC 并写入观测字段 |
| regression runner 指标提取 | 已落地 | metrics JSON 可直接汇总 `summary.zhiyuanAgentPocShadow`；支持等待并合并后置 `zhiyuan_agent_poc_shadow_event`；确认类 step 支持 `assertBackendExtraData` 断言真实后端状态变化 |
| Phase 1 SandboxFileCache | 已落地 | 8 个虚拟路径映射、4 路径 warm、TTL + planning version 失效 |
| plan item enrichment | 已落地 | `plan/items.json` 按 `volunteerId` 从候选池合并属性字段，真实民办/中外合作 filters 已验证可命中 |
| ZhiyuanAgent sandbox 读取 | 已落地 | `prompt.py` / `tools.py` 已从 direct deps 切到 `ctx.deps.sandbox` |
| Phase 2 `query_plan` 真实扫描 | 已落地 | 扫描 `plan/items.json`，支持 filters；候选查询走 `plan/candidates.json` |
| Phase 2 `explore_topic` 真实资料 | 首版已落地 | major/school 已接后端 profile API，失败时降级只读分析；career/region 保持轻量摘要 |
| Phase 2 `compare_entities` 结构化对比 | 首版已落地 | major/school 2-5 个对象并发取 profile，返回对比矩阵和当前方案命中 |
| Phase 2 `answer_policy` 报考政策问答 | 首版已落地 | 新工具已注册；整合政策框架、school profile 招生政策、参数可用性校验和可选官方来源检索，保持只读 |
| Phase 2 `review_plan` 方案审查 | 首版已落地 | 新工具已注册；执行/读取后端审查，按 focus 过滤 issues，可选只读修复建议，不自动改方案；明确与方案操作边界 |
| Phase 2 `confirm_pending` | 已落地 | 支持确认/取消、版本漂移守护、结构化 intent/plan pending 直接后端执行、sandbox 失效；`intent_change` 有方案时会在采纳报考要求后立即重算当前方案 |
| Phase 2 非阻塞 shadow | 已落地 | shadow 后台 task 运行，主链路不等待；完成后写独立 shadow event |
| service structured pending bridge | 已落地 | 卡片/短文本确认统一执行 4.0 结构化 `intent_change` / `plan_mutation` pending；旧预览 sink 会转成扁平结构化 `executionPayload`，不再写入或确认执行旧 `executionPayload.planPayload` |
| Phase 4 direct route | 已接入，默认关闭；真实口语 direct 已通过 | `ZHIYUAN_AGENT_ENABLED` / `ZHIYUAN_AGENT_ROLLOUT_PERCENT` 控制；无本地字符串 precheck；已按 v1.3 §9 放开 pending 下只读 direct，并增加无有效成绩回退 |
| Phase 2 `preview_intent_change` pending + diff | 已落地 | 归一化显式"要/不要/只看/必须有"后创建结构化 `pendingConfirmation`；裸属性/标签/类别诉求和明确长期诉求走报考要求路径；专业/院校/地域/属性标签意向优先调 `simulate_plan_diff`，失败时降级本地扫描 |
| Phase 2 `preview_plan_action` 结构化 pending | 首版已落地 | 新工具已注册；add/remove/move/replace/sort/generate/regenerate_order 只产出结构化 payload，不再生成旧 `planPayload`；已支持 `review_issue_code` 从审查 issue 解析操作范围，并兼容后端 issue code alias；当前方案锚定的筛选移出、具体项/位置/审查问题联动走方案操作 |
| 真实 LLM 工具选择验证 | 已通过 | 9 个 PoC/Policy/Review/Review-Action 场景全部通过 |
| 真实 service websocket 小样本 | 已通过 | 5/5 successful，PoC shadow 5/5 success |
| 真实口语 service direct | 已通过 4.0 direct | `examples/dialog_regression_400_realistic_user_cases.json` direct-only 最新复跑 14/14 successful，工具调用数 max=1，metrics: `/private/tmp/zhiyuan_400_realistic_direct_only_after_retry_reason_fix.json` |
| 真实 direct 确认执行闭环 | 已通过 | `examples/dialog_regression_400_direct_confirm_execution_cases.json` 4/4 successful；已覆盖 pending applied、planningState version 增长、方案项删除和报考要求写入，不再只按出卡判断；metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_retry_filter_fix.json` |
| G case direct 子集 | 已通过 | direct-only 最新复跑 8/8；G17 生成 `move_ordered_unit` 确认卡，G25 正负完整，G30/G32 均进入 `zhiyuan_agent_direct`；metrics: `/private/tmp/zhiyuan_400_g_case_direct_only_after_retry_filter_fix_rerun.json` |
| 320 G1-G32 direct 完整回归 | 已完成新一轮问题归档 | 最新 `49` steps，`44` successful，`5` failed；metrics: `/private/tmp/zhiyuan_400_direct_320_g1_g32_after_retry_filter_fix_rerun.json` |

注意：service shadow 默认关闭；开启后会后台运行，不阻塞主链路。turn event 中可能先记录 `status=running`，完整结果会在 `zhiyuan_agent_poc_shadow_event` 中落盘。

## 2. 本轮代码改动

### 2.1 PoC agent 包

新增目录：

```text
zhiyuan-agent/app/zhiyuan_agent/
├── __init__.py
├── agent.py
├── prompt.py
├── sandbox.py
└── tools.py
```

核心行为：

| 文件 | 内容 |
|------|------|
| `agent.py` | `ZhiyuanAgent(BaseAgent[str])`，接入 9 个工具；识别工具返回的 `next_step` 后直接回复；增加每轮总工具调用上限 |
| `prompt.py` | 构建紧凑 system prompt；通过 warmed `SandboxFileCache.peek()` 把成绩、方案摘要、风险、画像、pending 前置注入 |
| `sandbox.py` | `SandboxFileCache` + `BackendAdapter`；支持 8 个虚拟路径、TTL、planning version 失效、context prime/warm |
| `tools.py` | 实现 `read_state`、`answer_policy`、`explore_topic`、`compare_entities`、`preview_intent_change`、`preview_plan_action`、`query_plan`、`review_plan`、`confirm_pending`；状态读取统一走 `ctx.deps.sandbox.read()` |

本轮真实 LLM 发现一次问题：`不要排除经济学类` 被模型传成 negative。已通过两类修复稳定：

- Prompt 明确双重否定规则：`不要排除X/不排除X/别把X排除` 走 positive。
- 工具签名收窄为 `Literal` 枚举，避免模型把 `intent_type` 传成 `preference` 等无效值。

2026-07-01 继续按 `release-4.0.0-zhiyuan-agent-implementation-design.md` v1.1 收口用户交互语义：

- 用户意向层只保留显式报考要求：`exclude`、`only_keep`、`must_have`。软性“倾向/偏好强度”不再在 `preview_intent_change` 里生成 pending。
- 属性、标签、特性作为 selector 一等支持：`school_nature`、`school_category`、`school_level`、`program_type`、`school_tag`、`major_tag`、`major_category`。
- `preview_intent_change(intent_type="school")` 支持 `negative={"school_nature":["民办"]}`、`positive={"school_nature":["公办"]}`、`negative={"program_type":["中外合作"]}` 等结构；LLM 如果把“公办/民办”等放进 `values`，工具也会自动归入属性 selector，不当作学校名。
- 确认执行时仍复用现有后端 `UpdateConstraintStateReq` 三组正负列表，属性 selector 编码为可读 hard scope，如 `院校性质:民办`、`招生类型:中外合作`，并统一 `intentMode=constraint`。
- Java 修复/候选过滤链路已扩展 hard constraint scope 匹配，支持按院校性质、院校类型、院校层次、招生类型、专业门类/标签过滤候选，避免确认后被排除属性重新进入候选或修复方案。

2026-07-01 继续按 `release-4.0.0-zhiyuan-agent-implementation-design.md` §3.7 / §8.3 对齐“显式诉求优先”：

- 裸属性/标签/类别级表达走 `preview_intent_change`，例如“民办的不要”“中外合作都不要了”；这类诉求记录为后续报考要求，也会在当前已有方案时触发方案重新调整。
- 带“方案里/当前这些/这批”等当前方案锚点且明确“移出/删除/不要了”的表达，允许走 `preview_plan_action(remove, filters=...)`，例如“方案里的民办不要了”“当前这些中外合作都移出去”；不自动推断为长期报考要求。
- `preview_plan_action` 的模型路由边界包括当前方案筛选移出、具体项、位置编号、档位内具体目标和审查 issue 联动，例如“第3个不要了”“把广州南方学院移出去”“把审查里的高收费项移出去”。
- `confirm_pending(intent_change)` 采纳成功后，如果 `plan/summary.json.has_plan=true`，会立即调用 `generate_planning_ordered_plan(tenant_id, sessionid)`；无方案时只记录报考要求，不调用方案重算。
- `preview_intent_change` 预览文案已去掉“约束/硬性要求”等系统用语，改为“报考要求/诉求”；全局旧链路回复 sanitizer 也增加了“约束 -> 要求”的用户侧兜底替换。

2026-07-02 修复 G25 混合正负诉求：

- `ZhiyuanAgent` 专属关闭 `parallel_tool_calls`，避免同一轮并发拆成多个 `preview_intent_change` 后互相看不到 pending 状态。
- `preview_intent_change` 增加同轮 active intent pending 合并：如果同一轮先创建正向/负向 pending，后续调用会合并已有 `executionPayload.merged` 和当前 payload，再保存一个完整结构化 pending。
- 单次工具调用同时包含 positive + negative 时，`constraint_type` 统一归一为 `must_have`；最终卡片保留“要 X；不要 Y”，`constraintIntentType=must_have`。
- 新增单测覆盖禁并行工具、同轮正负 pending 合并、混合正负 constraint type 归一化，防止回退到只保留最后一次工具结果。

### 2.2 service shadow 接入

修改 `zhiyuan-agent/app/service.py`：

| 位置 | 内容 |
|------|------|
| `ChatService.__init__` | 增加 `ZHIYUAN_AGENT_POC_SHADOW` 开关，默认 false |
| `_maybe_run_zhiyuan_agent_poc_shadow` | 在主链路前创建独立 `RequestContext` 副本并启动后台 task |
| `_run_zhiyuan_agent_poc_shadow_task` | 后台运行 `ZhiyuanAgent`，完成后更新 request_context 并写 shadow event |
| `_summarize_zhiyuan_agent_poc_shadow` | 记录工具名、首个工具参数、`next_step`、耗时、token、回复预览 |
| `_observability_timing_fields` | 如 shadow task 已完成则收集完整结果；否则注入 `running` 占位 |
| 主消息处理入口 | request context 构建后、guard pipeline 前运行 shadow |

环境变量：

```bash
ZHIYUAN_AGENT_POC_SHADOW=1
ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS=30
ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE=1.0
```

2026-07-01 Phase 4 direct route 已接入 service，仍默认关闭：

- `ChatService.__init__` 增加 `ZHIYUAN_AGENT_ENABLED`、`ZHIYUAN_AGENT_ROLLOUT_PERCENT`、`ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS`；开启 direct 或 rollout 时复用 `ZhiyuanAgent`。
- `handle_message` 在 request context 和 sandbox warm 完成后、旧 guard pipeline 前调用 `_maybe_handle_zhiyuan_agent_direct_route`。
- direct route 不做 `_zhiyuan_agent_direct_remove_precheck` 这类字符串匹配前置判断；该 precheck 已移除，路由接管只由功能开关/rollout、active pending 状态、4.0 agent 结构化工具返回共同决定。
- 4.0 工具返回 `next_step=confirm` 且 `data.pending_created=true` / `pending_id` 存在时，service 从 sandbox/backend 读取 active pending，并按 `kind=intent_change|plan_mutation` 构建 `pendingConfirmationCard`。
- 当前存在 active pending 时不进入 direct route，继续由 pending 确认流处理，避免绕过已有待确认操作。
- direct route 的 intent 卡片用户可见文案统一为“报考条件/报考要求”，不再出现“约束/硬约束/软偏好/报考想法”。

2026-07-01 service structured pending bridge 已落地并继续收口：

- `_pending_confirmation_from_state` 只接受带 `action_family` + `atomic_actions` 的结构化 `plan_mutation` pending；非结构化历史 pending 不再投影到可执行状态。
- `handle_pending_confirmation` 增加统一 `_handle_structured_pending_confirmation` 分支，卡片点击或短文本“确认”可直接调用 4.0 `confirm_pending(action="confirm")` 执行结构化报考要求或方案调整。
- 旧预览链路如果还能产出可确认方案预览，service pending sink 会把 resolved apply payload 转成结构化 `executionPayload` 保存；确认阶段不再解析或执行旧 `executionPayload.planPayload`。
- 非结构化历史 pending 统一标记失败/失效并要求重新生成结构化预览，不再保留 `planPayload` 专用兼容分支，也不回退旧 `execute_plan_action`。
- pending prompt 注入不再暴露可执行 payload，只给模型动作类型、摘要和影响范围；执行仍由服务端 pendingConfirmation 链路负责。

输出位置：

```text
conversation_turn_event.zhiyuanAgentPocShadow
zhiyuan_agent_poc_shadow_event.shadow
```

### 2.3 regression runner 对比指标

修改 `zhiyuan-agent/examples/dialog_regression_runner.py`：

- 从本地 history 的 `route-observability` 消息中提取 `zhiyuanAgentPocShadow`。
- 合并后置 `zhiyuan_agent_poc_shadow_event`，避免非阻塞 shadow 完成后被主链路 history 保存覆盖或遗漏。
- 新增 `--poc-shadow-wait-seconds`，仅对声明 `expectedZhiyuanAgentPoc*` / `maxZhiyuanAgentPocToolCallCount` 的 step 等待 shadow 完成。
- 每条 record 保留 `turnObservability.zhiyuanAgentPocShadow`。
- summary 增加 `summary.zhiyuanAgentPocShadow`，聚合：
  - observed/statuses
  - firstTools/toolNames
  - nextSteps
  - duration
  - toolCallCount
  - totalTokens
  - errorExamples
- case step 支持直接断言 4.0 shadow 工具选择：`expectedZhiyuanAgentPocStatus`、`expectedZhiyuanAgentPocFirstToolNames`、`expectedZhiyuanAgentPocToolNames`、`expectedZhiyuanAgentPocNextSteps`、`maxZhiyuanAgentPocToolCallCount`。
- 新增真实口语/指代/省略验证集 `examples/dialog_regression_400_realistic_user_cases.json`。书面化验收 case 继续保留，但 4.0 后续验证必须同时覆盖日常短句和上下文指代，例如“有啥问题，咋弄”“那高收费的别要了”“民办的不要”“里面有民办没”。

### 2.4 Phase 1 SandboxFileCache 落地

新增 `zhiyuan-agent/app/zhiyuan_agent/sandbox.py`：

| 能力 | 状态 | 说明 |
|------|------|------|
| 虚拟路径标准化 | 已落地 | 支持 `score`/`score.json`、`plan/summary`/`plan/summary.json` 等 alias |
| BackendAdapter 8 路径 | 已落地 | `score.json`、`profile.json`、`constraints.json`、`plan/summary.json`、`plan/items.json`、`plan/candidates.json`、`plan/review.json`、`pending.json` |
| CacheEntry | 已落地 | `data`、`version`、`fetched_at`、`ttl_seconds` |
| 失效策略 | 已落地 | TTL 过期；`plan/*`、`constraints.json`、`pending.json` 受 latest planning version 保护 |
| warm | 已落地 | `score.json`、`profile.json`、`plan/summary.json`、`pending.json` 并行预热 |
| context prime | 已落地 | service 已加载的 score/profile/planning/pending 直接灌入 cache，避免 warm 重复打后端 |
| shadow 资源隔离 | 已落地 | shadow context 使用独立 `SandboxFileCache` 实例，不共享主链路 cache |

RequestContext 变更：

- `app/agent/context.py` 增加 `sandbox: SandboxFileCache | None` 字段。
- `app/service.py` 在主消息入口和 pending 确认执行上下文中创建 sandbox。
- 外部传入 `score_detail` 时会先转成 `ScoreDetail`，保证 sandbox 和原主链路拿到同一份成绩。

ZhiyuanAgent 读取迁移：

- `tools.py` 的 `read_state`、`explore_topic`、`query_plan` 状态读取已改为 `await ctx.deps.sandbox.read(...)`。
- `prompt.py` 的状态前置注入已改为 warmed cache 的 `sandbox.peek(...)`，不再从 `score_detail` / `planning_summary` / `init_profile` 直读。
- 缺少 sandbox 时返回明确 unavailable 状态，不再维护 direct deps fallback。

### 2.5 Phase 2 第一批：`query_plan` 真实方案扫描

`query_plan` 已从 PoC 摘要查询升级为扫描真实方案明细：

- `scope="plan"` 读取 `plan/items.json`，按工具内部 filters 扫描匹配，不再只返回 `planning_summary` 摘要。
- 支持 `school_nature`、`tier`、`school`、`major`、`tuition_max`、`province`、`limit`。
- `major` 支持 `majorName` 和 `majorItems` 中的专业/专业类匹配。
- `school` / `major` filters 会先走本地域层实体解析器归一化，再做模糊匹配。
- `scope="candidates"` 读取 `plan/candidates.json`，并把 `tier`、`province`、`school`、`major`、`limit` 下推到 `BackendAdapter.query_planning_candidate_pool(...)`。
- 结果返回 `matched_total`、`returned_total`、`items`、`truncated`，便于 shadow diff 直接对比事实命中。

### 2.6 Phase 2 第一批：`confirm_pending` 确认闭环

新增 `confirm_pending(action="confirm" | "cancel")`，并注册到 `ZhiyuanAgent`：

- 确认前读取 `pending.json`，无 active pending 时直接返回不执行。
- `cancel` 会将 pending 标记为 `cancelled`，清除本地 `conversation_phase.pending`，并失效 `pending.json`。
- `confirm` 会比较 pending 的 `sourceBackendVersion` 和当前 `plan/summary.json.version`；版本漂移时标记 `expired`，不执行后端变更。
- `intent_change` 直接从 pending 的 `executionPayload.merged` / `selectedData` 组装请求，调用 `update_planning_constraint_state(intentMode="constraint")`。
- `plan_mutation` 直接支持结构化 payload：`add_units`、`remove_units`、`move_unit` / `move_ordered_unit`、`sort_ordered_plan`、`generate_plan`、`regenerate_order`。
- 执行完成后标记 pending 为 `applied` / `failed`，并按 action 失效 `profile.json`、`constraints.json`、`plan/*`、`pending.json` 等相关虚拟文件。

为减少历史维护成本，新工具不再委托旧 `execute_plan_action`。`confirm_pending` 只接受扁平结构化 `action_family` + `atomic_actions` payload；非结构化历史 pending 会明确拒绝执行并提示重新生成预览。当前 service pending sink 也已停止写入旧 `planPayload`。

### 2.7 Phase 2 第一批：非阻塞 shadow

service shadow 从阻塞式离线对比改为后台执行：

- `_maybe_run_zhiyuan_agent_poc_shadow(...)` 只创建 shadow context 和 `asyncio.Task`，立即返回 `status=running`。
- shadow context 仍使用独立 `SandboxFileCache`，不共享主链路 cache。
- `_observability_timing_fields(...)` 在 turn event 发送前检查 task；如果已完成则注入完整 shadow，否则保留 `running`。
- task 完成后独立写 `zhiyuan_agent_poc_shadow_event`，不影响主链路响应。
- 新增 `ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE`，默认 `1.0`，离线评估保持全量，线上可降采样。

### 2.8 Phase 2 第一批延伸：`preview_intent_change` 结构化 pending + 真实 diff

`preview_intent_change` 已从纯本地预览升级为可写 active pending：

- 将 normalized intent 转成 `executionPayload.merged` 和 `selectedData.selected`，供 `confirm_pending` 直接执行。
- `constraint_type` 只保留 `exclude/only_keep/must_have`，一律进入 `intentMode=constraint`；用户交互层不再生成 `preference` pending。
- pending 使用 `kind=intent_change`、`actionFamily=apply_selected_intents`、`sourceBackendVersion=plan/summary.version`。
- 专业/院校/地域意向会基于 `RequestContext.init_profile` 构造完整 backend-format proposed profile，调 `simulate_plan_diff(...)` 生成真实 `plan_impact`。
- `plan_impact` 规范化为 `affected_count`、`affected_items`、`tier_impact`、`before_tier_counts`、`after_tier_counts`、`promoted`、`demoted`。
- `simulate_plan_diff` 不可用、返回空差异或当前没有完整画像时，降级到 `plan/items.json` 本地扫描，并在 `fallback_reason` 中标注原因。
- pending 保存成功后 prime `pending.json`，同一轮后续工具可直接读取 active pending。
- 新增 `ZHIYUAN_AGENT_PERSIST_PREVIEW_PENDING`，默认 `1`；纯 LLM 工具选择评估可设为 `0` 避免写真实后端。

限制：`career` 方向当前不在 `UserProfile.to_backend_format()` 后端画像结构中，暂不构造真实 diff，继续走本地/不可用摘要。

### 2.9 Phase 2 第三批首版：`preview_plan_action` 结构化 pending

`preview_plan_action` 已作为第 6 个工具注册到 `ZhiyuanAgent`，用于替代旧方案预览链路里的 opaque `planPayload`：

- 支持 `action=add/remove/move/replace/sort/generate/regenerate_order/pin_lock`。
- 预览阶段只创建 `pendingConfirmation`，不立即执行；确认统一交给 `confirm_pending`。
- `executionPayload` 使用结构化 `action_family` + `atomic_actions`，包含 `unit_ids`、`volunteer_ids`、`target_position`、`sort_field`、`filters` 等字段。
- `remove/move` 从 `plan/items.json` 解析当前方案项，支持 unitId/volunteerId、位置、位置范围、档位内序号、学校名、学校+专业文本匹配。
- `add/replace` 从 `plan/candidates.json` 解析候选 volunteerId；无法唯一定位时返回 `clarify`。
- `replace_units` 已补齐 `confirm_pending` 执行：remove ordered units → select working items → generate ordered plan。
- pending 保存成功后 prime `pending.json`，同轮可直接确认。

限制：候选选择质量评估和完整 ordered-plan pin/lock 执行接口仍未展开；当前优先保证结构化闭环和不依赖旧工具。`pin_lock` 已作为受控 unsupported action 进入新工具，明确不创建 pending，避免锁定/固定诉求误落到 move/no-change。

### 2.10 Phase 2 第二批：`explore_topic` 真实资料首版

`explore_topic` 从纯占位分析升级为 major/school 真实资料优先：

- `topic_type=major`：从用户问题中解析专业实体；如“计算机适合我吗”会优先归一到“计算机类”；按 level 调 `get_major_profile(...)` 或 `get_major_category_profile(...)`。
- `topic_type=school`：解析院校实体后调 `get_school_profile_by_name(...)`。
- 返回结构中新增 `entity`、`entity_level`、`profile_source`、`profile_facts`、`profile_raw`。
- `profile_facts` 只抽取核心事实字段，外层 Agent 负责自然语言综合，不再启动旧 explore 内部 LLM。
- 后端资料 API 不可用时返回 `profile_source=profile_error/profile_unavailable`，保持只读分析骨架，不阻断回复。

限制：career/region 仍是轻量摘要；专业/院校的个性化权重分析（`analyze_majors/analyze_schools`）尚未并入。

### 2.11 Phase 2 第二批：`compare_entities` 结构化对比首版

`compare_entities` 已作为第 7 个工具注册到 `ZhiyuanAgent`：

- 支持 `entity_type=major|school`，一次对比 2-5 个对象。
- 实体解析走新工具内 resolver；歧义对象返回 `clarify`，不让模型自行猜测。
- profile 数据并发获取：专业走 `get_major_profile` / `get_major_category_profile`，院校走 `get_school_profile_by_name`。
- 返回结构化 `rows`，包含 `profile_source`、`facts`、`in_current_plan`、瘦身后的 `raw`。
- 对比维度按 `comparison_focus` 做轻量筛选；外层 Agent 基于矩阵生成自然语言总结。
- 不调用旧 `major_compare_tool` / `school_compare_tool` 内部 LLM。

限制：暂未接入 `analyze_majors` / `analyze_schools` 个性化量化指标；当前先以 profile facts + 当前方案命中做只读对比。

### 2.12 Phase 2 第三批：`answer_policy` 报考政策问答首版

`answer_policy` 已作为第 8 个工具注册到 `ZhiyuanAgent`，用于替代旧 `answer_admission_policy_question` / `search_official_admission_sources` / `match_admission_rule_to_student` 的用户侧入口：

- 支持 `rule_domain=score_batch|eligibility|tuition_budget|enrollment_rules|school_rule|transfer_major|subject_requirement|physical_exam|oral_exam|general`。
- 如传入 `school_name`，先走 `school_entity_resolver` 归一化；歧义院校返回 `clarify`。
- 学校规则类问题优先读取 `get_school_profile_by_name(...)` 中的 `recruitmentPolicy`、`recruitmentPolicySourceTitle`、`recruitmentPolicySourceContent`，不启动旧学校政策工具。
- 目标学校/专业/省份先保留标准名称用于返回，再通过 `code_enrichment` 转后端编码调用 `check_plan_param_availability(...)`，避免把中文名直接传给校验接口。
- 默认离线稳定，不依赖外网搜索；`use_official_search=True` 时可调用 `search_official_admission_sources(...)` 补充官方来源结果。
- 返回结构统一为 `policy_facts`、`student_eligibility`、`source_references`、`source_lookup`，并固定 `state_mutation=false`、`next_step=respond`。

限制：官方来源检索仍是 opt-in 增强；尚未做网页事实抽取后的自动适配匹配，真实适配结论仍需后续结合 structured rule facts 扩展。

### 2.13 Phase 2 第三批：`review_plan` 方案审查首版

`review_plan` 已作为第 9 个工具注册到 `ZhiyuanAgent`，用于替代旧 `planning_workflow_tool.run_planning_review` 的用户侧入口：

- 支持 `focus=full_review|risk_only|tier_balance|tuition|career_fit`，默认按后端统一审查结果返回。
- `force_refresh=True` 时调用 `run_planning_review(...)` 执行后端审查；本地 backend 不可用时降级读取 `plan/review.json`。
- 审查结果通过 SandboxFileCache 读取和 prime，统一输出 `summary`、`issues`、`tier_balance`、`fix_proposals`。
- `generate_fix_proposals=True` 时只调用 `generate_planning_fix_proposals(...)` 读取处理方向，不自动生成/应用方案变更。
- 固定返回 `state_mutation=false`、`plan_mutation=false`、`next_step=respond`，覆盖 G21 “只读审查不应自动生成/修改方案”边界。
- 无正式方案时不调用后端审查，直接返回只读防护。

限制：首版只做结构化审查和建议摘要；核心 review issue 到删除/排序/重排预览已打通，复合范围选择、G2/G21 审查边界和更多真实 shadow case 仍需扩展。

## 3. 测试与验证结果

### 3.1 单元测试

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_base_agent.py tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_dialog_regression_runner.py tests/unit/test_request_context_new_fields.py tests/unit/test_request_context.py -q
```

结果：

```text
182 passed, 10 skipped
```

补充 RequestContext 回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_request_context_new_fields.py tests/unit/test_request_context.py -q
```

结果：

```text
17 passed
```

合并回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_base_agent.py tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_dialog_regression_runner.py tests/unit/test_request_context_new_fields.py tests/unit/test_request_context.py -q
```

结果：

```text
182 passed, 10 skipped
```

PoC 单文件回归：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q
```

结果：

```text
60 passed, 10 skipped
```

Phase 1 新增覆盖：

- `SandboxFileCache` cache hit 只调用一次 adapter。
- `invalidate(["score"])` 后强制 refetch。
- `warm(["score","profile","plan/summary","pending"])` 并行预热并命中后续读取。
- latest planning version 漂移后使 `plan/summary.json` 失效。
- `BackendAdapter` 8 个虚拟路径映射与 payload extraction。

Phase 2 第一批新增覆盖：

- `query_plan` 按 `school_nature`、`majorItems`、`tuition_max` 扫描真实 `plan/items.json`。
- `query_plan` 的属性/标签 filters 已接入 `app/domain/attribute_registry.py`，统一处理办学性质、梯度、院校/专业标签等别名和匹配。
- `query_plan(scope="candidates")` 将 query filters 下推到 `plan/candidates.json` adapter。
- `confirm_pending` 无 active pending 防护。
- `confirm_pending(cancel)` 标记 pending 为 `cancelled` 并失效 sandbox。
- `confirm_pending(confirm)` 版本漂移时标记 `expired`，不调用执行 API。
- `intent_change` pending 直接调用 `update_planning_constraint_state(intentMode="constraint")`。
- `confirm_pending(intent_change)` 有正式方案时会在要求写入成功后调用 `generate_planning_ordered_plan`，并返回 `plan_regenerated=true`；无正式方案时不会触发方案重算。
- `plan_mutation(remove_units)` 结构化 pending 直接调用 `remove_planning_ordered_plan_units`。
- 非结构化历史 pending 不再委托旧工具，统一拒绝执行并要求重新生成结构化预览。
- service 旧预览 sink 保存 plan pending 时已经转为结构化 `executionPayload`，不再产生新的 `planPayload` pending；确认端删除旧 `planPayload -> execute_plan_action` 执行尾巴和 `planPayload` 专用兼容判断。
- `resolve_pending_plan_payload_text` 已移除，pending prompt/context 不再提供任何可执行 payload 文本；短文本确认判定也不再从旧 `executionPayload.planPayload` 反解析 action family。
- service shadow 启动后先返回 `running`，后台 task 完成后更新 request context 并写 shadow event。
- service structured pending bridge 会把 4.0 `plan_mutation` pending 交给 `confirm_pending` 执行，并在成功后返回工作台刷新 followups。
- turn event 收集时可从已完成 shadow task 提取完整 shadow 结果。
- Phase 4 direct route 默认关闭但已接入主流程；禁用时不调用 agent，启用时可直接返回 4.0 只读回复或结构化 pending 确认卡。
- Phase 4 direct route 不使用字符串 precheck；确认卡创建依赖 4.0 工具返回 `next_step=confirm`、`pending_created=true`、`pending_id` 以及后端/sandbox active pending。
- Phase 4 direct route 的 intent 确认卡强制使用 `intentMode=constraint` 和“报考条件/报考要求”用户措辞。
- `preview_intent_change` 创建结构化 intent pending，并在 sandbox 中 prime `pending.json`。
- `preview_intent_change` 移除用户交互层软偏好模式，默认 `constraint_type=exclude`，只允许 `exclude/only_keep/must_have`，确认时统一写 `update_planning_constraint_state(intentMode="constraint")`。
- `preview_intent_change` 支持属性/标签 selector：`school_nature`、`school_category`、`school_level`、`program_type`、`school_tag`、`major_tag`、`major_category`，并将通用 `values` 中的“公办/民办/中外合作/985/师范”等自动归入属性维度。
- `confirm_pending(intent_change)` 将属性 selector 编码为现有后端可接受的 hard scope 字符串，如 `院校性质:民办`，不进入软偏好。
- Prompt 路由已对齐 §8.3：裸属性诉求和明确长期要求进入 `preview_intent_change`；当前方案锚定的属性筛选移出、具体项、位置编号和审查问题处理进入 `preview_plan_action`。
- 用户可见回复已清理系统术语：新 agent 工具文案不再输出“约束/硬性要求”，旧链路 sanitizer 兜底将“约束”改写为“要求”。
- `zhiyuan-server` hard constraint 过滤支持属性 scope 匹配，候选/专业组修复链路会按院校性质、招生类型、院校类型、院校层次、专业标签等过滤。
- Prompt 边界已收紧：分数/位次等 policy 问题必须走 `answer_policy`；“审查问题 + 移出/替换/排序/重排/重新调整/处理”直接走 `preview_plan_action`，不先落到只读 `review_plan`。
- `preview_intent_change` 成功接入 `simulate_plan_diff`，保存 pending 时同步保存真实 `planImpact`。
- `preview_intent_change` 在 diff 不可用时保留本地扫描降级路径，不阻断确认流程。
- `preview_plan_action(remove)` 创建结构化 `plan_mutation/remove_units` pending，payload 不包含旧 `planPayload`。
- `preview_plan_action(remove, filters=...)` 可按注册表属性/标签扫描 `plan/items.json` 并生成 `unit_ids`，覆盖“方案里的民办不要了”这类当前方案筛选移出表达。
- `preview_plan_action(remove, filters=...)` 已补充覆盖 `program_type=中外合作`、`school_category=理工/师范`、`school_level=985`，无命中时返回 `respond` 且不创建 pending。
- `preview_plan_action(move)` 能定位当前方案项并在缺目标位置时要求澄清；已支持 `第31-32个` 这类位置范围，以及 G17 风格 `tier + admission_ratio max + target_tier/target_ordinal` 的档位内局部重排。
- `preview_plan_action(pin_lock)` 对“锁定/固定位置”返回受控 unsupported，不创建 pending，不再误走移动/no-change。
- `program_type` 增加 `强基`/`强基计划` 归一，G30 风格“清华北大复旦的强基”会保留院校 + 招生路径 selector，确认后编码为 `招生类型:强基` hard scope。
- `preview_plan_action(add)` 从 `plan/candidates.json` 解析候选 volunteerId 并创建结构化 `add_units` pending。
- `preview_plan_action(review_issue_code=high_tuition)` 能从 `plan/review.json` 的 affected units 解析审查问题范围，用于“把审查里的高收费项移出去”这类明确处理动作。
- `preview_plan_action(review_issue_code=cooperative_program)` 支持中外合作审查问题；后端返回 `cooperative`、`sino_foreign` 或中文摘要时会规范到 `cooperative_program`，并透传 `source_code` 便于排查。
- `preview_plan_action(review_issue_code=admission_limit|special_enrollment)` 已支持限报/特殊招生等 item 风险问题的 affected units 删除预览。
- `preview_plan_action(review_issue_code=...)` 支持后端只返回 `affectedVolunteerIds` / `affectedItems[].volunteerId` 的情况，会反查 `plan/items.json` 生成执行用 `unit_ids`。
- `preview_plan_action(remove, review_issue_code=..., filters=...)` 支持审查问题范围与属性 filters 求交集，例如“高收费且民办”；无交集时不创建 pending。
- `preview_plan_action(action=sort|regenerate_order, review_issue_code=...)` 支持围绕录取率倒挂、梯度/冲稳保断层、保底不足等结构性审查问题创建排序/重排 pending，payload 带 `review_issue_target`，不把只读审查当处理终点。
- `preview_plan_action(replace + review_issue_code)` 在 `plan/candidates.json` 可用时可保守自动选择替换候选；候选池不可用/无命中时要求澄清，不用只读审查替代方案变更预览。
- `confirm_pending` 直接执行结构化 `replace_units`，串联 remove/select/regenerate。
- `explore_topic(major)` 接入 major/category profile API，并在“计算机”歧义时优先归一到“计算机类”。
- `explore_topic(school)` 接入 school profile API。
- `explore_topic` API 失败时保持只读降级，不影响回复。
- `compare_entities(major)` 并发获取专业/专业类 profile，返回结构化对比矩阵。
- `compare_entities(school)` 并发获取院校 profile，并标注当前方案是否包含对应院校。
- `compare_entities` 在对象数量不足时要求澄清。
- `answer_policy(score_batch)` 返回只读政策框架，不触发状态变更。
- `answer_policy(transfer_major)` 读取 school profile 招生政策字段并返回来源引用。
- `answer_policy(subject_requirement)` 将学校/专业标准名称转成后端编码后调用 `check_plan_param_availability`。
- `answer_policy(use_official_search=True)` 可纳入官方来源检索结果。
- `ZhiyuanAgent` 可在 `answer_policy` 返回 `next_step=respond` 后直接回复。
- `review_plan` 可直接读取 sandbox 审查结果，不触发方案变更。
- `review_plan(force_refresh=True)` 调用 `run_planning_review` 后刷新 `plan/review.json` cache。
- `review_plan(generate_fix_proposals=True)` 只返回修复建议，不自动改方案。
- `review_plan` 无正式方案时不调用审查接口，返回只读防护。
- `ZhiyuanAgent` 可在 `review_plan` 返回 `next_step=respond` 后直接回复。
- pending 保存失败时不假装可确认，返回 `pending_created=false`。

### 3.2 真实 LLM 工具选择测试

```bash
cd zhiyuan-agent
RUN_ZHIYUAN_AGENT_POC=1 .venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -v -s -k LLMSelection
```

结果：

```text
10 passed, 59 deselected
```

本轮在受限网络下首次运行出现 LLM DNS 连接失败；放开网络后使用 `ZHIYUAN_AGENT_PERSIST_PREVIEW_PENDING=0` 重跑通过，避免工具选择评估写入真实 pending。

2026-06-30 接入 `simulate_plan_diff` 后再次重跑真实 LLM 工具选择：`5 passed, 34 deselected`。本地 backend 未启动时 diff 调用连接 `localhost:8080` 失败，工具按预期降级到本地扫描，不影响离线工具选择评估。

2026-06-30 注册 `preview_plan_action` 后再次重跑真实 LLM 工具选择：`5 passed, 38 deselected`，原 5 个 PoC 场景未被新方案操作工具误吸收。

2026-06-30 `explore_topic` 接入 major/school profile API 后再次重跑真实 LLM 工具选择：`5 passed, 40 deselected`。本地 backend 未启动时 profile 调用失败，工具按预期降级，不影响离线工具选择评估。

2026-06-30 注册 `compare_entities` 后再次重跑真实 LLM 工具选择：`5 passed, 43 deselected`，原 5 个 PoC 场景未被对比工具误吸收。

2026-06-30 注册 `answer_policy` 后联网重跑真实 LLM 工具选择：`6 passed, 48 deselected`，新增 `分数和位次怎么参考` 稳定选择 `answer_policy`。本地 backend 未启动时 profile/diff 调用失败并降级，不影响工具选择评估。

2026-06-30 注册 `review_plan` 后联网重跑真实 LLM 工具选择：`7 passed, 53 deselected`，新增 `审查一下当前方案` 稳定选择 `review_plan`。本地 backend 未启动时审查调用失败并降级读取 sandbox，不影响工具选择评估。

2026-06-30 增加 `review_issue_code` 联动并收紧 `review_plan` / `preview_plan_action` 边界后，联网重跑真实 LLM 工具选择：`8 passed, 56 deselected`。新增 `把审查里的高收费项移出去` 稳定选择 `preview_plan_action(action="remove", review_issue_code="high_tuition")`，不再误把只读 `review_plan` 当作处理终点。

2026-06-30 扩展中外合作 review issue 联动、收窄 `review_issue_code` schema 为枚举并加入 issue alias/canonical 匹配后，联网重跑真实 LLM 工具选择：`9 passed, 57 deselected`。新增 `把审查里的中外合作项移出去` 稳定选择 `preview_plan_action(action="remove", review_issue_code="cooperative_program")`。

2026-06-30 扩展梯度 review issue 联动后，联网重跑真实 LLM 工具选择：`10 passed, 59 deselected`。新增 `按审查里的梯度问题重新调整排序` 稳定选择 `preview_plan_action(action="regenerate_order", review_issue_code="tier_gap")`。同轮发现 `建议考公吗` 偶发直接回复，已收紧 career prompt 边界，复跑通过。

2026-07-01 按 v1.1 设计移除用户交互层软偏好后，联网重跑真实 LLM 工具选择：`10 passed, 60 deselected`。`不要医学类` 仍稳定选择 `preview_intent_change`，`不要排除经济学类` 不再允许 `constraint_type=preference`；本地 backend 未启动导致 diff/profile/review 读取降级，不影响离线工具选择评估。

2026-07-01 补齐属性/标签 intent selector 与 Java hard constraint scope 匹配后，离线验证通过：

```text
zhiyuan-agent: 63 passed, 10 skipped
zhiyuan-server: RepairCandidateEligibilityTest, RepairDryRunSimulatorTest passed
```

2026-07-01 继续补强属性 selector 与真实 LLM 工具选择：

- 离线 PoC：`67 passed, 14 skipped`。
- Python 核心集合：`189 passed, 14 skipped`。
- Java 相关测试：`RepairCandidateEligibilityTest, RepairDryRunSimulatorTest, PlanningStateServiceTest` 通过。
- 真实 LLM selection：`14 passed, 67 deselected`。本地 backend 未启动导致 diff/profile/review 读取降级到 sandbox，不影响工具选择结论。
- 新增真实 LLM 覆盖：`不要民办学校`、`只看公办学校`、`不要中外合作`、`不要师范类院校` 均稳定选择 `preview_intent_change` 并带属性 selector。
- 同轮发现 `分数和位次怎么参考` 偶发直接回复、`按审查里的梯度问题重新调整排序` 偶发先走 `review_plan`；已收紧 prompt 边界并复跑通过。

覆盖场景：

| 场景 | 预期工具 | 结果 |
|------|----------|------|
| `不要医学类` | `preview_intent_change` + negative | 通过 |
| `计算机适合我吗` | `explore_topic` | 通过 |
| `方案里有没有民办` | `query_plan` | 通过 |
| `不要排除经济学类` | `preview_intent_change` + positive | 通过 |
| `不要民办学校` | `preview_intent_change(intent_type=school, negative.school_nature=民办)` | 通过 |
| `只看公办学校` | `preview_intent_change(intent_type=school, positive.school_nature=公办, constraint_type=only_keep)` | 通过 |
| `不要中外合作` | `preview_intent_change(intent_type=school, negative.program_type=中外合作)` | 通过 |
| `不要师范类院校` | `preview_intent_change(intent_type=school, negative.school_category=师范)` | 通过 |
| `建议考公吗` | `explore_topic(topic_type=career)` | 通过 |
| `分数和位次怎么参考` | `answer_policy` | 通过 |
| `审查一下当前方案` | `review_plan` | 通过 |
| `把审查里的高收费项移出去` | `preview_plan_action(review_issue_code=high_tuition)` | 通过 |
| `把审查里的中外合作项移出去` | `preview_plan_action(review_issue_code=cooperative_program)` | 通过 |
| `按审查里的梯度问题重新调整排序` | `preview_plan_action(action=regenerate_order, review_issue_code=tier_gap)` | 通过 |

2026-07-01 继续补强 G16/G17/G30：

- 离线 PoC：`72 passed, 17 skipped`。
- Python 核心集合：`194 passed, 17 skipped`。
- Java hard constraint：`RepairCandidateEligibilityTest` 通过。
- 真实 LLM selection：`17 passed, 72 deselected`。
- G16：`帮我把方案里第1个和第2个冲档锁定 位置不要动` 稳定选择 `preview_plan_action(action=pin_lock)`，返回 unsupported 且不创建 pending。
- G17：`帮我把保底区里录取率最高的那个调到保底的第一位` 稳定选择 `preview_plan_action(action=move, filters=...)`，保留档位 scope 和录取率 selector。
- G30：`清华北大复旦的强基都加进意向` 稳定选择 `preview_intent_change`，同时保留学校和 `program_type=强基`，不退化为普通院校偏好。

2026-07-01 继续补强 review issue 覆盖：

- 离线 PoC：`75 passed, 20 skipped`。
- `review_issue_code` 扩展到后端当前 preview-fixable 核心规则：高收费、中外合作、限报、特殊招生、录取率倒挂、概率断层、数量校验、边缘分、本省保底不足、非意向托底、组内安全垫不足，并保留 `tier_gap/low_safety/career_mismatch` 语义别名。
- 新增工具选择锚点：`把审查里的限报项移出去`、`按审查里的录取率倒挂重新排序`、`按审查里的保底不足重新调整方案` 均稳定进入 `preview_plan_action`。

2026-07-01 维护成本收敛：

- `review_issue_code` 归一化已下沉到共享 `app/tools/review_issue_registry.py::normalize_review_issue_code`，新 agent 不再维护独立 issue alias 大表；`preview_plan_action` 只保留用户侧 `tier_gap` canonical 与后端 `ratio_distribution` 的 source_code 兼容。
- 回归：`tests/regression/test_keyword_matchers.py + tests/unit/test_zhiyuan_agent_poc.py` 为 `116 passed, 20 skipped`；Python core + registry 集合为 `238 passed, 20 skipped`。

2026-07-01 继续补强 replace 候选选择：

- `preview_plan_action(action=replace, review_issue_code=...)` 在用户未指定候选、且候选池已缓存/可读时，会按同档位、同省、学费降低、规避当前 review issue 风险标签等保守规则自动选择替换候选，写入结构化 `replace_units` payload。
- 候选池不可用或无候选仍返回 `clarify`，不编造候选、不回退旧 `execute_plan_action`。
- 回归：离线 PoC `76 passed, 20 skipped`；Python core + registry 集合 `239 passed, 20 skipped`。

2026-07-01 补齐 G2/G21 审查边界：

- G2 `方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动`：prompt 明确收敛为 `review_plan(focus=tuition, generate_fix_proposals=True)`，只读返回处理方向，不创建 pending。
- G21 `现在这版强基+普通批方案合理不`：真实 LLM 工具选择约束为 `review_plan` / `query_plan` 只读路径，禁止同轮 `preview_plan_action(generate|regenerate_order)`。
- `review_plan` 无正式方案 guard 增加生成接口断言：不会调用 `generate_planning_initial_plan` / `generate_planning_ordered_plan`。
- 真实 LLM selection 子集：`2 passed`。本地 backend 未启动时 `run_planning_review` / `generate_planning_fix_proposals` 降级失败日志可接受，不影响工具选择结论。
- 回归：Python core + registry 集合 `239 passed, 22 skipped`。

2026-07-01 补强复合审查范围：

- `preview_plan_action(remove, review_issue_code=..., filters=...)` 已支持先按 `plan/review.json` 定位审查问题命中项，再按属性 filters 求交集；无交集时返回 `respond` 且不创建 pending。
- 新增真实 LLM selection：`把审查里的高收费且民办的项移出去` 稳定选择 `preview_plan_action(review_issue_code=high_tuition, filters.school_nature=民办)`，`1 passed`。
- 回归：离线 PoC `78 passed, 23 skipped`；Python core + registry 集合 `241 passed, 23 skipped`。

2026-07-01 补充真实口语验证口径：

- 新增 `examples/dialog_regression_400_realistic_user_cases.json`，专门覆盖真实用户更常见的短句、省略、上下文指代和口语表达。该集合与书面化能力 case 并行保留，不替代原有验收 case。
- 覆盖样例包括：`有啥问题，咋弄`、`那高收费的别要了`、`民办的不要`、`里面有民办没`、`贵的合作的这些怎么处理，先别动`、`中外合作都不要了`、`民办就算了`、`太贵是不是就不建议冲`、`经济学别给我排掉`、`考公这条路靠谱吗`。
- `dialog_regression_runner.py` 已支持逐 step 断言 `zhiyuanAgentPocShadow` 的首工具、完整工具序列、`next_step` 和工具调用上限，后续真实 service shadow 可以直接把口语 case 纳入质量门禁。
- 该集合当前是验证资产和断言能力落地，尚未完成真实 websocket 复跑；下一轮应使用 `ZHIYUAN_AGENT_POC_SHADOW=1` 跑该文件，并按失败结果决定是下沉 schema/registry/tool validation，还是保留极少量 prompt 锚点。

2026-07-01 按最新设计修正口语 case 语义边界：

- 裸属性诉求保持 `preview_intent_change`，例如“民办的不要”“中外合作都不要了”；这类更像用户在表达报考要求。
- 当前方案锚定的筛选移出保持 `preview_plan_action(remove, filters=...)`，例如“方案里的民办不要了”“当前这些中外合作都移出去”；用户最明确的诉求是调整当前方案，不自动推断为隐含长期要求。
- 新增 `第3个不要了` 作为 `preview_plan_action(action=remove)` 对照，确保具体位置操作仍走方案操作。
- 本地验证：`examples/dialog_regression_400_realistic_user_cases.json` JSON 解析通过；`tests/unit/test_zhiyuan_agent_poc.py -q` 为 `82 passed, 26 skipped`；`tests/unit/test_dialog_regression_runner.py -q` 为 `84 passed`。

2026-07-01 真实 LLM + service shadow 口语验证：

- 真实 LLM selection：`RUN_ZHIYUAN_AGENT_POC=1 .venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -v -s -k LLMSelection`，结果 `26 passed, 82 deselected`。按当时断言，`民办的不要`、`中外合作都不要了`、`经济学别给我排掉` 均稳定走 `preview_intent_change`，`第3个不要了` 仍走具体方案操作。
- 真实 websocket shadow：使用隔离后端 `127.0.0.1:18290` 和 agent `127.0.0.1:8039` 跑 `examples/dialog_regression_400_realistic_user_cases.json`，metrics 输出 `/private/tmp/zhiyuan_400_realistic_user_shadow_after_intent_regen.json`。
- 原断言口径总体结果：`steps=14`，`successfulSteps=9`，`failedSteps=5`；`zhiyuanAgentPocShadow.observed=12`，12 次 shadow 均 `success`，每轮 `toolCallCount=1`；shadow 耗时 `median=3182ms`，`max=19288ms`，明显低于主链多轮完整回答耗时。
- 按修正后的语义口径重新归类：`方案里的民办不要了` 和 `当前这些中外合作都移出去` 不再算 4.0 错例；它们走 `preview_plan_action` 可以被视为合理的当前方案调整。真实剩余问题主要集中在旧主链口语否定、policy 问句误建 pending、shadow observability 缺口和耗时。
- 4.0 shadow 工具分布：`review_plan=3`、`preview_intent_change=4`、`preview_plan_action=3`、`query_plan=1`、`explore_topic=1`；说明 4.0 新工具框架在只读审查、要求变更、方案操作、查询和探索五类任务上都能触发对应工具。
- 有效通过点：`方案里的民办不要了` 在 4.0 shadow 中选择 `preview_plan_action(remove, filters.school_nature=民办)`，符合“当前方案锚定筛选移出”的修正口径；主链实际走 `intent_change` 确认卡，属于旧链路和新口径不一致，但不影响 4.0 shadow 判断。
- 待修复 1：`当前这些中外合作都移出去` 在 4.0 shadow 中选择 `preview_plan_action`，方向可接受；主链落到 `runtime_intent_profile_plan_reroute` 的只读/建议回复，没有生成确认卡，需要修主链或切到 4.0 路由。
- 已修复 2：`民办就算了` 不再修旧链路；4.0 direct 侧通过 prompt/schema 工具选择收紧，将“算了/就算了/别考虑了/不用看”归为显式不要表达，稳定进入 `preview_intent_change(intent_type=school, negative.school_nature=民办)` 并生成报考条件确认卡。
- 待修复 3：`太贵是不是就不建议冲` 当前主链误建 `intent_change` 确认卡；这类问句应作为学费/预算/风险取舍的只读咨询，不应直接创建 pending。本轮没有拿到 shadow 观测，需补齐 fast/direct path 的 shadow observability。
- 观测问题：`第3个不要了` 主链正确生成 `plan_mutation/remove_ordered_unit` pending，但 runner 未拿到 shadow 结果；`太贵是不是就不建议冲` 也缺 shadow。需要让 direct/fast route 和 runtime hard-cut 路径统一附带 `zhiyuanAgentPocShadow`，否则无法完整评估 4.0。
- 下一步修复口径：不是收紧属性-only remove，而是明确分流。裸属性诉求和明确长期要求走 `preview_intent_change`；当前方案锚定的“移出/删除/不要了”走 `preview_plan_action(remove, filters=...)`；审查 issue 联动继续走 `preview_plan_action(review_issue_code=...)`。
- 修正断言后复跑：离线 `tests/unit/test_zhiyuan_agent_poc.py -q` 为 `82 passed, 26 skipped`，`tests/unit/test_dialog_regression_runner.py -q` 为 `84 passed`；真实 LLM selection 非沙箱复跑 `26 passed, 82 deselected`。沙箱内真实 LLM 失败是 DNS/network `nodename nor servname provided, or not known`，不是语义断言失败。

2026-07-01 补齐 4.0 shadow observability：

- service 保存主 turn 历史时，如果 `request_context._zhiyuan_agent_poc_shadow` 已是完成态，会同步追加 `zhiyuan_agent_poc_shadow_event` route-observability message，避免后台 shadow 先写入后被主链路保存覆盖。
- `_save_direct_guard_history`、runtime hard cut、direct local/atomic plan action、runtime intent profile plan reroute、semantic/profile replan 和 full-agent 成功/异常恢复保存路径已接入统一 `_append_turn_observability_messages`。
- `dialog_regression_runner.py` 新增 `--poc-shadow-wait-seconds`，仅在 step 声明 `expectedZhiyuanAgentPoc*` / `maxZhiyuanAgentPocToolCallCount` 时等待 shadow 完成后再读取 history；普通回归不增加等待。
- 新增单测覆盖：direct guard history 会追加完成态 shadow event；runner 只对 shadow 断言 step 开启等待。
- 验证：`tests/unit/test_zhiyuan_agent_poc.py -q` 为 `83 passed, 26 skipped`；`tests/unit/test_dialog_regression_runner.py -q` 为 `85 passed`。

2026-07-01 Phase 4 direct route 接入验证：

- 新增单测覆盖 direct disabled 不调用 agent、direct `preview_plan_action` 生成方案调整确认卡、direct `preview_intent_change` 生成报考条件确认卡、direct `answer_policy` 只读回复不生成确认卡。
- 新增/保留 service pending bridge 单测覆盖：结构化 `plan_mutation/remove_units` pending 通过 `handle_pending_confirmation` 调用 4.0 `confirm_pending` 执行，成功后返回 ordered/review 工作台刷新。
- 验证命令：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k "zhiyuan_agent_direct or service_pending_confirmation_uses_structured_plan_bridge or confirm_pending_rejects_non_structured_plan_payload"`，结果 `7 passed, 107 deselected`。
- 全量 PoC 单测：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q`，结果 `88 passed, 26 skipped`。
- 真实 service direct 已完成首轮验证，见下一条。

2026-07-01 Phase 4 direct route 真实口语复跑：

- 修复内容：4.0 prompt 明确“X算了/X就算了/X别考虑了/X不用看”属于显式不要；裸属性/标签/类别 + 这类否定表达走 `preview_intent_change`，只有带“方案里/当前方案/当前这些/里面这些/这批/这些/这几个”等当前方案锚点才走 `preview_plan_action(remove, filters=...)`。
- 新增真实 LLM selection 回归：`test_spoken_private_school_attribute_intent`，`民办就算了` 稳定选择 `preview_intent_change`；非沙箱运行结果 `1 passed, 114 deselected`。沙箱内 DNS/network 失败不计入语义结果。
- 基础单测回归：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k "zhiyuan_agent_direct or review_plan or service_pending_confirmation_uses_structured_plan_bridge"`，结果 `35 passed, 80 deselected`。
- 真实 service direct：开启 `ZHIYUAN_AGENT_ENABLED=true`、`ZHIYUAN_AGENT_POC_SHADOW=1` 跑 `examples/dialog_regression_400_realistic_user_cases.json`，metrics 输出 `/private/tmp/zhiyuan_400_realistic_user_direct_enabled_after_private_fix.json`。
- 结果：`steps=14`，`successfulSteps=14`，`failedSteps=0`；全部 `routingPath=zhiyuan_agent_direct`。
- direct 工具分布：`review_plan=3`、`preview_plan_action=4`、`preview_intent_change=4`、`query_plan=1`、`answer_policy=1`、`explore_topic=1`。
- shadow 同步结果：`observed=14`，`statuses.success=14`，每轮 `toolCallCount=1`；shadow 耗时 `median=2645ms`、`max=6439ms`，总 tokens `median=3830`。
- 关键修复样本：`民办就算了` direct 与 shadow 首工具均为 `preview_intent_change`，生成 `pendingConfirmationCard`，用户可见文案为“报考条件 / 院校要求：不要：民办”，未出现“约束/硬约束/软偏好”。

### 3.3 真实 service websocket shadow 对比

运行方式：

```bash
cd zhiyuan-agent
PYTHONPATH=. ZHIYUAN_REGRESSION_BACKEND_URL=http://127.0.0.1:8080 \
  .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases /private/tmp/zhiyuan_agent_poc_compare_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_400_poc_shadow_compare.json
```

结果：

```text
steps=5
successfulSteps=5
failedSteps=0
summary.zhiyuanAgentPocShadow.observed=5
summary.zhiyuanAgentPocShadow.statuses.success=5
```

逐 case 对比：

| Case | 主链路 routingPath | 主链路耗时 ms | 主链路工具数 | PoC 首工具 | PoC 耗时 ms | PoC tokens |
|------|--------------------|---------------|--------------|------------|-------------|------------|
| `poc-exclude-medical` | `full_agent` | 34844 | 1 | `preview_intent_change` | 2674 | 1227 |
| `poc-explore-computer-fit` | `full_agent` | 26882 | 1 | `explore_topic` | 1373 | 1219 |
| `poc-query-private-plan` | `full_agent` | 24997 | 1 | `query_plan` | 1261 | 1218 |
| `poc-double-negation-economics` | `runtime_intent_hard_cut` | 33607 | 0 | `preview_intent_change` | 2815 | 1223 |
| `poc-career-civil-service` | `full_agent` | 30034 | 1 | `explore_topic` | 1400 | 1219 |

PoC shadow 汇总：

```text
observed=5
success=5
firstTools:
  preview_intent_change=2
  explore_topic=2
  query_plan=1
nextSteps:
  confirm=2
  respond=3
durationMs:
  min=1261
  median=1400
  max=2815
toolCallCount:
  median=1
  max=1
totalTokens:
  min=1218
  median=1219
  max=1227
```

2026-07-01 真实口语 service shadow 复跑 `examples/dialog_regression_400_realistic_user_cases.json`：`14/14` shadow success，`zhiyuanAgentPocShadow.observed=14`。主链路 `13/14` successful，唯一失败是 `当前这些中外合作都移出去` 没有生成确认卡，落到旧链只读/建议回复；4.0 shadow 对应首工具为 `preview_plan_action(remove, filters.program_type=中外合作)`，已作为切换 direct route 的依据。

2026-07-01 真实口语 service direct 复跑同一集合：`14/14` successful，全部 `routingPath=zhiyuan_agent_direct`；`当前这些中外合作都移出去` 进入 `preview_plan_action(remove, filters.program_type=中外合作)` 并生成方案调整确认卡，`民办就算了` 进入 `preview_intent_change` 并生成报考条件确认卡。metrics: `/private/tmp/zhiyuan_400_realistic_user_direct_enabled_after_private_fix.json`。

2026-07-02 structured pending cleanup 后真实 direct 复跑：

- 确认执行闭环：`examples/dialog_regression_400_direct_confirm_execution_cases.json`，`steps=4`、`successfulSteps=4`、`failedSteps=0`，metrics: `/private/tmp/zhiyuan_400_direct_confirm_after_structured_pending_cleanup.json`。
- 关键链路：`第3个不要了` 首轮 `preview_plan_action` 生成结构化 `plan_mutation/remove_units` pending，确认轮 routingPath=`pending_plan_structured_short_text_confirm`，tool trace=`confirm_pending`，返回 ordered/review 工作台刷新；没有回退旧 `execute_plan_action`。
- 真实口语 direct：`examples/dialog_regression_400_realistic_user_cases.json`，`steps=14`、`successfulSteps=14`、`failedSteps=0`，shadow `observed=14/statuses.success=14`，direct 工具分布 `review_plan=3`、`preview_plan_action=4`、`preview_intent_change=4`、`query_plan=1`、`answer_policy=1`、`explore_topic=1`，metrics: `/private/tmp/zhiyuan_400_realistic_direct_after_structured_pending_cleanup.json`。
- G case direct 子集：`examples/dialog_regression_400_g_case_direct_subset.json`，`steps=8`、`successfulSteps=8`、`failedSteps=0`，shadow `observed=8/statuses.success=8`，metrics: `/private/tmp/zhiyuan_400_g_case_direct_after_structured_pending_cleanup.json`。

2026-07-02 重启电脑后恢复本地服务并发复跑：

- 环境恢复：`scripts/start-all.sh` 后台进程在当前执行环境中没有保活；本轮改为以前台会话保持 `zhiyuan-rank:5001`、`zhiyuan-server:8080`、临时 `zhiyuan-agent:8042` 运行。
- runner 注意事项：`dialog_regression_runner.py` 当前没有内建 `--concurrency` 参数；本轮按 case 文件拆成多个 runner 进程并发跑。重启后必须显式传 `--internal-service-url http://127.0.0.1:8080`，否则默认 `18290` 会导致 backend state clone / pending clear 环境失败。
- 确认执行闭环：`examples/dialog_regression_400_direct_confirm_execution_cases.json`，`steps=4`、`successfulSteps=4`、`failedSteps=0`，metrics: `/private/tmp/zhiyuan_400_direct_confirm_after_reboot_8080.json`。关键链路仍为 `第3个不要了 -> preview_plan_action`，`确认执行 -> pending_plan_structured_short_text_confirm + confirm_pending`，没有回退旧 `execute_plan_action`。
- 真实口语 direct：`examples/dialog_regression_400_realistic_user_cases.json`，`steps=14`、`successfulSteps=14`、`failedSteps=0`，shadow `observed=14/statuses.success=14`，metrics: `/private/tmp/zhiyuan_400_realistic_after_reboot_8080.json`。覆盖短句/指代/省略/双重否定，如“有啥问题，咋弄”“那高收费的别要了”“民办的不要”“经济学别给我排掉”。
- G case direct 子集：`examples/dialog_regression_400_g_case_direct_subset.json`，`steps=8`、`successfulSteps=7`、`failedSteps=1`，shadow `observed=8/statuses.success=8`，metrics: `/private/tmp/zhiyuan_400_g_case_direct_after_reboot_8080.json`。
- 新问题 G25：`把生物医学工程和智能医学工程加意向 排除临床医学和口腔` 期望一次 `preview_intent_change`；主 direct agent 实际调用两次 `preview_intent_change`，触发 `expectedToolNames` 和 `maxToolCallCount` 断言失败。最终用户可见 pending 只展示“不要：临床医学、口腔医学”，漏掉“要：生物医学工程、智能医学工程”。同轮 shadow 的首工具参数是单次完整结构：`positive.level2=[生物医学工程, 智能医学工程]` + `negative.level2=[临床医学, 口腔医学]`，说明工具 schema 可表达该诉求，问题在 direct route 多工具结果合并/渲染策略。

2026-07-02 G25 修复后复跑：

- 单测：`py_compile app/zhiyuan_agent/agent.py app/zhiyuan_agent/tools.py tests/unit/test_zhiyuan_agent_poc.py` 通过；`tests/unit/test_zhiyuan_agent_poc.py -q` 为 `91 passed, 27 skipped`。
- G25 单 case：`examples/dialog_regression_400_g_case_direct_subset.json --case-name 400-g25-mixed-positive-negative-intent-polarity`，`steps=1`、`successfulSteps=1`、`failedSteps=0`，tool trace 单次 `preview_intent_change`，卡片 summary=`专业要求：要：生物医学工程、智能医学工程；不要：临床医学、口腔医学`，`constraintIntentType=must_have`，metrics: `/private/tmp/zhiyuan_400_g25_after_mixed_constraint_fix.json`。
- G case direct 子集：`examples/dialog_regression_400_g_case_direct_subset.json`，`steps=8`、`successfulSteps=8`、`failedSteps=0`，shadow `observed=8/statuses.success=8`，shadow/tool call count max=1，metrics: `/private/tmp/zhiyuan_400_g_case_direct_after_g25_full_fix.json`。
- 确认执行闭环：`examples/dialog_regression_400_direct_confirm_execution_cases.json`，`steps=4`、`successfulSteps=4`、`failedSteps=0`，metrics: `/private/tmp/zhiyuan_400_direct_confirm_after_g25_fix.json`。
- 真实口语 direct：`examples/dialog_regression_400_realistic_user_cases.json`，`steps=14`、`successfulSteps=14`、`failedSteps=0`，shadow `observed=14/statuses.success=14`，工具调用数 max=1，metrics: `/private/tmp/zhiyuan_400_realistic_after_g25_fix.json`。

2026-07-02 320 G1-G32 direct 完整回归问题整理（仅记录，暂不修复）：

- 回归结果：`examples/dialog_regression_320_g1_g32_shadow_cases.json`，`steps=49`、`successfulSteps=46`、`failedSteps=3`；metrics: `/private/tmp/zhiyuan_400_direct_320_g1_g32_after_g17_g27_fix.json`。
- 失败分布：断言失败集中在 G4、G17、G25 三个 case；runner 记录为 `content=3`、`tool=1`，其中 G17 同时缺少期望的 `pendingConfirmationCard` 和 `move_ordered_unit`。
- 性能观察：主链路有效记录 median `6312ms`、p95 `26970ms`、max `51651ms`；shadow 完成记录 median `3082ms`、p95 `6124ms`、max `9323ms`。最慢 case 是 G21 “万一强基没过校测普通批怎么衔接”。
- Shadow 观察：`observed=49`，其中 `success=43`、`running=6`；`running` 主要出现在非阻塞 shadow 尚未完成的 turn event，需要以独立 shadow event 或等待参数确认完整结果。

本轮断言失败：

| Case | 用户表达 | 实际结果 | 客观问题 |
|------|----------|----------|----------|
| G4 | `那把网络与新媒体作为优先方向，跨境电商也可以考虑` | direct 生成 `preview_intent_change`，卡片展示“要：网络与新媒体、电子商务”，未出现“跨境” | 用户原词“跨境电商”在可见文案中被归一成“电子商务”；同时该表达含“优先/也可以考虑”，与 4.0 当前“只处理显式要/不要”的口径存在待确认空间 |
| G17 | `帮我把保底区里录取率最高的那个调到保底的第一位` | direct 调用 `preview_plan_action`，回复“还没有唯一定位到要调整的方案项”，未生成确认卡 | 档位内按录取率选择并移动到目标位置未稳定形成 `move_ordered_unit`；同类聚焦回归曾通过，完整回归中仍有不稳定表现 |
| G25 | `把生物医学工程和智能医学工程加意向 排除临床医学和口腔` | direct 卡片只展示“要：生物医学工程、智能医学工程”，漏掉“不要：临床医学、口腔医学” | 同一句混合正向“加意向”和负向“排除”时，负向部分在本次完整回归中丢失；与此前 G case 子集通过结论不一致，需要后续用最新服务进程重跑确认稳定性 |

本轮通过但需要记录的问题/观察：

| 类别 | Case/表达 | 现象 | 影响 |
|------|-----------|------|------|
| 复合诉求处理 | G12 `高收费的志愿占比多少 能不能换成便宜的` | 只走 `query_plan`，回答当前方案列表，没有形成“换成便宜的”调整预览 | “查询 + 调整”复合表达只处理了只读部分，方案调整诉求未被承接 |
| pending 下只读策略问答 | G21 `万一强基没过校测普通批怎么衔接` | 落到 `full_agent`，调用旧 `execute_plan_action`，耗时 `51651ms`，回复为“这次没有形成可确认的调整预览” | 用户问的是只读策略/政策衔接，实际回复偏系统失败兜底，且耗时最高 |
| pending 下 policy 问答 | G21 `强基进去后是不是就不能转专业了` | 落到 `full_agent` 而非 direct，内容可读但耗时 `29741ms` | active pending 存在时，独立只读政策问答仍可能回旧链路，性能和结构不稳定 |
| 无正式方案 add 意向 | G21 `那把南大和上交大的强基也补上` | 主链路认为需要正式方案，回复不写入报考偏好；shadow 认为可走 `preview_intent_change` | “补上”在无方案但有强基上下文时，当前方案操作和报考要求之间存在路由分歧 |
| 档案修正状态 | G22/G31 `湖北/620/物化生` 多轮修正 | 文本中承认新信息，但后续查询仍读取旧档案 `湖南 548 历史/生物/政治` | 用户口头修正未形成可确认/可持久化的状态更新，后续方案查询基于旧档案 |
| 初始成绩抽取 | G23 `我575分安徽物化生先看看` | direct 调 `read_state` 后回复“当前还没有拿到成绩信息” | 用户输入里已有成绩、省份、选科，但 4.0 direct 没有沉淀到 profile/score 流程 |
| 显式专业意向承接 | G23 `想学计算机或电子信息` | direct 只继续追问；shadow 首工具为 `preview_intent_change` | “想学 X”这类口语正向诉求是否应进入报考要求，当前 direct 与 shadow 不一致 |
| 软性偏好口径 | G23 `城市优先长三角`、G29 `网络与新媒体优先，跨境电商也可以考虑` | 仍可能走“报考想法/偏好”或硬性 pending | 与最新设计中“先不考虑软性偏好，只处理显式要/不要”的口径需要继续对齐 |
| 方案查询计数 | G3 `当前方案里有没有相关专业` | 回复“正式方案有45个志愿，命中114条” | 查询命中数可超过方案项总数，展示口径不清晰，可能混入专业子项计数 |
| 无方案探索回答 | G32 `有什么专业是比较好就业的吗`、`计算机和电子信息有什么区别` | direct 工具返回偏占位/元说明，缺少实质对比内容 | `explore_topic` / `compare_entities` 在无方案探索场景的信息密度不足 |
| pending 只读查询性能 | G27 `两万以上的都算贵 帮我看看有几个` | 功能通过，但走 `pending_readonly_plan_query` + 旧 `execute_plan_action`，耗时 `19073ms` | pending 存在时只读方案查询仍有旧链路依赖和性能成本 |

2026-07-02 特化修复尝试回退记录（仅记录，暂不修复）：

- G4 原词展示问题曾尝试用工具内 `_MAJOR_DISPLAY_ALIASES` 处理“跨境电商 -> 跨境电子商务/电子商务”，该方向已回退。原因：这是面向单个 case 的别名补丁，不是 4.0 框架内的统一实体保真方案。
- G32 无方案探索信息密度问题曾尝试在 `_fallback_major_profile_facts` 中硬编码计算机、电子信息、网络与新媒体、跨境电商等专业说明，该方向已回退。原因：工具代码内维护专业知识会增加维护成本，也容易变成针对回归样例的特化内容。
- 当前客观结论：G4 仍需要统一解决“用户原词 -> 规范实体”的展示保真；G32 仍需要统一解决 profile API 缺失时的探索/对比信息密度。
- 后续设计方向需在整体框架内评估：实体解析层输出 `raw_text` / `canonical_name` / `level` 等 metadata，由 preview renderer 统一展示原词与规范名；资料缺失降级应来自统一 profile/taxonomy/知识库层或通用维度模板，不应在 `tools.py` 内写具体专业内容。

本轮不作为问题的通过点：

- G26 `保底最后几个是什么学校 录取率多少` 已正确走 `query_plan`，展示保底末尾 5 条并包含录取率。
- G27 `方案里学费贵的太多了 能不能帮我换成便宜的` 已正确走 `preview_plan_action` 并生成方案调整确认卡。
- G27 active pending 后继续提出新删除请求，正确走 `pending_conflict_new_request_guard`，未创建第二张确认卡。
- G16 `锁定位置不要动` 已明确返回当前新工具不支持锁定，不创建确认卡，不改动方案。

2026-07-02 按 `release-4.0.0-zhiyuan-agent-implementation-design.md` v1.3 §9 推进首批修复：

- §9.1 复合诉求 `next_step`：`ZhiyuanAgent.should_return_directly_from_tool` 已改为仅对 `confirm` / `clarify` 硬停；`respond` 只读结果不再直接终止本轮，允许模型继续处理同句中的后续方案操作。
- §9.2 pending 下只读 direct：service direct route 不再因 active pending 直接退出；只读查询可继续进入 4.0 direct。为保持单 pending 安全，`preview_intent_change` / `preview_plan_action` 增加“本轮开始时已有 active pending”冲突守护，返回提示且不创建第二张确认卡。
- §9.3 正向意向边界：prompt 已补充“想学X/对X感兴趣/X方向”按正向报考要求处理，“也可以考虑X/X也行/不排斥X”作为弱肯定探索，不创建报考要求；地域示例补充 `城市优先长三角`。
- §9.4 档案/成绩边界：service direct route 增加有效成绩前置检查，无有效成绩时回退旧 intake 链路；prompt 明确成绩、省份、选科不由 4.0 九工具写入，不能假装已记录或已更新。
- 工具兼容：`preview_intent_change(intent_type="region")` 的地域归一化补充 `region_group` / `region_groups` 入参，避免 prompt 示例字段被忽略。
- 单测验证：`py_compile app/zhiyuan_agent/agent.py app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py app/service.py tests/unit/test_zhiyuan_agent_poc.py` 通过；聚焦单测 `9 passed, 115 deselected`；全量 PoC 单测 `97 passed, 27 skipped`。
- 待复核：尚未完成真实 websocket G12/G21/G27/G23/G25 复跑；需要用最新服务进程确认 `respond` 软停对真实 LLM 是否会引入多余工具调用，及 G25 完整回归不一致是否消失。

2026-07-02 继续按 v1.3 §9 推进并补齐 shadow 评估安全边界：

- Shadow 副作用隔离：`RequestContext` 增加 `dry_run_state_mutations`；service 启动 PoC shadow 时使用深拷贝的 `conversation_phase`，并开启 dry-run。shadow 仍可观测 `preview_intent_change` / `preview_plan_action` 的 `next_step=confirm` 和 pending 结构，但不调用后端 `save_pending_confirmation`，也不执行 `confirm_pending` 的真实写入或方案动作。
- Shadow 同轮语义保持：dry-run preview 会 prime shadow 自己的 `pending.json`，因此同轮多次工具调用仍可观察 pending 合并、active pending 冲突和后续确认语义；该状态只存在于 shadow sandbox，不污染主链路会话。
- Active pending 冲突语义收紧：本轮开始已有待采纳内容时，`preview_intent_change` / `preview_plan_action` 对新的变更诉求返回 `next_step=clarify`，作为硬停阻断；只读查询仍可通过 direct route 处理。
- 历史 pending 清理口径：旧 `executionPayload.planPayload` 的 pending 不再委托旧 `execute_plan_action`；短文本确认命中这类历史 pending 时不会执行旧工具，会要求重新生成结构化预览。
- 单测验证：`tests/unit/test_zhiyuan_agent_poc.py -q` 通过，`100 passed, 27 skipped`；service 聚焦回归 `tests/unit/test_chat_service_history_persistence.py -k "pending_readonly or direct or pending_conflict or zhiyuan_agent" -q` 通过，`21 passed, 499 deselected`。
- 待复核：还需要用当前进程重新跑真实 websocket G12/G21/G23/G25/G27，确认 shadow 不再产生真实 pending 副作用，并观察 §9.1 respond 软停在真实 LLM 下是否会多调工具。

2026-07-02 按 `release-4.0.0-zhiyuan-agent-implementation-design.md` v1.4 §9.5-§9.8 推进修复：

- §9.5 G17 档位内移动 selector：`preview_plan_action(action="move")` 的 filter selector 解析已支持从 `raw_user_text` 补偿提取“录取率最高/最低、学费最高/最低、最后一个”等通用选择语义；当 tier/filter 命中多个志愿且缺少 selector/ordinal 时返回 `ambiguous_selector` 澄清，不再静默取第一个。
- §9.6 G4 实体归一化展示保真：`preview_intent_change` 的实体归一化返回 `canonical -> raw` display aliases；用户可见 `message` / `summary` 展示为 `原词（规范名）`，执行 payload 的 `selected` 仍只使用规范实体，避免展示元数据混入执行字段。
- §9.7 G3 查询计数粒度：`query_plan` 的 `matched_total` 固定为志愿粒度；当命中明细数大于志愿数时，回复改为“命中X个志愿，涉及Y条专业明细”，避免“45个志愿命中114条”这类主粒度混淆。
- §9.8 G32 无资料探索/对比降级：`explore_topic` / `compare_entities` 在 profile API 无数据时返回通用 `fallback_dimensions` / `dimensions_template`，由后续 LLM 按维度组织回答；没有重新引入 `_MAJOR_DISPLAY_ALIASES`、`_fallback_major_profile_facts` 或任何具体专业百科硬编码。
- 补充单测：覆盖 `口腔 -> 口腔医学` 原词展示保真、G17 raw selector fallback、G17 ambiguous selector、G3 志愿/专业明细双粒度、G32 explore/compare fallback dimensions。
- 验证结果：`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_poc.py` 通过；聚焦单测 `29 passed, 3 skipped, 100 deselected`；全量 PoC 单测 `105 passed, 27 skipped`。
- 待复核：§9.9 G25 稳定性和 §9.10 respond 软停仍属于真实 LLM/service 验证项，需要在最新服务进程上继续跑 G25 单 case 多次、完整 G1-G32，以及 G12 复合诉求。

2026-07-02 按 `release-4.0.0-zhiyuan-agent-implementation-design.md` v1.5 §9.9-§9.12 推进：

- §9.9 G25 环境与 schema 修复：G25 fixture 的 source session 改为有有效 `userScoreDetail` 和 planning state 的 `17`；`_normalize_major_payload` fallback keys 补充 `major` / `majorList` / `major_list`；Prompt 增加混合正负示例，要求同一句正负诉求在同一次 `preview_intent_change` 里同时传 `positive` 和 `negative`。
- §9.9 负向漏参提示：`preview_intent_change` 增加 `raw_user_text` 参数，仅在用户原话明显包含排除诉求但工具入参没有 `negative` 时追加“预览里没有不要项”的提示；不从原文抽实体、不回填 payload。
- §9.10 direct 复合回复保留：service direct route 生成 pending card 后，不再无条件用 card primary 覆盖 agent 主回复；只有主回复为空或兜底短句时才用卡片文案补位。这样 `query_plan/review_plan -> preview_plan_action` 的“只读结论 + 待确认预览”会保留在 primary，同时继续返回 `pendingConfirmationCard` followup。
- §9.10 Prompt 收紧：明确“占比多少，能不能换成便宜的/换掉/移出去”属于查询 + 方案调整复合诉求；只读结果不是本轮终点，第二半句应直接生成方案调整预览，不再只回答后追问是否预览。
- 单测补充：新增 direct plan pending card 复合回复保留用例；调整 direct intent pending card 单测，保留 agent 主回复并继续验证卡片用户文案不出现系统用语。
- 静态/单测验证：`py_compile app/service.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_poc.py` 通过；`tests/unit/test_zhiyuan_agent_poc.py -q` 通过，`109 passed, 27 skipped`；direct 聚焦单测 `9 passed, 127 deselected`。
- G12 真实 service 验证：修 service 前主链路会把 agent 复合回复覆盖成纯卡片文案；修 service 后，命中 `query_plan -> preview_plan_action` 时 primary 已保留“高收费查询结果 + 下面是这次待确认预览”，并返回 pending card。Prompt 收紧后 G12 单 case 3 次复跑，2/3 同时处理查询和方案调整，达到 §9.12 C3 当前判定线；仍有 1/3 模型只回答并追问，作为稳定性观察项。
- 400 真实口语集合复跑：`examples/dialog_regression_400_realistic_user_cases.json`，`14/14` successful，shadow `14/14` success，工具调用数 max=1，metrics: `/private/tmp/zhiyuan_400_realistic_after_g12_service_prompt_fix.json`。
- G case direct 子集复跑：`examples/dialog_regression_400_g_case_direct_subset.json`，`5/8` successful，metrics: `/private/tmp/zhiyuan_400_g_case_after_g12_service_prompt_fix.json`。G25 通过：单次 `preview_intent_change`，`positive.major=[生物医学工程, 智能医学工程]` + `negative.major=[临床医学, 口腔]`，用户可见“要/不要”完整。失败项客观记录如下：
  - G17：实际已返回 `move_ordered_unit` pending card，但 runner 未拿到 direct turn observability，导致 `expectedRoutingPath` / `expectedToolNames` 断言失败；需继续排查观测落盘/等待逻辑。
  - G30：source session `65501205` 缺 `userScoreDetail`，direct route 成绩前置检查不通过，回退旧 `runtime_intent_hard_cut`；shadow 侧 4.0 正确命中 `preview_intent_change`。
  - G32：无正式方案场景被 `needs_plan_first_guard` 接管；shadow 侧 4.0 可 `query_plan` 并回答无方案，需确认该 fixture 是否应计入 direct route 验证或调整预期。

2026-07-02 继续修正 G case direct 子集 fixture 并复跑：

- Runner fixture 能力补齐：`examples/dialog_regression_runner.py` 支持 `cloneBackendScoreFromSessionId`，允许 case 从原业务 source 克隆 `planningState/userprofile`，同时从另一个稳定 source 只克隆 `userScoreDetail`。该能力只用于回归准备，不改变 4.0 direct route 成绩前置检查，也不绕过业务链路。
- G30/G32 case 修正：`examples/dialog_regression_400_g_case_direct_subset.json` 中 G30 保持 `65501205` 作为业务状态 source，补 `cloneBackendScoreFromSessionId=17`；G32 保持 `55001413` 的无方案状态，补 `cloneBackendScoreFromSessionId=26`。
- 单测/静态验证：`tests/unit/test_dialog_regression_runner.py -q` 通过，`87 passed`；`PYTHONPYCACHEPREFIX=/private/tmp/zhiyuan_pycache python3 -m py_compile zhiyuan-agent/examples/dialog_regression_runner.py` 通过。
- 单 case 验证：
  - G30：`1/1` successful，进入 `zhiyuan_agent_direct`，工具 `preview_intent_change`，pending payload 中 `school_intents.program_type=["强基"]` 与 `colleges=[清华大学, 北京大学, 复旦大学]` 分开保存；metrics: `/private/tmp/zhiyuan_400_g30_after_score_fixture.json`。
  - G32：`1/1` successful，进入 `zhiyuan_agent_direct`，工具 `query_plan`，无 pending，回复明确“还没有生成正式方案”；metrics: `/private/tmp/zhiyuan_400_g32_after_score_fixture.json`。
- G case direct 子集顺序复跑：`examples/dialog_regression_400_g_case_direct_subset.json`，`8/8` successful，shadow `8/8` success，工具调用数 max=1，metrics: `/private/tmp/zhiyuan_400_g_case_after_score_fixture.json`。G17 本次观测字段正常，`routingPath=zhiyuan_agent_direct`，工具 `preview_plan_action`，`actionFamily=move_ordered_unit`。
- 仍需关注：G30 用户可见摘要把“强基”和院校并列展示为“院校要求：要：清华大学、北京大学、复旦大学、强基”，执行 payload 正确但展示层可以继续优化成“院校 + 招生类型”分组。

2026-07-02 补齐确认后真实 action 验证：

- 问题背景：此前 direct 确认闭环主要验证“首轮出确认卡 + 确认轮走 `confirm_pending` + 返回工作台刷新”，但这只能证明交互链路打通，不能证明后端方案或报考要求真的被修改。
- Runner 能力补齐：`examples/dialog_regression_runner.py` 新增 `assertBackendExtraData` / `backendExtraDataAssertions`，每个 step 可在发送消息前后抓取后端 extra-data 快照，并断言 `equals`、`contains`、`greaterThanBefore`、`lengthChangedBy`、`changedFromBefore` 等结果；`planningState` 直接读取真实 `/inner/planning/.../state`，避免用 version=0 extra-data 误判。
- Case 补齐：`examples/dialog_regression_400_direct_confirm_execution_cases.json` 的确认轮已断言：
  - `第3个不要了 -> 确认执行`：`pendingConfirmation.status=applied`、`planningState.version` 增长、`orderedPlanState.units` 数量 `-1`。
  - `民办就算了 -> 采纳`：`pendingConfirmation.status=applied`、`planningState.version` 增长、`constraintState.hardConstraints.mustExcludeSchools` 包含 `院校性质:民办`。
- 执行链路修复：`tools.py` 的方案项执行 ID 推导与后端 `resolveDraftOrOrderedUnitId` 对齐；`sandbox.py` 的方案项 enrichment 优先保留 `orderedPlanState.units` 中真实 `unitId`，避免候选池 ID 覆盖执行 ID；`service.py` 的 direct confirm 路由识别 `confirm_pending` 结果，成功后补 `ordered` / `review` 工作台刷新，并将 routingPath 细分为 `direct_pending_plan_confirm` / `direct_pending_intent_confirm`。
- 最新真实验证：`examples/dialog_regression_400_direct_confirm_execution_cases.json`，`steps=4`、`successfulSteps=4`、`failedSteps=0`，shadow `observed=4/statuses.success=4`，metrics: `/private/tmp/zhiyuan_400_direct_confirm_with_backend_asserts_after_direct_followups.json`。
- 当前验收口径更新：4.0 的确认执行类回归必须包含最终 action 的后端状态断言，不能只看确认卡、回复文案或工作台刷新 followup。

2026-07-02 补齐高收费 follow-up 参数完整性与 filter 安全：

- 真实失败 case：`有啥问题，咋弄` 后接 `那高收费的别要了`。模型有时把这句映射为 `preview_plan_action(remove, review_issue_code=high_tuition)`，但当前审查结果没有可操作的 `high_tuition` affected units；也有时传 `filters={"tuition_level":"high"}`，旧工具未归一该 key。
- 问题定性：这是 4.0 direct route 内部的参数完整性和结构化 filter 安全问题，不回退到字符串 precheck，也不在工具层从原话做 NLU 特化。
- 修复方式：prompt 要求 `preview_plan_action` 必须携带 `targets` / `filters` / `review_issue_code` / 位置 selector 之一并保留 `raw_user_text`；agent 对 `missing_targets`、`missing_filters`、`review_issue_not_found`、`review_issue_units_not_in_plan` 允许模型补参重试一次；`tools.py` 将 `tuition_level=high` / `fee_level=high` 归一到 `program_type=["高收费"]`，未知 filter key 不再被当成“匹配全部”。
- 验证结果：聚焦单测与 runner 单测通过，`tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_dialog_regression_runner.py -q` 为 `205 passed, 28 skipped`；真实 LLM opt-in case `那高收费的别要了` 通过，模型能带定位参数。
- 真实 service direct-only 口语全集：`examples/dialog_regression_400_realistic_user_cases.json` 去掉 shadow 断言后复跑 `14/14` successful，metrics: `/private/tmp/zhiyuan_400_realistic_direct_only_after_retry_reason_fix.json`。
- 真实 service direct 确认执行闭环：`examples/dialog_regression_400_direct_confirm_execution_cases.json` 复跑 `4/4` successful，后端断言覆盖 `pendingConfirmation.status=applied`、`planningState.version` 增长、方案项数量 `-1`、`mustExcludeSchools` 包含 `院校性质:民办`，metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_retry_filter_fix.json`。
- 评估口径：direct 主链路和 shadow 观测分开看。shadow 在 dry-run 隔离上下文中后台运行，可能出现 `running` 或 timeout，不把 shadow 未完成直接计为 direct 主链路失败。

2026-07-02 G case direct 子集 direct-only 复跑：

- 验证环境：复用本地 `8075` direct 服务，当前 `ZHIYUAN_AGENT_POC_SHADOW=0`，因此原始 case 中 `expectedZhiyuanAgentPoc*` shadow 断言不适用于本轮 direct-only 验证。
- 原始 case 先跑出 `8/8` tool assertion failure，失败原因全部为 `zhiyuanAgentPocShadow no shadow result in turn observability`；实际 direct 业务路径均进入 `routingPath=zhiyuan_agent_direct`，不作为 direct 主链路失败。
- 生成临时 direct-only case `/private/tmp/zhiyuan_400_g_case_direct_subset_direct_only.json`，仅移除 shadow 断言，保留 direct route、tool、followup 和用户可见文案断言。
- direct-only 复跑结果：`steps=8`、`successfulSteps=8`、`failedSteps=0`，metrics: `/private/tmp/zhiyuan_400_g_case_direct_only_after_retry_filter_fix_rerun.json`。
- 覆盖结果：G2/G7/G21 只读审查走 `review_plan`；G16 锁定暂不支持走 `preview_plan_action` 且不出 pending；G17 走 `preview_plan_action` 并生成 `move_ordered_unit` 确认卡；G25 一次 `preview_intent_change` 同时保留“要：生物医学工程、智能医学工程”和“不要：临床医学、口腔医学”；G30 进入 `preview_intent_change`；G32 无正式方案查询走 `query_plan` 防御回复。
- 性能观察：8 步 median `7371ms`、p95/max `11640ms`；最慢为 G2/G7 只读审查回复生成。

2026-07-02 完整 320 G1-G32 direct 复跑：

- 验证命令：真实 service `8075` direct-only + 后端 `8080`，使用 `examples/dialog_regression_320_g1_g32_shadow_cases.json` 顺序执行，metrics: `/private/tmp/zhiyuan_400_direct_320_g1_g32_after_retry_filter_fix_rerun.json`。
- 总体结果：`steps=49`、`successfulSteps=44`、`failedSteps=5`；`failedByReason={"environment":1,"content":3,"tool":3}`。失败计数按断言类型统计会重复计入，同一个 step 可同时有 content/tool failure。
- 性能：有效 step `median=16433ms`、`p95=45480ms`、`max=68550ms`。最慢为 G23 `数学物理是强项化学一般`，耗时 `68550ms`；G21 强基政策问答和 G30 强基首轮也都超过 `45s`。
- direct 稳定点：G1、G2、G3、G7、G12、G16、G17、G19、G22、G26、G31 等关键路径能进入 4.0 direct 或既有 guard，并完成预期回复；G12 已可走 `query_plan -> preview_plan_action`，复合查询+调整被承接。
- 环境失败：G8 在清理 `planning intent` 时后端超时，未进入 agent，不计为 4.0 业务语义失败。
- G25 失败：完整历史 case 中 `把生物医学工程和智能医学工程加意向 排除临床医学和口腔` 被旧 `runtime_intent_hard_cut` 接管，用户文案是“偏好专业/排除专业”，没有走 4.0 direct 的“专业要求：要/不要”文案。8-case direct 子集同一诉求已通过，说明 `preview_intent_change` 工具可表达，问题在旧路由抢跑或完整 case 前置状态。
- G27 真实问题：`方案里学费贵的太多了 能不能帮我换成便宜的` 进入 4.0 direct，但走了 `preview_plan_action -> query_plan -> preview_plan_action` 三次工具调用，最终没有生成替换确认卡；回复要求用户继续选择处理方式。该 case 暴露 replace 自动候选或高收费替换策略仍不稳定。
- G27 口径问题：`两万以上的都算贵 帮我看看有几个` 实际走 4.0 `query_plan` 并正确返回 `37` 个高收费项，但旧断言仍期望 `execute_plan_action/query_ordered`，应更新为 4.0 direct 查询口径，不作为业务错误。
- G27 后续动作：`那把两万以上且跟我意向不沾边的先删掉` 实际生成 `remove_units` 确认卡；旧断言期望 `pending_conflict_new_request_guard`。由于本轮首步没有创建 pending，该行为不应直接判错，需要结合首步修复后重新定义期待。
- 旧链路残留观察：G21/G30 强基多轮、G23 正向意向、G29 软表达仍会走 `full_agent` 或 `runtime_intent_hard_cut`，并出现“偏好/报考想法”等旧文案。4.0 direct 子集通过的同类工具能力不代表完整历史链路已经替换完成。
- 文案观察：G22/G31 档案 inline 修正类目前没有写系统档案，整体边界正确；但个别中间轮次出现“已更正”等措辞，容易让用户误解系统档案已更新。后续应统一改为“你刚才口头说明的是……系统档案仍未更新”。

## 4. 当前结论

PoC 的核心假设在小样本中成立：

1. 状态前置注入 + 正交工具设计能让模型第一步直接选择业务工具，不需要先摸底。
2. `next_step` 终止信号能让工具结果直接回复，避免二次生成和继续乱试工具。
3. 9 个工具已覆盖本轮 5 个高价值验证场景、policy/review 只读场景及 pending 确认闭环单测，已验证场景每轮都只调用 1 个工具。
4. 双重否定问题可通过 prompt 极性规则 + schema 收窄稳定修复。
5. 与当前主链路相比，PoC shadow 的输入 token 约 1.2K，显著低于主链路 17K-37K 量级。
6. 真实口语 shadow 已能稳定覆盖 14 个场景，且 `query_plan` 的属性过滤、`preview_intent_change` / `preview_plan_action` 的口语化分流在真实数据上可复现。
7. Phase 4 direct route 已按功能开关/rollout 接入 service，且不再依赖字符串 precheck；400 真实口语集合 direct-only 最新 14/14 通过，确认执行闭环 4/4 通过且已包含最终后端 action 断言。G case direct 子集 direct-only 最新 8/8 通过，G25 正负完整，G17/G30/G32 已进入 4.0 direct 并通过断言。完整 320 G1-G32 最新为 44/49，通过结果说明核心 direct 能力可用，但旧路由抢跑、G27 replace 自动候选和历史断言口径仍需收口。

限制：

- `explore_topic` / `compare_entities` 已接入 major/school profile API，但 career/region、个性化权重分析和更多真实资料字段仍需扩展。
- `answer_policy` 已落地离线稳定首版；官方来源检索是 opt-in，网页事实抽取后的自动适配匹配仍未接入。
- `review_plan` 已落地只读审查首版；与 `preview_plan_action` 的核心 review issue 联动首版已覆盖，G2/G21 真实工具选择边界已通过，完整 service shadow case 仍需扩展。
- service shadow 已改为非阻塞后台 task；turn event 若早于 shadow 完成，可能只携带 `running` 占位，完整结果以独立 shadow event 为准。
- 当前样本只有 5 个 PoC 设计场景，还需要扩展到 3.2.0 G case 和 3.0.3/3.1.1 真实用户 case。
- `query_plan` 已能扫描方案明细，属性过滤在真实数据上已验证；但旧主链路里仍有部分展示文案和只读/调整分流需要替换。
- `preview_plan_action` 已只产出结构化 payload；核心 review issue 删除/排序/重排联动、review issue + filters 复合范围、replace 自动候选首版、remove filters 属性定位、G16 锁定 unsupported、G17 档位内重排和 G30 强基 selector 已落地；候选选择质量评估和更多真实 shadow case 仍需扩展。
- `preview_intent_change` 已接入 `simulate_plan_diff`；真实服务稳定性仍需通过更多 shadow case 和真实 service 样本继续观察。
- direct route 已完成 400 真实口语集合、确认执行闭环和 G case 子集复跑；确认执行闭环已断言后端真实变更。清理旧链路前仍需继续扩展到书面混合集合、320+ 历史回归和清理后回归。

## 5. 后续推进项

| 优先级 | 事项 | 目标 |
|--------|------|------|
| P0 | 扩展 shadow case 集合 | 覆盖 3.2.0 G1-G32 中与 intent/explore/plan query 相关的稳定 fixture，并把 400 口语集继续纳入门禁 |
| P0 | 扩展真实 service direct 验证 | 400 口语 case、确认执行闭环和 G case 子集已复跑通过；完整 320 G1-G32 最新 44/49；确认类 case 必须断言后端 action；继续修 G27 replace、收口旧路由抢跑，并跑清理后回归 |
| P0 | 复核 G12/G25 完整回归稳定性 | G25 最新子集已通过且正负完整；G12 单 case 达到 2/3，但仍需完整 G1-G32 direct 回归中继续观察 |
| P0 | 扩展 G case direct 覆盖 | 子集已 8/8；继续扩展到完整 G1-G32 direct 回归和清理后回归 |
| P0 | 补齐真实分析数据 | `explore_topic` 继续接入 analyze_majors/analyze_schools、career/region 方案覆盖分析 |
| P0 | 扩展 `preview_plan_action` 场景 | 覆盖候选选择质量评估和完整 shadow/service case |
| P0 | 扩展真实 diff shadow 验证 | 覆盖 `simulate_plan_diff` 成功/降级/空 diff 样本，观察耗时与稳定性 |
| P1 | 完善 9 工具正式版 | 扩展 review/plan action 联动、policy 官方来源抽取、compare/explore 个性化权重 |
| P1 | 建立 confusion matrix 报告 | 对比主链路 route/tool 与 PoC route/tool 的一致性和差异归因 |
| P1 | 旧链路清理计划 | direct 验证稳定后按设计文档 §6.4 删除旧规则引擎、旧工具和 service 编排分支，不再继续修补旧语义链路 |

## 6. 操作备忘

开启 service shadow：

```bash
ZHIYUAN_AGENT_POC_SHADOW=1 \
ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS=30 \
INTERNAL_SERVICE_URL=http://127.0.0.1:8080 \
RANK_SERVICE_URL=http://127.0.0.1:5001 \
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

查看单条对比：

```text
record.turnObservability.routingPath
record.turnObservability.toolCallCount
record.turnObservability.zhiyuanAgentPocShadow.firstToolNames
record.turnObservability.zhiyuanAgentPocShadow.firstToolArgs
record.turnObservability.zhiyuanAgentPocShadow.nextSteps
record.turnObservability.zhiyuanAgentPocShadow.durationMs
record.turnObservability.zhiyuanAgentPocShadow.totalTokens
```

查看汇总：

```text
summary.zhiyuanAgentPocShadow
```
