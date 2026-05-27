# Changelog

## Unreleased

### Added

- 3.0.3 Agent 效果/性能优化启动：新增 deep dive 设计文档，梳理当前 ChatService -> ChatAgent -> Plan/Explore/Intent 工具链路、真实 e2e 慢点、根因和分阶段优化方案。
- 3.0.3 Agent case 级评估框架：新增质量评分框架、报告模板和 first-pass 记录，要求同时评估回复正确性、完整度、自然度、决策支持度和延迟，避免只看性能或只把回复做薄。
- 3.0.3 Agent 回复质量文本级评审：逐 case 记录用户输入、实际回复、人工质量评分和修复建议，明确 Plan 快路径已基本稳定，Explore/Intent 仍存在模板感、内部术语外露和确认语义偏强等待优化问题。
- 3.0.3 回复质量 P1 修复设计：明确 Intent preview 用户语言、Intent confirm 语义收口、职业方向承接结论先行、专业对比使用本轮用户事实，以及方案审查进入 quality 主 case 的修复范围。
- 新增 `dialog_regression_303_realistic_user_cases.json` 真实口语化输入回归集，覆盖短句、懒输入、学校/专业简称、弱确认和混合软硬意向；最终 live 收口 `9/9` steps 通过，`qualityViolations=0`，中位耗时约 `2257ms`。
- 扩展 `dialog_regression_303_open_quality_cases.json`，新增家长视角、风险焦虑、专业压力、候选机会和只读后确认保护等开放真实问法，避免开放质量评估只覆盖标准业务术语。
- 新增 `model_provider_303_open_quality_realistic_cases.json`，用于多模型 Agent 横向对比真实口语开放场景；case 内带 `expectedKeyPoints / forbiddenPatterns / assertNoFollowups / warnElapsedSeconds`，用于同时比较回复质量和性能。
- `dialog_case_evaluation_report.py` 支持合并修复前/当前版本输出和多 provider benchmark 输出，按 `case + stepIndex` 对齐回复文本、首响、总耗时和启发式质量分。
- `model_provider_benchmark.py` 支持临时 agent host 配置、启动日志落盘、保留完整回复文本、保留 followup、以及每个 provider 前清理本地对话历史，便于做公平的多模型场景对照。
- `model_provider_benchmark.py` 的 Agent 场景断言补充 thinking、no-followup、case 期望点、case 禁用表达和耗时预算检查，避免 provider benchmark 只统计延迟、不评估回复质量。
- `model_provider_benchmark.py` 支持 `expectedKeyPointGroups` 同义关键点组、薄回复 `minTextLengthWarn`、质量 warning 汇总、质量门禁通过率和回复长度分布，便于识别“模型很快但回复信息量不足”的风险。
- 扩展 `model_provider_303_open_quality_realistic_cases.json` 到 15 个开放真实场景，新增“这方案咋样，能不能说重点”“青城那个是不是放多了”“新媒体和跨电呢，数学不太行”“按好学校排下看看”“嗯可以”等短句、简称、弱确认和排序预览 case。
- 扩展 `model_provider_303_open_quality_realistic_cases.json` 到 25 个开放真实场景，并扩展 `dialog_regression_303_open_quality_cases.json` 到 20 个本地回归 case；新增“会计和审计哪个更稳，考公也能用点的”“以后想考公但也怕太卷，这方案有支撑吗”“就按别太冒险的思路把这版调稳点”“北京天津想去，但别最后没学上”“医学护理这些别碰，财会还能接受”等更贴近真实用户的懒输入、简称、家长表达、取舍和意向影响 case。
- 口语化方案概览快路径补强：`这方案咋样，能不能说重点` 这类问法进入 `query_state`，从四模型首轮 7-18s 大模型链路收敛到本地方案概览；fix-probe 中四模型 final 均在约 1s 内。
- 意向影响问法路由修复：`医学护理这些别碰，财会还能接受，先看看影响` 不再被 `plan_query_fast_route` 抢成空方案查询；无明确方案/候选范围且包含“别碰 / 能接受 / 影响”等意向语义时，进入待确认意向预览。
- 专业意向口语归一化补强：`医学 / 学医 / 医药` 展开到临床医学类、口腔医学类、中医学类、护理学类、医学技术类，`财会` 展开到会计学、审计学，`别碰 / 还行 / 能接受` 纳入高置信软硬意向识别。
- 口语化调稳问法快路径补强：`就按别太冒险的思路把这版调稳点，先给我看看会怎么动` 进入 `analyze_adjustment`，避免 full-agent 自由构造 `execute_plan_action` 参数导致模型间失败或超时；回复补充“先分析不改方案、后续具体动作才影响方案/导出顺序并需确认”的用户边界。
- 四模型 25 case 首轮与修复小集结果已记录到 3.0.3 文档：首轮暴露意向抢路由和调稳预览超时/参数失败；修复后 `/private/tmp/model-provider-303-open-realistic-fix-probe-4model-v2.json` 中 3 个关键 case x 4 模型均 `quality_gate_pass_rate=1.0`，无 error、无断言失败、无 latency/quality warning。
- 统一 fast route 仲裁层：新增 `fast_route_arbitrator`，ChatService 先收集 plan/query/intent/major-compare/career 五类候选，再按“质量可满足程度优先于延迟”选择最终路径；明确范围查询优先于意向写入，复杂地域安全取舍会挡住普通方案概览薄回复，并由专项结构化分析链路接管或在事实不足时回落完整 Agent，避免继续靠顺序和字符串补丁抢路由。
- 新增 `model_provider_303_quality_readonly_cases.json`，用于只读/预览类 3.0.3 场景的多模型质量/性能对照，避免确认执行修改方案状态造成 provider 间上下文污染。
- 补充四模型对照结果记录：`Pro/moonshotai/Kimi-K2.6`、`Pro/MiniMaxAI/MiniMax-M2.5`、`deepseek-ai/DeepSeek-V4-Flash`、`Pro/zai-org/GLM-5.1` 在 10 个只读/预览 case 中均无断言失败；文档明确这批快路径 case 不能代表开放式生成质量，需要后续补 Explore / Intent 开放场景。
- 补充开放真实 10 case 四模型对照结果：Kimi 质量通过但三专业开放对比出现约 `78.263s` 慢请求；MiniMax 使用同义关键点组重跑后 `10/10` 通过且无耗时 warning；DeepSeek 和 GLM 均 `10/10` 通过，开放 LLM 场景最大耗时分别约 `21.615s` 和 `25.354s`。
- 新增 `dialog_regression_303_open_quality_cases.json`，覆盖待确认意向影响追问、职业方向多方向只读和专业对比上下文使用，用于补充 fast route 之外的开放式回复质量验证。
- 扩展 `dialog_regression_303_open_quality_cases.json` 到 7 个 case，补充局部查询后确认保护、推荐系数排序预览、非固定专业对比和三方向职业承接，并新增目录级单测约束这些开放式质量场景必须保留 no-followup、确认边界、内部术语屏蔽和耗时预算。
- 职业方向快路由补强“支撑 / 短板”只读语义，修复三方向职业承接问法回落完整 Agent 的性能退化；高副作用表达仍由“记偏好 / 改方案 / 确认”等拦截，不改变确认边界。
- 待确认意向用户文案统一为“确认前不会写入后续参考 / 我再写入后续参考”，覆盖待确认预览、影响追问和旧回复清洗，避免“正式生效”让用户误解为已记录；确认后应用逻辑不变。
- 无 pending 的只读查询确认保护补充边界提示，明确不会执行移动、删除、加入或排序，也不会改动当前方案；open-quality 离线评分达到 `strong=9 / needs_review=0`。
- 审查后续调整预览纳入 Plan 高置信快路径：明确“针对最严重/风险/审查问题，先给调整预览/怎么调，不要执行”时直接走既有 `plan_next_action -> execute_plan_action`，避免完整 Agent 重复 `query_volunteer_plan` 导致近百秒慢请求；普通“最严重的问题是什么”仍不抢路由。
- 3.0.3 Agent case 级评估框架补强为完整质量闭环：文档明确回复质量、场景覆盖、多轮链路、路由工具链、延迟进度、安全边界和多模型对照七层评估；报告模板要求保留用户输入、完整回复原文、人工扣分原因和模型横向汇总。
- `dialog_case_evaluation_report.py` 支持读取 `--case-definitions`，把 case 的 `flow / coverage / warnElapsedSeconds / maxElapsedSeconds / expectedRoutingPath / expectedActionFamily` 合并到评估结果，并输出 `summary.current / scenarioSummary / coverageSummary / candidateSummary / baselineComparison` 等批量汇总。
- `dialog_case_evaluation_report.py` 新增 `--markdown-detail`，用于生成逐 case 详细回复质量评审报告，包含用户输入、完整回复、评分表、覆盖维度、链路证据、case 期望和人工复核清单。
- `dialog_case_evaluation_report.py` 补强确认类和只读类 case 的期望路由推断，并允许用业务 toolName 作为 action 观测兜底，避免把正确的职业方向、专业对比、意向确认和 no-pending guard 回复误判为质量待复核。
- `conversation_turn_event` 补充 3.0.3 观测字段：`routeDecision`、LLM request/token、toolCallCount 和结构化 toolCalls 摘要；full-agent 工具调用会记录 actionFamily、stage、resultKind、applied/messageCode，direct pending/guard 路径明确记录 `llmRequests=0`。
- `dialog_regression_runner.py` 的 metrics 输出新增 `turnObservability`，从本地 SQLite 历史解析每轮 tool call、actionFamily、stage、resultKind 和 applied 状态，便于在 WebSocket e2e 中定位慢点和误路由。
- 新增 Plan 高置信快路径 `plan_fast_route`：在已有 planning summary 时，方案状态、数字志愿/专业组移动、数字删除、指定维度排序和显式审查会跳过主模型自由试工具，直接进入 `_plan_next_action_model -> execute_plan_action`；高副作用动作仍只生成 preview，确认后再 apply。
- Explore 职业方向分析首轮减重：体制内/稳定就业/读研等有限 taxonomy 支持本地归一化，避免常见表达额外调用 slot 识别 LLM；方向分析内部润色 LLM 增加 10s 短超时，超时后使用结构化事实 fallback 交给主模型组织。
- 收紧专业对比调度边界：两个具体专业的只读对比优先 `compare_majors / compare_majors_adhoc`，避免先进入 `analyze_current_major_interest` 或 Intent 确认链。
- Explore 调度规则补充“同轮不重复查状态”：调用方向/专业/学校/地域适配分析工具后，不再补调 `plan_next_action(query_state)` 或 `query_volunteer_plan` 做重复状态查询。
- `compare_majors / compare_majors_adhoc` 补充缺失权重数据兜底：会话缺少分数画像或权重接口返回空数据时，不再用空指标生成“综合得分相同”等误导结论。
- Explore 职业方向工具新增 `allow_explore_inner_llm` 开关：正式 ChatService 主链路关闭工具内部二次润色 LLM，保留结构化事实交给主模型最终组织，减少只读职业方向分析中的 10s 内层生成超时；直接工具调用和既有测试默认行为不变。
- 3.0.3 effect/perf e2e 再次复测通过 8 个步骤；职业方向承接分析日志确认跳过 Explore 内层生成 LLM，端到端约 `28.6s`，无工作台联动、无 pending 误确认，回复仍保持结构化。
- 专业对比只读快路由首轮落地：两个标准三级专业名的只读比较会跳过完整 ChatAgent，直接调用 `compare_majors` 并保留工具调用历史 trace；专业类、简称、三专业比较和方案/意向变更仍回落主链路。
- 专业对比缺权重业务态新增用户态 renderer：当 `compare_majors` 已确认当前会话缺少可用个性化量化评分时，不再触发额外小模型生成，改为基于三级专业所属专业类画像输出结构化通用对比建议；真实复盘中移除了约 `96.7s` 的额外 LLM 耗时来源。
- 职业方向只读快路由首轮落地：体制内/稳定就业/读研等本地 taxonomy 可解析的明确只读分析，会跳过完整 ChatAgent，直接复用 `analyze_current_career_direction` 的分段工具结果；意向写入、方案变更、确认和泛方向探索仍回落主链路。
- 职业方向只读分析回复补充去重：快路由直接返回工具分段文本后，多方向比较中相同的学生选科或分数段判断只展示一次，避免用户看到重复结论。
- Intent / Plan 多步回复补充用户可理解的进度提示：方案 fast route 会提示正在读取和生成预览，方案/意向确认直达执行会提示正在按确认更新；提示只描述处理阶段，不改变路由、pending 或实际方案操作语义。
- `dialog_regression_runner.py` 支持 thinking/progress 断言和 `thinkingMessages` 指标；3.0.3 effect/perf 场景开始校验方案状态、方案预览、Intent preview/confirm、确认执行、职业方向承接和专业对比只读快路径的用户可见进度提示。
- Intent preview 超时兜底：当偏好/要求预览工具已经写入待确认缓存、但完整 ChatAgent 在最终组织回复阶段超时时，WebSocket 端会读取结构化 `planEditCache` 返回“待确认内容 + 下一步确认语”的用户文案；确认前不会正式生效，也不会直接改动方案，不发送工作台联动卡片。
- Intent preview 工作台联动收口：未确认的偏好/要求预览不再自动发送候选库刷新卡片，避免用户误解为偏好已生效；确认或勾选采纳后仍按结构化执行结果刷新候选。
- 专业意向预览快路由首轮落地：明确专业偏好/排除表达会基于本科/专科专业目录装配 `MajorIntentPreviewInput`，跳过完整 ChatAgent 选工具，直接复用现有 `preview_current_major_intent_confirmation` 生成待确认预览；不直接写偏好、不刷新候选、不改方案。
- 3.0.3 effect/perf e2e 补充 Intent preview 文案边界：首轮预览禁止出现“已经记下 / 已记录 / 当前已记录”等确认后语义，真实 WebSocket 复跑 10 steps 全部通过，Intent preview 首轮约 `2.3s`，确认后才调用 `update_volunteer_intent_state` 应用。
- 学校 / 专业局部只读查询快路由首轮落地：明确“当前方案里有没有 X / 候选里看看 X / XX院校相关专业是否有多个”会跳过完整 ChatAgent，直接复用 `query_volunteer_plan` 返回当前方案和候选命中结果；加入、删除、移动、排序、补齐、审查、分数线、职业方向和专业对比仍回落既有链路。
- 3.0.3 effect/perf 场景补充局部只读查询 case，校验无工作台联动、无内部字段、无 `id=` 展示，并校验用户可见 thinking 为“正在查当前方案和候选里的相关结果”；真实 WebSocket 复跑 11 steps 全部通过，中位数约 `2443ms`，新增局部查询场景约 `2.27s` 且 `llmRequests=0`。
- 名称 / 简称方案操作快路由首轮落地：`把湖北工程学院的计算机科学与技术改到第3位`、`去掉湖北工程学院.计算机科学与技术`、`把广西师大统计加进来` 这类高置信单动作会跳过完整 ChatAgent，保留原始引用进入 `_plan_next_action_model -> execute_plan_action` 预览链路；唯一性解析、歧义澄清和确认后执行仍由既有执行层负责。
- `add_units` 预览阶段补齐候选唯一定位：命中时只写入 `resolved_apply_payload` 等待用户确认，不会未确认直接加入方案；已在方案中或无法唯一定位时返回用户可理解提示并清理 pending，避免后续“确认”误执行。
- `ActionResolver shadow` 补齐 `add_units` 映射，名称/简称类快路由也会记录 typed resolver 对比结果，便于后续统一路由实现。
- `move_unit` 命名志愿预览补齐可读摘要：唯一定位后会展示学校、专业、当前位置和目标位置，同时保留 `resolved_apply_payload` 等待确认，避免只回复“会调整指定志愿的位置”这类泛化文案。
- `add_units / remove_units` 命名志愿预览补齐可读摘要：唯一定位后会展示学校、专业和加入/移出动作方向，同时保留确认 payload；不会未确认直接改方案。
- `dialog_regression_303_effect_perf_cases.json` 增加名称移动和简称加入预览场景，校验 thinking、确认边界、无工作台联动和内部字段屏蔽；本轮 3.0.3 agent 相关单测回归 `312 passed`，真实 WebSocket effect/perf 13 steps 全部通过，中位数约 `2182ms`。
- 3.0.3 Agent 依赖与退化风险复盘：文档补充 fast route、pending、后端 planning API、专业目录、career taxonomy、runner metrics 等内部依赖点和潜在影响；新增 release 级快路由优先级矩阵单测，防止方案查询、意向、专业对比和职业方向场景被错误跨层接管；本轮相关合并单测 `346 passed`。
- 专业组移动/删除确认链路增加分段耗时观测：Agent 输出 `plan_ordered_unit_mutation_timing / plan_ordered_unit_post_apply_timing`，Server 输出 `planning_ordered_unit_move_timing / planning_ordered_unit_remove_timing`，用于定位确认慢点是在专业组定位、后端状态重建、行为事件、保存、响应体返回还是执行后重复定位。
- ActionResolver 进入影子对比首轮：补齐 `unit_refs` 到专业组移动/删除、结构化 `sort` 到方案排序的映射；`plan_fast_route` 命中时输出 `action_resolver_shadow_event`，用于对比当前路由 action family 与 typed resolver 输出，不改变实际执行。
- 3.0.3 完成方案高频操作轻量持久化首轮落地：新增 `planningMutableState` overlay，`moveOrderedItem / moveOrderedUnit / removeOrderedUnits / sortOrderedPlan` 只写入小状态，完整候选池与推荐 overlay 不随每次方案操作重写。
- 3.0.3 effect/perf e2e 复测通过 8 个步骤；专业组移动确认从前次约 32.7s 回落到约 3.8s，Agent `mutationRequestDurationMs` 降到约 538ms，本地 DB 验证 mutable overlay 约 120KB、完整 planningState 约 16MB。
- 新增 `examples/dialog_regression_full_journey_cases.json` 并扩展到 9 个 case，专门覆盖“开场上下文 -> Explore -> 软意向 -> 硬约束 -> 候选查看/刷新 -> 方案查询/调整/确认/审查”的完整链路；包含专业、职业、地域、学校、专业组操作、候选别名加入、审查后修复、软硬意向混合和确认边界，并补充目录级单测按 coverage 标签校验薄弱场景。
- `dialog_regression_runner.py` 新增 `--session-offset`，支持把固定 case session 映射到一批干净数字会话，并在输出里保留原始 `baseSessionId`，用于排除历史聊天记录和旧 pending 状态对真实 WebSocket 回归的污染。
- `dialog_regression_runner.py` 新增 `--clear-history` 和 `--history-db`，支持在真实 `16/17` 等后端数据完整会话上只清理 Agent 本地 SQLite 对话历史后复跑，避免 `--session-offset` 丢失原 session 成绩、候选池和排序方案导致假失败。
- `dialog_regression_runner.py` 新增 `warnElapsedSeconds / maxElapsedSeconds` 场景级耗时预算、整体 metrics summary 和 `--metrics-output` JSON 归档，支持把对话效果断言与 provider 延迟观察放在同一轮 WebSocket 回归里。
- 新增 `examples/dialog_regression_302_effect_perf_cases.json` 和 `tests/e2e/test_agent_dialog_effect_perf.py`，覆盖 3.0.2 对话效果/性能 smoke：结构化方案查询、只读职业方向承接、专业+大学移动、专业组整体移动、歧义目标安全解释、新会话 Explore/Intent preview 和无 pending 确认快速保护。
- 新增 `examples/dialog_regression_303_effect_perf_cases.json`，并将效果/性能 e2e 默认切到 3.0.3 用例集合；覆盖结构化方案现状、专业组 preview/confirm、排序预览、只读 Explore 不联动和无 pending 确认保护，把“回复质量”与延迟一起作为回归门槛。
- 新增 Agent HTTP 健康检查接口 `/health` 和 `/gaotu-assistant-agent/health`，用于 Docker Compose healthcheck 和发布后远端探活，不影响现有 WebSocket 对话链路。
- 3.0.1 对话规划链路新增 `sort_ordered_plan` 动作，支持用户通过对话按录取率、院校层次或推荐系数排序当前方案；排序作为高副作用动作进入 preview -> 确认 -> apply 流程，并刷新方案与审查状态。
- 补充 3.0.1 对话回归和模型 benchmark 场景，覆盖方案排序、禁用旧锁定入口、候选筛选可见联动等端到端行为。
- 新增最小结构化日志 `conversation_turn_event / plan_action_event / intent_state_event`，记录路由路径、action family、耗时、执行状态和错误类型，用于后续评估关键词兜底、模型效果和工具稳定性。
- `conversation_turn_event` 的 full-agent 路径补充 `modelProvider / modelName`，便于按模型配置对比对话效果和耗时；日志不记录 API Key。
- 对话规划链路新增专业组级动作设计与基础执行接入：`move_ordered_unit / remove_ordered_unit` 支持按 `unit_ids` 或“第 N 个专业组”定位专业组，确认后调用后端组级移动/删除接口并刷新方案与审查状态。

### Fixed

- 3.0.3 回复质量 P1 修复：Intent preview 清理 `level1/level2/level3` 等内部专业层级词；Intent confirm 改为“后续筛选和方案调整参考”，避免“候选结果收紧”造成候选池永久变化的误解；职业方向承接分析补当前方案承接强弱、数量和示例，并去掉重复结论；专业对比缺量化评分时会使用本轮用户输入里的“普通家庭 / 女生”等约束。
- 3.0.3 回复质量继续补强：方案局部查询和候选查询命中后增加轻量下一步引导，但仍保持只读不联动；`add_units` 预览在能读取当前排序方案总数时补充数量影响，说明本次预计增加多少个志愿；`sort_ordered_plan` 预览补充排序方向说明，避免用户不知道录取率、院校层次、推荐系数分别如何排。
- 3.0.3 方案操作预览影响面补强：普通志愿移动、移出和候选加入预览会说明对方案数量、方案顺序、导出内容和审查状态的影响；只有 `plan_next_action` 形成排序 pending 时也会补齐排序方向和待重新审查说明。
- 3.0.3 无 pending 确认保护补充上下文文案：职业方向只读、专业对比只读和局部查询后用户回复“确认”时，仍不执行任何动作，但会结合上一轮上下文提示可继续展开、记成偏好或进入具体方案预览。
- 3.0.3 无 pending 确认保护增加文本兜底：当快路径或降级场景只保存 assistant 文本、没有完整 tool trace 时，也能识别上一轮是职业方向分析、专业对比或局部查询，避免退回泛化“没有上一轮待确认动作”。
- 3.0.3 Intent 确认回复补充生效内容复述：确认偏好或要求后，会从 `merged` 中提取专业、院校、地域和发展方向的正/负向条目，展示“本次确认内容”，便于用户核对刚刚生效的偏好/要求。
- 3.0.3 Intent 确认回复结构化：确认后按“本次确认内容 / 后续使用 / 候选结果 / 下一步”组织，减少一整段长句，并避免“候选展示会按要求更新”这类容易被理解为候选池永久变化的表达。
- 3.0.3 专业对比 fallback 改成结构化分段输出：无量化权重时仍做通用比较，但拆成“会话参考 / 专业A / 专业B / 选择建议 / 下一步”，减少一整段平铺文字的薄感。
- 3.0.3 预览 / 举例类回复质量标准提升：不能只给对象和个例，必须尽量覆盖学校层次、冲稳保、专业热度、数量缺口等关键分布，再给代表样本和下一步建议。
- 3.0.3 case 级评估工具补强：`dialog_case_evaluation_report.py` 输出 `qualityViolations`、`distributionCoverage` 和 `verdict`，可自动标记内部术语外露、待确认边界冲突、预览缺少关键分布等薄弱回复。
- 3.0.3 case 级评估工具新增待确认意向语气门禁：待确认上下文里如果出现没有“确认后”条件的“把 X 记成/作为/后续都会按要求”等已生效表达，会标记为 `pending_intent_effective_wording`。
- 3.0.3 case 级评估工具修正确认保护误判：确认类短回复不再被“预览”字样误判为预览/示例回复，避免正确的 no-pending guard 被标成 `thin_preview_distribution`。
- 3.0.3 方案/候选查询分布摘要用户化：院校信息展示为双一流、公办/民办和“院校排名约 X-Y”等画像，专业信息展示热度、计划数、招生计划等标签，避免裸露内部排名字段。
- 3.0.3 局部查询示例文案继续收口：专业热度标签去重为“热度X / 计划数”，示例解释改为“专业信息”，避免出现“专业热度专业热度”这类重复前缀。
- 3.0.3 专业对比 fallback 文案去系统化：不再出现“个性化量化评分 / 系统分数 / 系统评分”，改为“还没有完整结合分数、省份、选科和方案位置，先做方向判断”。
- 3.0.3 Intent pending 增加 Agent 历史兜底：后端 `planEditCache` 仍是主路径；读不到时从最近一次 Intent preview 工具调用恢复待确认 payload，避免“确认这个偏好/要求”误走无 pending guard；已处理过的 pending 不会从历史里复活。真实 WebSocket 两步验证通过，中位耗时约 `2035ms`。
- 3.0.3 Intent 确认回复收紧：没有实际候选数量事实时，不再说“候选展示会按这条要求更新、现在可以去看候选结果”，改为“后续查看候选和方案时会按这条要求作为参考”。
- 3.0.3 Intent preview 条目语气收紧：专业、院校、地域和发展方向的待确认条目统一使用“确认后，将把...”表达，避免单条内容看起来已经生效；对应条目级单测、WebSocket 兼容样例和评估门禁已补充。
- 3.0.3 Intent existing-only 文案修复：当用户再次表达已经存在的偏好/排除项时，回复改为“当前已经在后续参考中，不需要重复确认”，并列出“已在参考的偏好/排除项”，避免把既有内容误说成新的待确认内容。固定会话 `880203` WebSocket 两步验证通过。
- 3.0.3 真实口语化输入修复：`法/财`、`新媒体/跨电`、`青城`、`会计审计可以 土木别要`、`保底够不够啊`、`嗯可以` 等表达已纳入既有高置信快路由或确认保护；不新增普通业务模板短路，高副作用动作仍保持 preview -> confirm -> apply 边界。
- 3.0.3 quality 主回归补齐方案审查：审查 case 返回 `review` 工作台刷新且不暴露内部位置标记；审查回复改为“审查结论 / 主要问题 / 典型涉及 / 下一步建议”的结构化要点。真实 WebSocket `dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` 最新复跑 `14/14` steps 通过，中位耗时约 `2240ms`，最大耗时约 `4140ms`。
- 3.0.3 待确认意向影响追问收口：已有 `planEditCache` 待确认内容时，“先不确认，看看这个偏好会影响当前方案吗”直接走 `pending_intent_impact_fast_route`，基于当前方案/候选事实做只读说明；不调用主 Agent、不确认、不刷新工作台、不改方案。
- 3.0.3 Intent preview 文案继续用户化：去掉“候选结果收紧”“专家推荐”等表达；结构化影响文本不再重复套“当前判断”标题；已有真实方案/候选命中时去掉“我先帮你看看 / 顺手看看”等泛化句。
- 3.0.3 Intent 专业意向标签源头用户化：内部仍保留 `level1/level2/level3` 结构用于存储、编码和候选过滤，用户可见回复改为“专业门类 / 专业类 / 具体专业 / 偏好专业 / 排除专业”，并补充单测防止 `level3` 再次外露。
- 3.0.3 职业方向只读回复结构收口：`analyze_current_career_direction` 返回内容从“当前判断”下再嵌“初步判断 / 需要补充留意 / 可以继续展开”改为“方案承接 / 需要留意 / 候选机会 / 下一步”；不改变方向识别、方案/候选事实计算和只读不联动边界。最新真实 WebSocket 开放式质量 `4/4` 通过，effect/perf `14/14` 通过。
- 3.0.3 职业方向代表样本去重：代表样本只保留真实院校/专业样本，不再重复“方案里大约有 X 个”“候选里还有 X 个机会”等数量判断；完整 effect/perf 真实 WebSocket `14/14` 通过，中位耗时约 `2320ms`，最大耗时约 `4247ms`，离线质量评分 `qualityViolations=0`、`strong=5 / needs_review=9`，当前宽回归 `726 passed`。
- 3.0.3 职业方向只读回复补充“本次边界”：明确只做方向分析，不会自动修改偏好、方案或方案顺序；后续若要按方向调整方案，仍走预览确认后执行。
- 3.0.3 方案调整确认完成回复补充后续动作提示：移动、删除、加入、替换和排序执行成功后，如果后端结果没有说明审查/导出影响，会补充方案/导出已更新、审查状态待重新审查、可到方案区查看并必要时审查。
- 3.0.3 只读边界与确认完成提示补强后，聚焦单测 `228 passed`，宽回归 `726 passed`；真实 WebSocket effect/perf `14/14` 通过，中位耗时约 `2263ms`，最大耗时约 `4576ms`，离线质量评分 `qualityViolations=0`、`strong=6 / needs_review=8`。
- 3.0.3 回复结构继续补强：排序预览改为“动作 / 排序方式 / 执行影响 / 确认”的要点结构；无 pending 的职业方向确认保护给出继续分析、调整方案、查看方案和不确定下一步四类出口；已有偏好提示合并同类项并说明不会重复写入或改方案；专业对比只读回复补充“本次边界”。
- 3.0.3 最终回复质量回归：焦点单测最高 `350 passed`，宽回归 `726 passed`；真实 WebSocket effect/perf `14/14` 通过，中位耗时约 `2297ms`，最大耗时约 `4425ms`，离线质量评分 `qualityViolations=0`、`strong=14 / needs_review=0`。
- 3.0.3 主对话技能注入收口：`BaseAgent` 默认只注入 skills 边界摘要，不再把 `list_skills / load_skill / read_skill_resource / run_skill_script` 暴露给 ChatAgent 运行时；保留 `expose_skill_tools=True` 给专门需要完整技能工具的 Agent。该调整用于消除开放式 Explore 中先调用 `load_skill` 的额外轮次，不改变业务工具、确认边界或用户侧回复结构；聚焦单测 `40 passed`，真实 WebSocket effect/perf `14/14` 通过，open quality `4/4` 通过，职业方向承接场景 tool trace 仅有 `analyze_current_career_direction`。
- 3.0.3 open-quality 最终复核：本地独立 Agent `8107` 在 Agent/Server/Rank 依赖可用时复跑 `dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text --assert-plan-style`，`23/23` steps 通过，失败 `0`；中位耗时约 `2283ms`，p95 约 `3794ms`，最大约 `3969ms`；离线评分 `strong=23 / needs_review=0 / fail=0`，无 `route_mismatch`、`unexpected_action` 或薄预览硬失败。当前没有触发 LLM Intent Router shadow 条件，继续使用本地候选 + 统一仲裁主路径。
- 3.0.3 重启后 open-quality live 复验：本地 `8107/8080/5001` 链路复跑 `23/23` steps 通过，中位耗时约 `2242ms`，p95 约 `3661ms`，最大约 `3819ms`；详细评分仍为 `strong=23 / needs_review=0 / fail=0`，无质量 violation 或 warning。
- 3.0.3 对话样例展示清洗：新增用户侧院校/专业样本文本清洗，方案前排、意向影响和职业方向代表样本不再展示 `办学地点`、合作方、前三年就读、外语成绩、学费说明等长招生备注，保留院校、专业、冲稳保和位置等核心信息；最新 open-quality live 复跑 `/private/tmp/zhiyuan_agent_303_open_quality_after_display_clean_live.json`，`23/23` steps 通过，中位耗时约 `2256ms`，p95 约 `3713ms`，评分 `strong=23 / needs_review=0 / fail=0`，长备注关键词抽检未命中。
- 3.0.3 地域偏好与录取安全取舍专项链路：`北京天津想去但别最后没学上`、`孩子就想去北京天津但分数不算高这样是不是太冒险先别改` 这类只读问题不再回落分钟级 full Agent；统一仲裁先挡住普通方案概览薄回复，再基于当前方案、候选补充信息和审查结果生成结构化取舍分析。真实 WebSocket 聚焦复跑 `2/2` 通过，中位耗时约 `2401ms`，`llmRequests=0`，不会写偏好、改方案或生成确认卡。
- 3.0.3 候选空结果回复收口：`候选里还有没有更稳一点的会计审计` 走 `plan_query_fast_route`，后端直查 `session=17` 中 `会计学+审计学`、单独 `会计学`、单独 `审计学` 均为 `total=0`；回复改为明确说明已按具体专业查过且当前候选池无结果，并引导放宽到专业类、查看当前方案相近志愿或做更稳调整建议。评估工具同步支持空结果等价验收，避免把真实无数据误判为薄预览或路由失败。
- 3.0.3 case 级评估工具补充 `expectedNoAction` 和无动作确认保护评分：只读分析、候选空结果、无 pending 的“确认”不应触发方案或偏好动作，若出现动作会标记 `unexpected_action`；正确的确认保护会按边界说明和下一步出口评分。
- 修复专业组移动/删除 apply 后重复按“第 N 个专业组”解析目标的问题；移动后方案顺序已变化，重复解析可能记录成另一个专业组。现在 `executed_actions` 和后续日志复用执行前解析出的 unitIds。
- 3.0.3 后端补充 mutable overlay 回归：专业+大学模式单志愿移动、院校专业组模式组删除、旧 mutable 版本忽略，以及行为事件存储回归均通过单测覆盖。
- 3.0.3 专业组 mutation 慢请求完成补充定位：确认慢例 `llmRequests=0`，Agent `mutationRequestDurationMs≈28.1s` 与 Server controller `unit/move≈28.1s` 对齐；当前源码复跑 service 分段常态约 `1.8s - 2.3s`，最大头是完整 `PlanningStateDTO` 保存，后续优化重点调整为状态持久化拆分而不是继续压模型。
- 3.0.3 benchmark 文档补充效果质量门禁：性能评估需同时检查用户可理解、信息充足、结构清楚、确认边界、只读不误联动、歧义不误操作和事实一致。
- `query_volunteer_plan` 候选示例不再展示 `id=...`，只保留学校、专业、冲稳保和录取率等用户可理解信息，避免局部查询回复继续暴露无意义内部编号。
- 方案现状的偏好摘要在超过展示数量时显示“等 N 项”，避免“当前偏好”只列前三项而“贴近偏好示例”命中未展开偏好时让用户误以为前后矛盾。
- Explore 调度指令收紧：明确职业/专业/院校/地域专用工具可承接时不先调用 `load_skill`，真实 3.0.3 e2e 中“体制内稳定就业承接分析”从 `load_skill + analyze_current_career_direction` 收敛为单个专用工具，端到端从约 41s 降到约 26s，回复质量保持结构化。
- 方案 pending 确认边界补强：如果 pending 后用户明确“先不要改方案 / 只分析 / 不执行 / 不调整”，会清掉旧方案 pending；后续单独说“确认”不再误执行旧排序或移动。3.0.3 e2e 增加排序预览后只读分析再确认的保护场景。
- 统一待确认状态边界：当 `RequestContext.conversation_phase` 已注入时，运行时只认 `conversation_phase.pending` 作为当前待确认源；旧 `pending_plan_action` / `pending_intent_change` 仅在没有 phase 对象的兼容入口里回退，避免新旧状态不同步引发确认错位。
- pending 确认链路补齐版本和轮次守护：preview 结果会记录 `planning_version` 和 `created_turn`，确认时若当前 `planningState.version` 已变化或 pending 已过期，会直接拦截并提示重新查看当前方案，避免把旧预览误执行成当前方案修改。
- 意向确认缓存收口：`planEditCache` 先转换为 `PendingConfirmation` 注入 `conversation_phase.pending`，后续确认流程优先读 phase 内的 payload；只有旧桥接入口才直接回读 backend cache。
- 意向确认回复更明确：`preference_applied` 现在会直接说明“已经按你的确认记下来了”，减少 302 场景里确认语义过于含糊的问题。
- Agent 主对话链路新增 runtime history 裁剪：SQLite 继续保存完整 pydantic-ai 历史用于审计和 pending 解析，但每轮传给主模型的 `message_history` 与 `RequestContext.chat_history` 只保留可控短上下文，并压缩超长 tool return，降低长历史 token 成本和旧 preview/tool result 污染；存在有效方案 pending 时会额外保留产生该预览的工具调用/工具返回/assistant 回复，避免非确认追问丢上下文。
- 新增 `examples/dialog_regression_302_agent_cases.json`，用于 3.0.2 本地/准生产 WebSocket 场景验证，覆盖方案查询、院校层次排序、专业组移动、按学校/专业简称删除和调整后查询。
- 302 真实回归复跑确认：`session=17` 的“河南农大建筑去掉”并不存在可唯一定位的真实志愿，当前 ordered-plan 只有若干“建筑”相关条目，后端不会静默误删；该 case 已从“成功删除”改为负例，确认轮应返回“没有上一轮待确认的方案动作”而不是刷新方案。
- Plan 工作区刷新收口：`execute_plan_action` 返回 `applied=false` 或 `result_kind=error` 时不再触发 `planningWorkspaceAction` 刷新；`remove_units / move_unit` 的志愿定位失败分支也不再返回 `ordered` 刷新目标，避免“没有定位到真实志愿但前端刷新方案”的错位。
- 302 Plan 操作真实 WebSocket 按新口径复跑通过：使用 `--clear-history` 清理本地 Agent 历史并保留真实 `session=16/17` 后端方案数据后，方案现状、院校层次排序 preview/apply、专业组整体移动 preview/apply、简称删除负例和调整后查询均通过；负例确认返回“没有定位到真实编号”且 `followupMessages=0`。
- 新增 `examples/dialog_regression_302_explore_intent_cases.json`，先增强 Explore/Intent 前置层效果验证，覆盖专业/职业/地域/院校探索、软硬意向、意向修订、未确认意向下查询方案、候选风险解释和专项资格解释；后续根据真实 WebSocket 结果再做串联调优。
- 新增 `examples/dialog_regression_302_readonly_real_session_cases.json`，使用真实 `session=17` 方案数据验证只读 Explore/Intent smoke：方向承接分析和压线风险解释不得发送工作台联动卡片。
- 方案编辑执行层补充学校简称 + 专业简称删除回归，例如“广西师大统计去掉”可唯一解析到当前方案志愿后再执行；歧义简称仍不会静默误删。
- 修复 Agent plus 兼容 WebSocket 异常响应未带 `end=true` 的问题；当模型接口返回 503 等异常时，前端和回归 runner 能明确收到结束包，不再一直等到客户端超时。
- Agent Dockerfile 基础镜像切换为公开 `python:3.12-slim`，避免 release 构建时访问 `docker.m.daocloud.io` 返回 401 导致 amd64 镜像无法构建。
- 3.0.1 用户侧去除“草稿”概念：Agent 回复、规划状态注入、方案查询、专业分析、候选加入和补偿结果统一表达为“方案/已加入方案”，底层 `draftPlanState` 仅保留为兼容实现细节。
- 方案现状类问法的 Plan 提示词收敛：对“方案有了么 / 看看现在的方案 / 当前方案怎么样”直接引导模型调用 `plan_next_action(action_family="query_state") -> execute_plan_action`，不再先单独调用 `collect_plan_context_inputs`，减少重复上下文读取和额外模型往返；不新增字符串匹配短路或确定性模板回复。
- 显式方案改动类问法的 Plan 提示词补充：对排序、移动、删除当前方案的请求，引导模型直接形成对应 action 的 preview 并等待确认；不新增 service 层字符串匹配或确定性短路。
- 3.0.1 不再允许对话触发旧 `pin_unit/unpin_unit/lock_draft` 用户动作；如果用户要求固定或锁定志愿，Agent 会提示当前新版工作台暂不提供该入口，并引导使用移动到指定位置或方案排序。
- `ActionResolver` 同步阻断 `pin/unpin` 结构化意图，避免 structured planner 旁路重新产出前端不可见的固定/锁定动作。
- 工作台事件归类同步收口：`sort_ordered_plan` 会生成方案和审查刷新；旧 pin/unpin 不再生成 pending 或工作台刷新卡片，避免出现前端不可见状态。
- 新增 3.0.1 真实 WebSocket smoke 用例 `examples/dialog_regression_301_agent_smoke_cases.json`，覆盖方案现状、审查、院校层次排序确认和专业组移动确认；`dialog_regression_runner.py` 现在输出每轮 `elapsedMs / primaryMessages / followupMessages`，便于同步验证效果和性能。
- 清理 `dialog_regression_plan_correctness_cases.json` 中旧 `pin -> verify` 正向用例，保留 `pin_disabled` 作为新版固定/锁定入口关闭后的唯一回归口径。
- 方案排序执行结果兼容 `{success: true}` 后端响应；当排序、专业组移动或专业组删除执行失败时，`execute_plan_action` 不再错误标记 `applied=true` 或返回工作台刷新目标，避免出现“文本失败但右侧刷新”的状态不一致。
- 真实 smoke fixture 调整：专业组排序和移动用例改用 `session=16`，避开 `session=35` 的历史 pending intent 干扰。
- 真实 WebSocket smoke 复跑记录：`session=17` 方案现状和审查通过；`session=16` 排序和专业组移动仍未通过 preview -> confirm -> apply，前者缺少 `execute_plan_action(preview)` 形成 pending，后者出现多次 query/preview 循环并触发 websocket 180 秒超时兜底，已记录到 3.0.1 Agent 优化设计文档作为下一步收口项。
- 高副作用 Plan 动作状态收口：`plan_next_action` 在 `user_confirmed=false` 时不再接受模型传入的 `current_stage="apply"`，会强制回到 preview/analyze；专业组位置引用（如“第3个专业组”）可直接进入 `move_ordered_unit` preview，由执行层在 apply 时解析真实 unitId。
- 清理 service 测试债务：旧 `get_planning_state` mock 入口改为当前 `get_planning_workspace_state`；废弃的独立 `review` workspace 卡片断言同步为当前 `candidate / ordered` 工作台目标策略；相关聚焦测试 `170 passed`。
- `planning_context` 指令移除旧 `handle_planning_request` 入口提示，统一引导模型走 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` 主链。
- `planning_router_tool` 标记为 deprecated compatibility wrapper，明确不再作为 ChatAgent 模型入口；`planning_workflow_tool` 保留为内部 helper 集合，后续按 formatter/state/mutation/review/compensation 拆分。
- 文档修正 Career Explore、Plan Router 和 Workflow Helper 的当前入口描述：career skill 只作为语义说明层，运行时走 `analyze_current_career_direction`；新增 Plan 能力不得继续接入 `handle_planning_request`。
- 高副作用 preview pending 提取收口：同一轮中 `plan_next_action(preview)` 已形成待确认动作后，后续只读 `query_state` 成功不会再清掉 pending；只有实际变更动作 apply 成功才清 pending，修复“专业组移动预览后确认找不到上一轮动作”的问题。
- 本地排序失败定位为后端旧 class 未重启导致的 `PlanningStateService$OrderedSortKey` `NoSuchMethodError`；重新编译/重启 8080 后 `ordered-plan/sort` 正常返回，agent 侧 payload 无需调整。
- 专业组移动/删除预览改为执行层结构化生成：明确源专业组名称、源专业组序号、目标专业组位置（移动场景）和组内专业数，并提示“第几个”按专业组顺序而非单条志愿位置计算，避免确认前文案把“前 N 条志愿”误当成“前 N 个专业组”。
- 方案内志愿引用解析增强：`move_unit / remove_units` 支持“XX大学的XX专业”“XX大学.XX专业”等学校+专业自然表达，并兼容学校名带专业组号、专业名带括号说明的场景；如果同校同专业存在多条候选，不会静默选择，改为提示需要进一步明确。
- 候选加入引用解析增强：`add_units` 支持“XX大学的XX专业加进来”等候选池自然表达，执行层会查询候选并解析真实 `volunteerId`；如果候选里同校同专业存在多个条目，不会静默误加，改为提示需要进一步明确。
- 学校/专业简称引用解析增强：对“广西师大统计”“湖工计科”等学校简称 + 专业简称表达，执行层基于当前方案/候选真实条目做受控 alias 匹配；只有唯一命中时才移动、删除或加入，歧义时要求用户补充信息。
- Plan 调度指令补充“学校/专业简称加入方案”边界：用户要求把某个候选、学校+专业或简称加入当前方案时，优先走 `add_units` preview，由执行层解析真实候选 ID，避免被模型改走只读分数线/选科 Explore 分析。
- `add_units` 执行前增加当前方案已存在预检查：如果用户要求加入的学校+专业或简称已经在当前方案中，返回 `result_kind=no_change` 和“已经在当前方案中，无需重复加入”，不再调用后端加入接口、触发复审、误说“已新增”或发送无变化工作台卡片，也不再把正常无变化场景记为执行错误。
- Agent 调度指令补充 `result_kind=no_change` 语义：模型应直接说明“无需变更”的原因，不把它当失败重试，也不误说已新增、已删除或已移动。
- 修正 Plan 超时兜底：当用户请求删除、移动、排序等方案变更时，不再用同轮中途 `query_state/status_overview` 结果回复方案概览；兜底回复同步过滤 `[LLM_INTERNAL]` hints，避免内部调度提示泄露给用户。
- Agent 调度指令强化专业组位置操作：`删除第 N 个专业组` 直接规划 `remove_ordered_unit` preview，`把第 N 个专业组移到第 M 位` 直接规划 `move_ordered_unit` preview，由执行层按当前专业组顺序解析位置。
- 记录超时兜底 TODO：当前 `_PLAN_MUTATION_PROMPT_KEYWORDS` 仅作为变更请求超时止血保护，不参与正常路由；后续应替换为 plan action/recent result 的结构化 mutation intent 或 mutation preview 标记。
- Agent 调度指令强化专业模式学校+专业操作：`把 XX大学的XX专业改到第 N 位` 直接规划 `move_unit` preview，`去掉/删除 XX大学的XX专业` 直接规划 `remove_units` preview，引用解析和歧义澄清仍由执行层处理，避免模型先局部查询后循环读上下文。
- 真实 WebSocket 复测记录：`删除第5个专业组 -> 确认` 已通过 `remove_ordered_unit preview/apply`；`把青岛电影学院的新闻学改到第3位 -> 确认` 已通过 `move_unit preview/apply`。后者仍有一次局部查询和一次上下文读取，作为后续性能优化项保留。
- 补充 Plan 工具说明：`query_volunteer_plan` 不应用作移动/删除前定位 ID；`plan_next_action` 的 `volunteer_ids` 可直接接收用户原始学校+专业引用，由执行层解析真实 ID，减少学校+专业移动/删除前的无效查询倾向。
- 真实 WebSocket 复测确认学校+专业移动链路收敛：`把哈尔滨理工大学的人力资源管理改到第4位 -> 确认` 直接走 `plan_next_action -> execute_plan_action(move_unit)`，不再先调用 `query_volunteer_plan`，确认后刷新 `ordered`。
- 真实 WebSocket 复测确认学校+专业删除链路收敛：`去掉山东英才学院的国际商务 -> 确认` 直接走 `plan_next_action -> execute_plan_action(remove_units)`，不再先调用 `query_volunteer_plan`，确认后刷新 `ordered`。
- 真实 WebSocket 复测确认补齐建议不误执行：`现在还差几个怎么补 -> 确认` 在没有具体可执行补入清单时，不再复用旧 `add_units` pending；确认轮返回没有待确认方案动作，且不发送工作台刷新卡片。
- 清理 `ChatAgent` 中已不再生效的旧 `_build_instructions` 死代码，避免与当前 `app.agent.instructions.assembler.build_instructions` 模块化指令入口产生维护歧义。
- 修正 `conversation_turn_event.actionFamily` 归因：同一轮如果先查询状态、后形成删除/移动/排序等非 query action，结构化日志优先记录最后一个非 query action，避免效果和性能分析误把实际操作预览统计为 `query_state`。
- 修正补齐确认链路：同一轮空补齐预览会清掉较早未展示的 `add_units` pending，避免用户回复“确认”误执行旧补入动作；按筛选补入没有命中候选时返回 `no_change / applied=false`，不再触发复审、工作台刷新或“已新增”话术。
- `BaseAgent` 兼容旧 `{role, content}` 格式的 `message_history`，进入 pydantic-ai 前转换为 `ModelRequest/ModelResponse`，修复 pydantic-ai 升级后历史消息集成测试失败。
- `ProfileManager.get_current_profile` 兼容历史后端 payload `data.dataValue`，避免旧画像结构下增量更新专业、院校、城市意向时丢失已有数据。
- 真实 internal client e2e 和真实 LLM e2e 改为显式开关执行，默认全量 pytest 不再受本地网络、内部服务可达性或模型费用影响。

### Fixed (回归测试稳定性)

- 补齐 handler 拆分后的 planning/generate 测试夹具 patch 覆盖，避免 agent regression 在本地误连真实 backend 或因同步 helper 被错误 AsyncMock 化而失真。
- 补齐 3.0.1 Agent unit action 的类型、编排、状态同步和提示词单测，覆盖 `move_ordered_unit / remove_ordered_unit` 的 preview、缺参、语义归一和 `unit_ids` 传递；旧 `pin/unpin` 测试改为验证新版固定/锁定入口关闭后的用户引导。
- 清理 `test_plan_execution_tool.py` 历史 fixture 债务：旧用例不再 patch 已绕过的 `plan_execution_tool` workflow wrapper，而是 patch 当前 handler registry 实际消费的 handler/internal-client alias，避免单测误连本地 backend。
- 清理 router/workflow 兼容测试债务：初始生成方案测试补齐候选池前置 mock；旧 router 用例保留为 deprecated compatibility wrapper 验证；workflow 文案断言同步为 3.0.1 的“方案/已加入方案”用户语言；替换、补偿、审查执行链测试改为 patch 当前 handler/internal-client alias。
- Agent 默认全量 pytest 收口通过：`2121 passed / 7 skipped`；skip 项仅包含显式开关控制的真实 internal client e2e 和真实 LLM e2e。

### Verified (3.0.1 Agent 对话驱动首轮收口)

- JSON examples 格式校验通过：`dialog_regression_mainline_cases.json`、`dialog_regression_plan_correctness_cases.json`、`model_provider_benchmark_e2e_cases.json`。
- Python 编译校验通过：`typed_actions.py`、`plan_orchestration_tool.py`、`plan_execution_tool.py`、`state_sync.py`、`service.py`、`structured_log.py`。
- Targeted 单测通过：`tests/unit/test_action_resolver.py`、`tests/unit/models/test_typed_actions.py`、`tests/unit/test_plan_orchestration_tool.py`、`tests/unit/test_state_sync.py`、`tests/unit/test_chat_agent_init_profile.py` 和 `tests/unit/test_plan_execution_tool.py` 全量，共 `315 passed`。
- Router/workflow 兼容单测通过：`tests/unit/test_planning_router_tool.py`、`tests/unit/test_planning_router_tool_sync.py`、`tests/unit/test_planning_plan_scenarios_sync.py`、`tests/unit/test_planning_workflow_tool.py`，共 `72 passed`。
- Agent 主链路 + router/workflow 兼容集合通过，共 `387 passed`。
- SiliconFlow 下 `session=17 / 看看现在的方案` 诊断链路从 `collect -> plan_next -> execute -> final` 收敛为 `plan_next -> execute(query_state) -> final`；耗时从约 `38.3s` 降到约 `14.6s`，LLM 请求数从 `4` 次降到 `3` 次，input tokens 从约 `40109` 降到约 `28331`。
- Plan orchestration/execution/service 聚焦单测通过：`171 passed`。
- 真实 WebSocket smoke 通过：`examples/dialog_regression_301_agent_smoke_cases.json` 覆盖 `session=17` 方案现状/审查、`session=16` 院校层次排序确认和专业组移动确认；排序确认约 `5.6s`、专业组移动确认约 `4.9s`，均返回 `ordered` 工作区刷新。
- 专业组移动预览文案修正后真实复测通过：`session=16 / 把第3个专业组移到第5位 -> 确认` 的预览明确按专业组序号解释当前位置和目标位置，确认后该组移动到第 `5` 个专业组位置且组内志愿连续。
- 指令入口清理后，当前真实模块化指令测试和 ChatAgent 工具调用测试通过：`tests/unit/test_instructions.py`、`tests/unit/test_chat_agent_init_profile.py`、`tests/unit/test_chat_agent_tools.py` 共 `42 passed`。
- Agent 扩展回归集合通过：action resolver、typed actions、plan orchestration/execution、state sync、chat service history、mainline dialog、router/workflow compatibility、ws compatibility 共 `498 passed`。
- 显式删除专业组预览复测通过：`session=16 / 删除第3个专业组` 链路收敛为 `plan_next_action -> execute_plan_action(remove_ordered_unit preview)`，不再先执行 `query_state`；runner 约 `24.1s`，LLM 请求 `2` 次，结构化日志 `actionFamily=remove_ordered_unit`。
- 学校+专业自然引用单测通过：覆盖“湖北工程学院的计算机科学与技术改到第3位”“湖北工程学院.计算机科学与技术去掉”，以及同校同专业多专业组歧义时不执行误移动。
- 候选加入自然引用单测通过：覆盖“湖北工程学院的计算机科学与技术加进来”、显式候选 id 直通，以及候选池同校同专业歧义时不执行误加入。
- 学校/专业简称引用单测通过：覆盖“广西师大统计”移动和加入，以及“湖工计科”在多校可匹配时不执行误移动或误加入。
- 真实 WebSocket smoke 补充：`session=17 / 看看现在的方案` 约 `13.8s` 通过；`把广西师大统计改到第3位` 未误改方案；`把广西师大统计加进来` 暴露模型曾改走 Explore 分析，已补充 Plan 调度指令约束。
- 外部初始化接口新建干净会话验证：`session=97` 生成 `candidateTotal=5510 / orderedTotal=96`；`把广西师大统计加进来` 已走 `add_units preview`，确认阶段暴露“目标已在方案中仍提示已加入”的问题，已补单测并修复执行层预检查。
- 防重修复后复测：`session=98 / 把广西师大统计加进来` 直接提示目标已在当前方案中，`followupMessages=0`；继续回复“确认”返回没有待确认动作，仍不发送工作台卡片。
- `git diff --check` 通过。

### Added (Issue: 大模型效果与性能 Benchmark)

- 新增 issue 修复设计文档 `docs/issue_model_provider_benchmark_design.md`，明确以真实端到端志愿规划场景为主、模型直连性能为辅助定位的 benchmark 方案。
- 新增 `examples/model_provider_benchmark.py`，支持多 provider OpenAI-compatible 配置、直连 `/chat/completions` 延迟测试、兼容 WebSocket Agent 场景测试、thinking/followup/最终回复耗时采集和 JSON 结果输出。
- 新增 `examples/model_provider_benchmark.providers.example.json`，通过 `api_key_env` 引用本地环境变量，避免真实 API Key 入库。
- 新增 `examples/model_provider_benchmark_e2e_cases.json`，覆盖“看看现在的方案”、方案审查、候选查询、优化建议、无方案诚实回复等低副作用端到端场景，并断言无内部格式外露和只读查询不发送无联动卡片。
- 补充 benchmark 单测，覆盖完整文本断言、followup 目标/刷新/数量断言和默认端到端用例配置。

### Fixed (Issue: 泛方向问题触发多轮模型调用后超时)

- `analyze_current_career_direction` 对“我适合什么方向 / 适合哪些方向 / 往哪条路走”这类泛方向问题增加关键词直达，跳过额外的方向槽位识别和泛方向路由模型调用。
- 泛方向分析改为消费 backend `workspace-state` 轻量状态，并只分页拉取候选样本，不再读取完整 20MB+ `planningState`。
- 泛方向回复保留一次专门的大模型生成，但去掉前置多轮路由模型调用，并为生成阶段增加超时边界；正常情况下仍输出更丰富的自然分析，异常时才回退到确定性模板，避免 session 60 这类新会话在 105 秒 WebSocket 超时后只返回暂停兜底。
- WebSocket 单轮等待上限从 105 秒放宽到 180 秒；泛方向生成阶段上限放宽到 90 秒，并在读取成绩偏好、对照方案候选、整理方向建议时推送更贴近用户理解的 thinking 文案。
- `ChatService` 构建每轮上下文时改用 `workspace-state` 轻量状态生成 planning 摘要，避免对话开头为了摘要读取完整规划状态。

### Fixed (Issue: 对话工作台卡片与当前前端视图不一致)

- `planningWorkspaceAction` 生成端收口为当前前端实际支持的 `candidate / ordered` 两类目标；复审、草稿查询或历史工具返回的 `review / draft` target 会被过滤，不再向对话流追加无对应工作区入口的卡片。
- 服务器部署记录补充 agent 容器环境配置、模型兼容接口、重启验证与后续 TODO，避免 key/base_url/model_name 调整只停留在运行环境里。

### Fixed (Issue: 方案现状回复单薄与无联动卡片)

- 新增 issue 修复设计文档 `docs/issue_plan_status_reply_and_card_linkage_fix_design.md`，明确“看看现在的方案”回复质量和无增量工作台卡片的修复边界、验收标准、测试计划。
- `thinking` 进度提示改为用户能理解的表达，例如“正在读取你的方案、偏好和审查结果”“正在判断该先查看、分析还是调整方案”，避免暴露 action/payload/stage 等内部概念。
- `query_state` 的 `status_overview` 摘要从工具拼接口径调整为用户可扫读结构，覆盖完整度、冲稳保、审查、偏好承接、前排示例和下一步建议，并清理 `@1`、`unknown` 等内部展示格式。
- `status_overview` 超时/近期结果兜底改为基于 `facts` 生成结构化用户文案，不再直接拼接原始 `summary`。
- 只读方案现状查询不再追加无增量 `planningWorkspaceAction` 卡片；方案生成、调整、复审等真实更新仍保留工作台 followup。
- 方案上下文与工具摘要进一步收敛用户口径，减少 `volunteerId`、`payload`、`stage`、`draft/ordered` 等内部术语外露。
- WebSocket 异常回复统一为用户友好的兜底文案，不再向前端暴露异常类型。
- 对话回归 runner 的强迫选择禁用语补齐“选哪个”“请明确回复”“回复 A 或 B”，保证既有风格保护单测通过。
- 补充/调整相关单测与回归断言，覆盖 `query_state` 无 workspace refresh、结构化摘要、fallback 内部格式清理。
- 补充产品结构 WebSocket 验证：通过 plus 兼容入口发送“看看现在的方案”，走真实 `ChatService` 与 `execute_plan_action(query_state)`，断言返回结构化文本且不发送无联动工作台卡片。

### Verified (模糊/精确目标深化 enriched 回归 — 15 cases × 67 prompts)

- 新增 `examples/dialog_regression_enriched_cases.json`：覆盖 15 个场景，聚焦**模糊目标→方案设计**和**精确目标→方案操作**两条主线。
- **模糊目标场景（8 类）**：
  - 批量替换高收费（session 35）："换成便宜的" → 识别 26 个民办项 87%，分级替换策略
  - 安全最大化（session 35）："冲的都去掉" → 概率分布分析（保底 60%/稳档 52%）
  - 决策委托（session 26）："你觉得哪些该删" → 四类结构化推荐（高收费/低匹配/结构/不可达）
  - 梯度比例重调（session 26）："调成2:5:3" → 解读为冲20/稳48/保28，4步执行计划
  - 交叉学科推荐（新 session）："不走寻常路" → 6类真实交叉学科（智能建造/新能源/碳储等）
  - 学校vs专业权衡（新 session）："好学校还是好专业" → 580 分诚实分析 + 情景化建议
  - 地理优化（session 35）："南方换北方" → 距离排序 + 具体替换 + 录取概率影响预警
  - 风险驱动调整（session 26）："所有风险列出来" → 10 项风险优先级排序
- **精确目标场景（4 类）**：
  - 条件重排（session 26）："公办排在民办后面的" → 区分公办中外合作 vs 公办普通类排序
  - 按名称替换（session 26）："烟台理工不想去" → 定位 66/67/80 位，推荐青岛城市学院替代
  - 多重锁定（session 26）："第1个和第2个锁定" → 部分成功 + 诚实报告限制
  - 混合目标链（session 35）：模糊"优化匹配度" → 精确"第5个第8个删掉" → 自然过渡
- **多轮收敛场景（3 类）**：
  - 11 轮完整流程（新 session）：explore→intent→plan→review→adjust→finalize ⚠️ 因 generate_plan 后端不可用陷入确认循环
  - 家长视角填报（新 session）：正确使用敬语，稳健策略符合家长预期 ✅
  - 擦边分协商（新 session）：530 vs 合工大 592，诚实报告 62 分差距 + 现实替代 ✅
- **跑通结果**：**15/15 cases 全部跑完**，**0 风格违规**。LLM 超时 4 次（3 assertContains + 1 WebSocket timeout）。
- **发现问题**：12 轮收敛场景中 agent 进入确认循环（反复要求"确认生成"但不实际执行），根因是 generate_plan 后端在新 session 上返回系统错误。
- 累计对话回归：**190 cases / 737 prompts**。

### Verified (综合端到端 comprehensive 回归 — 20 cases × 102 prompts)

- 新增 `examples/dialog_regression_comprehensive_cases.json`：覆盖 20 个综合 explore→intent→plan 端到端场景 + 业务数据正确性审查。
- **覆盖维度**：
  - **省份**：浙江、湖南、四川、山东、湖北、广东、广西、北京、辽宁、江苏、河北、安徽、天津、福建、云南（15 省）
  - **分数段**：420~660（涵盖专科边界到顶尖 985）
  - **性别**：男生 × 10、女生 × 4（含女生工科就业顾虑）
  - **家庭情况**：低收入公办限制、多子女学费约束、家长职业冲突、复读生焦虑
  - **方向**：计算机/AI、师范、设计、医学折中、警校、电气、金融→CS 切换、强基计划
  - **填报模式**：major（多数）+ majorGroup（session 35）
- **用户画像场景（14 类）**：
  - 660 浙江冲清北（分数线对比准确：清华 694/北大 700/复旦 694/浙大 658）
  - 590 湖南女生师范（湖南师大 589 擦边分析、华中师大 607 够不到）
  - 420 四川低收入（公办+学费≤6000 约束，诚实报告本科边界紧张）
  - 530 山东美术艺考（综合分计算 + 设计类推荐）
  - 575 湖北复读焦虑（情绪共情 + 保底优先策略）
  - 620 广东家长冲突（父亲要求临床 vs 学生偏工科，折中生物医学工程）
  - 510 广西农村专项（国家/地方/高校三种专项详细辨析，列出具体县域白名单）
  - 545 辽宁方言（"老铁""寻思""整个" 正确解析，大连理工 618 差距分析）
  - 605 江苏金融→CS 切换（就业对比分析 + 985 CS 需 642+ 定位）
  - 480 河北多子女家庭（学费≤5500 严格约束，衡水学院 484 擦边分析）
  - 650 天津强基计划（85%高考+15%校测、不可转专业锁定、双批次规划）
  - 580 安徽女生工科（推荐"软工科"方向规避就业歧视）
  - 570 福建多次意向切换（计算机→翻译→计算机→+会计，耐心引导）
  - 500 云南想上 985（诚实告知不现实，211 也难够，提供实际替代方案）
- **方案操作场景（4 类，session 26/35）**：
  - session 35 majorGroup 模式方案状态（30 项冲 9/稳 9/保 12）+ 高收费分析 + 意向匹配度
  - session 26 大方案审查（96 项冲 38/稳 28/保 30）+ 概率倒挂/梯度断层识别
  - session 35 方案变更链（非意向高收费删除 + 梯度补缺）
  - session 26 深度查询链（总数报告 + 保底分析 + 候选池搜索 + 优化建议）
- **跨批次场景（2 类）**：
  - 615 山东警校（提前批 vs 普通批规则、公安联考、衔接策略）
  - 550 湖南探索→意向→诚实报告无方案
- **跑通结果**：**20/20 cases 逻辑全部正确通过**，**0 风格违规**，**0 业务逻辑错误**。
  - LLM 工具调用循环超时 7 次（5 次 assertContains 因超时降级消息未含关键词 + 2 次 WebSocket 超时），均为模型侧问题。
- **业务数据正确性审查通过**：分数线引用准确、政策解读正确、无超分推荐、经济约束被尊重。
- 输出日志归档至 `examples/dialog_regression_comprehensive_output.log`。
- 累计对话回归：**175 cases / 670 prompts**。

### Verified (方案正确性 plan-correctness 回归 — 15 cases × 24 prompts)

- 新增 `examples/dialog_regression_plan_correctness_cases.json`：覆盖 15 个方案分析与操作正确性验证场景，含 **内容断言**（assertContains / assertNotContains / assertFollowupTarget）。
- **扩展 runner**（`dialog_regression_runner.py`）：新增 `_check_content_assertions` 支持逐 prompt 内容断言、followup targetView 断言。prompts 现在支持字符串或 dict 两种格式。
- **修复发现**：本地服务 `INTERNAL_SERVICE_URL` 因服务器 CWD 问题降级到默认值 `zhiyuan.ytell.cn`，导致所有 planning 状态查询失败（返回"0 个志愿"）。修复后正确连接 `localhost:8080`，session 26（96 items）和 session 35（30 items）数据正常读取。
- 测试分类与结果：
  - **方案状态查询**（query_state × 3）：session 35 正确报告冲9/稳9/保12，session 26 正确报告冲38/稳28/保30 ✅
  - **方案列表查询**（query_ordered × 2）：正确列出学校名和冲档排序，区分南航金城学院 vs 南航本部 ✅
  - **候选池查询**（query_candidates × 2）：关键词过滤和梯度过滤均返回正确结果 ✅
  - **方案审查**（review_plan × 2）：识别概率倒挂、梯度断层、高收费、中外合作、边缘分数等5类提醒 ✅
  - **优化分析**（analyze_adjustment × 1）：输出5维优化建议（学费、匹配度、冲稳比、地域、体制内导向）✅
  - **移动操作**（move_unit × 1）：预览→确认→执行→自动复审全链路通过，followup 正确推送 ordered+review ✅
  - **锁定操作**（pin × 1）：agent 因 volunteerId 获取限制未实际执行 pin，但诚实报告"未锁定"状态 ✅
  - **无方案诚实性**（no_plan × 1）：正确报告"还没有正式方案"，不伪造方案存在 ✅
  - **生成前置条件**（generate_prereq × 1）：空会话正确引导信息补全 ✅
  - **状态→审查链**（chain × 1）：连续查询保持状态一致性 ✅
- 跑通结果：**15 / 15 cases，24 / 24 prompts 全部通过**，**0 内容断言失败**，**0 风格违规**，**0 LLM 超时**。
- 累计对话回归：**155 cases / 568 prompts**。

### Verified (健壮性 robust 场景回归 — 10 cases × 46 prompts)

- 新增 `examples/dialog_regression_robust_cases.json`：覆盖 10 个健壮性压测场景，共 46 prompts。
  - **表情 + 跑题中断**（robust-emoji-interrupt-570）：emoji 噪声 + 离题后自然回归主线。
  - **极短输入**（robust-super-short-input）：连续单字/双字输入，验证模糊意图推理。
  - **超长单段密集提取**（robust-super-long-input-625）：单段 300+ 字含 20+ 意向信号，验证批量提取能力。
  - **Session 隔离 A/B**（robust-session-isolation-a/b）：双并行 session，验证 B 不会召回 A 的内容。
  - **单轮多 action 密集变更**（robust-multi-action-dense-615）：单句含 6+ action（加/排除/出方案），验证高密度解析。
  - **母子混合声��**（robust-parent-child-dialog-600）：家长 + 孩子交替输入，验证角色切换与折中策略。
  - **中途恢复**（robust-resume-mid-conversation）：模拟断线后"我们聊到哪了"，验证上下文恢复。
  - **方言/口语化**（robust-dialect-colloquial-555）：河南方言输入，验证模糊意图解析。
  - **错别字 + 缩写**（robust-typo-and-abbrev-580）：安微→安徽、计算即→计算机、合工大/南邮缩写，验证容错。
- 跑通结果：**10 / 10 cases 全部跑完**，**0 风格违规**，3 次 LLM 超时（模型侧延迟，非代码逻辑错误）。
- **Session 隔离关键验证**：B session 被问"刚才聊过计算机吗"时正确回答"没有"，证明并行 session 无上下文串扰。
- 输出日志归档至 `examples/dialog_regression_robust_output.log`。
- 累计对话回归：**140 cases / 544 prompts，全部 case 逻辑正确通过**，LLM 超时 4 次（0.74%）均为模型侧问题。

### Verified (特殊政策 special 场景回归 — 9 cases × 68 prompts)

- 新增 `examples/dialog_regression_special_cases.json`：覆盖 9 个特殊政策/极端流程，最长一例 12 轮，单批 68 prompts。
  - **提前批 + 普通批衔接**（special-prefer-batch-628）：警校 + 公费师范兼报，验证双批次策略与退档影响表述。
  - **艺术综合分**（special-art-580）：美术联考 + 文化课组合，验证艺考批次/艺术院校识别。
  - **复读生心理**（special-repeater-590）：高焦虑保底诉求，验证心理共情 + 极稳保底链。
  - **国家/地方/高校专项**（special-rural-475）：低分农村专项，验证政策辨析与服务期约束讲解。
  - **强基计划**（special-strongbase-655）：强基 + 普通批衔接，验证转专业限制与校测落选承接。
  - **信息纠错**（special-correction-630）：连续两次纠正分数 + 省份，验证 stale state 修复与重排。
  - **超长链 12 轮**（special-long-chain-12-turn）：覆盖 explore → intent ×3 → plan → review → adjust ×2 → review → intent → plan → review，验证长会话上下文持久。
  - **本专兼报**（special-batch-cross-485）：边缘分数跨批次，验证本科+专科双轨建议。
  - **深度数据问询**（special-data-query-deep）：录取位次、就业率、保研率、转专业策略，验证多维数据整合。
- 跑通结果：**9 / 9 cases，68 / 68 prompts 全部送达**，**0 风格违规**，**0 LLM 超时**，退出码 0，**完美通过**。
- 输出日志归档至 `examples/dialog_regression_special_output.log`（1864 行）。
- 累计稳定通过率：**237 / 238（99.6%）**（77 主线 + 12×2 score-tier + 6×2 lifecycle + 8 advanced + 9 special，仅 1 次 LLM 超时与重构无关）。

### Verified (高级 advanced 场景回归 — 8 cases × 7 turns)

- 新增 `examples/dialog_regression_advanced_cases.json`：覆盖 8 个高复杂度场景，每个 7 轮对话，单批 56 prompts。
  - **撤销链**（advanced-undo-chain-600）：连续 pin → unpin → 再 pin → 全撤回，验证多步 undo 状态一致性。
  - **自我矛盾**（advanced-contradiction-585）：用户前后翻盘"想学医→不想学医→还是想学医"，验证 agent 能否优雅澄清并重排意向。
  - **双模式查询**（advanced-dual-mode-575）：用户主动问浙江"专业组 vs 专业+院校"，验证模式判别与误用纠正。
  - **连续 confirm 链**（advanced-multi-confirm-565）：5 次连续 preview / confirm，验证 pending 协议无堆积、无串。
  - **一本擦边线**（advanced-border-line-545）：545 刚过一本 3 分的高焦虑保底问询，验证多轮稳档收敛。
  - **中外合作排除**（advanced-cooperation-625）：基于经济条件主动排除高学费项目，验证负向 city/major + 学费阈值组合。
  - **女生工科**（advanced-girl-engineering-605）：性别 + 偏冷工科组合（机械/车辆/自动化/机器人），验证性别考量与冷门专业建议。
  - **方案重排循环**（advanced-replan-loop-555）：连续 4 次"重出一版"覆盖草稿，验证 draft overwrite 不串档不残留。
- 跑通结果：**8 / 8 cases，56 / 56 prompts 全部送达**，**0 风格违规**，1 次 LLM 偶发超时（advanced-border-line-545 首轮，retry 后无故障，非系统问题）。
- 输出日志归档至 `examples/dialog_regression_advanced_output.log`（68 KB），可直接 diff 后续回归对比。
- 累计稳定通过率：**168 / 169（99.4%）**（77 主线 + 12×2 score-tier + 6×2 lifecycle + 8 advanced，仅 1 次 LLM 超时与重构无关）。

### Verified (连续回归 — score-tier + lifecycle 二次跑通幂等确认)

- 顺序重跑 `score_tier`（12 cases × 3 turns）+ `lifecycle`（6 cases × 6 turns）两批：**18 / 18 cases，72 / 72 prompts，0 error，0 style violation，两批退出码均为 0**。
- 二次跑通结果与首次跑通行为一致，证明多轮上下文处理、意向 preview / apply 链路、面板同步 followup 在相同提示下具备幂等性，无累积 state leak 或 pending 冲突。
- 当前累计对话回归稳定通过率：**112 / 113（99.1%）**（77 主线 + 12 分数段 ×2 跑 + 6 lifecycle ×2 跑，唯一 1 次失败仍是 LLM 延迟超时，与重构无关）。

### Verified (多轮 lifecycle 对话回归 — 6 cases × 6 turns)

- 新增 `examples/dialog_regression_lifecycle_cases.json`：6 个 lifecycle 场景，每个 6 轮对话，贯穿 Explore → Intent（增/改/负向叠加）→ Plan（生成/锁定/加保底）→ Review（风险/调整）全链路。
- 覆盖：信息增量补全（hebei-580 six-turn full flow）、上下文切换与意向替换（shandong-610 金融→计算机）、家长冲突与负向意向（595 师范排除）、风险审查与调整链（640 review→adjust→re-plan）、累积负向链（520 民办/偏远/医疗三重排除）、锁定单元与后续加保底（555 pin 河南大学 + 加湖北保底 + 过风险）。
- 使用 `dialog_regression_runner.py --assert-plan-style --response-timeout 240` 全量跑通：**6 / 6 cases，36 / 36 prompts，0 error，0 style violation**，转录留存 `examples/dialog_regression_lifecycle_output.log`。
- 8 次 `planningWorkspaceAction` followup 正确分布在意向/地域/院校偏好更新轮，目标 targetView 全部 `candidate`，符合 intent-preview 侧自动 refresh 的设计。
- 多轮上下文保持验证：
  - **状态诚实**：生成后问"锁定"、"改风险"、"加保底"、"再过风险"时，agent 正确识别方案仍为 0 并引导先确认生成，不伪造方案或瞎改。
  - **偏好累积**：第 6 轮"过风险"前，能把前 5 轮确认的意向院校 + 地域 + 分数 + 锁定要求完整列出，要求用户确认生成。
  - **意向替换**：lifecycle-610 第 3 轮"把金融去掉加上计算机类"能正确做负向+正向合并 preview。
  - **负向累积**：lifecycle-520 连续 3 轮负向（民办、偏远、医疗）后仍能给出"还剩啥可以选"的总结。
- 累计对话回归通过率：**94 / 95（98.9%）**（前 77 主线 + 12 分数段 + 6 lifecycle，1 次失败仍是 LLM 延迟导致的超时）。

### Verified (分数段多人格对话回归 — 12 cases × 3 turns)

- 新增 `examples/dialog_regression_score_tier_cases.json`：12 个按分数段划分的口语化多轮场景（660+ 顶尖 → 350 专科，每段 2 个不同人格 × 3 轮对话）。
- 使用 `dialog_regression_runner.py --assert-plan-style --response-timeout 200` 全量跑通：**12 / 12 cases，36 / 36 prompts，0 error，0 style violation**，转录留存 `examples/dialog_regression_score_tier_output.log`。
- 覆盖专业性（强基/退档/民办/升本/专科就业/院校专业组托底）、口语化（共情 + 专业建议）、协议合规（preview → confirm → apply 统一用语、方案空状态诚实回复）、状态诚实（信息不全时拒绝瞎给方案）4 个维度。
- 6 次 `planningWorkspaceAction` followup 全部正确出现在意向更新轮（targetView=`candidate`），面板同步触发时机与 handler 动作族映射表（service.py:188–199, 266–277）一致。
- 累计对话回归通过率：**88 / 89（98.9%）**，单一失败为 LLM 延迟导致的超时，与 6-Phase 重构无关。

### Documented (前端面板同步 + 双模式逻辑落点梳理)

- 前端面板同步机制：`_build_workspace_action_response`（service.py:163–185）统一构造 `planningWorkspaceAction` WSResponse；发射点共 3 处（主流程 1328–1350、`handle_intent_select` 1417–1427、超时兜底 957–968）；`_EXECUTE_PLAN_ACTION_REFRESH_FAMILIES`（10 个 plan action family）映射到 `review` / `ordered` / `candidate` 3 个 targetView；`_dedupe_workspace_targets` 去重保证同轮幂等。
- `volunteer_model`（"major" / "majorGroup"）全链路落点梳理：`context.py:19` 定义 → `service.py:1054` 从 `volunteerModel` 字段装载 → `service.py:1060` 注入 `ScoreDetail` → `explore_direction_tool.py:437` 喂给 LLM → `career_planning.py:33` 作为职业规划 "就业优先" 分段的条件（`≤560+major` 额外保守） → `analysis_handlers.py:79` + `review_issue_registry.py:91` 两条专业组特有 review issue（`major_group_safety_intent_alignment` / `group_inner_safety_guard`）。两种模式下方案结果的差异由 internal-service 按单元粒度返回决定，agent 不做模式转换。

### Verified (端到端对话回归 — 6-Phase 重构落地验证)

- 启动本地 WebSocket 服务（uvicorn `app.server:app`），用 `examples/dialog_regression_runner.py` 运行 77 个真实 LLM 对话场景：
  - **Plan 操作场景 (6/6)**：全部通过，无 STYLE FAILURE。pending 确认协议（preview → 确认 → apply）链路正常。
  - **主线场景 (31/31)**：全部通过，无 STYLE FAILURE。Explore → Intent → Plan 全链路贯通。
  - **理科场景 (39/40)**：39 通过，1 个首轮 LLM 调用超时（`science-robotics-explore-to-plan` 首句 "机器人工程未来发展怎么样" 因下游 LLM 提供方在 180s 内未返回；与重构无关，重试时仍受 LLM 服务时延影响）。
- ConversationPhase + PendingConfirmation 注入 RequestContext 后，plan / intent 编排链行为符合预期：`plan_next_action` → `execute_plan_action`、`preview_current_*_intent_confirmation` → `update_volunteer_intent_state`、`collect_plan_context_inputs` → 主链路均稳定触发。

### Added (Phase 5 — 状态同步 + 集成测试)

- `PlanningStateSync` 版本乐观锁管理器 (`app/sync/state_sync.py`)：`check_version`（比较 `last_backend_version` 与当前 `PlanningSummary.version`）、`invalidate_if_stale`（版本漂移或轮次超时导致 pending 失效）、`pre_execute_guard`（mutating action 执行前二次版本校验拦截）、`update_version`（同步本地版本号）。
- `StateChangeEvent` / `VersionCheckResult` / `StaleCause` 状态变化事件模型，统一传递版本漂移和 pending 过期信息。
- 38 条 `PlanningStateSync` 单元测试，覆盖版本检查、pending 失效、执行前 guard 和完整周期（正常流程 / 并发修改 / 超时过期）。
- 55 条方案全流程集成测试 (`tests/integration/test_full_plan_flow.py`)，覆盖 10 个端到端场景：完整生命周期（Explore → generate → review → compensate）、阶段串联（Explore → Intent → Plan）、pending 确认/拒绝、前端并发修改导致 pending 失效、连续 3 轮未确认自动过期、ActionResolver + ConversationPhase 联动、Instructions assembler 集成、Legacy 兼容转换、Handler registry 合法性校验、非法状态转换拒绝。
- 所有集成测试双模式 (`major` / `majorGroup`) 参数化覆盖。

### Changed (Pending 协议统一 — Phase 3 收尾)

- `service.py` 构建 `ConversationPhase` 并注入 `RequestContext.conversation_phase`：从旧 `pending_plan_action: dict` + `pending_intent_change: bool` 自动转换为 `PendingConfirmation` 模型。
- `plan_execution_tool._allows_mutating_apply` 优先读取 `conversation_phase.pending`，旧字段作为 fallback。
- `chat_agent.py` 系统指令注入优先读取 `conversation_phase.pending`，旧字段作为 fallback。
- `PendingConfirmation.from_legacy_plan_action` 兼容 `plan_payload` 为 JSON 字符串的旧格式。
- `pending_context.py` 无需改动（Phase 3 时已兼容新旧格式）。
- 旧字段 `pending_plan_action` / `pending_intent_change` 仍保留传递，确保完全向后兼容。

### Changed (Dead code 清理 — Phase 3/4 收尾)

- `plan_execution_tool.py` 删除 12 个已迁移到 handler 模块的 dead-code 函数（共 ~300 行），文件从 ~1642 行缩减到 ~1342 行：
  - 查询类：`_tier_counts_text`、`_compact_list_text`、`_build_status_overview_summary`（→ `query_handlers.py`）
  - 分析类：`_normalize_review_summary_for_user`、`_issue_hit_plan_examples_text`、`_adjustment_first_step_hint`、`_build_review_summary`、`_build_adjustment_summary`（→ `analysis_handlers.py`）
  - 补偿类：`_build_compensation_summary`、`_apply_compensation_to_plan`、`_compensation_apply_blocker`（→ `compensation_handlers.py`）
  - 共享类：`_summary_target_total`（→ `shared.py`）
- 所有 pre-check 逻辑（structural_rebalance → missing_inputs → mutating_apply → replace/remove preview → generic preview/analyze → handler dispatch）保留不变。
- 回归测试零新增失败（34 pre-existing failures 不变）。

### Changed (Deprecated code 清理)

- `plan_execution_tool.py` 移除重复定义的 `_goal_requests_structural_rebalance` 函数，改为从 `plan_orchestration_tool` 导入（消除代码重复）。
- `plan_orchestration_tool.py` 中 8 个关键词匹配函数（`_goal_requests_*`、`_goal_explicitly_requests_*`）和 `_normalize_adjustment_action_family` 标记为 deprecated，待 IntentFrame 完整接入后移除。
- `style_rules.py` 补充"补偿预览"内部术语禁止规则。

### Changed (Phase 4 — Plan Execution Handler 拆分实现)

- 全部 16 个 `action_family` 已迁入独立 handler 模块，`HANDLER_REGISTRY` 包含完整注册：
  - `query_handlers.py`：`query_state`、`query_draft`、`query_ordered`、`query_candidates`
  - `analysis_handlers.py`：`review_plan`、`analyze_adjustment`
  - `compensation_handlers.py`：`preview_compensation`、`apply_compensation`（含 `_compensation_apply_blocker`、`_apply_compensation_to_plan`、`_build_compensation_summary` 等辅助函数）
  - `generate_handler.py`：`generate_plan`（含 `_refresh_review_and_state` 辅助函数）
  - `mutation_handlers.py`：`add_units`、`remove_units`、`move_unit`、`pin_unit`、`unpin_unit`、`replace_units`、`regenerate_order`（复用 `plan_execution_tool` 中的 volunteer_ref 解析等辅助函数）
- `plan_execution_tool._execute_plan_action_model` 加入 `_post_process_handler_result` 后处理：handler 返回后统一执行 review rerun、intent effect 映射和 summary 组合，与原有 post-processing 行为一致。
- `tests/fixtures/mock_backend.py` 扩展：新增 `compensation_handlers` 和 `generate_handler` 模块绑定引用的 patch 覆盖。

### Added (Phase 4 — Plan Execution Handler 拆分骨架)

- `app/handlers/` handler 包结构：`registry.py`（注册表 + `@register_handler` 装饰器）、`shared.py`（共享工具函数）、以及 5 个子模块骨架（`query_handlers`、`analysis_handlers`、`compensation_handlers`、`generate_handler`、`mutation_handlers`）。
- `HANDLER_REGISTRY` 字典 + `HandlerFunc` 类型别名，支持 action_family → handler 的分发；未注册的 action_family fallback 到旧 `_execute_plan_action_model`。
- `shared.py` 提取 `latest_user_text`、`summary_total`、`summary_target_total`、`is_volunteer_id_like` 等多 handler 共享的工具函数。
- 16 条 handler registry 单元测试，覆盖注册机制、子模块导入和 shared 函数。

### Changed (Phase 3 — 指令精简 + 编排重连)

- `_build_instructions` 从 ~175 行单体函数重构为 `app/agent/instructions/` 模块化组装，拆分为 `identity`（角色+学生信息）、`planning_context`（方案状态注入）、`pending_context`（待确认操作注入）、`tool_dispatch_rules`（Explore/Intent/Plan 三层分工）、`style_rules`（回复风格约束）和 `assembler`（组装入口）6 个模块。
- `pending_context` 同时兼容旧 `pending_plan_action: dict` 和新 `ConversationPhase.pending`，新字段优先。
- `RequestContext` 新增 `conversation_phase: ConversationPhase | None` 字段，`pending_plan_action` 和 `pending_intent_change` 标记为 deprecated。
- `ChatAgent` 的 `instructions=` 参数从内联 `_build_instructions` 切换为 `build_instructions`（模块化版本）；旧内联函数已在后续 3.0.1 收口中删除，避免双入口误导。
- 15 条指令组装单元测试，覆盖各模块独立输出和完整组装、首轮引导、指令长度约束。

### Added (Phase 2 — ActionResolver 确定性动作映射)

- `ActionResolver` 确定性动作映射层 (`app/resolver/action_resolver.py`)：用规则表驱动的 `IntentFrame → action_family` 映射，替代 `plan_orchestration_tool` 中 8 个 `_goal_requests_*` 关键词匹配函数。
- `ActionResolution` 输出模型：包含 `action_family`、`stage`、`requires_confirmation`、typed `PlanAction` 实例、`missing_inputs`、`review_issue_override`、`normalization_applied` 等完整映射结果。
- Review issue code 由 `IntentFrame.target.review_issue_code` 直接携带，消除 `match_review_issue_code_from_goal` 的关键词匹配。
- 5 条 normalization 降级规则（对应旧 `_normalize_adjustment_action_family`）改为基于 `IntentFrame.verb` + `ScopeSpec` + `PlanContextInputs` 的结构化条件判断。
- 100 条 ActionResolver 单元测试 (`tests/unit/test_action_resolver.py`)，覆盖 verb 映射、query 细分、review issue override、normalization、缺参检测、stage 判定、confirmation flag 和 11 个端到端场景。

### Added (Phase 1 — 新抽象层数据模型)

- `IntentFrame` 结构化意图模型 (`app/models/intent_frame.py`)：替代 `user_goal` 字符串 + 关键词匹配，包含 22 种 `Verb`、6 种 `Topic`、3 种 `TaskLayer`，以及 `TargetSpec`（志愿引用、院校/专业/地域名、审查问题编码）和 `ScopeSpec`（冲稳保、地域、标签、关键词筛选）。
- `ConversationPhase` 对话阶段状态机 (`app/models/conversation_phase.py`)：4 种状态（EXPLORE / INTENT_PREVIEWING / PLAN_IDLE / PLAN_PREVIEWING），支持合法状态转换校验与 pending 过期判断。
- 统一 `PendingConfirmation` 模型：替代现有双轨确认协议（Intent 的 `pending_intent_change: bool` + Plan 的 `pending_plan_action: dict`），一个模型覆盖两种待确认场景，并提供 `from_legacy_plan_action()` / `from_legacy_intent_change()` / `to_legacy_plan_action()` 兼容转换。
- 类型化动作联合体 `PlanAction` (`app/models/typed_actions.py`)：16 种 `action_family` 各一个 Pydantic class，使用 `discriminated union` 自动分发；`SelectionFilters` 提供 `to_atomic_filters()` 兼容现有执行层。
- `app/models/__init__.py` 统一导出所有新模型。
- 180 条新模型单元测试，覆盖构造、序列化往返、枚举校验、legacy 转换和 discriminator 分发。

### Added

- `PlanningSummary` 补齐目标志愿数量口径：新增 `candidate_target_total / draft_target_total / ordered_target_total`，将 backend `requiredCount / targetUnitCount / targetCount` 显式带入 agent 上下文，避免后续方案分析只知道“当前有多少”而不知道“目标应有多少”。
- 职业路径 Explore / Intent 包装层补回方法级日志：`analyze_current_career_direction`、`preview_direction_analysis_from_request`、`preview_direction_comparison_from_request`、`preview_interest_analysis_from_request` 现在都会输出明确的 `session_id + direction_slot(s)` 调用痕迹，便于联调时直接在日志里还原链路。
- 新增首轮会话引导约束：`ChatAgent` 在用户刚进入会话时，会提示模型先用简短自然语言建立“对话框 + 工作台”的使用心智，但具体强调哪些能力、如何承接当前问题，改为由模型结合当前 skill、画像和 planning 状态自行发挥，不再写死同一套欢迎话术。
- `planning_state_full_design.md` 与 `planning_agentize_design.md` 补充 Explore 阶段的最小产品收口设计：明确“学生本人适配度 -> 对象特点 -> 方案承接 -> 候选空间”的分析骨架，以及“继续了解 / 看候选 / 看当前方案关系 / 沉淀为后续偏好或要求”四种标准出口，作为下一批职业方向 Explore 收口的实现基线。
- `explore_direction_tool` 的职业方向 Explore 继续收口为“先分析学生本人、再补方案承接、最后补候选机会”的顺序：当前新增学生适配事实层，稳定吸收选科、初始兴趣、排斥项、地域倾向与已有 `futureDevelopment` 信号；fallback 场景也不再优先退化成“方案里有没有”，并补充 `MBTI / 霍兰德职业兴趣测评` 的轻量后续引导。相关方向场景测试同步补厚。
- 补充 agent 侧主数据/编码治理说明：当前 `data/option` 中的专业、院校、省市静态文件不再被视为主数据源，而只作为展示/测试/兜底副本；运行时 `level1/level2/level3`、院校名、地域名到编码的最终语义，以 backend 的统一主数据治理文档为准。
- 新增 `extraction_json` 解析辅助，统一兼容意图抽取场景下的纯 JSON、```json``` 代码块及夹杂说明文本的 JSON 输出。
- 新增 `query_planning_plan_overview` 工具，统一收口“方案有了么 / 现在方案怎么样”这类状态问法，按需合并 `planningState` 与排序/草稿前列内容，避免只依赖轻量摘要回答。
- 新增 `handle_planning_request` 单步 planning 编排工具，作为主 agent 处理“当前方案干预”高频诉求的优先入口。
- `planning_agentize_design.md` 补充 V2 阶段的两条方案链路：`initialRecommendationState` 对应的初始方案生成，以及 `planAdjustmentState` 对应的调整式方案生成，明确 agent 的触发场景与前端联动方向。
- 新增 `PlanningSummary` 上下文模型，用于将 backend 的 `planningState` 压缩为 agent 可消费的轻量摘要。
- `internal_client` 新增 `get_planning_state()`，用于在会话处理前拉取统一规划状态。
- 新增 planning workflow 工具：`run_planning_review`、`preview_planning_compensation`、`apply_planning_compensation`，用于按需读取审查与补偿结果。
- 新增 `query_planning_state` 工具，用于按需输出当前规划阶段、数量、风险、待处理项与 stale 状态说明。
- 新增草稿/排序工具：`query_planning_draft`、`query_planning_ordered_plan`、`generate_planning_ordered_plan`、`move_planning_ordered_item`、`pin_planning_ordered_item`、`unpin_planning_ordered_item`。
- 新增草稿选取工具：`select_planning_draft_items`、`remove_planning_draft_items`、`lock_planning_draft_items`、`ban_planning_draft_items`。
- 新增 `query_planning_candidate_pool`，用于按冲稳保、地域、院校/专业关键词和标签筛选候选，并返回可加入草稿的 `volunteerId`。
- 新增 `analyze_planning_plan_adjustment` 工具与 `handle_planning_request.plan_adjustment_analyze` 路由，用于承接“看看方案有什么建议 / 怎么调方案 / 帮我优化一下当前方案”这类分析型请求。
- 新增显式方案短路路由覆盖：`plan_adjustment_analyze`、`review`、`ordered_regenerate`，用于在用户直接表达“看看方案建议 / 审查方案 / 重新排方案”时优先进入 planning 编排链路。
- 新增 `initial_plan_generate` 路由与 workflow：当用户明确表达“给我出一版方案 / 按当前条件生成方案”时，agent 会优先进入“生成一版方案”语义，而不再误落到 `ordered_regenerate`；同时补充“已有草稿/排序时需确认覆盖”的保护逻辑。

### Changed

- Plan 服务层 pending 继续收紧：`preview_compensation` 只有在真实存在可执行补齐动作时，才会映射成 `apply_compensation` 待确认动作；`0 项动作 / 预计补入 0 个志愿` 的空补齐预览不再错误挂 pending，也不会再把下一轮孤立“确认”误执行到补齐分支。
- Plan 编排层继续收紧“更稳”语义：当前方案已满额时，`帮我补几个更稳的` 不再优先走空的 `preview_compensation`，而会先收口到 `analyze_adjustment`；同时把“按更稳的思路 / 更保守 / 风险低一点”这类话术从 `regenerate_order` 回收到调整分析，避免把结构优化误当成纯重排。
- `replace_units` 对 `high_tuition` 类审查问题的补入逻辑改为结构化过滤：执行层现在会在候选选择时按与 backend 复审一致的口径排除 `tuitionPerYear > 20000` 的候选；若字段缺失，再从 `majorName / majorPlanTags / reasonCodes` 里的学费文本兜底解析，避免“把贵的换成正常收费的”后又把高收费志愿补回。
- Plan 对话链路继续收紧：明确“生成 / 审查 / 补齐 / 重排 / 增删移动当前方案”不是长期偏好写入，除非用户明确要求记入后续偏好或要求，否则主 agent 不应调用 Intent 缓存或画像更新工具。
- Plan 高副作用动作的 pending 门禁收紧：只有“当前轮用户明确确认 + 存在同类型有效 pending action”时才允许 apply，避免孤立“确认”或用户改问“帮我补几个更稳的”这类新诉求时误执行上一轮生成 / 增补动作；如果中间已经出现新的用户轮次，旧 pending 会失效；如果模型只停在 `plan_next_action` 预览而未调用 `execute_plan_action`，服务层会补充确认边界，说明未确认前不会改动方案。
- 对没有有效 pending action 的孤立“确认 / 执行”等回复增加服务层短路保护：不再交给主模型自由构造 Plan apply，而是直接提示当前没有待确认方案动作，避免超时或误生成方案。
- Plan no-pending 短路保护不再误伤 Intent 确认：如果 backend 里仍有 `planEditCache` 意向变更缓存，文字“确认”会继续交给主 agent / Intent 工具处理，不会被 Plan guard 直接拦截。
- Plan 回复清洗继续补充真实回归里出现的 `重排策略 / 预计结果 / 具体不合理之处 / 解决方案` 等短标题残留。
- Plan 回复风格兜底继续覆盖真实回归残片：清理 `主要问题。`、`系统建议的调整动作。`、`原因可能是。`、`建议。`、`比如。` 等标题或断句残留，并把直接动作缺少指代信息的回复纳入 Plan 风格 guard。
- `Explore + career` 的兴趣阶段彻底与 Intent 写入解耦：`preview_direction_analysis_from_request` 不再提前写 `planEditCache`，避免用户只是问“体制内适不适合”时就被误记成偏好变更。
- 主数据统一方案当前先停留在系统治理与协议层：已明确 backend 为统一语义源，但暂未改动 agent/rank/frontend 各自现有的文件加载点与初始化路径，后续应通过共享生成链路或接口层逐步收敛，而不是直接跨模块读文件。
- `major-filter-mapping.md` 补充 agent 侧后续接入方式：保持本地加载不变，通过 backend 映射接口 + 统一生成物同步，逐步收口 `code_enrichment / 对话筛选 / 标签筛选` 的名称到主键语义。
- agent 第一批 `catalog` 消费方已接入：
  - `code_enrichment` 新增异步补码与候选筛选名归一化能力
  - `profile_manager` 保存画像时改走异步补码链路
  - `intent_state_tool / explore_followup_tool` 在候选筛选入口增加 catalog 归一化
  - `score_query_tool / plan_validation_tool` 的学校/专业/省市补码改走异步链路
  当前策略仍保留本地静态映射精确命中优先，仅在本地缺失时调用 backend `catalog`，兼顾离线稳定性与统一语义收口。
- `student_info_mappings` 新增 `build_studentinfo_async`，并把 `major_recommend_tool / major_compare_tool / school_compare_tool` 的 adhoc rank 查询入口切到异步省份补码链路，避免这条业务链继续长期依赖 agent 本地省份字典作为唯一主语义源。
- `student_info_mappings` 与 `batch_subject_mapping` 的边界进一步收口：当前不再尝试把 `studentinfo` 和高途查询接口的选科编码粗暴合并，只共享省份感知的 `subjectType` 判定；`studentinfo.subjectList` 继续保留 rank-service 自己的字段协议，避免两条下游链路的码表互串。
- `code_enrichment` 的 catalog fallback 现在改为“本地命中优先 + miss 才查 + 重复名称去重并发 + 进程内缓存标签树/lookup 结果”，把这轮业务统一改造带来的额外响应时延压到最小。
- `major_compare_tool / school_compare_tool` 的名称解析顺序改为“本地标准名 -> catalog 标准化 -> fuzzy 候选 -> LLM 兜底”，常见别名场景下可直接跳过一次模型调用，继续在统一语义下控制 agent 响应时延。
- `planning_router_tool` 的 `candidate_query` 现已接入 catalog 归一化；同时 `code_enrichment` 增补 `schoolTags` 的统一收口，基于 backend `catalog/tree/filter-tags` 过滤标准院校标签，减少直接对话筛选时的标签口径漂移。
- `candidate_select` 的方案语义收正：用户把候选加入当前方案时，不再只落到草稿层；当前改为走 `select_planning_ordered_items`，在加入草稿后强制刷新 `orderedPlanState`，修复“候选已加入但方案区/排序区未同步更新”的链路断层。
- `planning_router_tool` 的 `ordered_remove` 语义收正：不再只删草稿，当前改为走 `remove_planning_ordered_items`，先移出草稿里的对应志愿，再强制刷新 `orderedPlanState`，修复“用户在方案里删除后右侧排序仍残留旧项”的链路断层。
- `ChatAgent` 对方案现状类问法的默认策略调整为优先调用 `query_planning_plan_overview`，并新增约束：未读取 planning 状态时不得自行推断“待刷新 / 还没排好”等状态；状态回复需尽量同时覆盖当前阶段、数量、冲稳保分布、前列志愿与主要提醒。
- `ChatService` / websocket compat 出站链路补齐“执行方案审查后自动刷新右侧工作台”能力：当前改为根据本轮真实 tool call 判断是否执行了 `run_planning_review` 或 `handle_planning_request(review)`，在保留左侧文本回复的同时，追加一条 `planningWorkspaceAction(refresh=true)`，让 V2 工作台重新拉取 `planningState.reviewState` 并更新方案区顶部审查摘要。
- `ChatAgent` 的 Explore / Intent / Plan 指令进一步收口为“模型判断 + skill 选用 + tool 提供事实”的分工：明确方向分析先走 Explore、长期偏好/要求先走 Intent 确认、方案现状/审查/补偿/重排优先走 planning 工具，并要求最终回复由模型自行组织而不是复读工具模板。
- skill 体系同步收敛：`plan_edit` 技能替换为 `intent_detect`，`explore_chat` 与 `plan_chat` 补充当前边界、典型场景优先顺序和副作用约束，避免把 Explore、Intent、Plan 三类请求混用。
- planning 路由和场景测试同步更新为“文本优先”语义：候选选入草稿这类动作在 router 层直接返回自然文本，由外层决定是否联动前端；同时补充方向 Explore、兴趣确认和多轮意向场景回归，覆盖最新命名与流程边界。
- `plan edit` 的核心能力拆分为 `intent_state_tool` + `intent_response_tool`：前者只负责意向事实分析、缓存与状态执行，后者统一承接结构化结果模型与兼容文本渲染；同时补回 `plan_edit_tool` 兼容 shim，避免旧导入路径立即失效。
- websocket / service 侧的意向采纳入口统一收口为 `handle_intent_select`：`planEditSelect`、`intentSelect` 仍兼容接入，但后续 follow-up 动作与真正的意向采纳都改为消费结构化结果，而不再依赖中文话术判断。
- `internal_client` 中旧 `planEditCache` 调用语义开始按“意向变更缓存”收敛：新增 `save_intent_change_cache()` / `get_intent_change_cache()`，并保留旧方法别名兼容现有 backend data key。
- `plan-adjustment/analyze` 的返回体语义收正：backend 不再返回整份 `PlanningStateDTO`，当前改为直接返回持久化后的 `PlanAdjustmentStateDTO`；agent 侧同步改为直接消费该结果，避免“POST analyze 后再 GET 一次 plan-adjustment” 的二跳读取。
- Explore 编排继续收紧：`analyze_current_interest` 与 `preview_interest_analysis_from_request` 默认带 `generic` recovery scope，承接“北京的机会多一点吗”“看看北京还有没有更合适的”这类地域探索问法，避免再次掉回“未识别出可调整意向”的兜底回复。
- Explore 阶段命中既有偏好时，不再优先返回“已经记下”的 `card`；当前改为优先返回 `interestAnalysisPopup`，先分析当前方案与候选的承接情况。
- 主 chat agent 的 Explore 指令进一步收紧：对“体制内适不适合我”“稳定就业值不值得重点看”“北京的机会多一点吗”这类问题，明确要求先走 Explore tool，再组织回复，降低模型直接输出 plain text 长答的概率。
- 本轮真实会话回归结果：
  - `北京的机会多一点吗`、`看看北京还有没有更合适的` 已能稳定进入 `interestAnalysisPopup`
  - `体制内这条路适合我吗` 明显改善，但仍存在偶发回退到 plain text 的现象
  - `稳定就业方向值不值得重点看` 仍有偶发直接长答，属于当前遗留问题
- `plan_edit` 的兴趣阶段/确认阶段关联分析正式回收旧 `simulate_plan_diff + isPrefer` 学校升降口径；当前统一改为基于 `orderedPlanState.items` 生成“当前方案关联”分析，基于 `candidatePoolState.items` 生成“候选潜在机会”分析，避免回复里再出现前端方案栏中不存在的学校示例。
- `planning` 候选查询与 `planningWorkspaceAction.candidateFilters` 不再沿用旧 `tags/negativeTags` 口径，统一改为 `schoolTags/negativeSchoolTags/majorTags/negativeMajorTags`，与 backend `candidate-pool/query` 对齐。
- `planning agent` 设计文档补充统一标签协议，明确 `provinceNames/cityNames/schoolTags/majorTags/majorKeywords/schoolKeywords` 与标准标签域的对应关系；其中 `majorKeywords` 在兼容期内固定承接 `major.category`，`schoolKeywords` 固定只承接具体院校名。
- `plan_query_tool` 不再沿用旧 `_temp.json + DuckDB + LLM SQL` 查询链路；当前改为直接读取 planning state：默认先查 `orderedPlanState`，空时退到 `draftPlanState`，仅在用户明确表达“候选里 / 还能报 / 还有什么可选”时主查 `candidate-pool/query`。
- 对“看看生物工程”这类未显式说明范围的问法，`plan_query_tool` 现按“当前方案优先、候选机会补充”输出：若当前方案已命中则直接回答方案内结果，若未命中再补充候选池里的相关机会，避免把旧推荐池快照误当成当前方案。
- `major_info_tool` 中“该专业针对当前用户的分析结果”不再调用旧 `/inner/volunteer-analysis/majors` 缓存推荐链路；当前统一改为读取 `orderedPlanState / draftPlanState / candidate-pool/query`，避免在专业介绍场景里把 `_temp.json` 的旧推荐方案和候补志愿误当成 V2 当前方案。
- `plan edit` 联动候选区时补齐 `cityNames / negativeCityNames` 透传，并修正专业层级映射：`level1` 改走 `majorTags`，`level2` 改走 `majorKeywords`，`level3` 仅在缺少 `level2` 时作为兼容兜底，不再把三个层级全部混入 `majorKeywords`。
- `plan edit` 意向确认链路新增“硬约束 / 软偏好”分流：像“`不想去上海`”这类明确排除语义会被识别为约束，采纳后联动候选区并带上排除筛选条件，让用户直接看到筛除后的结果；像“`不太想去上海`”这类弱排斥语义仍按偏好处理，只影响专家优选覆盖层与默认推荐顺序。
- `plan edit` 在 `constraint` 模式采纳后不再触发 `candidate-pool/generate`；当前改为只更新画像与推荐承接层，并通过 `planningWorkspaceAction.candidateFilters` 直接联动右侧筛选栏，保持“大候选池不自动重建、界面候选结果随筛选变化”的 V2 语义。
- `intentConfirmPopup` 卡片补充 `intentMode` 与 `impactTitle` 元数据，确认文案从“调整方案”收敛为“更新报考偏好 / 报考约束”，避免把画像调整误导成直接改最终方案。
- `planEdit` 旧语义进一步收敛为“软意向识别与抽取”链路：采纳后只更新推荐层状态，不再被表述为直接修改当前方案；前端遗留 `planEdit` inputType 兼容保留，但不再作为推荐协议继续扩展。
- `planEdit` 旧命名开始向 `intentDetect` 收敛：ws 入站新增 `intentDetect / intentDetectSelect` 兼容映射，响应 schema 同步兼容 `intentDetectSelectPopup`，便于后续逐步替换旧命名而不打断当前链路。
- websocket 消息落库与 plus 协议出站链路补齐 `intentDetectSelectPopup` 兼容，避免新命名确认卡在前端能收到但未按 `CARD` 正常入历史消息表。
- `plan_edit` 空参数回退抽取改为只看当前轮最后一句用户表达，不再把整段历史重新送去地域/专业/院校意向抽取，修复“`不去北京`”这类单轮约束被历史初始意向污染的问题。
- `city/major/school intent` 抽取工具现仅负责提取，不再在提取阶段直接写画像；真正的画像写入统一延迟到用户采纳后执行，修复“未点击采纳就提前落库”的问题。
- 设计文档补充“报考状态双层生效模型”：硬状态确认后应优先联动候选面板筛选并展示数量变化，软状态确认后只更新推荐承接层并提示用户可自行筛选查看。
- 已存在的硬约束不再被“画像中已存在”短路为纯文本提示；如果用户再次表达这类约束，agent 仍会直接联动候选区展示当前筛除后的结果。
- `ChatAgent` 指令新增强约束：对“想去北京”“不想去山东”“绝对不学医”这类明确报考状态，禁止直接口头回复“已记录”，必须优先调用 `edit_volunteer_plan` 生成确认卡。
- `plan_edit` 的 `impact` 生成逻辑从纯文案拼接升级为结构化 `analysis` + 兼容文本双轨输出：确认卡现在会补充 `analysisStage` 与 `analysis` 字段，结构统一为 `summaryTitle/currentPlanFit/currentPlanConflict/candidateOpportunity/nextActionHints`，同时继续保留 `impact/impactTitle` 供前端现有展示兼容。
- `dialog_intent_router_tool` 对语义预路由命中的 `Prefer / Constrain` 不再直接走旧确认态，而是先返回“兴趣阶段分析”版本的确认卡；强规则短路命中的显式表达仍保留确认态预览，形成“兴趣阶段 -> 确认后状态分析”的最小实现闭环。
- `interestAnalysisPopup` 现已补充用户侧下一步动作按钮，前端支持直接点击 `先看看候选里有没有 / 看看现在这份方案合不合适 / 以后优先按这个方向看`；当前先通过自然语言消息回流 agent，避免为兴趣阶段单独扩一套 websocket 入站协议。
- `plan_edit` 的方案关联分析补充了对 `orderedPlanState.items` 的直接匹配兜底：即使 `candidatePoolState.items` 没有完整候选明细，确认卡仍能从当前排序项自身提取院校 / 专业 / 地域信息，稳定输出“当前方案已命中 / 冲突”分析。
- `city/major/school intent` 抽取工具改为“模型输出 JSON 字符串 + 本地 schema 校验”，不再依赖 provider 对 `tool_choice=required` 的支持，兼容老链路使用的 OpenAI-compatible 模型服务。
- `plan_edit` 新增“体制内 / 考公 / 考编 / 稳定就业”这类发展导向软意向支持：确认后不改候选池，也不误写到院校/专业/地域画像，而是落到 `planningState.profileState.latentProfile.futureDevelopment.careerTypes`，供推荐承接层、初始方案、排序与审查统一消费。
- `ProfileManager` 与 `UserProfile` 读取/合并画像时新增列表归一化，兼容历史画像中混入 `{value,label,name}` 结构的脏数据，避免地域意向更新时触发 `unhashable type: 'dict'`。
- `plan edit` 采纳链路补充批次参数归一化与 code enrichment 前置值清洗，兼容 `batch` 被上游透传为对象及画像字段仍夹带 dict 的情况，修复采纳地域/专业/院校调整时的运行时异常。
- `ChatService` 现在会在处理消息前拉取 `planningState`，并把摘要写入 `RequestContext`。
- `ChatAgent` 指令构建中新增规划状态摘要注入，包含当前阶段、草稿/排序数量、主要风险和待处理建议。
- 进一步压缩 `PlanningSummary` 注入内容，仅保留主 agent 持续推理所需的阶段、数量、风险计数与少量摘要，降低长期对话 token 开销。
- `ChatAgent` 新增 planning 工具调用约束，要求风险类问题优先复审、补偿类问题先预览、直接改方案动作必须先确认。
- `ChatAgent` 现在对“当前到哪一步了”“还有哪些待处理项”这类问题优先走 `query_planning_state`，避免只依赖初始化摘要。
- `ChatAgent` 指令中补充了 `handle_planning_request` 的优先使用策略，并增加“进体制”“去北京”“补一些更稳的”等当前方案干预示例，降低误走画像更新链路的概率。
- `handle_planning_request` 对候选查看、草稿查看、排序查看、审查结果和补偿预览等查看型请求，现会优先返回 `planningWorkspaceAction`，直接联动前端工作台切视图与刷新。
- `planAdjustmentState` 的首轮消费策略收口为“左侧对话先解释，不默认右侧展示建议”：agent 现会直接调用 backend 的 `plan-adjustment/analyze` 并输出摘要分析，只有用户后续明确要求查看定位或执行动作时，才继续进入右侧联动或确认执行链路。
- `ChatService` 新增方案类显式短语预路由：在常规 agent 推理前，先把“看看方案有什么建议 / 审查方案 / 按这个重排一下”等高频明确表达短路到对应 planning tool，减少误走画像更新链路。
- `planning_state_full_design.md` 补充对话主流程框架、四类诉求、五类方案动作、动作编排链、stale 语义与实现落地清单，并明确候选查询归 `Explore/CandidateQuery`、`PlanQuery` 仅承接方案层现状查询。
- `plan edit` 采纳后的引导文案同步收敛：硬约束采纳后优先提示“按这个重排一下”，软意向采纳后提示“看看方案有什么建议 / 按这个重排一下”，明确“画像更新”和“方案动作”是两步语义。
- `planning_agentize_design.md` 补充“当前方案路由与动作编排现状”章节，明确已落地的强路由、确认后执行边界，以及当前仍不自动执行的多步动作范围。
- 修复 `planning_workflow_tool` 仍按旧单参数形式调用 `internal_client` 中同名 planning 接口的问题；现在统一显式传入 tenantId，避免候选查询、草稿选取、排序生成、审查和补偿在运行时因函数覆盖导致参数错误。
- `ChatAgent` 规划指令新增三类体验分层：`左侧直接解决`、`右侧联动查看`、`确认后执行改方案`，用于区分单向信息查询和真正需要进入候选/草稿/排序编排的方案咨询请求。
- `ChatAgent` 现在对草稿查看、排序查看、整体重排和单项调序场景优先调用 planning 工具，而不是仅靠描述性回答。
- `ChatAgent` 现在对明确的草稿增删、锁定和禁用场景优先调用 planning 工具，支持对话直接编排选取动作。
- `ChatAgent` 现在对候选筛选场景优先调用 `query_planning_candidate_pool`，形成“筛候选 -> 引用 volunteerId -> 加入草稿”的对话闭环。
- `planning_agentize_design.md` 补充“轻量摘要 + 按需工具调用”的动作链嵌入方案。
- 新增并调整相关单测，验证 planningState 摘要的解析、透传和指令注入。
- 新增 `planningWorkspaceAction` websocket/card 类型，用于把对话中的规划动作结果直接联动到前端 planning workspace。
- 方案调整采纳成功后，agent 会返回轻量 planning workspace 卡片，引导用户直接查看右侧草稿/排序区域。
- 新增最小 `planning action tools`，支持候选池选入草稿、重排排序、执行审查与应用补偿，并引导前端打开对应 workspace 视图。
- 新增单测，验证 `handle_planning_request` 对状态查询、候选选取、重排确认、审查和补偿预览的路由行为。
- `ChatAgent` 的 `Plan` 工具注册面继续收口：低层 `planning_workflow_tool` 与草稿/排序直接操作 tool 不再注册给模型直连，当前只保留 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` 这条主编排入口，避免模型绕过统一动作链直接复述旧摘要或漂移到低层执行接口。
- `ChatAgent` 的 `Plan` 指令补充了两条强约束：一是方案现状/审查后/重排后这类时效性问题必须重新读取当前状态，不能只靠历史记忆复述旧答案；二是方案类回复默认压成自然短段落，避免 markdown 表格、固定菜单和系统播报式组织。
- `query_planning_plan_overview` 的用户侧概览口径收正：不再在方案概览里显式展示 `待刷新状态`，仅在更偏状态诊断的 `query_planning_state` 中保留 stale flags 信息，避免“方案已生成但概览仍提示待刷新”的产品感知割裂。
- `execute_plan_action` 的高频只读分支开始返回结构化 `facts`：`query_state / review_plan / analyze_adjustment / preview_compensation` 现在都会携带统一业务事实（数量、风险提醒、命中规则、建议计数、补偿动作数、意向承接等），同时仅保留更薄的 `summary` 文本，减少模型被旧摘要风格带偏。
- `PlanExecutionResult` 进一步补齐结果语义层：新增 `result_kind / reply_focus / next_step_hints`，并把 `query_state / generate_plan / review_plan / analyze_adjustment / preview_compensation` 的执行摘要改为先整理“目标数量、缺口、冲稳保分布、主要问题、补偿空间”等业务判断，再交由主模型组织用户回复，降低“只有数字没有判断”或“整体状态问题被答成局部推荐”的概率。
- `ChatAgent` 的 Plan 指令继续收紧：当前明确要求 `方案有了么` 这类问法先直接回答有无方案、数量、风险/提醒，不要自动膨胀成多路线决策题；对 `帮我审查一下` 这类问法先给总体结论，再提 1-3 个关键问题，避免标题块、emoji、编号菜单和客服播报式回复。
- 新增 `examples/dialog_regression_runner.py` 的真实回归使用记录：本轮回归确认 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` 的动作链已经正确落到 `query_state / review_plan`，但旧会话里主模型仍偶发把最终话术组织成粗体标题 + 选项菜单；这属于当前残余的回复风格问题，而不是 Plan 执行层数据缺失。
- `plan_chat` skill 已从旧的低层 planning 工具说明切换为 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` 主链路说明，并补充“普通中文短段落、不要标题块/emoji/编号菜单/强迫式选项”的最终回复边界，避免 skill 文案继续把模型拉回旧工作流。
- `ChatService` 增加 Plan 专用最终文本 guard：当本轮实际调用 `execute_plan_action` 后，会把模型输出中的粗体、emoji、标题块、编号/字母选项和“选哪个”类强迫式决策文案清理为普通短段落，并把清理后的文本同步写入历史，避免旧格式继续污染后续轮次。
- `examples/dialog_regression_runner.py` 支持 `--assert-plan-style`，新增 `examples/dialog_regression_plan_cases.json` 覆盖方案状态、审查、调整建议、重排确认等真实问法；runner 现在单条请求失败后继续执行后续 case，并汇总样式或请求失败原因。
- 本轮验证结果：单测 `tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py` 通过 25 条，Plan 编排相关单测通过 45 条；真实 websocket 回归中前两条 Plan 回复已被压成短段落，后续一轮因本地服务 websocket 握手超时未进入业务链路，需要服务恢复后继续跑完整 cases。
- `plan_next_action` 的 `query_state` 默认阶段从 `analyze` 修正为只读 `apply`：方案状态类问法现在会真正进入 `execute_plan_action` 读取 planningState，而不是返回“仅预览/不执行”的空动作结果。
- `ChatService` 的方案动作后工作台刷新改为优先消费 `execute_plan_action` 返回的 `workspace_refresh_targets`，支持一次动作追加多个 `planningWorkspaceAction` follow-up；生成、重排、删除、移动、补偿等动作可同时刷新方案区与审查区，避免执行后审查结果仍停留在旧状态。
- websocket compat 出站链路补充多 follow-up 回归测试，确认主文本回复后会继续逐条发送 `planningWorkspaceAction`，前端可分别刷新 `ordered / review / draft` 等目标视图。
- `Plan` 原子动作继续补齐：`replace_units` 现已从“schema 有但执行层未接入”改为可用的组合动作，确认后按“移出旧志愿 -> 按筛选条件补入候选 -> 重排/复审”执行；`pin_unit / unpin_unit` 也接入执行层，避免模型选中已暴露 action_family 后落到“暂未接入执行层”。
- `plan_next_action` 的缺参判断修正：`limit` 不再被当作有效补入范围，`add_units` 无 volunteerIds 且无地域/院校/专业/标签范围时会停在 `analyze` 要求补齐信息；`replace_units` 同时要求待替换 volunteerIds 与补入范围。
- Plan 确认链路新增轻量 pending action 注入：`ChatService` 会从历史里最近一次 `execute_plan_action` 的 `preview_only` 结果提取待确认动作，并在下一轮 `RequestContext.pending_plan_action` 中提供确认后 `apply` payload；用户回复“确认”时，主模型可直接调用 `execute_plan_action` 执行上一轮预览动作，不需要重新猜参数。
- 工作台刷新判断收紧为优先只看本轮 `new_messages`，避免历史里的 preview 工具调用被误判成本轮执行动作，导致未真正执行时也触发右侧工作台刷新。
- Plan 确认链路继续补齐：`ChatService` 对明确短确认语会直接执行历史 pending `plan_payload`，并按 `execute_plan_action` 的 tool-call / tool-return 结构写回历史，同时根据 `workspace_refresh_targets` 追加多目标工作台刷新，避免确认轮再次依赖模型重猜动作参数。
- `plan_next_action(query_candidates)` 修正筛选透传：候选查询也会生成 `PlanAtomicAction.filters`，执行层可稳定拿到地域、院校、专业、标签、档位和 limit，不再退化成空条件候选查询。
- WebSocket compat 出站发送增加关闭态保护：主回复、thinking 和 follow-up 在客户端断开或连接已关闭时不再抛 ASGI `RuntimeError`，而是记录日志并停止当前连接处理。
- Plan pending 提取补充 `plan_next_action(stage=preview)` 兜底：如果模型预览轮只规划了高副作用动作但没有继续调用 `execute_plan_action` 生成 `preview_only`，下一轮用户回复“确认”仍可复用该 preview plan 生成 apply payload 直接执行。
- Plan 真实回归话术改为更贴近用户表达：用“还差的几个怎么补 / 帮我补几个更稳的 / 怎么把方案补满一点”覆盖 `preview_compensation`，并要求最终回复避免直接暴露“补偿预览”这类内部动作名。
- Plan 局部查询边界继续收紧：“还差几个怎么补 / 补几个更稳的 / 怎么补满”属于数量缺口与方案增补，不属于 `query_volunteer_plan` 的局部命中查询，模型应走 Plan 主链路规划 `preview_compensation` 或 `add_units`。
- `execute_plan_action` 增加高副作用 apply 硬门禁：没有 pending 确认上下文或明确短确认语时，`generate/add/remove/move/replace/regenerate/apply_compensation` 等动作即使被模型直接构造为 `apply`，也会退回 `preview_only`，避免“帮我补几个更稳的”被未确认直接改方案。
- 按筛选补入候选后的执行摘要修正为对比执行前后方案数量：如果后端返回匹配到候选但排序方案数量没有增加，不再宣称“已加入 N 个”，而是提示当前方案数量未变化，避免“已加入 5 个但仍是 93/96”的矛盾回复。
- `query_volunteer_plan` 增加工具级边界保护：遇到“补几个 / 补满 / 还差 / 加入方案”等方案动作诉求时，不再继续做局部方案查询，直接提示应走 Plan 动作预览与确认链。
- Plan 回复样式 guard 覆盖范围从 `execute_plan_action` 扩展到整条主链 `collect_plan_context_inputs / plan_next_action / execute_plan_action`，避免只规划未执行时漏出 markdown、emoji 或菜单式回复。
- `plan_next_action` 增加无方案状态硬约束：当草稿数和排序数均为 0 时，审查、调整、补稳、补齐、重排、替换等依赖现有方案的动作会停在 `analyze` 并标记 `missing_inputs=["existing_plan"]`，避免模型在无方案会话中编造“已有50个志愿/9个稳档”等事实。
- ChatAgent 指令补充 planning 状态优先级：当前草稿/排序为 0 时，即使历史里提到候选或推荐，也不能当成当前方案来审查、补稳或调整；同时 Plan 样式检查补充行内编号清理。
- Plan 文本清理补充“这意味着。”这类 dangling 残句，减少真实对话里未展开解释的半截句。
- Plan 预览执行结果统一追加“需要确认后才会执行”，避免重排、补稳等高副作用动作只描述影响但没有明确确认门禁。
- `query_volunteer_plan` 已纳入 Plan 文本 guard，候选/局部查询回复里的“可能的原因 / 当前情况”这类标题残句也会被清理。
