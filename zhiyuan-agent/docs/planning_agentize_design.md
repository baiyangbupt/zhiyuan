# planningState 在 Agent V3 的接入与编排设计

## 1. 目标

本设计文档聚焦 `gaotu-zy-agent-v3` 如何围绕 backend 的 `planningState` 做对话初始化、动作编排和人机协同，不讨论 backend 规则实现细节本身。

目标是让 agent 从“黑盒出结果”升级为“围绕统一状态理解用户、执行基础能力、解释决策过程”。

## 2. Agent 侧核心职责

agent 在新架构下不再直接承担“独立生成最终志愿表”的职责，而是承担四项职责：

- 读取当前规划状态
- 把用户意图拆解为规划动作
- 决定直接执行、确认执行还是引导前端操作
- 对系统动作和规则结果做可理解解释

## 3. Agent 初始化上下文

## 3.1 必须读取的 planningState 字段

每次会话初始化，或者多轮对话中的关键动作前，agent 至少要读取：

- `sessionId`
- `version`
- `phase`
- `staleFlags`
- `profileState`
- `constraintState`
- `candidatePoolState.summary`
- `draftPlanState`
- `orderedPlanState`
- `reviewState`
- `pendingActions`
- `operationLogs`

其中最重要的是以下六类信息：

- 用户已经提供过什么画像
- 当前方案处于哪个阶段
- 用户已经手动选择了什么
- 用户已经手动调整了什么
- 当前有哪些风险
- 当前系统建议做哪些补偿

## 3.2 初始化上下文组装建议

建议在 v3 内部组装一个 `PlanningConversationContext`，最少包含：

- `sessionMeta`
  - `chatSessionId`
  - `planningVersion`
  - `phase`
- `profileSnapshot`
  - 显式画像
  - 潜在画像
  - 身体条件
- `planSnapshot`
  - 草稿摘要
  - 排序摘要
  - 当前志愿数量
- `riskSnapshot`
  - review 摘要
  - 风险项列表
- `suggestionSnapshot`
  - pending actions
  - 最近 operation logs

这样做的目的是让大模型直接看到“当前状态摘要”，而不是自己解析整份大 JSON。

## 4. Agent 可调用能力模型

建议把 backend 的 planning 接口在 v3 内抽象成标准 operation，而不是让 skill 或 prompt 直接感知接口路径。

建议 operation 列表如下：

- `get_state`
- `get_profile`
- `update_explicit_profile`
- `update_latent_profile`
- `update_physical_constraints`
- `derive_constraints`
- `generate_candidate_pool`
- `query_candidate_pool`
- `select_draft`
- `remove_draft`
- `lock_draft`
- `ban_draft`
- `generate_ordered_plan`
- `move_ordered_item`
- `pin_ordered_item`
- `unpin_ordered_item`
- `run_review`
- `preview_compensation`
- `apply_compensation`

建议每个 operation 统一建模为：

- `name`
- `purpose`
- `input`
- `requiresConfirmation`
- `sideEffects`
- `recommendedWhen`

## 4.0 V2 阶段的两条方案链路

Agent 在 `sessionDetailV2` 下，后续需要明确区分两类“方案相关”请求，不再把它们都混成旧 `planEdit` 或简单排序动作。

### A. 初始方案生成

适用场景：

- 用户尚未主动整理草稿
- 用户说“给我出个方案”“先推荐一版”“想看看系统怎么搭配”

处理目标：

- 调 backend 生成当前候选视图下的 `initialRecommendationState`
- 结果主要作用在候选区
- 不直接改草稿
- 不直接改排序

### B. 调整式方案生成

适用场景：

- 用户已经有草稿或排序
- 用户说“看看方案有没有问题”“怎么调更合理”“帮我优化一下”

处理目标：

- 调 backend 生成 `planAdjustmentState`
- 先在对话中返回分析与建议
- 用户确认后才真正应用到草稿或排序

## 4.1 Agent 侧三类请求分流

agent 在编排前，应先判断用户请求属于哪一类：

### A. 临时查看

例如：

- “看看北京有哪些计算机相关志愿”
- “稳区里还有哪些师范类”
- “有没有适合进体制的专业先看一眼”

处理原则：

- 优先走查询链路
- 可直接在左侧总结
- 结果过多时可联动右侧候选面板定位
- 不写画像
- 不写约束
- 不触发后续排序和审查失效

### B. 方案偏好

例如：

- “更想去北京”
- “不太想去山西”
- “以后优先推荐就业好的”
- “想上计算机”
- “想留本省”
- “想去一线城市”
- “不想只进体制内”

处理原则：

- 先确认，确认的是“是否要纳入后续推荐考虑”
- 写入 `profileState`
- 触发推荐覆盖层重算
- 不直接重建候选基础池
- 不直接替用户改当前候选面板筛选
- 可提示用户“也可以去右侧按这个方向筛选看看”，但筛选动作默认由用户自己触发
- 在需要时提示用户右侧专家优选组合与推荐顺序会更新
- 前端确认卡片应明确展示为“报考偏好确认”，避免让用户误以为系统已经直接修改了最终方案
- 旧 `planEdit` 命名应逐步收敛为 `intentDetect`，语义固定为“软意向识别与抽取”，不要再把它表述成直接改方案
- 兴趣阶段与确认阶段的方案分析，不再依赖旧 `simulate_plan_diff + isPrefer` 升降结果；当前应统一改为：
  - 直接读取 `orderedPlanState.items`，分析“当前方案里”的命中、弱关联和冲突项
  - 直接读取 `candidatePoolState.items`，分析“候选里”尚未进入方案但更相关的潜在机会
- 因此任何“当前方案里...”的学校示例，都只能来自当前 `orderedPlanState`，不能再混入旧推荐快照或模拟升降项

### C. 方案约束

例如：

- “只报计算机相关专业”
- “不报中外合作”
- “学费必须低于 1 万”
- “不想去上海”
- “只去北上广”
- “就想学工科方向”
- “绝对不学医”
- “不去体制外”

处理原则：

- 识别为硬约束
- 先确认
- 确认后优先把约束显式映射为右侧候选面板筛选条件，让用户先看到筛除后的候选结果与数量变化
- 同步写入 `profileState / constraintState`，使后续专家推荐、排序和审查继续沿用这条要求
- V2 当前默认不进一步重建候选基础池，应保持“大候选池稳定、当前候选结果由筛选条件决定”的语义
- 前端确认卡片应明确展示为“报考约束确认”，并提示采纳后会直接联动候选面板筛选和数量变化

补充说明：

- 软意向确认只改变推荐层
  - 推荐系数
  - 专家优选组合
  - 默认推荐顺序倾向
- 不直接触发当前方案的行级变化
- 只有进入明确的方案动作编排链路时，才会做排序重排、补志愿或审查执行

## 4.2 报考状态确认后的双层生效模型

无论正向还是负向，报考状态都分为“硬”和“软”，且确认后都要写入后续推荐层；区别只在于是否自动联动候选面板。

### A. 硬状态

例如：

- 正向硬：`只去北上广`、`就想学工科方向`
- 负向硬：`不考虑留省内`、`不去南方`、`不去体制外`、`绝对不学医`

确认后效果：

- 自动联动右侧候选面板
- 带上对应筛选条件
- 刷新对应区间或全部候选数量
- 让用户看到“筛除后还剩什么”
- 同时更新推荐层状态，供后续专家优选组合、默认排序、审查、补偿继续使用

### B. 软状态

例如：

- 正向软：`想上计算机`、`想留本省`、`想去一线城市`、`想找薪资高的`
- 负向软：`不想留本省`、`不太想去南方`、`不想只进体制内`、`可以不考研`

确认后效果：

- 不自动替用户改当前候选面板筛选
- 可以提示用户去右侧按这个方向筛选查看
- 同时更新推荐层状态，影响专家优选组合与默认推荐顺序

### C. 工作台联动协议建议

当 agent 需要联动工作台时，建议统一通过 `planningWorkspaceAction` 传递：

- `targetView`
- `refresh`
- `candidateFilters`
  - `tiers`
  - `provinceNames`
  - `negativeProvinceNames`
  - `cityNames`
  - `negativeCityNames`

## 4.3 对话分层视角下的 Explore / Intent / Plan

从用户视角，真实对话并不是直接按“查候选 / 改画像 / 调方案”展开，而是先从某个方向、词汇、顾虑或目标出发，再逐步进入更深的方案动作。因此在 agent 编排上，需要在 planningState 之上，再补一层对话任务分层。

推荐统一拆为三层：

### 4.3.0 两轴语义模型

为了避免“方向探索”和“意向确认”混在一起，建议固定采用“两轴模型”：

#### A. 任务轴

- `Explore`
  - 用户在了解、比较、判断适配度
  - 只读分析，不写状态，不改方案
- `Intent`
  - 用户在表达“以后按这个来”的偏好或要求
  - 先确认，再写状态
- `Plan`
  - 用户在围绕当前方案做查看、审查、调整、增删、重排

#### B. 主题轴

- `career`
  - 职业路径、发展路线、就业取向
- `school`
  - 学校、院校层次、院校类型、学校比较
- `major`
  - 专业、专业方向、专业大类、就业表现、学科适配
- `region`
  - 省份、城市、地域机会、留本省、一线城市

关键约束：

- 先判任务，再判主题
- 同一主题在 `Explore / Intent / Plan` 下必须走不同链路
- 用户意向与方向探索不能共用同一个语义入口
- 学校对比、专业对比、查分数等能力属于主题内部技能，不属于 Intent 或 Plan 动作

示例：

- “体制内适不适合我” = `Explore + career`
- “以后优先按体制内方向看” = `Intent + career`
- “把更适合体制内的往前提” = `Plan + career`
- “北京机会多吗” = `Explore + region`
- “以后优先北京” = `Intent + region`
- “把北京的两个加进方案” = `Plan + region`

### A. Explore

定义：

- 用户先了解一个方向、对象或顾虑
- 目标是解释、分析、比较、扩展信息
- 不直接落状态

典型场景：

- “北京有哪些学校”
- “体制内适不适合”
- “土木工程就业怎么样”
- “华南理工值不值得冲”
- “中外合作到底有什么区别”

这一层的主要任务：

- 理解用户此刻更关心的是学校、专业、地域、发展方向还是方案风险
- 调用对应 skill / tool 获取事实
- 结合当前会话语境组织成自然回答
- 在需要时补充“这和当前方案、候选有什么关系”

Explore 内部建议继续按主题拆分，不再用一个宽泛入口兜所有主题：

- `Explore + career`
  - 职业路径分析
  - 例如体制内、稳定就业、读研深造、就业导向
- `Explore + school`
  - 学校层次、学校比较、学校机会分析
- `Explore + major`
  - 专业适配、专业价值、专业比较、专业机会分析
- `Explore + region`
  - 地域机会、留省/出省、城市比较

其中一些现有能力，本质上属于“主题内部技能”：

- 学校主题：`get_school_introduction`、`compare_schools`、`compare_schools_adhoc`、`get_school_recommendations`
- 专业主题：`get_major_introduction`、`compare_majors`、`compare_majors_adhoc`、`get_major_recommendations`
- 分数/录取主题：`query_admission_score`、`query_score_line`

这些能力服务于 Explore 主题分析，不应被误解释成 Intent 写状态或 Plan 执行动作。

这一层不应该直接做的事：

- 不更新偏好或要求
- 不直接改候选视图
- 不直接改草稿、排序、补偿结果
- 不把用户的一次兴趣表达直接解释成长期偏好

### B. Intent

定义：

- 用户希望把某个方向正式记成后续持续生效的报考偏好或报考要求
- 目标是状态确认与落库，而不是单次解释

典型场景：

- “以后优先看北京”
- “不想去体制内”
- “中外合作不要”
- “以后更偏稳定就业”
- “后面都按工科方向来”

这一层的主要任务：

- 判断用户是“先了解”还是“要记下来”
- 生成确认卡，让用户明确采纳
- 用户显式确认后，才更新 profile / constraint / latent profile
- 确认后再决定是否需要联动右侧候选、推荐、审查

这一层必须保留的硬边界：

- 一切真正改状态的动作都必须显式确认
- “偏好”与“要求”都要进入统一标签语义，而不是散落在不同临时字段中
- 确认前只做预览和分析，不得先写后撤

### C. Plan

定义：

- 用户围绕当前方案本身做查看、分析、预览和执行
- 目标是操控当前工作台，而不是单纯积累长期画像

典型场景：

- “看看当前方案”
- “候选里还有没有更稳的”
- “帮我补几个保底”
- “把这个调到第 3 位”
- “检查下这版方案有没有问题”
- “按当前情况重新出一版”

这一层的主要任务：

- 读取当前 planningState
- 判断用户要的是只读分析、右侧联动查看，还是实际执行改动
- 优先围绕候选、草稿、方案、审查、补偿这些当前状态来回答
- 在执行前按动作类型做确认

这一层的动作再分两类：

- 只读动作
  - 查询候选
  - 查询草稿
  - 查询方案
  - 查看审查
  - 查看方案调整建议
- 写动作
  - 加入草稿
  - 移出草稿
  - 锁定 / 禁用
  - 生成 / 重排方案
  - 应用补偿

其中写动作必须确认；只读动作不需要确认。

## 4.4 模型、skill、tool 的职责边界

为了避免重新回到“规则分流 + 模板回复”，建议把职责边界固定如下：

### A. 模型负责什么

- 判断用户当前是在 Explore、Intent 还是 Plan
- 判断这一轮更适合左侧直接解释、右侧联动查看，还是确认后执行
- 决定应该调用哪个 skill / tool 组合
- 基于 tool 返回事实，用自然语言组织回答

模型不应承担：

- 直接拼接接口路径
- 依赖固定关键词或正则做硬路由
- 复述 tool 的模板化原文

### B. skill 负责什么

- 提供某一领域的思考框架与可调用能力集合
- 约束该领域下的回答目标和信息组织方式
- 帮助模型在 Explore / Intent / Plan 内部做更稳定的推理

skill 不应承担：

- 直接做状态写入
- 私自修改统一规划状态
- 用规则替代模型决策

### C. tool 负责什么

- 承担单一、明确、可验证的执行能力
- 输入清晰、输出清晰、副作用可感知
- 在需要时返回结构化 workspace action

tool 不应承担：

- 重新猜测用户到底想干什么
- 在内部靠关键词自行做大范围语义分流
- 输出大段面向用户的固定文案模板

## 4.5 当前实现中的混杂点

以当前 `gaotu-zy-agent-v3` 实现看，整体已从服务端硬路由走向“模型 + tools”，但仍有几类旧形态残留，需要在后续逐步收敛。

### A. Explore 与 Intent 仍然在 `intent_state_tool` 中耦合

当前情况：

- 用户只要提到某个方向，容易被拉进 Intent 确认链路
- 兴趣分析、确认卡、采纳执行共用了一套较重的预览链路
- 某些 fallback 仍会把“了解一下”推向“整理成偏好/要求”

期望方向：

- Explore 单独作为“分析能力”
- Intent 单独作为“状态确认能力”
- 两者可以共用底层事实查询，但不共用语义入口

### B. Plan 层仍有双入口漂移

当前情况：

- 历史上模型既可以直接调用细粒度 planning tools，也可以调用 `handle_planning_request`
- 当前 3.0.1 运行时已经收口为 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action` 主链
- `handle_planning_request` 保留为 deprecated compatibility wrapper，不再作为新增能力入口

期望方向：

- 新增方案能力必须接入 Plan 主链
- 细粒度 planning helper 只在执行层内部复用
- 不再让旧 router 负责“猜用户语义”

### C. 部分 tool 仍在内部做旧式字符串分流

当前情况：

- 某些查询工具仍通过关键词猜测“查方案还是查候选”
- 某些意向工具仍会在缺少结构化字段时做上下文回捞和 fallback

期望方向：

- 让模型先做语义判断
- tool 只接收明确 scope / action / filters
- fallback 仅保留在执行稳定性边界，不能反向主导业务路径

## 4.5.1 `intent_state_tool` 的拆分范围

当前 `intent_state_tool` 同时承载了 Explore、Intent、Explore 后续动作编排、兜底恢复四类职责，是现阶段最明显的“语义边界过重”模块。

为了避免一次性重写，建议按“先拆职责，再收敛入口”的方式处理。

### A. 继续保留在 `intent_state_tool` 的能力

这些能力本质上属于 Intent 层，应继续保留在 `app/tools/intent_state_tool.py`：

- `analyze_volunteer_intent_change`
- `update_volunteer_intent_state(action="confirm")`
- `update_volunteer_intent_state(action="reject")`
- `_apply_intents`
- `_build_cache_data`
- `_load_cached_intents`
- `_build_candidate_filters_from_intents`
- `_query_candidate_total`
- `_query_candidate_base_total`
- 与确认卡、采纳缓存、状态写入直接相关的辅助函数

这部分的统一定位应当是：

- 输入已经是“明确准备记成偏好 / 要求”的结构化意图
- 输出是确认卡、确认结果或状态变更结果
- 不承担“先帮用户分析这个方向值不值得考虑”的职责

### B. 应从 `intent_state_tool` 迁出的能力

以下能力本质属于 Explore 层，不应继续留在 Intent 模块中：

- `preview_interest_analysis_from_request`
- `preview_direction_analysis_from_request`
- `_build_direction_interest_analysis`
- `_generate_direction_analysis_content`
- `_build_plan_relation_analysis`
- `_enrich_plan_relation_analysis_from_state`
- `_build_impact_preview_from_analysis`

建议迁移到新的 Explore 模块，例如：

- `app/tools/explore_direction_tool.py`
- 或 `app/tools/explore_relation_tool.py`

迁出后的定位应是：

- 只做方向 / 词汇 / 关注点的理解与解释
- 可以补充其与当前方案、候选机会的关系
- 只输出分析结果或探索卡片
- 不直接输出偏好 / 要求确认卡

### C. 应单独抽出的“Explore 后续动作处理器”

当前 `handle_interest_analysis_action` 实际是一个小型编排器，负责处理 Explore 卡片上的动作：

- `candidate_query`
- `plan_analyze`
- `prefer_confirm`
- `constrain_confirm`

这类能力建议单独抽到一个 Explore follow-up 模块，例如：

- `app/tools/explore_followup_tool.py`

该编排器现在由 `ChatService.handle_intent_select` 在识别到 `actionType` 后直接分流调用，不再挂在 `intent_state_tool` 内部。这样 Core 层只负责业务事实和状态执行，Explore follow-up 层负责兴趣阶段动作承接。

其职责应限定为：

- 把 Explore 卡片上的后续动作翻译为进一步的 Explore / Intent / Plan 调用
- 不负责真正的状态写入
- 不负责重新解释用户原始语义
- 对外优先返回 `ExploreFollowupResult` 这类结构化事实；旧文本由兼容渲染层生成，不再让后续流程依赖中文话术判断

这样可以避免：

- Explore 后续点击又重新回到 Intent 确认链路
- 让 Explore 和 Intent 在模块边界上持续纠缠

当前落地状态：

- `handle_interest_analysis_action_result` 是结构化入口
- `handle_interest_analysis_action` 是兼容文本入口
- `ChatService.handle_intent_select` 对 `actionType` follow-up 已直接消费结构化结果，再交给 response 层渲染文本
- 职业方向识别与方向适配分析统一在 `explore_direction_tool`，`intent_state_tool` 不再重复承载这套 Explore 能力
- 方向相关性当前集中为“证据计算”事实层，负责给模型提供可解释样本，不负责自然语言路由；后续可替换为统一标签体系评分或模型评估

### D. 应收缩边界的 fallback 与恢复逻辑

以下逻辑短期可以保留，但必须收缩责任边界：

- `_recover_intents_from_context`
- `career_intent_tool.extract_career_intent`
- `_should_use_direction_interest_analysis`

短期保留的原因：

- 当前模型实际调用时仍可能漏传结构化参数
- 完全移除 fallback 会降低链路稳定性

但后续边界应收敛为：

- fallback 只用于“模型已经明确选择 Intent 工具，但参数缺失”
- fallback 不能再反向决定“这轮到底属于 Explore 还是 Intent”
- `career` 这类方向槽位也应切到独立 extractor，不应长期保留字符串模式匹配

## 4.5.1 `career_intents` 的隐含设计约束

当前实现里，`career_intents` 在缓存结构上与 `major_intents / school_intents / city_intents` 并列出现，但它们在语义层和执行层并不完全平级。

### A. 当前语义定位

- `major_intents / school_intents / city_intents`
  - 更接近显式报考意向
  - 可以较稳定地映射到统一标签体系或候选筛选字段
  - 能直接联动右侧候选筛选

- `career_intents`
  - 更接近发展方向偏好
  - 当前主要作用于 Explore 分析、推荐承接、方案关联判断和后续偏好确认
  - 不能直接视为天然可筛选的候选标签

### B. 当前隐含假设

系统当前默认认为：

- “体制内 / 稳定就业 / 深造发展”这类方向不是单一标签
- 它们需要通过院校性质、院校分类、专业方向、升学条件等多维特征综合判断
- 因此在未定义统一标签映射前，不能直接把 `career_intents` 当作候选 filter 使用

这也是为什么当前 `explore_followup_tool` 中：

- `major / school / city` 可以进入候选筛选映射
- `career_intents` 只能影响 Explore 分析与后续确认，不能直接筛出右侧固定候选结果

### C. 对后续设计的要求

后续若继续收敛语义层，建议把 `career_intents` 从“平级 intent 包”中进一步正名，例如：

- `direction_intents`
- `development_intents`

从而避免误导后续实现者把它理解成与地域、院校、专业完全平级的显式筛选项。

### D. 若未来要支持方向直筛

只有在补齐以下定义后，才能把 `career_intents` 映射为候选筛选：

- 与统一标签体系的映射规则
- 对应的院校标签、专业标签、培养路径标签集合
- 命中规则与置信度边界

在这些规则明确之前，`career_intents` 仍应被视为“方向偏好”，而不是“直接筛选条件”。

## 4.5.2 `career` 与 latent profile 抽取器的接入决策

当前链路按“是否值得作为独立 extractor”拆成两类：

- `career / futureDevelopment.careerTypes`
  - 需要独立 extractor
  - 原因不是它更重要，而是它已经有明确槽位、明确确认语义、明确写入位置
  - 当前允许的方向槽位只有 3 类：
    - `system_public_service`
    - `stable_employment`
    - `further_study`
  - 它在 agent 里的职责是：
    - Explore 阶段做方向适配分析
    - Intent 确认后写入 `latentProfile.futureDevelopment.careerTypes`
    - 后续影响推荐承接与方案关联分析
  - 因此它适合像 `major / school / city` 一样，使用模型抽取，而不应继续依赖手写短语匹配

- `interest_personality / family_context`
  - 暂不接成一等 extractor
  - 不是不能做，而是当前还缺少稳定的三件事：
    - 明确槽位体系
    - 用户确认语义
    - 写入后会影响哪些推荐/方案能力
  - 在这些没收敛前，直接暴露 extractor 只会把“理解用户”提前做成“过早落状态”

因此当前阶段的接入策略是：

- `career`：接入独立 extractor，替换 `intent_state_tool` 里原先的字符串恢复逻辑
- `interest_personality / family_context`：先由模型在 Explore 阶段自然理解，不立即写状态；等槽位体系和生效链路明确后再补 extractor

## 4.5.4 `intent_mode` 的责任边界

`intent_mode` 的判定责任应尽量上移，不应继续留在工具层靠文案匹配来猜。

### A. 正确职责划分

- 模型 / 上游编排层
  - 负责判断这次表达更接近“偏好”还是“要求”
  - 在调用 `analyze_volunteer_intent_change` 时显式传入 `intent_mode`

- `intent_state_tool`
  - 负责承接结构化结果
  - 负责确认卡生成、缓存、落状态、候选联动
  - 只保留最小结构化兜底，不再根据“别去 / 不太想 / 要不还是 / 吧”这类措辞猜测模式

### B. 为什么不能继续放在工具层猜

原因不是实现麻烦，而是语义责任错位：

- 用户文案的缓和语气并不稳定
- 同一句里可能同时出现 Explore 和 Intent 语义
- 不同上游入口已经具备更完整上下文
- 如果工具再二次猜测，会把模型已经做出的任务判断打散

因此后续原则应固定为：

- 能显式传 `intent_mode` 的地方，一律显式传
- 工具层只做结构化 fallback，不做话术级判定

## 4.5.3 场景到抽取器的映射

### A. 现在就应该走 extractor 的

- “想进体制”
- “以后更想走稳定就业”
- “不想只读研，想早点就业”
- “后面优先按考公方向看”

这些请求已经具备：

- 明确方向槽位
- 明确正负态度
- 明确确认后写入位置

### B. 现在不应直接走 extractor 落状态的

- “体制内适不适合我”
- “我这种性格是不是更适合当老师”
- “家里经济一般，学费太高会有压力”
- “我比较内向，适不适合做研发”

这些请求目前更适合：

- 先走 Explore
- 先做解释、适配分析、方案承接分析
- 只在用户明确表达“以后按这个方向考虑”后，再进入 Intent / 确认链路

## 4.5.4 文件级改造范围建议

为了控制改动范围，建议按文件边界拆分：

### A. `app/tools/intent_state_tool.py`

保留：

- 意向确认预览
- 意向采纳 / 拒绝
- 缓存读写
- 状态落库
- 候选筛选条件映射

收敛后不再负责：

- 方向探索分析
- 探索卡点击后的后续编排
- 大范围用户语义恢复

### B. 新增 Explore 模块

建议新增：

- `app/tools/explore_direction_tool.py`

负责：

- 方向类 Explore 分析
- 方向与方案 / 候选的关系分析
- 输出 Explore 卡片或结构化事实

如后续需要，再拆出：

- `app/tools/explore_followup_tool.py`

负责：

- Explore 卡片按钮动作承接
- 把动作导向候选查看、方案查看或 Intent 确认

### C. `app/agent/chat_agent.py`

后续改造重点：

- 让主 agent 优先在 skill 层面判断 Explore / Intent / Plan
- 不再把 Intent 确认工具当作“既能探索又能确认”的复合工具
- 明确挂载新增 Explore tool，弱化对 `intent_state_tool` 的语义依赖

### D. `skills/explore_chat/SKILL.md`

需要同步更新：

- 将 Explore 的方向分析能力明确绑定到新的 Explore tool
- 强调 Explore 不直接改状态
- 仅当用户明确转入“以后按这个来”时，再调用 Intent 工具

### E. `skills/intent_detect/SKILL.md`

需要同步更新：

- 去掉其承接“兴趣阶段分析”的表述
- 明确该 skill 只服务于偏好 / 要求确认与采纳
- 将“先了解一下”的场景回退给 Explore

## 4.5.3 兼容与灰度原则

为了不打断当前前端和确认链路，拆分时建议遵循以下原则：

### A. 前端消息类型先兼容不变

短期内保留现有消息类型：

- `intentConfirmPopup`
- `interestAnalysisPopup`
- `planningWorkspaceAction`

即使内部模块拆开，也不要先动前端协议。

### B. 先迁内部实现，再收外部命名

短期目标：

- 先把 Explore 的实现迁出去
- 先让 Intent 模块只负责确认与采纳

后续再考虑：

- 是否统一 popup 类型命名
- 是否把 Explore 卡片协议进一步抽象

### C. 确认边界不能动

拆分过程中必须保持：

- 所有真正的状态修改仍然显式确认
- 硬要求确认后仍然可以联动右侧候选
- 软偏好确认后仍然不自动改当前候选视图

这些属于系统稳定边界，不应在语义重构时一起调整

## 4.6 推荐的后续收敛顺序

为了降低风险，建议按以下顺序逐步收敛，而不是一次性推翻：

### 第一步：先拆 Explore 与 Intent

目标：

- 把“兴趣分析”和“状态采纳”拆成两个语义清晰的能力
- 用户先了解，不应自动进入确认
- 用户明确说“以后按这个来”时，再进入确认卡

### 第二步：收敛 Plan 层执行入口

目标：

- 高层上保留统一的 planning 执行入口
- 底层工具继续存在，但弱化其对业务语义的感知
- 让模型更稳定地把 Plan 当成“当前工作台操作层”

### 第三步：移除 tool 内部的大范围语义判断

目标：

- 去掉“查方案还是查候选”“这是偏好还是要求”这类字符串路由
- 保留必要的参数校验、确认校验和异常恢复
- 让模型真正成为业务理解与编排中心

### 第四步：把用户回复全面收回到模型生成

目标：

- tool 返回结构化事实与结构化动作
- 面向用户的解释、引导、下一步建议尽量由模型生成
- 避免固定模板、固定段落、固定两三段文案

## 4.7 对话主链路的目标状态

收敛后的主链路应当是：

1. 用户表达一个问题、兴趣或动作诉求
2. 模型判断其属于 Explore / Intent / Plan 中的哪一层
3. 模型调用对应 skill / tool 拿到事实或执行结果
4. 若涉及状态修改，先走显式确认
5. tool 返回结构化结果或 workspace action
6. 模型基于当前语境组织成自然回答

目标并不是让所有动作都“自动完成”，而是让系统对不同用户阶段有不同承接方式：

- 想先了解的，得到解释和分析
- 想把想法记下来的，得到确认与状态更新
- 想直接改方案的，得到围绕当前工作台的可执行动作
  - `schoolKeywords`
  - `negativeSchoolKeywords`
  - `majorKeywords`
  - `negativeMajorKeywords`
  - `schoolTags`
  - `negativeSchoolTags`
  - `majorTags`
  - `negativeMajorTags`

### 4.7.1 Explore 阶段的最小产品收口

当前 `Explore` 已经具备方向分析、兴趣阶段分析和 follow-up 骨架，但从产品角度看，还需要继续固定两件事：

1. `Explore` 先回答“这个方向/对象和用户本人的适配度”
2. `Explore` 回答完后必须把用户送到一个明确的下一步出口

#### A. 最小分析骨架

Explore 阶段的推荐分析顺序应固定为：

1. 学生本人适配度
2. 方向或对象本身的特点
3. 当前方案承接情况
4. 候选机会空间

其中：

- 第 1 层优先级高于第 3、4 层
- 第 3、4 层属于“补充承接分析”，不是 Explore 的起点
- 不应让 Explore 退化成“先从方案里捞学校”或“先从候选里列样本”

最小事实来源建议：

- `score_detail`
  - 分数
  - 选科
  - 省份
  - 模式
- `init_profile`
  - 已知兴趣
  - 排斥项
  - 地域倾向
- `planning_summary / orderedPlanState / candidatePoolState`
  - 当前方案是否承接
  - 候选是否仍有空间
- 若已有 `latentProfile`
  - 风险偏好
  - 职业导向
  - 其他长期发展倾向

#### B. 四种标准出口

Explore 阶段完成一次回答后，下一步应稳定收敛到以下四类之一：

1. `继续了解`
2. `看候选机会`
3. `看当前方案关系`
4. `沉淀为后续偏好/要求`

这四种出口不是新的硬规则路由，而是 Explore 层输出结果时的最小产品约束。

补充说明：

- 当用户追问的是“更细的人格/职业兴趣适配”，且当前 Explore 已完成初步分析时，
  可以在 `继续了解` 这一出口下，温和补充“如果需要更专业的评估，可进一步做 MBTI 与霍兰德职业兴趣测评”。
- 这属于 Explore 的增强引导，不是新的主出口，也不是强制动作。

目标是避免两类坏体验：

- 只分析，不推进，用户不知道接下来该干什么
- 还在了解阶段，就被系统直接推去确认或改方案

#### C. 第一批实现优先级

为了控制风险，第一批优先收职业方向 Explore 这条线：

- `体制内 / 考公`
- `稳定就业`
- `深造 / 读研`

原因：

- 当前已经有 `explore_direction_tool`
- 当前已有方向场景测试
- 但仍然存在“偏方案承接分析、不够像对学生本人做分析”的问题

第一批收口目标不是扩大覆盖面，而是让这条线稳定满足：

- 先解释用户本人是否值得重点了解这条方向
- 再补方案/候选承接
- 最后给一个自然的下一步出口

其中：

- 硬状态确认后，通常返回 `targetView=candidate` + `candidateFilters`
- 软状态确认后，通常只返回解释文本，或返回“可前往候选区查看”的轻提示，不自动附带筛选条件

## 4.2.1 方案链路的工作台联动

除画像/约束确认外，后续还需要支持两类方案链路联动：

### A. 初始方案生成联动

建议返回：

- `targetView=candidate`
- `refresh=true`

作用：

- 让前端刷新候选区
- 展示 `initialRecommendationState`
- 在候选项上标识 `专家优选组合`

### B. 调整式方案生成联动

建议返回：

- 对话侧直接给出 `planAdjustmentState` 的摘要分析
- 默认不联动右侧工作台展示建议

作用：

- 先让用户在左侧理解“哪里有问题、建议怎么调”
- 若用户接着要求查看当前排序、定位受影响条目或执行改动，再进入右侧联动或确认执行链路
- 默认不直接应用建议

## 4.3 统一标签协议

Agent 在 `sessionDetailV2` 链路中，只能面向 backend 约定的统一标签协议做抽取、确认和工作台联动，不应继续把 rank 原始 tag 或旧前端命名直接暴露给用户。

标准标签域如下：

- `region.school_province`
- `region.school_city`
- `school.category`
- `school.nature`
- `school.feature`
- `school.level`
- `major.discipline`
- `major.category`
- `admission.type`
- `constraint.limit`

Agent 侧运行时字段映射约定：

- `provinceNames / negativeProvinceNames`
  - 对应 `region.school_province`
- `cityNames / negativeCityNames`
  - 对应 `region.school_city`
- `schoolTags / negativeSchoolTags`
  - 对应 `school.category / school.nature / school.feature / school.level`
- `majorTags / negativeMajorTags`
  - 对应 `major.discipline / admission.type / constraint.limit`
- `majorKeywords / negativeMajorKeywords`
  - 兼容期内只承接 `major.category`
- `schoolKeywords / negativeSchoolKeywords`
  - 只允许承接具体院校名
  - 不允许承接“公办 / 民办 / 双一流 / 北京院校 / 省会城市”这类属性

专业层级与候选筛选字段映射表：

| 语义层级 | 中文含义 | 抽取结果字段 | 候选筛选字段 | 说明 |
| --- | --- | --- | --- | --- |
| level1 | 专业门类 | `level1 / negative_level1` | `majorTags / negativeMajorTags` | 对应 `major.discipline` |
| level2 | 专业大类 | `level2 / negative_level2` | `majorKeywords / negativeMajorKeywords` | 兼容期内承接 `major.category` |
| level3 | 具体专业 | `level3 / negative_level3` | 暂无独立标准字段 | 仅在缺少 `level2` 时可兼容兜底，不应与 level1/level2 混塞 |

补充约束：

- 旧 `major category / subcategory` 命名只允许作为兼容映射存在，不应继续在 agent 对外文案中出现
- `planEdit` 已收敛为 `intentDetect`
  - 语义是“识别用户软意向 / 硬约束并生成确认”
  - 不表示“直接编辑方案”
- 如果用户表达“不要北京”“不去温州”这类地域约束，agent 必须优先映射到 `provinceNames/cityNames` 这条标准链路，而不是混入 `schoolTags`
- 如果用户表达“想学计算机类”“不考虑材料类”，agent 必须优先映射到 `major.category`，兼容期运行时落到 `majorKeywords`

## 5. 用户意图到 operation 的映射

## 5.1 画像类意图

典型用户表达：

- “我更想去北京”
- “我不接受中外合作”
- “我更适合工科”
- “家里希望学费不要太高”

建议映射：

- 若为软意向：更新显式画像或潜在画像，并触发推荐覆盖层重算
- 若为硬约束：先联动候选面板筛选让用户感知结果，再更新显式画像或身体条件，并继续影响后续推荐与排序；当前不自动重建基础候选池
- 若仅为临时查看：不更新状态，转为查询链路

## 5.2 选取类意图

典型用户表达：

- “把这些学校加进去”
- “这个专业不要了”
- “保留这个学校”

建议映射：

- `select_draft`
- `remove_draft`
- `lock_draft`

## 5.3 排序类意图

典型用户表达：

- “帮我重新排一下”
- “把这个学校提前”
- “这个位置固定住”

建议映射：

- `generate_ordered_plan`
- `move_ordered_item`
- `pin_ordered_item`
- `unpin_ordered_item`

## 5.4 审查与补偿类意图

典型用户表达：

- “现在这个方案稳不稳”
- “还有什么风险”
- “帮我自动补齐”

建议映射：

- `run_review`
- `preview_compensation`
- `apply_compensation`

## 6. 执行策略分层

agent 不应对所有操作一律直接执行。建议分三层：

## 6.1 直接执行

适用于低风险、可逆或纯分析型动作：

- 获取状态
- 更新画像
- 推导约束
- 生成候选池
- 运行审查
- 预览补偿

执行后应直接告知用户：

- 做了什么
- 结果是什么
- 下一步建议是什么

## 6.2 先解释再确认

适用于会直接改动方案结果的动作：

- 自动补偿
- 批量加入草稿
- 重新生成排序
- 批量删除或替换志愿

建议采用统一确认模板：

1. 发现了什么问题
2. 准备如何处理
3. 会影响哪些志愿
4. 是否现在执行

## 6.3 引导用户去前端操作

适用于高主观性、高交互成本操作：

- 在多个相近学校之间做主观取舍
- 对已排好的长列表做精细拖拽
- 手动核对中外合作、高收费、限报等细节

agent 在这类场景中不应过度代替用户决策，而应输出：

- 当前风险/差异点
- 推荐关注项
- 建议在前端完成的操作

## 7. Agent 对用户手动操作的感知

## 7.1 必须感知的状态变更

每次执行重要操作前，agent 至少要重新拉取：

- `version`
- `phase`
- `orderedPlanState`
- `reviewState`
- `pendingActions`

如果版本发生变化，说明用户或其它系统动作已经改过当前方案。

## 7.2 处理原则

若检测到用户手动操作：

- 不直接覆盖用户操作
- 先解释当前状态变化
- 基于最新状态继续给建议

例如：

- 用户刚刚拖拽了排序，agent 下一步优先运行审查，不要立即重新排序
- 用户刚刚删除保底志愿，agent 应提示保底风险，而不是立刻默默补回

## 8. Agent 输出格式建议

为了避免“大段泛化建议”，建议将 agent 输出约束成以下几类结构：

## 8.1 状态说明

用于回答“现在到哪一步了”：

- 当前阶段
- 当前志愿数量
- 当前主要风险
- 当前待处理建议

## 8.2 动作说明

用于回答“我刚刚做了什么”：

- 执行动作
- 影响对象
- 为什么这样做
- 是否需要你确认下一步

## 8.3 风险解释

用于回答“为什么提示这个风险”：

- 风险名称
- 命中依据
- 可能后果
- 建议处理方式

## 8.4 补偿说明

用于回答“为什么推荐补这些志愿”：

- 触发的审查项
- 补偿目标
- 新增候选为何被选中
- 是否避开了高风险项

## 9. Skill 设计建议

建议将 skill 切成三类，而不是一个超大 skill：

- `state_reader`
  - 负责读取和摘要 `planningState`
- `action_planner`
  - 负责意图识别和 operation 编排
- `strategy_explainer`
  - 负责解释冲稳保、梯度、保底、补偿和风险规则

这样做的好处是：

- prompt 更短
- 行为更稳定
- 后续更容易灰度替换或升级单一模块

## 10. v3 内部模块建议

建议在代码上拆三层：

## 10.1 `PlanningStateClient`

负责：

- 请求 backend planning 接口
- 处理 DTO 映射
- 统一错误处理与重试

## 10.2 `PlanningContextBuilder`

负责：

- 将原始 `planningState` 压缩为 agent 可用摘要
- 将 review 和 compensation 结果转成可解释文本和结构化上下文

## 10.3 `PlanningActionPlanner`

负责：

- 将用户输入映射为 operation 序列
- 判断每步是否应直接执行
- 判断是否需要确认
- 判断是否应转前端操作

## 11. 推荐的对话处理流程

一轮标准流程建议如下：

1. 读取最新 `planningState`
2. 判断版本是否变化
3. 识别当前用户意图
4. 规划 operation 序列
5. 判断直接执行 / 确认执行 / 引导前端
6. 执行可执行步骤
7. 用 `reviewState` / `pendingActions` 解释结果
8. 告知下一步建议

## 12. 多轮对话案例

## 12.1 用户问“现在方案稳不稳”

建议流程：

- `run_review`
- 读取 `reviewState`
- 总结主要风险
- 若存在 `pendingActions`，同时说明“可以自动补”

## 12.2 用户说“帮我补齐更稳一点”

建议流程：

- `preview_compensation`
- 解释触发原因
- 说明准备补哪些候选
- 请求确认
- 确认后 `apply_compensation`
- 重新展示结果

## 12.3 用户说“把北京的学校再往前排一点”

建议流程：

- 如果是明确志愿，直接 `move_ordered_item`
- 如果是模糊诉求，先列出受影响候选
- 调整后 `run_review`

## 13. 错误与兜底策略

agent 需要考虑以下异常状态：

- `planningState` 不存在
- 候选池为空
- 排序结果为空
- 审查结果过期
- 补偿建议为空

建议降级策略：

- 缺状态：先初始化并解释当前未完成的步骤
- 缺候选：重新生成候选池
- 缺排序：提示先完成草稿选取
- 无补偿建议：明确说明当前没有可安全自动补偿的候选

## 14. 落地顺序建议

建议按以下顺序推进 agentize：

1. 接入 `PlanningStateClient`
2. 建立 `PlanningConversationContext`
3. 支持只读能力
   - 读取状态
   - 运行审查
   - 解释风险
4. 支持预览能力
   - 预览补偿
   - 解释补偿来源
5. 支持写操作
   - 更新画像
   - 应用补偿
   - 生成排序
6. 最后再补复杂交互
   - 局部调序
   - 前端协同引导

## 15. 当前建议的下一步

设计确认后，建议下一步不是立刻全量改造 v3，而是先做一个最小闭环：

- 初始化时读取 `planningState`
- 支持“运行审查 -> 解释风险 -> 预览补偿 -> 确认后应用补偿”

这样可以最快验证 agent 是否真正从“聊天助手”升级为“规划编排助手”。

## 16. 当前已完成的最小接入

当前 v3 已完成第一步最小接入：

- 在会话处理前调用 backend `planningState` 查询接口
- 将返回结果压缩为极轻量的 `PlanningSummary`
- 将 `PlanningSummary` 写入 `RequestContext`
- 在 agent instructions 中注入当前规划阶段、草稿数、排序数、风险摘要和待处理建议

这意味着当前 agent 已经具备以下基础感知能力：

- 知道用户不是从零开始填报
- 知道当前方案处于哪个阶段
- 知道当前主要风险和待处理补偿建议

当前仍未完成的关键动作能力包括：

- 将补偿结果和用户操作解释为更结构化的对话输出

## 17. 当前动作链嵌入方式

当前采用的不是额外 planner 框架，而是“主 agent + 按需工具”的轻量嵌入方式：

- 主 agent 初始化时只注入极短 `PlanningSummary`
- 不把完整 `reviewState.checks`、`pendingActions`、草稿明细、排序明细长期塞进 prompt
- 当用户追问“稳不稳”“有什么风险”“怎么补”“帮我补齐”时，再调用对应 planning tool 拉取最新结果

当前最小动作链工具包括：

- `collect_plan_context_inputs`
- `plan_next_action`
- `execute_plan_action`

历史低层 planning tools、`handle_planning_request` 和 `planning_workflow_tool` 仍保留为兼容或内部 helper，但不再作为主 agent 新增能力的设计入口。

执行约束如下：

- 先区分三类体验目标：
  - `对话框直接解决`：单点查询、解释、比较、风险说明，不默认改动工作台
  - `工作台联动查看`：用户需要看到候选、草稿、排序、审查或补偿预览在当前方案中的结构化结果
  - `确认后执行改方案`：会直接改动草稿、排序或补偿结果
- 对于“体制内更适合哪些专业”“北京有哪些学校”“这个专业就业怎么样”这类单向查询，优先在对话框直接回答；只有结果较多、用户明确要求查看完整列表、或需要继续操作时，再引导工作台
- 对于“看看其他好就业的专业有没有机会”“如果加了 XX 现在方案怎么办”“不想去 XX 了”“再补一些更稳的”这类会影响当前方案的请求，优先进入 planning 编排链路
- 对于“找些更适合进体制的专业”“想去北京”“补一些更稳的”“把这个移到第3位”这类一句话只对应一个 planning 动作的请求，主 agent 也应先走 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`
- `plan_next_action` 负责生成结构化 `PlanActionPlan`，表达 analyze / preview / apply 阶段和 action family
- `execute_plan_action` 负责受控执行，并在需要时内部复用 planning helper 和 internal client
- 对于“查看候选”“查看方案”“执行审查后让我看结果”“先看看补齐建议”这类查看/定位型请求，只有需要刷新、聚焦或筛选工作台时才返回 `planningWorkspaceAction`
- 对于“看看方案有什么建议”“怎么调方案更合理”“帮我优化一下当前方案”这类分析型请求，优先在对话里回答；只有用户确认执行改动时才进入 mutation
- 旧 `query_planning_*`、`select_planning_*`、`move_planning_*`、`pin_planning_*` 等低层接口不再作为模型直连入口新增能力

这种方式的优点是：

- 主 prompt token 成本稳定
- 风险和补偿判断基于最新状态，而不是历史摘要
- 复杂状态只在需要时读取，降低长期多轮对话的上下文负担
- 在不引入额外 planner 框架的前提下，为高频用户诉求提供更稳定的单步落地路径

## 8. 当前方案路由与动作编排现状

当前线上语义已经收口为两条主链路：

- `analyze_volunteer_intent_change` / `update_volunteer_intent_state`：处理软意向 / 硬要求的识别、预览、确认与落库
- `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`：处理围绕“当前方案”的查看、分析、审查、排序、增删移动、重排与补齐动作

`handle_planning_request` 已退为 deprecated compatibility wrapper，只用于历史协议和测试迁移期兼容，不作为当前主 agent 的新增能力入口。

### 8.1 当前已落地的显式短路路由

为了降低主 agent 在意图更新链路和方案动作链路之间漂移，`ChatService` 会在常规 agent 推理前先做一层显式短路：

- 明确意向表达优先进入 `preview_intent_edit_from_request`
- 明确方案分析表达优先进入 `handle_planning_request.plan_adjustment_analyze`
- 明确方案审查表达优先进入 `handle_planning_request.review`
- 明确整体重排表达优先进入 `handle_planning_request.ordered_regenerate`

历史短路曾覆盖的典型表达包括：

- “看看方案有什么建议”
- “怎么调方案”
- “帮我优化一下当前方案”
- “审查方案”
- “看看方案有没有问题”
- “有没有风险”
- “按这个重排一下”
- “重新排方案”
- “帮我重排”

这样做的目的不是替代 LLM，而是先兜住高频、明确、单意图的规划诉求，避免在“更新画像”和“改当前方案”之间误路由。

### 8.2 软意向 / 硬约束确认后的当前语义

当前版本下，软意向和硬约束都要求用户显式确认后才真正生效。

硬约束确认后：

- 更新画像中的约束 / 偏好语义
- 同步输出 `planningWorkspaceAction.candidateFilters`，直接联动工作台筛选栏
- 让用户先看到界面候选结果如何变化
- 同步打脏推荐承接层，供后续专家优选、排序与审查使用
- 不直接自动改当前草稿
- 不直接自动改当前排序方案

软意向确认后：

- 更新画像中的偏好语义
- 若命中“体制内 / 考公 / 考编 / 稳定就业”等发展导向，不再硬塞进院校 / 专业 / 地域画像，而是写入 `profileState.latentProfile.futureDevelopment.careerTypes`
- 同步影响推荐承接层和后续专家优选逻辑
- 不自动改当前候选筛选栏
- 不直接自动改当前草稿
- 不直接自动改当前排序方案

这与 V2 约定保持一致：画像变化负责更新“后续怎么推荐”，当前方案是否真正调整，必须由用户继续发起明确动作。

对应 stale 口径：

- `candidatePool = false`
- `recommendationOverlay = true`
- `initialRecommendation = true`
- `orderedPlan = true`
- `planAdjustment = true`
- `review = true`

也就是说，软意向确认会影响推荐理解、初始方案、排序方案、调整建议与审查结果，但不会自动触发候选基础池重建。

补充约定：

- 当前对话反馈不应再主打“系统优选组合增加哪些、减少哪些”
- 这类反馈属于旧的推荐覆盖层视角，已经弱化
- 新口径应统一收敛为“方案关联分析”

其中：

- 在确认前，先做“兴趣阶段分析”
  - 当前方案是否已命中这个方向
  - 候选里是否还有更值得看的机会
  - 是否值得进一步沉淀成偏好或约束

- 在确认后，做“确认后的状态分析”
  - 当前方案有哪些项已经符合这条偏好 / 约束
  - 当前方案有哪些项与这条约束冲突，或对该偏好覆盖不足
  - 候选里有没有更适合作为补充或替换的机会
  - 下一步更适合继续看候选、分析方案还是直接重排

这层分析的核心目标是帮助用户继续思考下一步，而不是把确认反馈做成一段“优选变化播报”。

### 8.3 当前方案动作的执行边界

`handle_planning_request` 当前只负责单步动作编排，不负责未经确认的多步自动执行。

已稳定支持：

- 看候选 / 看草稿 / 看排序
- 看方案分析建议
- 执行方案审查
- 看补偿预览
- 用户确认后的整体重排
- 用户确认后的补偿应用

当前仍明确不自动做的事情：

- 分析完后自动执行 add / replace / reorder 多步链
- 因软意向确认直接改当前方案
- 因硬约束确认直接改当前方案
- 未确认时直接执行补偿或重排

### 8.4 与前端工作台的联动原则

当前联动原则也已经收口：

- 查看型请求优先返回 `planningWorkspaceAction`，让前端切到候选 / 草稿 / 排序等对应视图
- 分析型请求优先在左侧对话中直接回答，不默认要求右侧展示建议面板
- 只有当用户明确要求执行重排、补偿或其他直接改方案动作时，才进入确认后执行链路

### 8.4.1 当前最小实现口径

当前在 agent 侧，先落一个不依赖 backend 新增分析接口的最小实现：

- 语义预路由命中的 `Prefer / Constrain`
  - 先返回“兴趣阶段分析”版本的确认卡
  - 不再直接落到旧的确认态播报
- 强规则短路命中的显式表达
  - 例如“想去北京”“不去北京”
  - 仍直接走确认态预览

确认卡同时保留两层数据：

- 兼容字段
  - `impact`
  - `impactTitle`
- 新增结构化字段
  - `analysisStage`
    - `interest`
    - `confirmed`
  - `analysis`
    - `summaryTitle`
    - `currentPlanFit`
    - `currentPlanConflict`
    - `candidateOpportunity`
    - `nextActionHints`

这样做的目的：

- 前端当前无需立即改卡片展示协议
- agent 与测试可以先围绕结构化字段稳定演进
- 后续 backend 若补充更完整分析数据，可以直接替换 `analysis` 生成逻辑，而不必再改确认卡协议

当前实现补充说明：

- `analysis` 的“当前方案命中 / 冲突”不再强依赖 `candidatePoolState.items` 的完整候选映射
- 当 `orderedPlanState.items` 已经带有院校 / 专业 / 地域等展示字段时，agent 会直接基于排序项自身做标签命中分析
- 这样可以避免 backend 对 `planningState` 做轻量裁剪后，确认卡退化成只剩候选机会、看不到当前方案承接情况

后续演进约定：

- `interestAnalysisPopup` 不直接暴露“记成偏好 / 记成要求”这类系统词
- 用户侧只展示自然语言动作
  - 例如“先看看候选里有没有”“以后优先按这个方向看”“以后别再给我推荐这类”
- 前端点击后再映射到内部动作语义
  - `prefer_confirm`
  - `constrain_confirm`
  - `candidate_query`
  - `plan_analyze`
- `candidate_query` 只作为 Explore 阶段的候选机会查询事实，不自动刷新右侧候选面板；右侧候选筛选联动仍限定在用户确认“要求”之后

### 8.4.2 方案查询与候选查询拆分

`PlanQuery` 在 V2 里不再沿用旧版 `session_volunteer_{id}_temp.json + DuckDB + SQL 生成` 这条链路，当前最小实现已经切换为直接读取 planning state 相关接口，按“当前方案”与“候选机会”两类语义拆分：

- 当前方案查询
  - 主查 `orderedPlanState.items`
  - 若当前还没有排序方案，再退到 `draftPlanState.items`
  - 典型问法：
    - “当前方案里有没有生物工程”
    - “排序方案里看看北京的学校”
- 候选机会查询
  - 直接走 `candidate-pool/query`
  - 典型问法：
    - “候选里还有什么生物工程”
    - “还能报哪些北京的学校”
- 默认兜底
  - 像“看看生物工程”这类未显式声明范围的问法
  - 先回答当前方案命中情况
  - 若当前方案未命中，再补充候选池中的机会

这样调整的原因：

- `_temp.json` 属于旧版推荐池快照，不再等价于当前 V2 的“方案”
- 用户问“看看某专业”时，更自然的第一语义通常是“当前方案里有没有”
- 若当前方案没有命中，再补“候选里还有机会”，对用户更有可操作性

当前实现口径：

- 默认文本回答会明确区分“当前排序方案 / 当前草稿”和“候选机会”
- agent 不再依赖下载 OSS 文件、DuckDB 建表、LLM 生成 SQL
- 后续若 backend 提供更强的结构化查询接口，可继续替换实现，但保留这层语义拆分

### 8.5 当前阶段仍待继续建设的部分

本轮落地解决的是“路由更稳定、语义更一致”，不是完整闭环的终态。当前仍待继续完善的能力主要包括：

- 分析建议到具体 add / replace / reorder 动作的自动编排闭环
- 更细粒度的方案调整策略选择与确认 UI
- 对“分析后直接按建议执行”的多步事务化约束

### 8.6 从规则路由向 LLM 编排迁移的保守方案

历史上对话链路曾形成一套较稳定、但偏规则驱动的受控结构：

- `app/service.py`
  - 强规则短路 `should_force_intent_preview`
  - planning 显式短路 `preview_planning_request_from_content`
  - 语义分类短路 `preview_dialog_intent_route`
  - 其后才进入主 agent
- `intent_state_tool`
  - 负责兴趣分析卡、确认卡、采纳后的状态更新与前端联动
- `planning_router_tool`
  - 负责高频单步 planning 动作的显式映射

这套旧实现的主要问题是：

- 对“体制内适不适合”“这个方向值不值得看”这类问题，规则路由过早决定路径，容易直接落到候选或方案读取
- 对需要先解释、再引导下一步的场景，规则很难表达“先读画像，再看方案，再决定要不要查候选”这类柔性路径

但这套旧实现也稳定保护了几条关键边界，迁移时不能把这些执行边界一起删掉。

#### 8.6.0 迁移总原则

后续从规则路由迁移到 LLM 编排时，应遵守一条总原则：

- 原则上尽可能由模型来判断
- 尽量减少问法级、语句级的硬匹配
- 通过 skill 编排和 tool 调用完成整体逻辑
- 只在“状态调整环境”增加少量硬规则，以提高系统稳定性

这条原则对应的职责分工应固定为：

- 模型负责
  - 语义理解
  - 当前阶段判断
  - 先查什么、后查什么
  - 解释组织
  - 下一步动作建议
- skill / tool 负责
  - 读取画像
  - 读取方案 / 候选 / 审查状态
  - 方向分析
  - 候选查询
  - 方案分析
  - 确认链路承接
  - 真正的状态执行
- 硬规则负责
  - 是否允许直接改状态
  - 是否必须先确认
  - 是否允许联动右侧工作台
  - 是否允许执行重排 / 补偿 / 落画像
  - 是否允许跳过执行边界

也就是说：

- 规则不再主导“怎么理解用户”
- 规则只主导“哪些事情不能乱做”

后续实现若出现冲突，应优先遵守这条约束：

- 能交给模型理解的，就不再新增硬匹配
- 只有状态调整和执行边界，才允许增加稳定性规则

#### 8.6.0.1 当前已落地的 model-first 收口

当前版本已经把对话入口进一步收口到 model-first：

- `ChatService.handle_message`
  - 不再做 intent / explore / plan 的前置短路
  - 不再在 service 层做显式规则分流
  - 统一只负责：
    - 读取上下文
    - 组装 `RequestContext`
    - 进入主 agent

- 主 agent
  - 成为唯一的对话理解与触发入口
  - 由模型自己决定：
    - 当前更像 Explore / Intent / Plan 哪一类
    - 应优先调用哪个 skill
    - 需要查询什么工具
    - 是直接回答、联动右侧，还是进入确认链路

- skill 层
  - 显式分为：
    - `explore-chat`
    - `intent-detect`
    - `plan-chat`
  - skill 只提供“这一类任务应如何理解和调用能力”的指导，不再承担 service 级规则分流职责

同步清理的旧逻辑包括：

- `should_force_intent_preview`
- `preview_planning_request_from_content`
- `resolve_forced_planning_request`
- `dialog_intent_router_tool`
- `direction_orchestrator_tool`

也就是说，当前对话侧已经不再保留：

- 基于关键词的 intent 强制短路
- 基于关键词的 plan 强制短路
- 基于本地 fallback 的 explore / intent 分类兜底

但以下边界仍保留在工具和执行层：

- 是否需要确认才能改画像
- 是否允许直接改方案
- 是否允许执行重排、补偿、落画像
- 是否返回 `planningWorkspaceAction`

这保证了：

- 理解和触发交给模型
- 真正状态变更仍受控

#### 8.6.1 必须保留的边界

以下能力不建议直接下放给 LLM 自由决定，只允许模型“建议”，最终执行仍由受控层完成：

- 状态写入边界
  - 更新显式画像
  - 更新 latent profile
  - 更新候选筛选条件
  - 生成初始方案
  - 重排方案
  - 应用补偿
  - 草稿增删锁禁
- 确认边界
  - 长期偏好 / 要求落库前必须确认
  - 会改动当前方案的动作必须确认
  - 会改变前端工作台状态的执行型动作必须确认
- 协议边界
  - `interestAnalysisPopup`
  - `intentConfirmPopup`
  - `planningWorkspaceAction`
- 候选语义边界
  - 大候选池不自动重建
  - 右侧候选 = 大候选池 + 当前筛选
  - 硬要求确认后联动筛选，不自动重建大候选池
  - 软意向不直接改候选结果

这些边界一旦交给模型自由处理，最容易退化成：

- 用户只是想了解，模型直接把内容落成偏好 / 要求
- 用户只是想分析，模型直接改方案
- 用户只是想筛候选，模型顺手更新画像或重建候选池

#### 8.6.2 可以下放给 LLM 的部分

更适合交给 LLM 的是“理解与计划”，而不是“状态执行”：

- 用户当前真正目标判断
  - 想了解
  - 想比较
  - 想分析当前方案
  - 想看候选机会
  - 想沉淀成长期偏好 / 要求
  - 想直接执行方案动作
- 多步只读分析路径选择
  - 先看画像
  - 再看当前方案
  - 是否补查候选
  - 是否补查专业 / 院校信息
- 下一步动作建议生成
  - 看候选
  - 看方案适配
  - 以后优先按这个方向看
  - 以后按这个要求来

换言之，LLM 更适合决定：

- “这句话现在更像是在问什么”
- “先查什么再回答更合理”
- “回答之后该给用户什么下一步选项”

而不适合直接决定：

- “是否立即落状态”
- “是否立即改方案”
- “是否立即联动右侧工作台”

#### 8.6.3 推荐的新分层

建议把现有架构从“规则直接决定执行路径”调整为四层：

1. Guardrail 层
- 只负责高风险动作拦截
- 保证确认边界、状态边界、协议边界不被绕过

2. Intent Orchestrator 层
- 由 LLM 输出中间语义，不直接执行
- 例如：
  - `understand_direction`
  - `analyze_plan_fit`
  - `inspect_candidates`
  - `commit_preference`
  - `commit_requirement`
  - `execute_plan_action`

3. Skill Executor 层
- 只负责调用白名单 skill
- 不自行创造新的状态语义
- 可限制最大步数和允许的能力组合

4. State / Action 层
- 最终状态写入、确认卡生成、前端联动仍走现有受控工具

这意味着后续迁移的重点不是“让模型全权接管”，而是：

- 让模型接管“理解和计划”
- 保留工具层对“执行和落状态”的控制

#### 8.6.4 第一阶段的替换范围

第一阶段建议只替换“理解”，不替换“执行”。

建议替换的部分：

- `preview_dialog_intent_route`
  - 从固定 `Explore / Prefer / Constrain / Plan` 规则分流，迁移到中间语义 + skill 计划
- `preview_planning_request_from_content`
  - 减少对显式短语匹配的依赖
  - 尤其是“想了解 / 想分析 / 想看机会”这类不应被硬编码的路径
- 兴趣阶段问题的路径选择
  - 例如“体制内适不适合”“这个方向值不值得看”

第一阶段明确不替换的部分：

- `apply_selected_intents` / 旧兼容入口 `handle_plan_edit_select`
- `_apply_intents`
- `planningWorkspaceAction`
- 方案生成 / 重排 / 补偿执行
- 候选筛选联动
- 画像与 latent profile 更新

也就是：

- 让 LLM 决定“该走兴趣分析、方案分析、候选查看还是确认卡”
- 但真正执行仍走现有工具和状态机制
- 执行结果必须优先使用结构化事实字段联动前端，例如候选筛选使用 `candidateFilters`，不要再通过最终中文文案做流程判断

#### 8.6.5 第一阶段建议收敛的 skill

第一阶段不建议一开始铺太大，建议只收敛为 4 类只读 / 半只读能力：

1. `profile_read_skill`
- 读取初始画像
- 读取 latent profile
- 读取 score detail

2. `plan_state_read_skill`
- 读取 ordered / draft / candidate summary / review

3. `direction_analysis_skill`
- 分析“体制内 / 考公 / 就业 / 深造 / 稳定”这类发展方向
- 只负责解释与承接分析，不直接改状态

4. `intent_commit_skill`
- 当模型认为用户已经从“了解”进入“确认采纳”阶段时
- 进入现有确认卡 / 采纳链路

第一批最适合迁移的典型问法：

- “体制内适不适合”
- “考公是不是更适合我”
- “这个方向值不值得看”
- “以后就业稳一点会不会更适合”

原因是这些问题本质上都更像“分析型问题”，而不是“立即执行型问题”。

#### 8.6.6 迁移时最容易破坏的现有效果

如果直接切到“LLM 自由编排”，最容易退化的现有效果包括：

- 明确表达硬要求时，一定先确认
- 软意向不会直接改候选
- 硬要求不会自动重建候选池
- 方案分析和方案执行严格分离
- 前端仍然只接既有的卡片 / 工作台联动协议
- 兴趣阶段先分析，不直接采纳
- 点击按钮后的动作仍是确定性的

因此，迁移过程中必须持续验证这些行为没有回退。

#### 8.6.7 回归检查清单

迁移第一阶段后，至少要覆盖以下回归样本：

1. 兴趣分析类
- “体制内适不适合”
- “这个方向值不值得看”
- 预期：
  - 不直接返回生硬的候选或方案结果
  - 先给解释型分析
  - 再给下一步动作

2. 明确软意向类
- “以后优先按这个方向看”
- “更想去北京”
- 预期：
  - 仍进入确认链路
  - 不直接改状态

3. 明确硬要求类
- “不去北京”
- “不看中外合作”
- 预期：
  - 仍进入确认链路
  - 确认后联动筛选
  - 不自动重建大候选池

4. 方案分析类
- “看看现在这份方案合不合适”
- “方案有什么建议”
- 预期：
  - 仍走方案分析能力
  - 不直接进入执行型动作

5. 执行型动作类
- “按这个重排”
- “应用补偿”
- 预期：
  - 仍需确认
  - 不被 LLM 自由跳过确认边界

#### 8.6.8 迁移目标的正确边界

这次迁移的目标，不是“取消规则，让模型完全接管”。

正确目标应是：

- 保留少量 Guardrail 规则
- 把大部分“如何理解这句话、该先分析还是先查再答”的判断交给 LLM
- skill 保证执行可控
- 状态变更与前端协议继续保持确定性

只有在这个边界下，才能既改善“规则太僵硬”的问题，又不破坏当前已经稳定下来的确认语义、候选语义和前端联动语义。

### 8.7 第一阶段试点：方向适配分析编排

第一阶段不建议直接把所有兴趣 / 偏好 / 要求场景都切到新编排。更合适的试点范围是：

- `体制内 / 考公`
- `稳定就业`
- `深造发展`

这一类问题的共同特点是：

- 用户更像是在问“这个方向适不适合我”
- 回复需要先解释，再引导下一步
- 不应该一上来就直接捞候选、捞方案或进入确认落库
- 但也确实需要结合画像、当前方案和候选机会来判断

典型试点问法：

- “体制内适不适合我”
- “考公是不是更适合我”
- “以后想稳一点，应该怎么选”
- “更适合深造还是更适合就业”
- “这个方向值不值得看”

#### 8.7.1 试点目标

试点阶段的目标不是“自动改状态”，而是让 agent 先学会：

- 判断用户是在“方向适配分析”语义下发问
- 先决定要读哪些只读能力
- 组织一段解释型回复
- 再决定是否要给出下一步动作

这里要特别强调：

- 试点里的 `Explore` 不应退化成“先看当前方案里有没有”
- 正确顺序应是：
  - 先做个性化适配分析
  - 再做方向本身解释
  - 最后补方案 / 候选承接分析

也就是说：

- 个性化分析是主干
- 方案层分析是收尾补充

不应该出现的行为：

- 一上来直接返回候选结果列表
- 一上来直接返回当前方案命中项列表
- 未经分析就进入“记成偏好 / 要求”的确认链路
- 用强规则把“想了解”直接当成“想采纳”

#### 8.7.2 中间语义协议

建议为这类问题单独定义一组比 `Explore / Prefer / Constrain` 更贴近用户任务的中间语义。

第一阶段只需要以下枚举：

- `direction_understand`
  - 用户想先理解某个发展方向
  - 例如“体制内适不适合我”
- `direction_compare`
  - 用户想比较两个方向
  - 例如“更适合考公还是更适合就业”
- `direction_plan_fit`
  - 用户明确想看当前方案和这个方向是否匹配
  - 例如“现在这份方案适不适合走体制内”
- `direction_candidate_opportunity`
  - 用户明确想看候选里是否还有更匹配的机会
  - 例如“候选里还有没有更适合考公的”
- `direction_commit_preference`
  - 用户明确表示想把这个方向纳入后续长期偏好
  - 例如“以后优先按体制内方向看”
- `direction_commit_requirement`
  - 用户明确表示想把这个方向纳入排他性要求
  - 例如“以后不要再给我推荐体制外的”

第一阶段建议约束：

- orchestrator 只能输出上述有限枚举
- 不允许直接输出最终协议类型
- 不允许直接输出执行型状态变更动作

#### 8.7.3 Orchestrator 输出协议

建议让 orchestrator 输出结构化 JSON，而不是自由文本。

最小字段建议：

- `semantic_type`
  - 上述中间语义枚举之一
- `direction_slots`
  - 例如：
    - `system_public_service`
    - `stable_employment`
    - `further_study`
- `analysis_plan`
  - 只读能力调用计划
  - 例如：
    - `read_profile`
    - `read_plan_state`
    - `inspect_candidate_opportunity`
- `answer_mode`
  - `explain_only`
  - `explain_then_actions`
  - `direct_confirm`
- `confidence`
  - 供 guardrail 决定是否回退到旧链路
- `reason`
  - 一句短语说明为什么这样判定

示例：

```json
{
  "semantic_type": "direction_understand",
  "direction_slots": ["system_public_service"],
  "analysis_plan": ["read_profile", "read_plan_state"],
  "answer_mode": "explain_then_actions",
  "confidence": 0.88,
  "reason": "用户在询问体制内方向是否适配自己，核心诉求是解释分析而非立即执行"
}
```

#### 8.7.4 第一阶段可用 skill

试点阶段不建议上太多能力，避免 LLM 编排发散。建议只开放以下只读或半只读 skill：

1. `read_profile`
- 读取：
  - `score_detail`
  - `init_profile`
  - `latentProfile`
  - `latentProfile.futureDevelopment`
- 作用：
  - 判断学生基础背景、兴趣性格、家庭诉求与当前潜在发展倾向

2. `read_plan_state`
- 读取：
  - `orderedPlanState`
  - `draftPlanState`
  - `candidatePoolState.summary`
- 作用：
  - 判断当前方案是否已经承接这个方向

3. `direction_analysis`
- 只做方向解释
- 不直接落状态
- 输入：
  - 方向槽位
  - profile 摘要
  - plan 摘要
- 输出：
  - 这个方向和用户自身特征的适配度
  - 为什么适合 / 不太适合
  - 当前更匹配的部分
  - 当前较弱的部分
  - 是否值得继续往这个方向看

4. `candidate_opportunity_inspect`
- 仅在用户明确想看机会，或 orchestrator 认为有必要补充机会判断时使用
- 只返回“有没有必要继续看”的摘要
- 第一阶段不直接返回大列表，避免又退化成“捞结果”

5. `intent_commit_skill`
- 仅在 `direction_commit_preference / direction_commit_requirement` 时进入
- 仍然复用现有确认卡和采纳链路

#### 8.7.5 第一阶段编排规则

试点阶段建议加上明确的调用限制：

- 最大只读 skill 步数：2
- 默认顺序：
  - 先 `read_profile`
  - 再 `read_plan_state`
- 只有在以下条件之一时才允许补 `candidate_opportunity_inspect`
  - 用户明确问“还有没有机会”
  - 当前方案明显不承接该方向
  - orchestrator 明确判定需要补充机会判断

第一阶段不允许的链路：

- `direction_understand -> 直接 candidate_query 列表`
- `direction_understand -> 直接 confirm popup`
- `direction_understand -> 直接 planningWorkspaceAction`
- `direction_understand -> 直接状态写入`

#### 8.7.6 第一阶段回复产物约束

为了不破坏当前前端协议，试点阶段的产物只允许以下三类：

1. 普通文本回复
- 用于单纯解释型场景

2. `interestAnalysisPopup`
- 用于“先解释，再给下一步动作”
- 这是试点阶段最推荐的默认产物

3. `intentConfirmPopup`
- 仅在用户明确从“了解”转入“采纳”时使用

第一阶段默认不直接返回：

- `planningWorkspaceAction`
  - 除非用户明确点了“看看候选里有没有”
- 方案执行型动作结果
  - 例如重排、补偿、直接改当前方案

#### 8.7.7 试点问题的目标链路

以“体制内适不适合我”为例，目标链路应为：

1. orchestrator 判定：
- `semantic_type = direction_understand`
- `direction_slots = [system_public_service]`

2. 执行只读计划：
- `read_profile`
- `read_plan_state`

3. 生成解释：
- 当前兴趣、性格、学科优势、家庭诉求、未来发展倾向，与“体制内/考公导向”的适配度
- 这条方向本身更看重的路径特征是什么
- 当前哪些背景更支持往体制内方向看
- 当前方案里哪些内容较贴近这条方向
- 哪些地方目前承接一般
- 是否值得继续深入看

4. 返回 `interestAnalysisPopup`
- 按钮：
  - `看看现在这份方案合不合适`
  - `先看看候选里有没有`
  - `以后优先按这个方向看`

不正确的链路是：

- 直接从当前方案里捞学校 / 专业来回答
- 直接从候选里捞一批结果来回答
- 直接回答“方案里有 A/B/C”
- 直接回答“候选里还有 X/Y/Z”
- 直接给确认卡要求采纳

#### 8.7.8 与旧链路的兼容方式

第一阶段不建议直接删掉旧链路，而应采用“试点命中 -> 新编排；未命中 -> 回退旧链路”的方式。

推荐兼容顺序：

1. 先用 orchestrator 判断是否属于方向适配分析试点问题
2. 若高置信度命中：
  - 进入新编排
3. 若低置信度或失败：
  - 回退到当前：
    - `should_force_intent_preview`
    - `preview_planning_request_from_content`
    - `preview_dialog_intent_route`

这样做的好处：

- 不会一次性打断现有稳定行为
- 可以逐类扩展试点范围
- 便于做 A/B 对照与回归

#### 8.7.8.1 当前已落地的最小实现边界

当前版本已先落两层迁移：

1. 方向语义判定层
- 由 LLM orchestrator 输出 `semantic_type + direction_slots`
- 不再在本地用字符串规则补 `direction_slots`
- 不再在分类失败后走本地方向 fallback
- 方向数量允许 `1..N`，不假设只有单方向或双方向

2. 方向分析生成层
- `interestAnalysisPopup.analysis` 改为“模型基于上下文生成”
- 输入上下文包括：
  - 学生基础信息
  - 初始画像摘要
  - 当前方案摘要
  - 各方向在方案中的承接计数
  - 各方向在候选中的机会计数与少量样本
- 输出仍保持前端既有结构：
  - `summaryTitle`
  - `currentPlanFit`
  - `currentPlanConflict`
  - `candidateOpportunity`
  - `nextActionHints`

仍然保留的硬逻辑边界：

- 方案/候选“是否与某方向相关”的底层判定，当前仍使用本地规则函数做事实抽取
- 模型负责“如何组织解释”，不直接负责状态写入
- 当分析生成失败时，可以退回模板化文案兜底，但兜底只用于异常场景，不参与正常语义路由

这一步的目标不是一次把 Explore 全部 agentize，而是先把：

- “语义理解”从规则迁到模型
- “解释组织”从模板迁到模型

后续仍可继续把：

- 方向相关事实抽取
- 多轮追问与澄清
- Explore -> Prefer / Constrain / Plan 的转移判断

进一步迁到统一的 skill 编排里。

#### 8.7.9 第一阶段回归检查

试点接入后，至少要覆盖以下检查点：

1. “体制内适不适合我”
- 预期：
  - 不直接返回方案项列表
  - 不直接返回候选列表
  - 先给解释型分析

2. “以后优先按体制内方向看”
- 预期：
  - 进入确认链路
  - 不直接落状态

3. “以后不要再给我推荐体制外的”
- 预期：
  - 进入确认链路
  - 确认后仍遵守当前候选与状态语义

4. “候选里还有没有更适合考公的”
- 预期：
  - 可以进入机会查看
  - 但不能跳过解释层直接退化成旧的生硬捞数

5. “看看现在这份方案适不适合走稳定就业”
- 预期：
  - 进入方案适配分析
  - 不直接变成执行型方案调整

#### 8.7.10 第一阶段成功标准

试点成功不等于“模型更自由”，而等于以下几点同时成立：

- “体制内 / 稳定 / 深造”类问题不再被过硬规则直接带偏
- 现有确认边界没有退化
- 前端协议没有新增不稳定分支
- 回复更像“先分析，再引导下一步”，而不是“先捞结果”
- 当 orchestrator 失败时，旧链路仍能稳定兜底

#### 8.7.11 2026-04-23 Explore 回归补充

本轮又补做了一轮真实会话回归，重点覆盖两类 Explore 问法：

1. 地域 Explore
- `北京的机会多一点吗`
- `看看北京还有没有更合适的`

2. 职业方向 Explore
- `体制内这条路适合我吗`
- `稳定就业方向值不值得重点看`

本轮结论：

- 已修复
  - 地域 Explore 不再掉回“还没准确整理出可调整意向”的兜底文本
  - 若地域偏好已存在于当前画像中，Explore 阶段不再优先返回“已经记下”的 `card`
  - 地域 Explore 当前优先返回 `interestAnalysisPopup`

- 仍遗留
  - 职业方向 Explore 仍存在少量模型绕过 tool、直接输出 plain text 长答的现象
  - 其中 `体制内这条路适合我吗` 已可进入 `interestAnalysisPopup`
  - `稳定就业方向值不值得重点看` 仍有偶发 plain text 长答

当前判断：

- 问题已不在标签体系或 planningState 数据结构本身
- 主要仍在主 agent 的 Explore tool 选择稳定性
- 后续应继续沿“模型 + skill + tool”路线收紧，而不是回退到关键词规则分流

建议的后续收敛：

1. 继续收紧主 agent 对职业方向 Explore 的 tool-first 指令
2. 补一组固定回归样本：
   - `体制内适不适合`
   - `稳定就业适不适合`
   - `读研值不值得优先考虑`
   - `北京机会多不多`
3. 若仍不稳定，再考虑在 Explore tool 输出层增加更强的结构约束，而不是在路由层追加字符串规则
