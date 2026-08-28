# 基于 Codex App Server 的志愿填报核心对话引擎设计

- 日期：2026-08-28
- 状态：已完成分节讨论，待书面审阅
- 适用范围：志愿填报核心对话、数据查询、候选推荐、方案构建和最终确认
- 不包含：本设计阶段不修改生产代码，不替换现有最终写入链路

## 1. 背景

现有志愿填报应用已经具备院校库、专业库、历年招生数据、当年真实招生信息、用户画像、zhiyuan-rank、方案状态管理和确认执行能力。当前主要问题不是缺少数据，而是对话 Harness、业务工具和事实状态混合在一起：

- 模型可见工具过多，工具选择和调用次数不稳定。
- 自由文本实体抽取存在歧义、错绑和错误覆盖。
- 推荐逻辑混合熵权、静态数据和手工倍率，难以解释、校准和审计。
- 对话历史、用户画像和业务事实没有清晰分层，导致上下文膨胀和旧状态污染。
- 对话能够回答问题，但缺少真实规划师主动梳理、促进取舍和完成最终方案的能力。
- app/service.py、app/zhiyuan_agent/tools.py 和 PlanningStateService.java 等文件重新承担过多职责。

本设计采用 Codex App Server 作为可替换的通用对话 Harness，同时保留 Java、数据库、录取率引擎、Rank、Solver 和现有 CAS 确认链路作为业务事实与执行内核。

## 2. 设计目标

### 2.1 核心目标

1. 关键招生事实准确、可追溯、可解释。
2. 模型不能绕过权限、状态版本或用户确认。
3. 减少错误、重复和无意义的工具调用。
4. 用规划师工作流帮助用户逐步形成可靠选择。
5. 充分利用 Codex Thread、Turn、streaming、compaction、Skills 和 outputSchema。
6. 保留现有成熟业务能力，通过渐进迁移而不是一次性重写完成升级。
7. App Server、模型或 Harness 可以替换，不把业务状态锁定在 Codex Thread 中。

### 2.2 非目标

- 不让 App Server 成为成绩、画像、候选或方案的权威状态源。
- 不让模型直接查询数据库、执行 SQL 或调用代码场景工具。
- 不让 Skill 承担实时事实、权限判断或事务执行。
- 不在第一阶段重写现有录取率引擎和最终 CAS 写链路。
- 不使用端到端 LLM 直接生成最终志愿表。

## 3. 总体架构

推荐拓扑：

    前端
      → Conversation Gateway
      → Codex App Server
      → Zhiyuan Domain MCP
      → Java 后端 / 数据库 / 录取率引擎 / Rank / Solver

职责边界：

| 组件 | 职责 |
|---|---|
| 前端 | 对话、结构化卡片、规划档案、候选和方案工作台 |
| Conversation Gateway | 鉴权、会话映射、Turn 编排、事件转换、幂等和恢复 |
| Codex App Server | Thread/Turn、模型交互、流式事件、Skills、compaction、steer 和 interrupt |
| Domain MCP | 唯一业务工具平面、可信会话绑定、能力授权和统一工具协议 |
| Java | 权威状态、实体解析、证据、规则、事务、版本和审计 |
| 录取率引擎 | 按招生单元计算基于成绩和位次的录取率 |
| Rank | 候选偏好匹配、比较和解释维度 |
| Solver | 组合方案、顺序、风险结构和省份规则优化 |
| Plan Review Policy | 冲稳保框架、梯度、有效保底和最终审查 |

前端不得直连 App Server。所有 App Server 协议必须在 Gateway 内转换成稳定的 Zhiyuan Conversation Protocol。

## 4. App Server 的采用边界

### 4.1 复用能力

- Thread 和 Turn 生命周期。
- 流式 item 事件。
- steer 和 interrupt。
- 对话 history 与自动 compaction。
- Skills 的渐进披露。
- 工具搜索和延迟加载能力。
- approvals 和 hooks。
- baseInstructions 与 developerInstructions。
- 每轮 outputSchema。

### 4.2 生产约束

- 固定 Codex 版本或源码 commit，不能无门槛跟随升级。
- 优先以 sidecar、stdio 或 Unix socket 方式完成 PoC，不让前端或公网直接访问 App Server。
- thread/start.dynamicTools 仍视为实验能力，不作为核心业务工具入口。
- 核心业务工具通过固定 Domain MCP 暴露。
- 默认关闭 shell、文件修改、Git、浏览器、多 Agent 等代码场景能力。
- Codex Thread 只负责对话连续性，不能成为业务恢复的唯一依据。

### 4.3 隔离接口

Gateway 内定义 HarnessClient：

    createThread()
    resumeThread()
    injectState()
    startTurn()
    steerTurn()
    interruptTurn()
    rebuildThread()

CodexAppServerHarness 是第一个实现。业务系统不直接依赖完整 App Server 事件和字段。

## 5. 单轮数据流

### 5.1 接收输入

Gateway：

- 校验登录用户、租户和会话权限。
- 维护 conversationId 与 threadId 的映射。
- 生成 turnId，处理断线重试和重复提交。
- 先持久化用户原始消息。
- 不接受前端或模型提供的可信 userId、sessionId 或 threadId。

### 5.2 生成 Turn Snapshot

Java 每轮生成版本化、紧凑、按任务投影的 Snapshot，包含：

- 省份、年份、成绩、位次和选科。
- 已确认硬约束和相关偏好。
- 当前规划阶段。
- 方案、画像和状态版本。
- 当前待处理 Proposal。
- 当前阶段允许的能力。
- 缺失事实和开放问题。

Snapshot 不重复携带完整画像、完整方案表或大量历史查询结果。

### 5.3 注入状态

- 状态未变化时不重复注入。
- 状态变化时注入结构化 StatePatch。
- Thread 重建或版本不连续时注入完整紧凑 Snapshot。
- App Server compaction 后，在下一轮重新确保最新 Snapshot 已注入。

### 5.4 执行 Turn

每轮使用：

- 短小稳定的常驻指令。
- 当前主 Skill。
- 当前阶段允许的 Domain MCP 能力。
- 与场景匹配的 outputSchema。

### 5.5 调用工具

Domain MCP 基于可信 Thread/session binding 读取服务器端上下文，不信任模型参数中的身份信息。工具返回结构化数据、Evidence、限制和状态版本。

### 5.6 写操作

写操作遵循：

    preview → pending → confirm → apply → postcondition

模型只能创建 Proposal。用户确认后，Gateway 直接调用 Java；Java 重新读取权威版本、执行 CAS、验证后置条件并记录审计。

### 5.7 流式输出

Gateway 将 App Server item 转换为：

- assistant.delta
- assistant.completed
- planning.status
- evidence.updated
- recommendation.card
- action.proposed
- action.applied
- recoverable.error

内部推理、原始工具参数和鉴权信息不发送给前端。

## 6. 可信会话绑定

这是 App Server 集成的首要 Go/No-Go 条件。

必须验证 App Server 是否能够在普通 MCP tool call 的非模型元数据中稳定传递可信 threadId 或等价调用上下文。

若原生能力满足：

- Gateway 建立 threadId 与业务会话的服务器端绑定。
- Domain MCP 根据 threadId 查询用户、会话、状态版本和授权。

若原生能力不满足：

- 对 App Server MCP Client 或本地 MCP Proxy 做极小适配。
- 在协议层注入签名的短期上下文。
- 签名内容不进入模型可见参数。
- Domain MCP 校验签名、有效期、线程、用户和能力。

不得用“让模型传入真实 sessionId/userId”作为生产降级方案。

## 7. Skills 分层

### 7.1 常驻规则

常驻指令只包含不可违反的原则：

- 数据库事实优先于模型记忆。
- 不猜测成绩、位次、实体和招生结论。
- 歧义实体必须澄清。
- 推荐必须显示依据、版本和限制。
- 写入必须使用 Proposal。
- 旧对话状态不能覆盖权威最新状态。
- 不调用非业务代码工具。

### 7.2 主 Skills

第一期只建设六个主 Skill：

| Skill | 负责场景 |
|---|---|
| profile-discovery | 梳理成绩、选科、地域、专业、家庭约束和风险偏好 |
| school-major-exploration | 院校、专业、培养路径和取舍探索 |
| admission-fact-analysis | 招生计划、选科要求和历年录取分析 |
| candidate-recommendation | 生成候选招生单元并解释依据 |
| plan-construction | 从候选集合构建志愿方案 |
| plan-final-review | 查漏补缺、风险审查和最终确认 |

每个 Skill 必须包含：

- 适用和不适用条件。
- 前置信息。
- 标准步骤。
- 允许工具类别。
- 证据要求。
- 澄清规则。
- 调用预算和停止条件。
- 输出结构。
- 失败和降级策略。

每轮使用一个主 Skill，加常驻规则和必要的按需参考资料。Java 给出 planningStage、recommendedSkill 和 allowedCapabilities，MCP 在服务器端强制能力边界。

### 7.3 插件组织

    zhiyuan-codex-plugin/
    ├── .codex-plugin/plugin.json
    ├── skills/
    │   ├── profile-discovery/
    │   ├── school-major-exploration/
    │   ├── admission-fact-analysis/
    │   ├── candidate-recommendation/
    │   ├── plan-construction/
    │   └── plan-final-review/
    ├── references/
    │   ├── evidence-policy.md
    │   ├── planner-questioning-guide.md
    │   └── recommendation-explanation-guide.md
    └── evals/
        ├── skill-routing/
        ├── tool-selection/
        └── entity-resolution/

## 8. Domain MCP 工具目录

第一期工具控制在约 15 个，以用户目标为粒度、读写分离、批量优先。

### 8.1 实体

- entity.resolve

### 8.2 院校和专业库

- catalog.search_schools
- catalog.get_school
- catalog.search_majors
- catalog.get_major

### 8.3 招生事实

- admission.get_current_plan
- admission.get_history
- admission.check_eligibility

### 8.4 推荐和方案

- recommendation.generate_candidates
- recommendation.compare_candidates
- plan.generate_draft
- plan.validate

### 8.5 受控写操作

- profile.propose_patch
- plan.propose_changes
- plan.propose_finalize

apply 不暴露给模型。

### 8.6 统一返回协议

工具使用统一信封：

    status
    data
    resolvedEntities
    evidence
    limitations
    stateVersion

固定错误状态：

- needs_clarification
- not_found
- stale_state
- capability_denied
- constraint_violation
- temporarily_unavailable

### 8.7 调用治理

- 相同参数自动去重。
- 列表查询批量优先，避免 N+1。
- 每个 Skill 有调用预算。
- 同一失败调用最多重试一次，且参数必须有效变化。
- 写 Proposal 每轮最多创建一次。
- 状态过期后停止推理并刷新 Snapshot。
- 工具元数据维护正负 golden prompts。

## 9. 实体与数据可信度

### 9.1 标准实体

必须区分：

- 院校。
- 校区。
- 招生单位。
- 专业。
- 专业类。
- 专业组。
- 具体招生计划项。
- 批次和招生类别。

自由文本只作为解析输入。推荐、方案和审计必须使用标准实体 ID，尤其是 admissionUnitId 或 admissionProgramId。

### 9.2 解析状态

- resolved：唯一可信匹配。
- ambiguous：返回候选并由用户选择。
- not_found：明确缺失，不构造虚假实体。

下游工具优先只接受标准 ID。模糊匹配、别名和上下文约束由 Java 实体服务完成。

### 9.3 Evidence

MCP 为事实生成服务器端 evidenceId，记录：

- 证据类型和来源等级。
- 数据集与记录 ID。
- 查询指纹。
- 数据版本和发布时间。
- 适用省份、年份、类别和选科模式。
- 数据限制和新鲜度。

模型只能引用已有 evidenceId。Gateway 校验 Evidence 是否属于当前 Turn 和会话。

### 9.4 历史可比性

跨年分析至少检查省份、高考模式、批次、招生类别、实体口径、计划人数、位次、特殊招生和专业拆分合并。

后端输出 comparable、adjusted 或 not_comparable，并说明原因。模型不能自行拼接不可比数据。

### 9.5 数据缺失

严格区分零值、不招生、未发布、未收录、不适用和仅有上级口径数据。缺失时显示 coverage、missingFields、fallback 和 limitations，不用模型记忆补齐。

## 10. 回答与 Artifact 协议

重要咨询、推荐和方案审查使用严格 outputSchema：

    responseType
    message
    artifactRefs
    evidenceRefs
    uncertainties
    clarification
    proposalRef

关键数据卡片由 MCP/Java 生成的 Artifact 驱动，模型不能重新拼装关键数字。模型主要负责：

- 说明结论。
- 解释依据和取舍。
- 指出限制。
- 推进下一步。

Gateway 在输出前校验：

- Evidence 引用存在并属于当前 Turn。
- Artifact 和 Proposal 属于当前用户。
- 状态版本仍然有效。
- 关键数字来自后端 Artifact。
- 重大限制已经展示。
- 推荐包含资格校验。

## 11. 上下文与长期记忆

### 11.1 五层上下文

| 层级 | 内容 |
|---|---|
| L0 | 常驻规则 |
| L1 | 当前 Turn Snapshot |
| L2 | 当前任务 Working Set |
| L3 | Codex Thread 对话历史 |
| L4 | Java 长期画像和决策记录 |
| L5 | 数据库事实和 Evidence |

Thread 记住对话；Working Set 记住当前思路；Java 记住已确认事实；Evidence Ledger 记住结论依据。

### 11.2 画像状态

画像记录区分：

- observed
- tentative
- proposed
- confirmed
- superseded

记录 field、value、sourceType、sourceId、sourceQuote、confidence、effectiveYear 和 updatedAt。模型推断不得直接成为 confirmed。

### 11.3 信息策略

- 权威事实优先使用系统数据，冲突时不静默覆盖。
- 硬约束必须明确确认。
- 软偏好可以暂存，在正式推荐前集中确认。
- 模型推断只进入 Working Set，后续通过问题验证。

不再设置通用的“回答后再让另一个模型抽取并直接写画像”的链路。专有实体由 entity.resolve 验证；画像写入使用 profile.propose_patch。

### 11.4 三本规划账本

- Decision Ledger：选择、排除、原因和后续变化。
- Evidence Ledger：数据、版本和依赖结论。
- Open Loop Ledger：待确认偏好、缺失信息和下一步问题。

### 11.5 恢复

Thread 丢失时：

1. 创建新 Thread。
2. 注入常驻规则和最新 Snapshot。
3. 注入结构化对话摘要。
4. 注入 Decision/Open Loop 摘要。
5. 恢复最近少量可见消息。
6. 继续当前规划阶段。

## 12. 推荐、录取率、Rank 与 Solver

### 12.1 独立维度

候选评价保持四个独立维度：

- Eligibility：是否有资格填报。
- Admission Probability：招生单元录取率和冲稳保。
- Preference Fit：是否符合用户偏好。
- Data Confidence：数据和计算结论是否充分。

不再把这些维度混成一个含义不明的总分。

### 12.2 现有录取率引擎

继续使用当前系统针对招生单元、结合成绩和位次计算的录取率，作为权威风险信号：

| 录取率 | 风险 | 展示 |
|---|---|---|
| [0%, 50%) | 风险较高 | 冲 |
| [50%, 70%) | 风险适中 | 稳 |
| [70%, 99%] | 风险较低 | 保 |

即使为 99%，也不表述为保证录取。

录取率：

- 由现有后端引擎计算。
- 模型只能读取和解释。
- Rank 不得通过人工倍率修改。
- Solver 可以作为风险维度使用，但不重新计算。
- 保存算法、数据、参数和 Snapshot 版本。

### 12.3 候选推荐

推荐流水线：

    权威 Snapshot
      → 硬约束过滤
      → 候选召回
      → 读取招生单元录取率
      → 偏好匹配
      → 候选解释
      → Solver 组合
      → Plan Review Policy

候选只能来自当年真实招生数据。硬约束必须直接排除，不能通过降低分数软处理。

### 12.4 偏好匹配

用户权重来源于明确排序、规划师式取舍问题、确认选择和可解释默认先验。熵权不再作为用户价值权重。

输出专业、地域、职业、院校类型、成本等独立匹配维度和正负因素。缺失数据降低可信度，不能简单计零分或满分。

### 12.5 Solver

Solver 负责整张方案，而不是逐项排名：

- 志愿数量和省份规则。
- 冲稳保结构。
- 录取率梯度。
- 专业、地域和院校覆盖。
- 风险相关性。
- 用户锁定项和排除项。
- 最终顺序。
- 方案空档和断层。

省份与年份规则通过 ProvincePolicy 版本化。

## 13. Plan Review Policy

老版本审查规则需要保留并从 Prompt、条件分支和大文件中抽取为独立规则包：

- 冲稳保结构规则。
- 梯度保护规则。
- 有效保底规则。
- 顺序和省份规则。
- 用户接受度规则。
- 数据可信度规则。
- 最终兜底规则。

### 13.1 框架性分层

检查各风险层数量、比例、集中度和策略匹配。不同省份、年份和进取/均衡/稳健策略使用不同版本化配置。

### 13.2 梯度保护

不仅检查冲稳保标签，还检查具体录取率：

- 相邻志愿风险断层。
- 同层过度集中。
- 冲到稳、稳到保的连续过渡。
- 后半段风险反向升高。
- 表面分散但实际高度相关的招生单元。

### 13.3 有效保底

区分：

- 概率保底：录取率达到 70% 至 99%。
- 有效保底：概率、资格、当年招生、数据可信度和用户接受度全部通过。

有效保底还检查学费、地域、专业、办学类型、计划异常、数量和相关性。

### 13.4 共用规则

Solver 在生成时使用 Plan Review Policy 作为约束和优化目标；Plan Validator 在生成后再次使用同一规则包审查，避免生成器和审查器互相矛盾。

每条规则返回 ruleId、ruleVersion、severity、status、affectedPositions、evidence 和 repairOptions。模型只能解释和引导修复，不能自行宣布方案安全。

## 14. 规划师式对话

### 14.1 状态机

    goal_framing
      → profile_discovery
      → preference_tradeoff
      → candidate_exploration
      → candidate_shortlist
      → plan_construction
      → plan_final_review
      → finalized

状态由 Java 保存，允许用户随时提问和回退。

### 14.2 每轮行为

每轮：

1. 先回答当前问题。
2. 说明其对方案的影响。
3. 推进一个最有价值的下一步。

追问优先级：

    阻塞资格判断
      > 改变大批候选
      > 改变冲稳保结构
      > 区分用户偏好
      > 一般补充信息

每轮最多一个主要问题，并解释提问原因。用户可以跳过软偏好问题。

### 14.3 真实取舍

优先通过真实候选对比帮助用户形成偏好，而不是只问抽象问卷。记录用户确认的 Tradeoff，供 Rank 和 Solver 使用。

## 15. 前端规划工作台

前端分为：

| 区域 | 作用 |
|---|---|
| 对话区 | 解释、澄清和确认 |
| 规划工作区 | 候选、比较、方案和审查 |
| 规划档案区 | 成绩、选科、偏好、约束和进度 |

结构化组件包括：

- entity.disambiguation
- profile.confirmation
- preference.tradeoff
- evidence.card
- candidate.list
- candidate.comparison
- plan.draft
- plan.diff
- review.finding
- action.confirmation

候选支持收藏、排除、锁定、比较、查看依据、请求替换、调整策略和标记接受程度。

前端显示业务化进度，不暴露工具名称和内部 Harness 事件。

## 16. 最终方案链路

    冻结 Snapshot 和数据版本
      → Solver 生成最终草案
      → Plan Review Policy 全量审查
      → 展示并处理审查问题
      → 生成 Finalize Proposal
      → 用户确认
      → Java CAS 写入
      → Postcondition
      → 最终 Artifact

最终审查至少覆盖：

- 志愿数量和省份规则。
- 招生单元真实性和资格。
- 冲稳保结构和梯度。
- 有效保底数量。
- 用户是否真正接受保底项。
- 调剂、退档、学费、校区和办学类型。
- 锁定项。
- 数据新鲜度。
- 未确认重大风险。

最终 Artifact 保存方案、录取率、风险结构、锁定项、有效保底、主要依据、遗留风险及所有数据和算法版本。

## 17. 评测体系

### 17.1 三层评测

- Turn 级：Skill、工具、实体、Evidence、澄清、重复调用和 Proposal 安全。
- Dialog 级：重复提问、偏好变化、阶段推进、打断、compaction 和恢复。
- Plan 级：招生单元真实性、资格、录取率、冲稳保、梯度、有效保底、锁定项和规则一致性。

优先级：

    确定性断言
      > 数据库和规则回放
      > 规划师评审
      > LLM Judge

LLM Judge 只用于表达、自然度和规划师感，不判断招生事实或方案合规。

### 17.2 数据集

- Golden Cases。
- 脱敏 Production Replay。
- Adversarial Cases。
- 真实 Planner Service Cases。

### 17.3 硬门槛

以下必须为零：

- 未授权写操作。
- 硬约束违反。
- 虚假招生单元进入方案。
- 关键事实无 Evidence。
- Proposal 跨用户或跨会话执行。
- 过期版本写入成功。
- 冲稳保分类与录取率不一致。
- 高严重度审查问题未展示。

持续优化工具误调用率、重复调用率、实体准确率、对话轮数、规划师保留率、延迟、Token 和成本。

## 18. 可观测性

全链路关联：

- conversationId
- turnId
- threadId
- snapshotVersion
- skillName
- toolCallId
- evidenceId
- candidateSetId
- artifactId
- proposalId

系统应能解释 Skill 选择、工具调用、状态版本、证据依赖、Proposal 失败、compaction 影响和各组件耗时。不记录隐藏推理，只记录结构化业务决策。

## 19. App Server PoC 验收

必须验证：

1. Thread/Turn 多轮和恢复。
2. 流式事件顺序和断线。
3. Skill 加载和版本切换。
4. 固定 Domain MCP。
5. outputSchema。
6. steer、interrupt 和取消一致性。
7. compaction 后质量。
8. Thread 重建。
9. 并发隔离与资源。
10. 协议升级兼容。
11. 可信 Thread/MCP binding。

可信 binding 无法满足且无法通过极小适配解决时，App Server 不进入生产主链路。

## 20. Shadow 与迁移

### 20.1 迁移原则

采用 Strangler 方式，保留现有 zhiyuan-agent 对外协议和旧引擎回退能力。第一阶段在其中增加 Conversation Gateway v5 和 HarnessClient，逐步把状态、工具、推荐和写执行迁出 Python 单体。

### 20.2 灰度阶段

1. 固定数据快照离线回放。
2. 内部规划师试用。
3. 生产只读 Shadow。
4. 学校、专业、招生咨询 Canary。
5. 候选推荐 Canary。
6. 方案草案和审查。
7. Proposal 写链路。
8. 最终方案链路。

### 20.3 实施顺序

1. 冻结现状并建立回放基线。
2. 定义 Gateway、Snapshot、Artifact 和 Evidence 协议。
3. 完成 App Server Go/No-Go PoC。
4. 完成可信 Thread/MCP binding。
5. 建设只读 Domain MCP。
6. 建设六个基础 Skills。
7. 迁移实体解析和数据咨询。
8. 接入现有招生单元录取率引擎。
9. 拆分 Rank 的偏好匹配。
10. 提取 Plan Review Policy。
11. 引入方案 Solver。
12. 接入 Proposal 和最终确认。
13. Shadow、Canary 和逐场景切流。
14. 收缩旧 Python 单体和旧工具集合。

### 20.4 第一期里程碑

第一期完成：

- App Server 稳定承载多轮对话。
- 可信 binding 通过。
- 六个 Skills 实际加载。
- 只读 Domain MCP 上线。
- 学校、专业和招生事实咨询迁移。
- 实体消歧和 Evidence 协议落地。
- Production Shadow 持续运行。
- 现有最终写入链路保持不动。

之后再迁移推荐、Solver、审查和最终方案。

## 21. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| App Server 协议或实现仍不稳定 | 固定版本、HarnessClient 隔离、兼容测试和旧引擎回退 |
| MCP 无可信 Thread 上下文 | 作为 PoC 阻塞项，必要时做极小协议适配 |
| Skill 仍无法约束工具 | MCP allowedCapabilities 和 Java 授权强制兜底 |
| 模型生成错误数字 | 关键数字只由 Artifact 渲染，Evidence 校验 |
| 新旧状态冲突 | Snapshot 版本、CAS、StatePatch 和 fail closed |
| 上下文继续膨胀 | Skill 投影、紧凑 Snapshot、Evidence 引用和 compaction |
| 推荐难以解释 | 风险、偏好、资格、数据可信度拆分 |
| Solver 与审查矛盾 | 共用 Plan Review Policy |
| 一次性迁移风险过高 | Shadow、Canary、逐场景切流和旧链路回退 |

## 22. 已确认的最终决策

1. 直接集成 Codex App Server 优于从零实现通用 Agent Harness，但必须置于 Gateway 之后并保持可替换。
2. Domain MCP 是唯一业务工具平面。
3. Java、数据库、录取率引擎和 Solver 是事实与决策内核。
4. Skill 管工作流，MCP 管能力边界，Java 管事实和执行。
5. Codex Thread 不保存权威业务状态。
6. 关键数据通过 Evidence 和 Artifact 向用户展示。
7. 继续使用现有招生单元录取率及冲稳保阈值。
8. 老版本框架分层、梯度保护和保底规则整合为 Plan Review Policy。
9. 前端只依赖稳定 Gateway 协议。
10. 采用 PoC、Shadow、Canary 和渐进迁移，不进行一次性替换。

## 23. 进入实施计划前的检查点

本设计进入实施计划前，需要书面确认：

- App Server PoC 的部署形态和固定版本。
- 可信 Thread/MCP binding 的验证结果。
- 第一期迁移场景和可接受回退方式。
- 现有录取率引擎的正式接口、边界值和版本字段。
- 老版本 Plan Review 规则清单和业务负责人。
- Gateway v5 是先落在现有 zhiyuan-agent 内，还是独立部署。

这些检查点不改变总体架构，但会决定实施任务的拆分和先后顺序。
