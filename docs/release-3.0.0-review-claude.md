v3.0.1 实现全景分析报告
  
  一、实现现状与遗留问题

  1.1 死代码：旧指令系统未清理

  chat_agent.py 第 77–267 行的 _build_instructions 函数（约 190 行）是 完全的死代码。ChatAgent.__init__ 实际传入的是模块化版本
  build_instructions（来自 assembler.py），旧函数不会被任何路径调用。这带来两个危害：

  - 新开发者会困惑哪套指令系统是生效的
  - 修改旧版本以为生效了，实际不会有任何效果

  建议：直接删除 _build_instructions 及其上方注释块。

  1.2 内存级缓存在多进程部署下不安全

  plan_execution_tool.py 中的 _RECENT_PLAN_EXECUTION_RESULTS: dict 是模块级变量，TTL 180 秒。Uvicorn 以多 worker
  模式启动时，每个进程持有独立副本，导致：

  - Worker A 执行 preview → Worker B 接收 confirm → 找不到 payload → 失败
  - 用户看到"操作不存在"的莫名错误

  建议：迁移到 Redis / 共享存储，或在架构层保证 session 粘性（sticky session）。

  1.3 双重 Pending 系统共存

  RequestContext 同时保留了 deprecated 的 pending_plan_action: dict 和新的 conversation_phase: ConversationPhase。pending_context.py 中用
  if-elif 同时支持两套，增加了状态判断的分支复杂度。

  service.py 的 _extract_pending_plan_action 是一个 ~100 行的状态机扫描器，每次请求都要从头遍历整个 message_history 来推导 pending 状态 ——
  这既是性能瓶颈，也容易在边界条件下误判。

  建议：完成 ConversationPhase 迁移后删除旧路径；pending 状态应由写入端显式标记，而非由读取端从历史推导。

  1.4 Handler 迁移半成品

  registry.py 注释明确写道："只有 query handlers 已迁入，其他仍由旧 _execute_plan_action_model 处理"。这意味着：

  - query_state、query_draft、query_ordered、query_candidates 走新 registry
  - add_units、remove_units、move_unit、replace_units、sort_ordered_plan、generate_plan、regenerate_order、review_plan、apply_compensation
  等核心 mutation 仍在旧的巨型 switch 中

  建议：制定迁移路线图，按风险级别分批迁入；每批附带集成测试。

  ---
  二、设计文档与实现的背离
  
  2.1 核心背离：关键词路由 vs. Model-First 原则

  设计文档 planning_agentize_design.md 第 8.6.0.1 节明确提出 "model-first routing" 原则 —— 语义理解和动作分类应由 LLM 完成，service
  层不应做基于关键词的硬编码分流。

  tool_dispatch_rules.py 第一条规则也写着：

  ▎ "对话理解与触发由你基于语义、上下文和当前规划状态判断，不要依赖固定关键词、硬编码短语或模板化分流。"

  但实际实现严重背离这一原则，至少有三层关键词路由：

  第一层：Service 层直接旁路 LLM

  ┌─────────────────────────────────┬──────────────────────────────────┬─────────────────────────────────────────────────────────────┐
  │              函数               │               机制               │                            后果                             │
  ├─────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ _is_basic_plan_status_question  │ 16 个精确匹配中文短语            │ 用户说"方案现在什么情况"就不匹配，走了更慢的完整 Agent 路径 │
  ├─────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ _is_plan_action_confirmation    │ ~22 个确认短语 + startswith 匹配 │ "可以这样做"、"嗯嗯" 不匹配；"确认一下时间"被误匹配         │
  ├─────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ _is_pending_intent_confirmation │ ~14 个确认短语，纯精确匹配       │ "好呀"、"ok"、"没毛病" 等均无法触发                         │
  └─────────────────────────────────┴──────────────────────────────────┴─────────────────────────────────────────────────────────────┘

  第二层：plan_next_action 的纯规则路由

  plan_orchestration_tool.py 的 _plan_next_action_model 是 完全基于规则的路由器，标注为 "Deprecated" 但仍是唯一生效路径。包含 ~10
  个关键词匹配函数：

  _goal_requests_replacement(text)       # "换成""替换成""补回"...
  _goal_explicitly_requests_reorder(text) # "重排""重新排""重新排序"...
  _goal_requests_adjustment_analysis(text) # "换一下""调一下""降风险"...
  _goal_requests_stability_fill_preview(text) # "补稳""加个保底"...
  _goal_requests_structural_rebalance(text) # "全部重排""打散重来"...
  _goal_explicitly_requests_regeneration(text) # "重新生成""再来一版"...

  _normalize_adjustment_action_family 更进一步：即使模型已经选择了 action_family，这个函数会根据关键词 覆盖模型的决策。这直接违反了
  model-first 原则。

  第三层：Post-processing 管线覆写 LLM 输出

  Service 层对每个 LLM 回复做 5 步后处理：

  1. _normalize_plan_reply_style — 按关键词删除/替换句子
  2. _append_plan_preview_confirmation_boundary — 扫描回复内容判断是否需要追加确认边界
  3. _normalize_pending_intent_reply — 匹配并替换 intent 相关措辞
  4. _normalize_user_facing_terms — "画像" → "报考参考信息" 等字符串替换
  5. _sanitize_reply_for_user — 清理 [LLM_INTERNAL] 标记

  这 5 层后处理本身就是 prompt 工程不够到位的症状。如果 style_rules 和 tool 返回值在源头就做好了用户化表达，service
  层不应该需要这么重的文本操作。

  2.2 设计背离总结

  ┌─────────────────────┬───────────────────────────────────────┬──────────┐
  │      设计原则       │               实际实现                │ 偏离程度 │
  ├─────────────────────┼───────────────────────────────────────┼──────────┤
  │ Model-first routing │ 三层关键词匹配 + LLM 后处理覆写       │ ⛔ 严重  │
  ├─────────────────────┼───────────────────────────────────────┼──────────┤
  │ 统一 pending 管理   │ 新旧双系统共存 + 历史扫描推导         │ ⚠️  中等  │
  ├─────────────────────┼───────────────────────────────────────┼──────────┤
  │ Handler 模块化      │ 仅 query 迁移，mutation 仍在 monolith │ ⚠️  中等  │
  ├─────────────────────┼───────────────────────────────────────┼──────────┤
  │ Tool 返回面向用户   │ 大量内部术语，靠 post-processing 补救 │ ⚠️  中等  │
  └─────────────────────┴───────────────────────────────────────┴──────────┘

  ---
  三、SOTA 方案对标：如何更合理地实现 Agent 对话驱动

  3.1 当前架构的根本矛盾

  当前系统在「信任模型」和「管控模型」之间摇摆不定：

  - Instructions 说"不要依赖固定关键词"
  - Service 层 却用 16 个精确匹配短语旁路模型
  - plan_next_action 是纯规则引擎
  - Post-processing 暗中改写模型输出

  这种"模型负责生成 + 代码负责纠偏"的模式，本质上是把 LLM 当成了一个不可信的文本生成器，然后用 heuristic 来"兜底"。结果是
  两边都做不好：模型因为输出会被改写而学不到正确模式；规则因为无法穷举而持续漏网。

  3.2 SOTA 路线：Structured Output + Semantic Router + Guardrails 三层架构

  更先进的做法是明确分层：

  ┌─────────────────────────────────────────┐
  │  Layer 1: Semantic Router (LLM-based)   │  输入分类
  │  ─ intent classification                │
  │  ─ action planning                      │
  │  ─ confirmation detection               │
  ├─────────────────────────────────────────┤
  │  Layer 2: Structured Execution          │  确定性执行
  │  ─ tool orchestration                   │
  │  ─ state management                     │
  │  ─ API calls                            │
  ├─────────────────────────────────────────┤
  │  Layer 3: Output Guardrails             │  输出过滤
  │  ─ safety checks (not content rewrite)  │
  │  ─ terminology blocklist                │
  │  ─ format validation                    │
  └─────────────────────────────────────────┘

  关键区别：

  ┌────────────────────────────┬────────────────────────────────────────────────────────────────────────┐
  │          当前做法          │                               SOTA 做法                                │
  ├────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
  │ Service 层关键词匹配做分类 │ LLM 做分类，输出 structured JSON（intent_type, confidence, reasoning） │
  ├────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
  │ plan_next_action 纯规则    │ LLM 决策 + 规则约束（LLM 选动作，规则检查合法性）                      │
  ├────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
  │ Post-processing 改写内容   │ Guardrail 只 reject/retry，不改写                                      │
  ├────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
  │ 确认检测靠短语集           │ LLM 判断"用户是否在确认上一轮操作"（few-shot classification）          │
  └────────────────────────────┴────────────────────────────────────────────────────────────────────────┘

  3.3 具体改造路径

  3.3.1 用 Lightweight Classifier 替代精确短语匹配

  当前的 _is_plan_action_confirmation 和 _is_pending_intent_confirmation 用 ~35 个硬编码短语做确认检测。改为：

  async def classify_user_intent(
      user_message: str,
      pending_context: PendingContext | None,
  ) -> IntentClassification:
      """用小模型做 intent 分类，返回 structured output。"""
      # 使用 haiku/mini 级别模型，延迟 <200ms
      # few-shot examples 覆盖：确认、拒绝、追问、新话题
      result = await fast_model.run(
          prompt=CLASSIFICATION_PROMPT,
          result_type=IntentClassification,  # Pydantic model
      )
      return result

  IntentClassification 包含：
  - is_confirmation: bool — 是否在确认上一轮预览
  - is_rejection: bool — 是否拒绝/想改
  - is_new_topic: bool — 是否切换了话题
  - confidence: float — 置信度
  - reasoning: str — 判断依据

  为什么这样更好：
  - 能处理 "嗯嗯好的就这样"、"ok"、"行吧"、"可以可以" 等无穷变体
  - 能区分 "确认" (确认操作) vs "确认一下XX的情况" (新查询)
  - 带 confidence 和 reasoning，支持可观测性和后续迭代

  3.3.2 plan_next_action 改为 LLM + 规则约束

  当前 plan_next_action 是纯规则的 action router。改为：

  async def plan_next_action(ctx, user_goal, context_inputs):
      # Step 1: LLM 决策（选 action_family + stage + 参数）
      plan = await planner_model.run(
          prompt=build_planning_prompt(user_goal, context_inputs),
          result_type=PlanActionPlan,  # 强类型输出
      )

      # Step 2: 规则层只做合法性校验，不做分类
      violations = validate_plan_constraints(plan, context_inputs)
      if violations:
          plan = apply_constraint_fixes(plan, violations)

      return plan

  规则层只检查：
  - preview 前置条件（有无方案、有无候选等）
  - 副作用边界（高危操作必须 preview 先行）
  - 容量限制（志愿数上限等）

  规则层不做：
  - action_family 分类（模型做）
  - 关键词匹配（模型做）
  - goal 语义理解（模型做）

  3.3.3 Post-processing 精简为纯 Guardrail

  将当前 5 步后处理精简为 2 步：

  1. Terminology Blocklist（保留）— 确保 volunteerId、action_family 等内部术语不出现在最终输出
  2. [LLM_INTERNAL] Sanitization（保留）— 清理内部标记

  删除 _normalize_plan_reply_style 和
  _append_plan_preview_confirmation_boundary。这两个函数要解决的问题（模型输出了不当措辞、模型遗漏了确认边界）应该通过改进 prompt 和 tool
  返回值来解决，而不是在后处理中打补丁。

  ---
  四、用户随意表达的稳定处理

  参考 dialog_regression_robust_cases.json 的 9 类场景：

  4.1 当前方案对随意表达的脆弱性分析

  ┌────────────┬────────────────────────┬───────────────────────────────────────────────────────────────────────┐
  │    场景    │        用户表达        │                               当前风险                                │
  ├────────────┼────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ 单字输入   │ "嗯"、"生成"           │ _is_plan_action_confirmation 匹配不到 "嗯"，走完整 Agent 路径浪费一轮 │
  ├────────────┼────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ emoji 噪声 │ "帮我看看方案🤔"       │ _is_basic_plan_status_question 精确匹配失败（多了 emoji）             │
  ├────────────┼────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ 方言/口语  │ "俺想学计算机""中不中" │ 所有关键词匹配函数都以普通话为基准                                    │
  ├────────────┼────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ 错别字     │ "安微""计算即"         │ 精确匹配无法容错                                                      │
  ├────────────┼────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ 超长段落   │ 200 字一段话           │ Token 浪费但功能不受影响                                              │
  ├────────────┼────────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ 多指令密集 │ "先审查再把第3个换了"  │ 当前 plan_next_action 只能处理单一 action_family                      │
  └────────────┴────────────────────────┴───────────────────────────────────────────────────────────────────────┘

  4.2 推荐方案：Preprocessing + Few-shot Normalization

  用户原始输入
      ↓
  [Preprocessor] — emoji 清洗、标点规范化、基础错字纠正
      ↓
  [Intent Classifier] — LLM-based，few-shot examples 覆盖方言/口语/错别字
      ↓
  [Normalized Intent] — structured output: {type, entities, confidence}
      ↓
  Agent 主循环

  4.2.1 Preprocessor（规则层，无 LLM 调用）

  def preprocess_user_input(raw: str) -> str:
      # 1. 去除无意义 emoji（保留表达情感的）
      text = strip_decorative_emoji(raw)
      # 2. 全角→半角标点规范化
      text = normalize_punctuation(text)
      # 3. 常见错别字词典（"安微"→"安徽"，"计算即"→"计算机"）
      text = apply_typo_corrections(text)
      # 4. 保留原文作为 metadata，用纠正后的文本做后续处理
      return text

  错字词典应该从线上日志中挖掘（见第六节数据闭环）。初始版本可以从 robust test cases 中提取。

  4.2.2 Few-shot Intent Classifier

  在 intent classification prompt 中加入方言/口语/单字的 few-shot examples：

  用户: "嗯" → 上下文有待确认操作 → is_confirmation=true
  用户: "嗯" → 上下文无待确认操作 → is_continuation=true（模型自然接话）
  用户: "中不中" → is_confirmation_question=true
  用户: "俺想去北京" → is_intent_expression=true, region="北京"
  用户: "先审查再把第3个换了" → is_multi_action=true, actions=["review", "replace#3"]

  4.2.3 Multi-Action 拆分

  当前架构不支持单轮处理多个 action。对于"先审查再把第3个换了"，推荐方案：

  1. Intent Classifier 识别为 multi_action
  2. 拆分为有序 action 队列: [review_plan, replace_units(position=3)]
  3. 按序执行，每步结果聚合后一次性回复

  这需要扩展 PlanActionPlan 支持 action 队列，或在 service 层增加 multi-turn orchestration。

  ---
  五、回复质量稳定性控制

  5.1 当前问题分析

  根据 regression test cases 和代码分析，回复质量不稳定的根因：

  1. Prompt 过长导致指令遵循率下降：identity + planning_context + pending_context + first_turn_guidance + tool_dispatch_rules + style_rules +
   skills 的组合指令量巨大（估算 3000-5000 tokens），加上 message_history，容易超出模型的有效注意力窗口
  2. Tool 返回值格式不统一：有的返回 JSON，有的返回自然语言，有的混合。模型无法形成稳定的"收到 tool 结果后该怎么组织回复"的模式
  3. Post-processing 与 Prompt 的矛盾：prompt 说"你自然组织回复"，但 service 层又会改写。模型如果"学会"了 post-processing
  的偏好（比如总是说"确认后执行"），反而可能触发 _remove_unbacked_plan_confirmation_copy 的清洗
  4. 缺乏回复格式的 structured output 约束：模型回复是自由文本，无法强制包含特定结构（如"结论→分析→下一步"三段式）

  5.2 推荐方案：分层 Prompt + Response Schema + Online Evaluation

  5.2.1 Prompt 分级加载

  当前所有指令在每轮都全量加载。改为按需加载：

  def build_instructions(ctx):
      parts = [build_identity(ctx.deps)]  # 必须

      # 按当前状态判断需要哪些指令段
      if has_planning_state(ctx.deps):
          parts.append(build_planning_context(ctx.deps))
      if has_pending_action(ctx.deps):
          parts.append(build_pending_context(ctx.deps))
      if is_first_turn(ctx.deps):
          parts.append(build_first_turn_guidance())

      # tool_dispatch_rules 按检测到的 task layer 精简
      parts.append(build_targeted_dispatch_rules(ctx.deps))

      # style_rules 始终加载但压缩为关键条目
      parts.append(build_compact_style_rules())

      return "\n\n".join(parts)

  5.2.2 Tool 返回值标准化

  统一所有 tool 返回为标准信封格式：

  class ToolResponse(BaseModel):
      """统一 tool 返回格式，让模型形成稳定的处理模式。"""
      status: Literal["success", "error", "preview"]
      summary: str  # 用户面向的一句话概要
      details: str | None  # 可选的详细内容（已经是用户语言）
      next_options: list[str]  # 建议的下一步（用户面向）
      internal_notes: str | None  # [LLM_INTERNAL] 标注的内部调度信息

  这样模型可以形成稳定模式：
  1. 读 summary 作为回复的第一句
  2. 展开 details 作为分析段
  3. 用 next_options 收尾
  4. 忽略 internal_notes

  5.2.3 Response Quality Evaluation（在线评估）

  在 post-processing 位置增加一个 评估而非改写 的步骤：

  async def evaluate_response_quality(
      user_message: str,
      agent_reply: str,
      context: dict,
  ) -> ResponseQuality:
      """用小模型快速评估回复质量，不改写。"""
      return await evaluator.run(
          prompt=EVAL_PROMPT,
          result_type=ResponseQuality,
      )

  class ResponseQuality(BaseModel):
      has_internal_terms: bool     # 是否泄漏了内部术语
      is_on_topic: bool            # 是否回答了用户的问题
      tone_appropriate: bool       # 语气是否合适
      has_actionable_next_step: bool # 是否包含了下一步引导
      score: float                 # 0-1 综合分
      issues: list[str]            # 具体问题

  - 评估结果写入日志（见第六节），不阻塞回复
  - score < threshold 时触发 retry（最多 1 次）
  - 长期积累评估数据，用于 prompt 迭代优化

  ---
  六、数据闭环与算法驱动优化

  6.1 当前数据现状

  系统目前 几乎没有数据闭环：
  - MessageStore 仅持久化前端可见消息（用户消息 + Agent 回复），不含 tool 调用详情
  - ChatHistoryStore 保存 pydantic-ai 完整消息历史（含 tool 调用），但仅用于多轮对话恢复
  - 没有回复质量评估数据
  - 没有用户反馈信号（点赞/点踩/手动编辑）
  - 没有 intent classification 的准确率度量
  - 没有 tool 调用成功率/延迟的聚合统计

  6.2 数据闭环架构

  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
  │  Online      │     │  Data Lake    │     │  Offline     │
  │  Logging     │────▶│  (Structured  │────▶│  Analysis    │
  │  Pipeline    │     │   Events)     │     │  Pipeline    │
  └─────────────┘     └──────────────┘     └──────────────┘
                                                 │
                      ┌──────────────┐            │
                      │  Model &     │◀───────────┘
                      │  Prompt      │
                      │  Registry    │
                      └──────────────┘

  6.2.1 Online Logging Pipeline

  每轮对话产出一条结构化事件：

  @dataclass
  class ConversationTurnEvent:
      session_id: str
      turn_id: int
      timestamp: datetime

      # 输入
      user_message: str
      preprocessed_message: str  # 纠错后
      intent_classification: IntentClassification  # 分类结果

      # 路由决策
      routing_path: str  # "fast_confirm" / "fast_status" / "full_agent"
      action_family: str | None

      # Tool 调用
      tool_calls: list[ToolCallRecord]  # name, args, duration_ms, success

      # 输出
      raw_reply: str  # 模型原始回复
      final_reply: str  # post-processing 后
      post_processing_applied: list[str]  # 哪些步骤做了修改

      # 质量
      response_quality: ResponseQuality | None

      # 性能
      total_duration_ms: int
      llm_duration_ms: int
      tool_duration_ms: int

  6.2.2 关键指标体系

  ┌────────┬───────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────┐
  │  维度  │                             指标                              │                         用途                          │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 覆盖率 │ 快速路径命中率 (fast_confirm + fast_status) / total           │ 衡量关键词集合是否够用 → 切 LLM classifier 后跟踪精度 │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 准确率 │ Intent classification accuracy (human-labeled sample)         │ 衡量分类器质量                                        │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 稳定性 │ Post-processing 修改率（非空 post_processing_applied 的比例） │ 下降 → prompt 在改善                                  │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 延迟   │ P50/P95/P99 of total_duration_ms, llm_duration_ms             │ 超时监控                                              │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 质量   │ Response quality score 分布                                   │ 均值上升 → 系统在改善                                 │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 容错   │ 错别字纠正触发率、方言表达识别率                              │ 衡量 preprocessor 覆盖度                              │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 用户   │ 确认率（preview 后用户确认的比例）                            │ 衡量 preview 质量                                     │
  ├────────┼───────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ 用户   │ 重复提问率（同一 intent 连续出现）                            │ 下降 → 一次回答质量在提升                             │
  └────────┴───────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────┘

  6.2.3 Offline Analysis → Prompt/Model 迭代

  [Weekly Pipeline]
      ├── 提取 post_processing_applied 频次最高的 pattern
      │     → 这些 pattern 说明 prompt 需要强化哪些约束
      │
      ├── 提取 intent_classification 低置信度样本
      │     → 补充 few-shot examples
      │
      ├── 提取错别字纠正日志
      │     → 更新 typo_corrections 词典
      │
      ├── 提取 response_quality score < 0.6 的案例
      │     → 人工标注 → 加入 regression test suite
      │
      └── 提取 tool 失败率最高的 action_family
            → 优化对应 handler 或 prompt

  6.2.4 未来：算法驱动的优化方向

  短期（1-3 月）：
  1. 动态 Few-shot Selection：根据用户当前 intent 类型，从历史优质案例库中动态选择最相关的 few-shot examples 注入 prompt，而非静态模板
  2. A/B Testing 基础设施：对 prompt 变更、模型选择、tool 返回格式等维度做对照实验，用 response_quality score 作为北极星指标
  3. 错字修正模型：积累足够多错别字日志后，训练一个轻量 seq2seq 模型替代静态词典

  中期（3-6 月）：
  4. Retrieval-Augmented Tool Selection：将"用户表达 → 最优 tool 序列"的历史数据建成向量索引，运行时检索最相似的历史 pattern，作为 tool
  选择的参考
  5. Prompt 自动优化：基于 DSPy/TextGrad 等框架，用 regression test cases 的通过率作为目标函数，自动搜索更好的 prompt 表达
  6. User Preference Model：基于用户历史交互（确认/拒绝/追问模式），建立用户偏好画像，个性化调整回复详略和风格

  长期（6-12 月）：
  7. 端到端 Fine-tuning：积累足够多的 (user_message, context, ideal_reply) 三元组后，在基础模型上 fine-tune
  一个志愿填报专用模型，替代通用模型 + 长 prompt 的方案
  8. Reward Model：训练一个 reward model 判断回复质量，用于 inference-time best-of-N 采样或 RLHF
  9. Multi-Agent Orchestration：将当前的 single-agent + skill 架构拆分为 Router Agent + Specialist Agents，每个 specialist 独立优化

  ---
  七、综合优先级建议

  ┌────────┬─────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────┬────────┐
  │ 优先级 │                                     改造项                                      │             预期效果             │ 工作量 │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P0     │ 删除死代码（旧 _build_instructions）                                            │ 消除混淆                         │ 0.5d   │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P0     │ 引入 LLM-based intent classifier 替代 _is_plan_action_confirmation /            │ 确认检测覆盖率从 ~35 个短语 →    │ 3d     │
  │        │ _is_pending_intent_confirmation                                                 │ 无限变体                         │        │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P1     │ plan_next_action 从纯规则改为 LLM + 规则约束                                    │ 消除最大的设计背离               │ 5d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P1     │ Tool 返回值标准化 + source-level 用户化                                         │ 减少 post-processing 依赖        │ 3d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P1     │ 数据 logging pipeline 上线                                                      │ 建立改进的数据基础               │ 3d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P2     │ 精简 post-processing 管线                                                       │ 消除模型-后处理矛盾              │ 2d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P2     │ 内存缓存迁移到 Redis                                                            │ 解决多进程部署问题               │ 2d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P2     │ ConversationPhase 完成迁移，删除 deprecated 路径                                │ 降低状态管理复杂度               │ 2d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P3     │ Preprocessor（emoji 清洗 + 错字纠正）                                           │ 提升随意表达的容错率             │ 2d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P3     │ Handler 迁移完成                                                                │ 代码结构标准化                   │ 5d     │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────┼────────┤
  │ P3     │ Response quality evaluator 上线                                                 │ 质量可度量                       │ 3d     │
  └────────┴─────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────┴────────┘

  ---
  八、关键结论

  v3.0.1 的架构设计（Explore/Intent/Plan 三层 × 主题轴、model-first routing、structured tool
  chain）是合理且前瞻的，但实现中因赶工和稳定性焦虑引入了大量的关键词 heuristic 作为"保险"，结果形成了 "设计说信任模型、实现却不信任模型"
  的矛盾状态。

  这种矛盾的代价是：
  1. 每加一个新功能都需要同时维护 prompt + 关键词集 + post-processing 三套逻辑
  2. 用户随意表达（方言、错字、单字、多指令）的处理能力受限于关键词集的覆盖度
  3. 无法通过改善 prompt 来持续提升效果，因为 post-processing 会覆写改善

  破局的关键路径是：先建立数据 logging（让改进可度量），然后用 LLM-based classifier
  替代关键词匹配（让语义理解能力与模型能力同步提升），最后精简 post-processing 到只保留安全过滤（让 prompt 优化的效果直接体现在用户体验上）。
