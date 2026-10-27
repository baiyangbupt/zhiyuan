# 方案质量与审查隔离：设计自审及契约反例审查

日期：2026-10-21。基线：`8fefcd7` 加工作区既有成绩修复。

对象：`../specs/2026-10-21-plan-quality-and-review-containment-design.md`。
实际样本：会话 `10042000`，version 5；调查记录见
`2026-10-21-session-10042000-plan-quality-review.md`。

**审查性质：同一执行者的自审、现有代码核对与契约/反例审查，非独立第三方审查。**
**状态：设计已收紧，待用户确认；代码问题仍未修复，本轮没有实施或部署验收。**

## 1. 结论与范围

推荐采用独立服务端暂停策略隔离旧经验审查，保留确认、事务、资格与动作自身的后置。
不建议只隐藏按钮，也不建议关闭整个 review/执行框架。A 仅隔离误导性结论，B 才补真实
资格与生成缺陷；A 不能描述成“专项问题已经修好”。新评价与自动建议恢复为 C，另确认。

本轮没有修改业务代码、真实会话、运行配置，没有重启或提交。既有成绩修复及其他用户
工作区改动均保留。以下“收紧”仅指设计约束明确，不代表运行系统已满足。

## 2. 自审发现及设计处置

代码锚点以下均相对 `zhiyuan-server/src/main/java/com/ytell/zhiyuan/`，Agent 单列完整路径。

### R1 / P0：把旧审查开关当总开关会误伤执行，且不真正停止旧结论

- 证据：`service/biz/PlanningStateService.java:1115` 的 review workflow 仍调用审查和建议；
  `service/biz/PendingPlanningCommandBizService.java:1563` 的命令路径要求 rerunReview。
  `service/biz/UnifiedPlanPostconditionValidator.java:117` 明确 safety 报告与 satisfied 分离。
- 反例：关闭 fix command/search 或直接去掉 rerunReview，既可能继续显示旧通过结果，
  又破坏冻结请求或正常 user_goal 的执行，不能实现“暂停旧审查”。
- 设计收紧：4.1–4.5 独立 policy；不改冻结载荷；adapter 返回 paused，真实硬后置保留。
  旧本省数量、固定学费等经验规则不能借机升级为所有用户动作的新硬门槛。

### R2 / P1：专项字段已存在，但新增 Python 字段并不足以支持单独确认

- 证据：`model/dto/CreateSessionReq.java:39` 已有 specialPlan；
  `service/biz/VolunteerFilterChain.java:420` 已有 false 过滤。
  `zhiyuan-agent/app/gateway/contracts.py:531` 没有此字段；
  `service/biz/ChatSessionBizService.java:429` 的空请求判定未检查它，445 的摘要也未展示。
- 反例：仅传 `specialPlan=false` 仍会在 Java preview 被当空请求；即使强行落值，
  用户也可能看不到确认的具体资格变更。
- 设计收紧：5.1–5.2 覆盖严格布尔、空请求守门、资格摘要、卡片/文字同链；已有完整成绩
  无需重输，未完整时仍遵守既有必填条件。专项分类型及清空明确不在第一批完整能力内。

### R3 / P1：增量 DTO 默认值会覆盖用户既有筛选事实

- 证据：`model/dto/CreateSessionReq.java:36` 默认 filterType=2；
  `service/biz/ChatSessionBizService.java:561` 按 DTO 序列化合并。
  离线调用现方法，只有专项 false 的增量把已有 filterType 从 3 改为 2。
- 反例：用户只是确认“无专项”，专业正向筛选却被静默改成非负向筛选。
- 设计收紧：5.2 从 HTTP 原始白名单字段导出 typed patch，不从 DTO 默认值或模型
  providedFields 推断；prepare 冻结合并结果、补丁语义与版本，执行不再次猜测增量。

### R4 / P1：只要求“保留来源”而没有可信载体，仍会把助手猜测当事实

- 证据：`zhiyuan-agent/app/gateway/service.py:1480` 的成绩预览携带模型草稿上下文；
  当前 Java CreateSessionReq 没有 userOriginalText 或 sourceVersionGuard 字段。
  `service/biz/PlanningStateService.java:10111` 的 specialLimits 只从 true 提取正向标签。
- 反例：从特殊限制列表的缺失反推 false，或接受模型自报的消息 ID，都会凭空补资格。
- 设计收紧：5.1–5.2 三态不反推；来源由网关基于持久用户消息注入 prepare 元数据，
  Java 核验会话/归属/角色，不能把文本混入成绩真相；来源不明则请重述。确认仍是最终授权。

### R5 / P1：修初始档位顺序不能变成所有操作整版重排

- 证据：`service/biz/StagedDeterministicPlanSolver.java:949` 按 stableOrder 首次出现
  的档位建桶；真实 45 组复现为 stable → protect → sprint。
  `service/biz/PlanAdmissionInterpretationService.java:365` 的旧判断没有报告此异常。
- 反例：只全局固定 tier comparator，可能让用户普通 fill/add 后手排顺序整体洗牌。
- 设计收紧：6.2 分离 initial_tier_order、preserve_current 和已有单项 move；空 ordered
  fill 首版也覆盖；6.3 单一诊断区别默认档位结构与用户授权顺序，unknown 不算正常。

### R6 / P1：整版对话重排并不是当前已有能力

- 证据：`zhiyuan-agent/app/gateway/contracts.py:307` 的 goal 列表有 move_units，
  无整版按档位重排；`model/dto/planning/OrderedPlanSortReq.java:7` 仅 sortField，
  `web/controller/PlanningFacadeController.java:295` 调用直接排序写入。
- 反例：把 facade sort 当作冻结提案使用，会绕过这次要保留的预览确认链。
- 设计收紧：6.2 不再把 explicit_reorder 列为第一批现成能力；只复用单项移动，整版
  对话动作另确认 schema/冻结顺序/后置。不承诺当前不支持的一键重新生成或回滚。

### R7 / P1：暂停检查放错顺序会推翻成功回执，或把旧卡留在 applying

- 证据：`service/biz/PendingPlanningCommandBizService.java:93` 先核对 pending/
  frozen、再重放台账；164 的 isAuditableReviewCommand 仍依赖旧 fix flag；178 在
  回滚完成后写独立失败审计。
- 反例：在 replay 前检查暂停，已成功操作会显示未生效；在旧 flags 关闭时依赖该判断
  做失败审计，暂停拒绝可能无台账且卡不能收敛。伪装 proposalSource 还可能绕路。
- 设计收紧：4.4 绑定服务端来源，完整鉴权/内容绑定后优先重放；新执行才查 policy。
  暂停拒绝审计不依赖旧 flag，保留 rollback 后失败记录，不造第二份幂等真相。

### R8 / P1：全方案资格硬门若不分动作，会阻止修复已存在的错误

- 证据：当前成绩更新先更新事实，再把依赖置 stale；
  `service/biz/PlanningStateService.java:634` 并不自动重写 ordered items。
- 反例：原方案有两个专项冲突，确认无专项被旧项阻止；或只移除第一个时，因另一个
  仍冲突而回滚，导致用户永远清不掉错误项。候选先过滤还可能让删除目标无法解析。
- 设计收紧：5.3 按动作分层。资格事实可更新并标冲突；纯删除允许分次收敛，不要求
  满容量，被删项不要求仍可选。新增/补齐/替换最终不得含已知冲突，pinned 不能资格豁免。

### R9 / P1：paused 空摘要会被现有消费者误判为通过

- 证据：`service/biz/PlanningWorkflowStatusBuilder.java:125` 将 null summary 当 0 风险；
  `service/biz/ConversationSnapshotService.java:139` 注入 reviewSummary 等背书信息。
  Web WorkspacePanel 仍消费 checks 与 summary。
- 反例：后端返回空 findings，但旧前端/快照仍显示“暂无风险”，等价于伪造通过。
- 设计收紧：4.3 availability 优先，公开响应副本不污染内部 domain；全消费者齐套后
  才启 paused，并停止旧 summary/hardFeasible 背书及“请重新审查”的循环建议。

### R10 / P1：只改排序/资格实现而不升级冻结版本，会偷换旧确认语义

- 证据：`service/biz/StagedDeterministicPlanSolver.java:53` 使用固定 solverVersion；
  真实命令依赖 pending 摘要和冻结内容绑定，不允许确认后实时重规划。
- 反例：升级前准备、升级后执行，如果仍接受无资格版本/旧排序策略的冻结结果，
  可能带回专项或错误顺序；如果换算法实时重算，则与用户看见的内容不一致。
- 设计收紧：6.2 solver/排序/资格/候选要求来源版本进冻结与 digest；不兼容未执行卡
  要求新预览，已成功命令仍重放原回执。恢复 active 也要求新评价，不信旧缓存/旧建议。

### R11 / P1：匹配启发分不等于用户意向，生成成功不等于方案适配

- 证据：样本 positive/mustInclude/preferMajors 等已确认来源为空，但现方法报告
  4 组“非意向托底”；`service/biz/PlanningStateService.java:12248` 使用启发性适配信息。
  电气方向为助手提出，用户泛称可以出一版，不能追认为主线授权。
- 反例：以 preferred/intentScore 替代用户偏好，或未经同意用“少选医学”作为新优化目标。
- 设计收紧：6.1/6.4 无意向时定位探索草案，不报偏离意向，不偷调权；成绩/资格/方向/
  顺序各自展示授权范围；回执把执行成功与待核验质量分开。

### R12 / P1：证据冲突不能降级为普通 unknown 后绕过明确资格否认

- 证据：原专项风险判断遗漏名称信息，设计因而要补名称证据；但正式标签和名称可能
  不一致，组级要求和个别专业要求也不能互相替代。
- 反例：用户明确无专项，候选名称写地方专项但某标签写普通；若统一降级 unknown，
  再按“unknown 可探索”放行，会重新带回已经识别出风险的条目。
- 设计收紧：5.3 单列 requirement_evidence_conflict 并保留证据；全否时不能靠降级
  放行。组级要求向专业继承，逐个核对已选项。B16 覆盖该反例；这属于设计推演，未声称
  实际会话已出现正式字段与名称矛盾。

## 3. 证据与验证边界

临时私有诊断目录 `/tmp/zhiyuan-session-10042000-review/`，不加入版本库。
直接调用现有构建产物记录如下，不是新算法的模拟结果：

| 观察 | 原实现结果 |
| --- | --- |
| 45 组选中结果经原排序器 | stable → protect → sprint |
| 原解读方法是否识别该逆序 | false |
| 地方专项名称但无专项标签的旧风险判断 | false |
| 无用户正向专业意向时旧托底检查 | 不通过，影响 4 组 |
| 旧过滤器能否识别本例的明确专项排除 | true |
| 仅资格增量合并后的 filterType | 原 3 变 2 |

Python 原 ScoreUpdateRequest 对 specialPlan 返回 extra_forbidden；Java 空请求守门与
摘要缺项为源码核对结论。没有把“源码可推导”冒称为浏览器端到端已执行的结果。

本轮检查：3 份文档的空白/占位符检查通过，5 个本地文档引用存在；A1–A8、B1–B16 共
24 条验收编号及 R1–R12 审查编号无缺失/重复，`git diff --check` 通过。另从 Agent 目录
重新调用实际 ScoreUpdateRequest，复现 specialPlan 的 extra_forbidden，未触碰业务数据。
本轮没有运行修复后的业务回归；前轮成绩修复的测试数字不作为本设计已落地的证据。

## 4. 待确认及后续门槛

以下为产品选择，不是已经修复或可以直接部署的结论：

1. A 暂停旧经验审查，但保留真实硬校验；默认 active，仅经确认的受影响环境启 paused。
2. B 第一批完整支持明确“无任何专项”；分类型资格及清空另切片，未支持必须说清楚。
3. 无主线允许不限专业探索草案，不擅自补电气/多样性硬约束。
4. 新首版冲→稳→保；存量不自动改，第一批仅复用单项 move，不冒充整版对话重排。
5. A/B 分批实现验收；C 新评价另确认；真实会话不自动迁移、真实部署另行授权。

用户确认上述边界后再形成实施计划，并按矩阵补先红后绿测试、跨端审查和隔离 fixture
写链验收。独立第三方审查本轮未进行，后续如安排应明确授权并单独记录结论。
