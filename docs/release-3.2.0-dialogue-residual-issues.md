# Release 3.2.0 Dialogue Residual Issues

本文记录 3.2.0 当前对话框架已经收口后仍需要持续验证、确认或结构化升级的问题。它不替代 `release-3.2.0-current-framework-review.md`，定位是“遗留问题台账”：每个问题必须说明当前框架是否支持、风险在哪里、后续用什么验证闭环。

当前原则：

- 不把生产 case 修成 service 字符串分支。能结构化的进入 resolver / profile node / TurnDecision / action DSL / ProposalCompiler。
- 如果 schema 或下游 contract 不能表达真实诉求，记录为框架缺口，不用运行时文本补桥。
- 效果优先级高于性能。30-40s 的长尾可以接受，但不能牺牲语义正确性、pending/card 一致性和回复事实边界。
- 生产回捞 case 用来发现真实问题；修复完成后要沉淀到 unit、model-node benchmark 或 dialog regression，不只停留在临时日志。

## 1. 当前验证基线

截至 2026-06-28，本轮已确认的基础状态：

- 单元和离线基准：相关单测与 `test_model_node_benchmark.py` 通过，离线 model-node benchmark 为 50/50。
- 已做 targeted 生产回捞验证：
  - `320-prod-supplement-negative-major-correction`：2/2 通过，`不要排除经济学类` 没有继续输出“排除专业类：经济学类”。
  - `320-prod-quality-tuition-and-school-nature`：3/3 通过，`公办/民办` 没有再被当作专业。
- 完整生产资产并行回归已跑通：`/tmp/zhiyuan-agent-prod-assets-18337-r1` 为 18/18 case 通过、37 step、0 content failure。耗时 median 16.4s、p95 31.4s、max 34.3s。
- R22 修复后生产资产三组已在最新 `18339` 重跑：`/tmp/zhiyuan-agent-prod-assets-18339-r2` 为 18/18 case、37/37 step 全通过；耗时 median 17.4s、p95 38.3s、max 38.9s。
- 最新隔离 agent `18342` + backend `18290` + rank `18292` 已重跑生产回捞资产三组：`/tmp/zhiyuan-agent-prod-assets-18342-r1` 为 18/18 case、37/37 step 全通过。质量上未观察到严重语义分错；长尾仍存在，慢例包括命名学校增补专业组 60.2s、地域确认后候选查询 48.2s、公办诉求 46.2s、海南招生追问 41.3s。
- 最新隔离 agent `18344` + backend `18290` + rank `18292` 已完成高收费定点回归：`/tmp/zhiyuan-agent-high-tuition-18344-r6.metrics.json` 为 3/3 step 通过。第三步 `把高收费的换成正常收费的看看` 已进入 `direct_atomic_plan_action -> replace_units -> no_change`，不再降级成泛 `review_plan`，也不再回复“共 0 个专业组还建议替换”。
- 最新隔离 agent `18344` 已重跑生产回捞资产三组：`/tmp/zhiyuan-agent-prod-assets-18344-r3` 为 18/18 case 全通过。质量上未观察到严重语义分错；有 2 条 latency warning：地域确认后候选查询 53.3s、海南招生职业院校查询 56.3s。
- 最新隔离 agent `18344` 已按并发 8 跑 13 个 case 文件的小全量回归：`/tmp/zhiyuan-agent-full-regression-18344-p8-r1` 为 141 case，107 通过、34 失败。本轮没有环境/连接失败，失败主要是内容断言和 followup 协议，report 分桶为 `reply_focus_gap=24`、`assertion_noise_thinking=8`、`selector_gap_no_executable_preview=3`。生产资产三组在该轮仍 18/18 通过，主要问题转向 selector 可执行预览、旧断言噪声和回复聚焦。
- 最新隔离 agent `18346` 已重跑生产回捞资产三组：`/tmp/zhiyuan-agent-prod-assets-18346-r5` 为 18/18 case、37/37 step 全通过，0 failure、0 warning。耗时 median 18.2s、p95 34.6s、max 35.4s；慢例包括地域确认后江西候选查询 35.4s、命名学校增删专业组 34.6s、海南招生来源追问 29.5s。质量上未观察到严重语义分错、错误 pending/card 或回复事实边界回退。`/tmp/zhiyuan-agent-prod-assets-18346-r4` 是 sandbox localhost 权限导致的 `Operation not permitted` 环境失败目录，不作为质量基线。
- 最新隔离 agent `18346` 已按并发 8 跑完整 29 个 case 文件全回归：`/tmp/zhiyuan-agent-full-regression-18346-p8-r1` 为 423 case，370 通过、53 失败；1074 step 中 1011 通过、63 失败。失败原因均为 `content`，未观察到 request/environment/tool 失败。生产资产在本轮全量中 17/18 case、36/37 step 通过，唯一失败是 `320-prod-quality-major-negative-and-positive-mix` 第二步 `补充进入机械类...专业和学校` 被 full-agent 工具选择转成 `add_units` 方案增补预览，属于真实语义边界问题。性能为 median 17.3s、p95 42.3s、p99 59.1s、max 109.3s；report 为 `/tmp/zhiyuan-agent-full-regression-18346-p8-r1/report-summary.json`。
- 最新隔离 agent `18342` 已跑并发 8 全量回归：`/tmp/zhiyuan-agent-full-regression-18342-p8-r1` 为 414 case，306 通过、108 失败；1007 step 中 855 通过、152 失败。该结果不能直接等同于质量回退：其中 29 个 case 是 backend `18290` 一度 connection refused 的环境失败，20 个 case 是 WebSocket keepalive/request 长尾失败，生产资产在本轮全量里的失败均为环境 setup 失败，不能推翻单独生产资产 18/18 的质量基线。
- 完整历史全量回归已用并发 8 跑完：`/tmp/zhiyuan-agent-full-regression-18337-p8-r1` 为 423 case，367 通过、56 失败；1074 step 中 1007 通过、67 失败。该结果不能直接等同于线上质量通过率，因为大量旧 fixture 依赖已有正式方案，而当前固定测试环境对应 session 多数没有正式方案。
- 最新代码隔离 agent `18339` 已重跑同口径并发 8 全回归：`/tmp/zhiyuan-agent-full-regression-18339-p8-r2` 为 423 case，369 通过、54 失败；1074 step 中 1013 通过、61 失败。生产资产 18/18 case、37 step 全通过。`18339-r1` 是 sandbox localhost 权限导致的环境失败目录，不作为质量基线。
- `TurnDecision` 模型节点已增加内部超时保护，默认 25s。Kimi 节点长尾不再直接拖到 WebSocket 180s；超时时记录 `turnDecisionTimeoutCount/turnDecisionDurationMs` 并走保守 fallback。
- R16/R18 聚焦修复已在隔离新版 agent `18339` 上验证：`correctness-pin-disabled-in-301-35` 通过，路由为 `direct_local_plan_action_unsupported`，无 pending/card；`303-open-quality-civil-service-plan-support-lazy` 通过，无 pending/card，回复明确只做方案支撑分析。
- 生产回捞定点 case `320-prod-quality-region-include-vs-plan-add` 已在最新 `18339` 上复验：`加入广东和江西` 仍生成地域意向 pending；确认后 `江西的大学有哪些适合我` 已改为 `candidate_pool` 只读查询，无 pending/card，回复能列出江西候选机会。该步耗时 66.8s，质量通过但性能长尾仍需后续处理。
- 影子 case `320-shadow-G27-tuition-readonly-and-atomic-selector-observation` 已在重启后的最新 `18339` 上复验：`两万以上且跟我意向不沾边的先删掉` 进入 `direct_atomic_plan_action / remove_units`，结果 `no_change`，无意向 pending/card；该步耗时 26.1s。
- 当前最新代码验证 agent 使用独立端口 `18346`；固定测试环境的 `18090/18091/18092/3001` 不应被验证进程扰动。
- 最新代码 agent `18346` 已完成 R27 命名学校 + 专业类增补定点复验。原 `把河南农业大学的建筑类加进来` 已路由到 `direct_atomic_plan_action/add_units`，执行层返回 `no_change`；后端候选池按 `schoolKeywords=["河南农业大学"]` 查询为 0，按 `majorKeywords=["建筑类"]` 查询为 26，说明该断言是 fixture 数据过期，不应强行生成确认卡。替代样本 `把华中农业大学的建筑类加进来` 命中 1 个候选，返回 `preview_only`，followup 包含 `pendingConfirmationCard`，metrics 为 `/tmp/zhiyuan-agent-add-units-18346-huazhong-target.metrics.json`。
- R30 定点稳定性已在 agent `18346` 上连续复测 3 轮：`/tmp/zhiyuan-agent-r30-stability-18346-r1.metrics.json`、`r2`、`r3` 均通过，`补充进入机械类...专业和学校` 均走 `runtime_intent_hard_cut/apply_selected_intents`，未重现全回归里的 `add_units` 误路由。当前判断是低频模型/上下文漂移，不是确定性规则错误。
- 已继续从 `assets/production-dialogue-cases-since-20260614-043817-20260621-1601.json` 回捞两批原始生产样本验证稳定性：第一批 `/tmp/zhiyuan-agent-prod-asset-raw-stability-18346-r1.metrics.json` 为 26 step，25 通过、1 个 performance failure，语义未观察到严重误路由；第二批 `/tmp/zhiyuan-agent-prod-asset-raw-stability-18346-r2.metrics.json` 为 34/34 step 通过、0 failure。两批合计 60 step，路由分布为 `runtime_intent_hard_cut=30`、`full_agent=19`、`needs_plan_first_guard=8`、`pending_intent_short_text_confirm=3`。唯一失败是 `补入预览` 125.9s 超过性能阈值，不是内容失败。
- 最新生产资产三组已在 agent `18346` 上按并发 8 连续复跑两轮：`/tmp/zhiyuan-agent-prod-assets-threepack-18346-p8-r2` 和 `r3` 均为 18/18 case、37/37 step 通过。`r2` 路由分布为 `runtime_intent_hard_cut=14`、`full_agent=12`、`pending_intent_short_text_confirm=4`、`direct_atomic_plan_action=4`、`direct_readonly_plan_query=3`，耗时 median 19.0s、p95 35.5s、max 40.2s；`r3` 路由分布为 `runtime_intent_hard_cut=15`、`full_agent=9`、`direct_readonly_plan_query=5`、`pending_intent_short_text_confirm=4`、`direct_atomic_plan_action=4`，耗时 median 18.9s、p95 27.7s、max 41.9s。两轮无 content/tool/environment failure。
- `r2/r3` 之间存在可接受但需观察的路由波动：`江西的大学有哪些适合我` 和 `电力，铁道，航空职业技术学院...` 在 `full_agent` 与 `direct_readonly_plan_query` 间切换；`不要排除经济学类啊` 在 `full_agent` 与 `runtime_intent_hard_cut` 间切换。结果均通过，说明当前回复质量未受明显影响，但模型/路由稳定性仍不能视为完全收敛。
- 已新增并验证额外 production-raw 探针 `examples/dialog_regression_320_prod_asset_additional_raw_cases.json`：`/tmp/zhiyuan-agent-prod-additional-raw-18346-p3-r1` 为 3/3 case、4/4 step 通过。覆盖长文本梯队偏好、`方案要增加动物医学专业`、`模拟方案怎么只有冲/稳和保去哪了`。未发现严重语义分错；长文本梯队偏好耗时 45.3s 触发 latency warning；`动物医学` 场景未误改方案，但回复没有明确保留动物医学未来意向，继续归入 R33 双轨回复缺口。
- 本轮尝试对 G50-G55 做 live-node 小范围 benchmark，但 live-node runner 未能稳定生成报告；已给 `examples/model_node_benchmark.py` 增加 `--case-ids` 和 `--case-timeout-seconds`，并将 live-node timeout 归为 `provider_env/timeout`，避免污染质量矩阵。fixture 层 G50-G55 已通过 `/tmp/model-node-r31-r33-fixture-filtered.json`，6/6 passed。

## 2. 遗留问题分级

P0 必须优先处理：

- 严重语义分错：用户只读诉求进入 mutation，或 mutation 被写成未来偏好。
- 错误 pending/card：无结构化候选却承诺确认执行，或有可执行候选但不发卡。
- 实体误归类导致硬约束错误：例如职业方向当专业、地域当专业、院校性质当专业。
- 上下文引用错误：把不存在的当前方案、已取消 pending、或上轮无关实体当成本轮操作对象。

P1 需要尽快收敛：

- 强度误判：软偏好升为 `must_have/only_keep/exclude_hard`，或硬排除降级。
- 回复质量问题：事实边界正确但措辞过强、过泛、上下文继承不清。
- schema 可表达但 runtime 没有统一走结构化链路。

P2 可以排在语义稳定之后：

- latency 长尾、重复工具调用、batch query 缺失。
- 前端展示细节和 workspace refresh 体验优化。

## 3. 当前遗留问题台账

| ID | 问题族 | 当前状态 | 风险 | 后续处理 |
| --- | --- | --- | --- | --- |
| R1 | 完整生产资产回归 | 最新 `18346` 当前代码生产资产三组按并发 8 连续复跑两轮，`r2/r3` 均 18/18 case、37/37 step 通过、0 failure；并发 8 全回归中生产资产为 17/18 通过，唯一失败是 `补充进入机械类...专业和学校` 被转成 `add_units` 方案增补预览；高收费定点 3/3 通过；R30 定点稳定性复测 3 轮均通过；两批原始生产回捞合计 60 step 内容层未见严重误路由；额外 production-raw 3 case、4 step 通过 | 单独生产资产和原始回捞未发现新的严重语义分错，但全量并发暴露了“补充进入”在已有 pending 和正式方案上下文中可能被误判为当前方案增补；r2/r3 存在 `full_agent` 与 direct/query/hard-cut 的路由波动但未造成失败；原始回捞还暴露若干 schema/回复质量缺口，主要是冲稳保比例、策略词、复杂偏好截断和 no-plan 回复边界 | 保留为回归基线，后续失败按 `environment / semantic / reply_quality / latency / framework_gap` 分桶；`补充进入` 语义边界单独进入 R30，生产原始样本新缺口进入 R31-R33；继续用并发 8 双轮验证稳定性 |
| R2 | 高收费正向语义和后续方案动作 | “高收费意向采纳后要求把当前方案高收费换成正常收费”已修复为 plan action 仲裁，第三步进入 `replace_units`；若当前方案没有命中高收费项，返回 `no_change` 明确不生成替换预览 | 用户说“高收费也能接受/预算可以放宽”时，schema 和 Java goal contract 可能无法表达正向接受；如果后端审查 affected ids 缺失，只能用结构化 review issue fallback 保守定位 | 单独确认 budget schema：是增加 `acceptable` budget/specialLimit，还是表达为删除预算上限/删除 special-limit negative policy；继续验证 affected ids 缺失时的 review issue scope |
| R3 | 公办/民办强度 | 已避免把公办/民办识别成专业；但生产 targeted 中观察到“你这全是民办”可能被写成 `exclude_hard=民办` | 用户可能只是要求少一点、优先公办或解释占比，硬排除会收窄过度 | 增加 school-nature 强度 case：`全是民办`、`民办少点`、`不要排除民办`、`保底要公办不要民办` 分别验证 |
| R4 | 职业方向被当专业 | `体制内/稳定就业` 已在 profile normalization 中向 career slot 收敛，并已有单测覆盖；原始生产回捞 `prod-dialogue-session-3753` 中 `我想要优先稳定体制内` 已输出 `发展方向：体制内/考公导向`，未当作专业 | full-agent 或旧 formatter 若绕过 profile schema，仍可能把职业词写入专业实体或专业类偏好；同时“政策/经济报告推荐”类问题回复容易泛化，若没有外部资料证据，不应宣称已经结合实时报告 | 加入 production dialog 回归和 model-node 异常 case；如果 live 仍错，优先修 profile node / adapter，不在 service 匹配“体制内”；政策/报告类回复单独要求事实边界或接入证据源 |
| R5 | 撤销负向约束的复杂分句 | 已按 reversal clause 处理，支持 major/school/region/career，budget 只做负向抑制 | “不要排除A，但B还是排除”这类句子若跨实体、跨分句处理不一致，会误撤销或误保留 | 继续扩展 benchmark：院校、地域、职业、专业调剂、高收费分别覆盖同句正负混合 |
| R6 | 复杂上文引用 | 当前主要依赖最新 utterance、active pending、formal plan 和已有结构化 payload；不是完整对话实体记忆解析。原始生产回捞 `prod-dialogue-session-3675` 中，用户先列出一批学校和专业，随后说 `将其按照冲稳保加入志愿方案`，系统因 active pending 先采纳了上一轮地域条件，虽然后续回复能从历史总结学校列表，但结构化 pending 没接住“其”指代的学校列表 | “这个也别排除”“刚才说的那个学校”“前面那类专业”“将其加入”可能找错最近实体或被 active pending 抢占；这会导致真实对象没进入可执行 preview 或 pending | 后续抽 `MentionResolver / EntityMemory`，把最近实体、类型、来源轮次、极性和可引用范围结构化；短确认/短指代需要先解析 referent，再决定是否 apply existing pending |
| R7 | 上下文过泛继承 | targeted case 中观察到“不要排除经济学类”后回复仍带较宽的“人文社会科学”门类偏好；原始生产回捞 `prod-dialogue-session-3715` 中 `不要排除经济学类啊` 已正确输出 `可以考虑专业：经济学类`，但后续复杂偏好又出现 `不优先专业类：经济学类`，需要确认是否符合“除了经济学类以外其他好就业专业”的语义 | 状态可能是对的，但回复让用户误以为系统又扩大或反转了意向范围；“不排除 / 不优先 / 除了A也可以考虑其他”三者混用会影响用户信任 | 回归中单独标注 `reply_quality_context_overcarry`；需要区分“历史仍保留”与“本轮新增/修正”，并在 pending card 中区分 `positive / acceptable / deprioritize / exclude` |
| R8 | 专业调剂/服从调剂 | 已倾向归入特殊限制，而不是专业实体 | 下游是否能把“不要调剂”用于方案筛选/增补仍需验证；如果只存在 profile 文案，方案动作可能接不上 | 在生产资产和 plan action 中验证 `专业调剂` 是否进入可执行 policy；不能只看回复文本 |
| R9 | “除了A以外其他好就业专业” | 已有关注点，但仍需更大回归 | 容易生成假的正向实体“非A专业”，或把“好就业”错误当具体专业 | benchmark 期望应是 `exclude_hard=A` + `career/employment preference`，禁止合成不存在的专业实体 |
| R10 | 当前方案增补志愿策略 | 方案动作已要求 structured recommendation、preview、source version guard 和 pending card；执行层已补 `add_units` structured filter fallback：自然语言候选引用未唯一命中但 selector 已有 school/major/region/tag 条件时，可先按候选池结构化条件生成可确认预览 | 增补先加哪些、是否结合意图/推荐分/结构约束/去重/梯度容量，仍需通过生产 case 观察；当前 fallback 只解决“selector 可定位候选但 ref 未唯一匹配”的卡片缺口，不解决多学校增补的完整排序证据 | 回归中记录 add_units 的 candidate selection evidence：硬约束优先、软偏好排序、风险/梯度、重复和容量约束；继续把多学校、多地域、专业标签增补沉到 add_units DSL evidence |
| R11 | 只读建议后的短确认 | no-pending guard 能防止无卡确认直执行 | 用户体验上，系统给出“建议可以处理”后用户说确认，可能只能得到无 pending 提示 | 后续需要一等 `selectableProposal/suggestedTransition`，让低副作用建议可明确升级为待确认动作 |
| R12 | service 过渡区 | 已大量迁入 compiler，但 service 仍承担调用、sink、history、reply guard 和 workspace followup | 后续继续加业务判断会让旧补丁层回流 | 新增行为必须先说明归属模块；service raw prompt 业务路由不得新增 |
| R13 | 不可执行 preview 的回复边界 | 已有结构化 guard 覆盖 `error/no_change/non-actionable preview` | 回复可能仍偏泛，用户不知道是缺选择器、缺基础资料，还是候选不足 | 生产回归里把 `missing_inputs / needs_volunteer_selection / no_change` 分开评估回复质量 |
| R14 | 性能长尾 | 30-40s 当前可接受；历史长尾来自 tool loop、candidate refresh、重复查询。两批原始生产回捞合计 60 step 的慢点集中在短 pending 上下文和 full-agent fallback：`补入预览` 125.9s、`要调整` 81.6s、`多补充211` 69.5s、`替换` 55.1s；生产资产并发 r2/r3 median 稳定在约 19s，p95 27.7-35.5s，max 40-42s；额外长文本梯队偏好 45.3s，主要耗在 `intentEntityProfileDurationMs=33.0s` | 如果直接压缩工具调用，可能损失证据质量；短句 pending 上下文慢且语义不复杂，说明 guard/TurnDecision/profile pipeline 仍有可优化空间；长文本 profile 抽取耗时说明 schema 越复杂越需要结构化/分块而不是 full prompt 重抽 | 先完成质量回归，再做 tool budget、batch query、EvidencePlan 前置优化；优先优化短确认/短待办/无方案 fast guard 和长文本 profile 抽取，不改变 sideEffect 判定 |
| R15 | 全量旧 fixture 与当前环境不一致 | `18339` 并发 8 全回归仍有大量旧断言噪声，主要是 old pending expectation、thinking 文案、无正式方案 fixture 和 followup protocol | 容易把正确的 `needs_plan_first` 边界误判成质量失败，干扰修复优先级 | 将这类 case 拆成两套：一套显式 seed 正式方案验证方案操作，一套验证无方案边界回复；旧 thinking/followup 文案断言单独降噪 |
| R16 | 只读分析被升级为意向 pending | 已收敛：career-only fast path 不再跳过 side-effect 仲裁；聚焦 live case 无 pending/card，回复按方案支撑只读分析返回 | TurnDecision 仍可能把“以后想考公...这方案有支撑吗，先看看”判成 `intent_pending/future_reference`，需要继续降低模型节点误判；该 live case 延迟 52.5s，有性能长尾 | 把该句加入 TurnDecision/model-node benchmark；后续优化 readonly plan-support 快路径，目标是在不损失证据质量下减少 full-agent 长尾 |
| R17 | 上文指代合并不足 | `那两个都加吧 城市的话武汉最好...` 只保留地域，丢了上文两个专业方向 | 多轮真实对话中用户常用“那两个/这些/前面那个”继续表达意向，丢实体会导致 pending 不完整 | 并入 R6 的 `MentionResolver / EntityMemory`，补充 case 验证跨轮同类型实体引用 |
| R18 | 不支持动作误入意向 | 已修复并 live 验证：runtime intent 不再把 `锁定/固定` 降级成 `only_keep` 意向；AtomicPlanAction compiler 拒绝 pin/lock no-op move；最终走 `direct_local_plan_action_unsupported` | 仍依赖 LocalPlanActionDsl 返回 `unsupportedAction=pin_or_lock_unit`；如果新增其他 unsupported 动作，需要统一扩展 unsupported action DSL，而不是散落到 service | 保留聚焦回归；后续把更多 unsupported 动作族纳入 `unsupportedAction` 枚举和 model-node 异常集 |
| R19 | 模糊当前方案删除/移除被写成全局排除 | `把河南农大建筑去掉` 生成“排除院校：河南农业大学”并允许采纳 | 用户可能是要移除当前方案里某个学校+专业组合，不是全局排除院校 | 当前方案引用和 school+major 组合解析需要先判断是否有 referent；无 referent 时不能降级为全局排除 |
| R20 | 方案局部重排 selector 不完整 | `保底区里录取率最高的那个调到保底第一位` 进入 direct atomic action 后只回复缺少必要信息 | 框架已识别动作，但 selector 无法表达“tier 内按录取率选 top1 并移动到 tier 首位” | 扩展 PlanAction selector：tier scope + sort key + first candidate + intra-tier target position |
| R21 | 地域院校机会查询误入地域意向 pending | 已修复并 live 验证：`江西的大学有哪些适合我` 不再创建 `偏好地域：江西` pending；TurnDecision prompt、IntentSideEffect 仲裁和 ProposalCompiler query anchor 已补齐；production asset fixture 增加 `assertNoFollowups` | 当前实现是“只读院校/候选查询 anchor 阻断 runtime intent fast path + 侧效仲裁”，不是单 case service 字符串分支；仍依赖模型最终能回答候选机会，live 该步 66.8s | 已加入 unit、model-node benchmark 和 production quality case；后续优化 readonly candidate query 快路径，减少 full-agent 前置 guard 长尾 |
| R22 | 当前方案组合删除被误写成预算意向 | 已修复并 live 验证：`两万以上且跟我意向不沾边的先删掉` 不再生成“学费预算：每年不超过 20000 元”的意向 pending，改为 `remove_units` 当前方案动作，selector 含 `min_tuition_per_year=20000` + `preference_fit=unrelated` | 根因是 future-reference anchor 把任何“意向/偏好”都当成后续意向写入，导致“跟我意向不沾边”这种关系过滤盖住当前方案 mutation；这类词不能靠整句字符串分支处理 | 已收窄 ProposalCompiler future anchor：仅 `加到意向/作为偏好/后续参考/记录` 等写入动作算 future reference；保留 direct atomic DSL 处理组合 selector。后续可把 current-plan atomic mutation 更早短路，减少一次无效 profile 抽取 |
| R23 | PlanQuery 条件传播和空结果回复 | 已修复并在 `18342` 生产资产验证：候选池/当前方案只读查询保留 `province_names/city_names/school_keywords/major_keywords/school_tags/major_tags` 等列表条件；空结果回复会带查询条件边界 | 如果条件在 compiler/query handler/reply 任一层丢失，用户会看到“没有结果”但不知道系统查了什么，容易误以为事实不存在 | 已由 production source followup 覆盖海南招生场景；后续将 Java `PlanQueryCondition` 统一后继续收敛 Python query path |
| R24 | TurnDecision 模型节点长尾 | 已新增 25s 内部超时，超时写入 observability 并保守 fallback；相关单测通过 | Kimi 节点偶发长尾仍会牺牲一次 turn 的准确路由，但不会再把整轮拖到 180s；fallback 仍需保证不创建错误 pending/card | 全量回归继续统计 `turnDecisionTimeoutCount`，若质量受影响，优先进入 model-node benchmark/提示词或节点拆分，不用 service 字符串兜底 |
| R25 | review issue 批量删除/替换 preview 缺口 | 执行层已支持结构化 review issue scope 的多命中 preview，并在 affected ids 缺失时对 `high_tuition/cooperative_program` 做受控 fallback；高收费无命中时返回 `no_change` | fallback 只覆盖明确 review issue code，不看用户原句；如果后端 review scope 不完整，仍可能只能保守提示无命中或要求补充替换方向 | 继续扩展 `remove_units/replace_units` selector：数量/影响说明、source version guard、候选容量预检和更多 review issue code；断言区分“无命中 no_change”“缺替换方向”“可执行 preview” |
| R26 | 命名学校专业组增补直达不足 | `把方案中自动调整增加湖南的...专业组，可以是工科的` 能生成 `add_units` plan pending，但走 full-agent，前置 guard 约 48.6s；回复只说“符合条件的候选”，缺少可解释选择证据 | 质量未明显错，但结构化 direct atomic/action DSL 未覆盖“多学校 + 地域 + 专业标签 + 增补专业组”，性能和可解释性都不足 | 后续扩展 add_units DSL：学校列表、地域、专业标签、candidate selection evidence、去重/容量/梯度约束；避免把多学校列表压成逗号字符串或只靠 full-agent |
| R27 | 候选/当前方案“加进来”误入未来偏好 / add_units 可执行预览 | `18342` 全回归发现多条“把 X 加进来”曾走 `runtime_intent_hard_cut` 写成意向；当前 `18346` 已能把命名学校 + 专业类增补路由到 `direct_atomic_plan_action/add_units`，执行层 structured filter fallback 已 live 验证：`把华中农业大学的建筑类加进来` 命中 1 个候选并生成 `preview_only + pendingConfirmationCard`；`把河南农业大学的建筑类加进来` 因候选池无该学校返回 `no_change`，不发空卡。旧 `河南农业大学` 断言已判定为 fixture 数据过期 | 仍需继续观察 TurnDecision/ProposalCompiler 是否会把其他“加进来/加入方案”误判为 future intent；多学校、多专业组增补仍缺 selection evidence 和容量/梯度解释；无候选时回复要保留筛选条件边界，不能承诺确认执行 | 保留 R27 作为 P0/P1 交界问题继续回归：`加进来/加入方案` 在 formal plan/candidate pool 存在时必须走 `plan_mutation/add_units` 或明确无法定位；已增加执行层单测覆盖 selector fallback 和 no-change 边界，dialog regression 已把过期样本刷新为候选池真实存在的 `华中农业大学 + 建筑类` 并收紧 route/action/result/card 断言 |
| R28 | 分析型问法误生成 pending | `物理不太好但选了物化地，计算机还现实吗` 在全回归中生成 `偏好专业类：计算机类` pending，缺少适配性分析；`小语种现在还能选吗，怕就业不好` 也暴露回复聚焦问题。相反，`我630江苏物化生想去南京` 能被 semantic arbitration 降级为分析，说明机制存在但不稳 | 用户问“现实吗/能不能选/怕就业不好/适合吗”时，真实诉求通常是只读分析，不是记录偏好；误发 pending 会收窄后续推荐且破坏信任 | 将这些样本加入 TurnDecision/IntentSideEffect/model-node benchmark；增强 `analysis_only` 仲裁对问句、风险顾虑、适配性咨询的覆盖；回归中增加 `assertNoFollowups` 和回复必须包含风险/适配分析 |
| R29 | 并发 8 环境/连接稳定性 | `18342` 全回归后半段出现 29 个 backend connection refused setup 失败、约 20 个 WebSocket keepalive/request timeout；最新 `18346` 全回归 423 case 已完整跑完，未观察到 request/environment/tool 失败，说明当前隔离环境稳定性明显好转 | 大规模回归仍可能把环境/连接问题混进质量结果，容易误判为模型或框架退化；同时全量 p95 42.3s、max 109.3s 说明长链路性能仍有长尾 | 后续全回归继续保留健康检查/自动重试；生产资产和 P0 语义集单独跑作质量基线；request timeout 单独归因性能/稳定性，不与 content failure 混算 |
| R30 | “补充进入/纳入考虑”在意向更新和方案增补之间摇摆 | `18346` 单独生产资产 `320-prod-quality-major-negative-and-positive-mix` 通过：第二步被解释为补充未来专业偏好 pending；但并发 8 全回归中同一步被 full-agent 工具链转成 `plan_next_action/execute_plan_action add_units -> preview_only`，回复只说“补入指定志愿或按条件补入候选”，没有列出机械类、仪器类、能源动力类、电气类、电子信息类，也错误生成方案确认卡。后续 R30 定点稳定性复测 3 轮均通过，原始生产同族 `prod-dialogue-session-3776` 最后一步也稳定走 `runtime_intent_hard_cut/apply_selected_intents` | 这是 R27 的反向问题：不是“当前方案加进来被写成偏好”，而是“补充进入专业方向/学校范围”在已有正式方案上下文下被当成当前方案 mutation。直接匹配“补充进入”字符串会误伤真实方案增补，必须看对象粒度、上下文 anchor、是否有具体候选/专业组、是否有“当前方案/加到方案/补齐志愿”等结构化证据。当前表现更像低频模型/上下文漂移，不能因 targeted 通过就关闭 | 增加 TurnDecision/model-node benchmark 和 dialog regression：`补充进入X专业和学校` 在没有具体院校专业组、且上轮是 intent pending 时应保持 `intent_pending/future_reference`；`把X学校Y专业组加进当前方案` 才走 `plan_mutation/add_units`。full-agent 工具可用性也要受 TurnDecision sideEffect/scopeAnchor 约束，不能让工具选择覆盖语义仲裁 |
| R31 | 冲稳保比例/梯度策略没有结构化承接 | 原始生产回捞 `prod-dialogue-session-3759` 中 `冲50%，稳30%，保20%` 的 TurnDecision 已判断为 `intent_pending/future_reference`；focused 探针在有正式方案上下文时能给出当前方案比例分析，但仍不是结构化 pending。G50/G51 已加入 model-node fixture 并通过，但 live-node 子集暂未稳定产出报告 | 用户表达的是 tier ratio / risk appetite / plan structure preference，不是普通专业、地域、院校实体；当前 schema 和 action 承接不足会导致真实策略丢失。用字符串匹配 `冲50` 会误伤当前方案重排和只读咨询，必须结构化表达比例约束 | 增加 `tierRatioPreference / riskStructurePreference` schema，进入 TurnDecision、profile node、pending card 和 PlanAction selector；benchmark 覆盖 `冲50稳30保20`、`多一些稳和保`、`保底多一点`、`冲稳保按3:4:3`；区分无正式方案的未来偏好和有正式方案的结构调整预览 |
| R32 | 策略/质量形容词被当专业实体 | 原始生产回捞 `prod-dialogue-session-3776` 中 `优质工科专业`、`干净专业组工科` 曾被输出到 `偏好专业`；`prod-dialogue-session-3696` 中 `不挑专业也不挑地域，只为了保本，更希望公办学校` focused 探针只稳定保留公办，安全优先/放开专业地域仍没有完整进入回复；额外长文本梯队偏好能保留大部分专业实体和负向专业，但耗时较长 | “优质、干净、保本、安全、好就业、考公、技术岗”这些是策略/质量/职业导向，不一定是实体；误塞到专业实体会污染推荐和 hard/soft intent，漏掉策略又会降低推荐质量 | 扩展 profile schema：区分 `majorEntity`、`majorCluster`、`careerDirection`、`riskPreference`、`schoolQualityPreference`、`flexibilityPreference`。resolver 只做实体归一，不承载策略词；formatter/card 要按类型展示；长文本 tiered preference 需要结构化分层而不是压成单个 pending 文案 |
| R33 | no-plan guard 吞掉可作为未来偏好的信息 | 原始生产回捞 `prod-dialogue-session-3729` 中，带 `方案中增加/去掉/专业组` 的请求被正确拦为 `needs_plan_first`；但同句里还有 `生物科学和化学保住院校层次`、多学校列表和工科方向，这些没有被整理成可采纳的未来偏好或后续生成方案输入。额外探针 `方案要增加动物医学专业` 未误改方案，但走 full-agent add_units 后因缺基础信息 no-op，回复只提示缺资料，没有明确回显动物医学未来意向 | no-plan guard 语义安全，但会让真实偏好信息丢失；用户无正式方案时，系统既不能改方案，也不应把所有信息丢掉。若直接把所有 no-plan mutation 降为 intent，又会误写当前方案动作 | needs-plan-first 回复应支持“不能改当前方案 + 可整理为未来偏好/生成方案输入”的双轨结构，但必须显式区分不可执行 plan mutation 和可采纳 intent；相关信息进入 pending 要经过 TurnDecision/Profile schema，不在 service 从文本补捞 |

## 4. 需要结构化确认的框架缺口

以下问题不适合继续用字符串匹配或单 case 分支处理：

1. 高收费正向接受如何表达。
   当前负向预算/特殊限制比较清楚，但“能接受高收费、预算可放宽、不要把高收费全删掉”需要 schema 和 downstream policy 明确。否则回复可以说清，方案动作却无法稳定执行。

2. 公办/民办到底是 school 实体、schoolNature 过滤器，还是特殊 policy。
   当前避免了“当专业”的错误，但长期应让 `公办/民办` 以院校性质进入 filter/policy，而不是混在具体学校名里。

3. 上文引用需要一层实体记忆。
   仅用最近一句和已有 payload 足以覆盖“不要排除经济学类”这类明确表达；但真实对话里大量“这个/那个/刚才那个/前面那类”需要按实体类型、来源和轮次解析。

4. 增补志愿需要可解释选择证据。
   用户关心“为什么先加这些”。框架上应把 hard constraints、soft preferences、recommendation score、risk/tier、duplicate/capacity constraints 放进 preview evidence，而不是只返回最终候选。

5. 低副作用建议到高副作用执行的升级协议。
   只读建议后用户短确认不能绕过 pending guard；要提升体验，需要显式 suggested transition，而不是让 service 从回复文本恢复动作。

6. 组合 selector 和意图约束交集。
   `两万以上且跟我意向不沾边的先删掉` 已可通过 direct atomic DSL 表达为 `remove_units` + 学费阈值 + `preference_fit=unrelated`。后续仍要扩展更多组合条件：例如“概率低且非核心意向”“民办且离家远”“冲档里不贴合专业方向”等，统一沉到 selector DSL 和 evidence，不从 service 文本恢复动作。

7. `公办/民办` 需要进入一等 `schoolNature` schema。
   当前已经避免当专业，但仍可能被模型放进 `school` 实体或靠特殊限制文案承载。长期应在 profile、PlanQuery filters、PlanAction selector 和 Java policy 中统一表达。

8. Atomic/PlanAction DSL 的标量和列表 contract 需要统一。
   生产回归观察到模型可能把 `provinceKeyword/schoolKeyword` 返回成 list，而 schema 仍按 string 约束。应在 DSL model 层接受 list 或规范成列表字段，compiler 不应依赖逗号拼接字符串。

9. review issue scope 的方案动作需要可执行 preview。
   `cooperative_program` 这类审查问题已经能识别，但删除/替换链路需要多命中 selector、数量预览、影响说明和确认卡，不能长期退回“请点选单条志愿”。

10. 命名多学校增补需要结构化 selection evidence。
    多学校、多地域、专业标签、梯度容量、推荐分和去重约束必须能在 add_units preview 中解释。否则“先增加哪些”无法维护，也无法稳定验证回复质量。

11. `加进来/加入方案` 需要上下文敏感的 mutation anchor。
    同一句“加上/加进来”在“作为偏好/以后参考”语境下是 future intent，在 formal plan 或候选池明确存在、并带学校/专业/专业组对象时应优先解释为当前方案 `add_units`。这应由 TurnDecision、PlanAction DSL 和 compiler 共同表达，不能在 service 里靠字符串兜底。

12. 分析型问句和意向写入需要更强的语义边界。
    “现实吗、适合吗、怕就业不好、能不能选、会不会太卷”等通常是 readonly analysis。只有用户明确说“作为偏好/记下来/以后优先/别要/只保留”时才应生成 pending。该边界应进入模型节点 benchmark 和 IntentSideEffect 仲裁。

13. 冲稳保比例和安全边际需要一等 schema。
    `冲50%，稳30%，保20%`、`多一些稳和保`、`只为了保本` 不是普通实体，也不等同于立即改当前方案。需要能表达 tier ratio、risk appetite、plan structure preference，并在已有正式方案时升级为可预览的 plan-structure adjustment。

14. 策略词和实体词需要分层。
    `优质工科`、`干净专业组`、`好就业`、`保本`、`考公技术岗`、`不挑专业地域` 不能全部塞进专业/院校实体。当前 profile node 需要把实体、策略、职业、风险、灵活性拆开，否则推荐和回复卡片都会混淆。

15. no-plan guard 需要双轨回复协议。
    当前 guard 能保证无正式方案不执行 mutation，但也会吞掉同句里的未来偏好。合理做法是返回“当前不能改方案”的边界，同时结构化列出“可作为生成方案/后续推荐参考的信息”，由用户确认是否采纳。

## 5. 下一轮验证计划

1. 持续重跑生产回捞资产 case。
   当前最新基线为 agent `18346` + backend `18290`，生产资产三组并发 8 双轮 `/tmp/zhiyuan-agent-prod-assets-threepack-18346-p8-r2`、`r3` 均 18/18 case、37/37 step 通过；原始生产回捞两批合计 60 step 中内容层未见严重误路由，额外 production-raw 探针 3/3 case 通过。后续新增资产继续按 case 汇总 content failure、semantic failure、reply quality、framework gap 和 latency。

2. 把失败分流到对应资产。
   模型 schema 错误进入 `model_node_benchmark_320_cases.json`；resolver/normalizer 错误进入 unit；runtime sideEffect/pending 错误进入 dialog regression；纯回复质量进入 production quality cases。

3. 为 R31-R33 补最小回归资产。
   R31 放入 TurnDecision/model-node benchmark 和 dialog regression，要求 tier ratio 能进入结构化 pending 或 plan-structure preview；R32 放入 profile-node benchmark，要求策略词不污染专业实体；R33 放入 no-plan guard regression，要求不能改方案但不丢未来偏好摘要。

4. 优先修 P0 语义链路。
   只要出现 wrong sideEffect、wrong pending/card、实体类型误归类、无依据承诺，就先修框架层，再谈性能。

5. 在质量稳定后再看性能。
   统计 median/p95/max 和慢 case 的工具链路。若质量无损，再推进 tool budget、batch query 和 EvidencePlan 缓存。

## 6. 并发 8 全回归分桶

### 6.1 `18346` 最新全回归

本轮命令使用 `examples/dialog_regression_parallel_runner.py`，`--parallelism 8`，输出目录为 `/tmp/zhiyuan-agent-full-regression-18346-p8-r1`。运行环境为 agent `18346`、backend `18290`、rank `18292`；使用真实 history DB `/root/dev/zhiyuan/zhiyuan-agent/data/chat_history.db`。

总体结果：

- case：423 total，370 passed，53 failed。
- step：1074 total，1011 passed，63 failed。
- failure reason：`content=63`；未观察到 `request/environment/tool` 失败。
- report：`/tmp/zhiyuan-agent-full-regression-18346-p8-r1/report-summary.json`。
- route 覆盖：`full_agent=523`、`runtime_intent_hard_cut=208`、`needs_plan_first_guard=103`、`pending_intent_short_text_confirm=78`、`pending_readonly_plan_query=55`。
- 失败 route：`needs_plan_first_guard=18`、`full_agent=15`、`runtime_intent_hard_cut=12`、`pending_intent_short_text_confirm=6`、`direct_atomic_plan_action=1`、`runtime_intent_profile_plan_reroute=1`。
- step latency：median 17.3s、p90 33.6s、p95 42.3s、p99 59.1s、max 109.3s。

生产资产结果：

- 生产资产三组在全量中为 18 case、37 step；17/18 case 通过，36/37 step 通过。
- 唯一失败：`320-prod-quality-major-negative-and-positive-mix` 第二步 `补充进入机械类，仪器类，能源动力类，电器类以及电子信息类专业和学校`。
- 失败链路：TurnDecision 判断为 `intent_pending/future_reference`，但 full-agent 工具链实际调用 `plan_next_action -> execute_plan_action`，动作变成 `add_units -> preview_only`，并生成方案确认卡。
- 回复问题：没有列出机械类、仪器类、能源动力类、电气类、电子信息类这些用户明确实体，只泛化成“补入指定志愿或按条件补入候选”。
- 结论：这是 R30 的真实语义边界问题，不是环境噪声，也不适合用 service 字符串匹配处理。

失败分桶：

- `reply_focus_gap`：42。多为回复没有命中特定断言、缺少实体回显或文案聚焦不足；其中 R30 属于高优先级语义边界，不应混入普通文案噪声。
- `assertion_noise_old_pending_expectation`：8。旧 case 期待确认后 ordered refresh，但当前没有可执行 preview 或没有正式方案。
- `assertion_noise_thinking`：8。fast/direct route 没有输出旧 thinking 文案，内容本身不一定错误。
- `selector_gap_no_executable_preview`：3。位置移动、专业组删除/移动等 selector 仍存在可执行 preview 缺口。
- `fixture_mismatch_no_formal_plan`：2。旧 fixture 期待正式方案，当前 session 没有正式方案，系统返回 `needs_plan_first`。

质量判断：

1. 相比 `18339` 的 369/423，本轮为 370/423，表面通过数略升；但生产资产从单独 18/18 到全量 17/18，暴露了 `补充进入` 在 full-agent 工具选择层的语义漂移。
2. R27 命名学校 + 专业类 add_units 已能覆盖，但 R30 说明反向边界必须补：不是所有“补充/进入/加入”都应当前方案增补。
3. R28 仍存在回复质量问题：`物理不太好但选了物化地，计算机还现实吗` 本轮无 pending/card，但回复仍偏“计算机类方向可采纳”的模板，没有充分回答学科适配和学习压力。
4. 性能上没有 request timeout，但政策专项、only_keep 临床、职业/专业分析等长尾仍超过 60s；质量优先下先处理 R30/R28，再做 tool budget 和 readonly 快路径。

### 6.2 `18342` 最新全回归

本轮命令使用 `examples/dialog_regression_parallel_runner.py`，`--parallelism 8`，输出目录为 `/tmp/zhiyuan-agent-full-regression-18342-p8-r1`。运行环境为 agent `18342`、backend `18290`、rank `18292`。

总体结果：

- case：414 total，306 passed，108 failed。
- step：1007 total，855 passed，152 failed。
- failure reason：`content=62`、`request=59`、`environment=29`、`performance=2`。部分 case 含多个 step 或同一 case 多个失败维度。
- route 覆盖：`full_agent=471`、`runtime_intent_hard_cut=163`、`needs_plan_first_guard=92`、`pending_intent_short_text_confirm=69`、`pending_readonly_plan_query=40`。
- 失败 route：`needs_plan_first_guard=18`、`full_agent=15`、`pending_intent_short_text_confirm=7`、`runtime_intent_hard_cut=7`、`direct_atomic_plan_action=2`。
- step latency：min 0ms，median 18.3s，p90 51.4s，p95 68.5s，p99 115.4s，max 248.9s。

失败分桶：

- `environment_backend_connection_refused`：29。集中在 `320_g1_g32_shadow` 和生产资产后半段，metrics 的 step 0 显示 backend state clone / pending clear / planning intent clear 对 `18290` connection refused。生产资产本轮全量失败均属于此类，不能视为生产资产质量回退。
- `request_ws_keepalive_timeout`：约 20。集中在 advanced/enriched/lifecycle 等长链路，例如 `advanced-multi-confirm-565` 最后一轮 `现在意向都生效了吗帮我列一下` 96.5s 后 WebSocket keepalive ping timeout。
- `workspace_followup_or_old_pending_expectation`：约 12。旧 case 仍期待 ordered refresh 或 plan pending，但当前真实路径是 no-plan guard、intent apply 或无可执行 preview。
- `fixture_mismatch_no_formal_plan_or_selector_gap`：约 10。旧 fixture 期待排序/移动/专业组调整，但当前 session 缺正式方案或 selector 不可执行。
- `fixture_mismatch_plan_state`：约 9。旧断言要求“冲/稳/保/个”等方案状态词，但当前状态为空方案或工具证据不足。
- `assertion_noise_thinking_or_fastpath`：约 8。fast path 不发旧 thinking 文案，内容本身不一定错误。
- `reply_focus_gap`：约 8。回复没命中特定断言词，需要逐条判断是文案聚焦还是旧断言过窄。
- `semantic_add_units_misrouted_to_intent`：至少 5 条，其中 2 条失败、3 条通过但质量有风险。典型样本：`把湖北工程学院的计算机科学与技术加进来`、`把广西师大统计加进来`、`把河南农业大学的建筑类加进来`。
- `semantic_analysis_vs_intent_pending`：至少 1 条明确失败，另有通过但质量不足样本。典型样本：`物理不太好但选了物化地，计算机还现实吗` 生成计算机类偏好 pending。

本轮直接结论：

1. 生产资产单独跑的 18/18 仍是当前更可靠的生产回捞质量基线；全量中的生产资产失败是环境 setup 失败。
2. 质量上最严重的是 `add_units` 当前方案动作误入 future intent，其危害高于普通回复聚焦问题，因为用户目标完全没有执行。
3. 第二类真实质量问题是分析型问法误生成 pending；它说明 `analysis_only` 仲裁仍需扩展到“现实吗/适合吗/怕就业不好/能不能选”。
4. 性能和稳定性恶化明显：median 仍约 18s，但 p95 到 68.5s，max 248.9s；TurnDecision 25s timeout 能避免单节点拖到 180s，但全链路和 WebSocket 保活仍有长尾。
5. 下一步应先补强断言和 benchmark，再修 TurnDecision/DSL/compiler：不能让“通过率”掩盖通过但错链路的 case。

### 6.3 `18339` 最新全回归

本轮命令使用 `examples/dialog_regression_parallel_runner.py`，`--parallelism 8`，输出目录为 `/tmp/zhiyuan-agent-full-regression-18339-p8-r2`。`r1` 是 sandbox localhost 权限导致全部失败的环境噪声，已排除。

总体结果：

- case：423 total，369 passed，54 failed。
- step：1074 total，1013 passed，61 failed。
- failure reason：`content=59`、`tool=1`、`request=1`；其中一个 step 同时命中多个 reason。
- route 覆盖：`full_agent=527`、`runtime_intent_hard_cut=224`、`needs_plan_first_guard=90`、`pending_intent_short_text_confirm=78`、`pending_readonly_plan_query=49`。
- 失败 route：`needs_plan_first_guard=18`、`full_agent=15`、`runtime_intent_hard_cut=10`、`pending_intent_short_text_confirm=7`，另有确认/超时类 step 无 route。
- 生产资产：`dialog_regression_320_prod_asset_micro_cases` 5/5、`quality_cases` 7/7、`supplemental_cases` 6/6，合计 18/18 case、37 step 全通过。

失败分桶：

- `reply_focus_gap`：37。多为回复没有命中特定旧断言或聚焦不够清楚，未集中表现为 pending/card 错误。
- `assertion_noise_old_pending_expectation`：8。旧 case 期待 pending 确认和 ordered refresh，但当前无可执行 preview 或无正式方案。
- `assertion_noise_thinking`：7。fast path 没有发旧 thinking 文案，不宜为了断言回退慢路径。
- `fixture_mismatch_no_formal_plan`：3。旧 fixture 与当前 session 无正式方案的环境事实不一致。
- `selector_gap_no_executable_preview`：3。位置/专业组移动和删除 selector 仍缺可执行预览。
- `intent_context_merge_gap`：1。`那两个都加吧 城市的话武汉最好 长沙南京也行` 仍丢上文“那两个”的专业方向，只保留城市意向。
- `unknown`：2。`两万以上且跟我意向不沾边的先删掉` 已在后续聚焦修复中关闭为 R22；剩余真实 unknown 主要是 `确认这个最终版` 180s timeout。

性能基线：

- step elapsed：min 2.0s，median 17.5s，p90 29.4s，p95 34.0s，p99 52.5s，max 180.0s。
- 生产资产仍干净，但 R21 live 单步 66.8s 表明只读候选查询的 guard + full agent 链路有明显长尾。
- 当前按“效果优先”标准，median/p95 可接受；真正需要优先处理的是 50s+ 长尾和 180s request timeout，前提是不牺牲 sideEffect/pending 正确性。

本轮直接结论：

1. 最新代码相比 `18337` 基线从 367/423 提升到 369/423，失败 step 从 67 降到 61；没有观察到生产资产语义回退。
2. R21 地域院校查询误入地域 pending 已在生产资产严格断言和全回归中保持通过。
3. 当前更严重的问题不是性能均值，而是 R6/R17 上文引用合并、R20 局部 selector 表达能力，以及旧 fixture 断言噪声影响判断。
4. 下一步修复不应落在 service 字符串匹配；`那两个` 需要 EntityMemory/MentionResolver，更多组合删除/替换诉求需要继续扩展 action DSL selector 和意图匹配证据。

### 6.4 `18337` 旧基线

本轮命令使用 `examples/dialog_regression_parallel_runner.py`，`--parallelism 8`，输出目录为 `/tmp/zhiyuan-agent-full-regression-18337-p8-r1`。运行期间 agent `18337` 稳定，未观察到服务挂死；失败集中在内容断言和少量工具/展示契约，不是环境端口不可用。

总体结果：

- case：423 total，367 passed，56 failed。
- step：1074 total，1007 passed，67 failed。
- 失败原因：`content=67`，另有 1 个 step 同时带 `tool` 维度。
- route 覆盖：`full_agent=513`、`runtime_intent_hard_cut=240`、`needs_plan_first_guard=86`、`pending_intent_short_text_confirm=79`、`pending_readonly_plan_query=57`。
- 失败 route：`full_agent=18`、`needs_plan_first_guard=17`、`runtime_intent_hard_cut=11`、`pending_intent_short_text_confirm=7`、`direct_atomic_plan_action=2`、`pending_readonly_plan_query=2`。

失败分桶：

- `fixture_or_env_no_formal_plan`：约 34 case。旧 case 期待已有正式方案并断言“冲/稳/保、排序、移动、确认刷新”，但当前 session 没有正式方案，系统返回 `needs_plan_first` 或 0 志愿边界。该类优先改回归资产或 seed 数据，不作为代码修复入口。
- `progress_thinking_expectation`：约 6 case。内容基本可用，但 fast path 没有发旧断言要求的 thinking 文案。需要决定是否继续强制 thinking 文案，不宜为了断言增加慢路径。
- `workspace_followup_expectation`：约 4 case。多为确认后期望 `targetView=ordered` 或 refresh，但当前动作是意向采纳/无方案状态。需要重新定义采纳意向后是否必须刷新 ordered view。
- `reply_contract_or_fixture_text`：约 7 case。多为回复没有命中特定词或旧文案；其中部分是低风险断言过窄，部分需要产品口径确认。
- `semantic/framework risk`：少数但优先级更高，包括 R16-R20。它们涉及 wrong sideEffect、上下文实体丢失、unsupported action 误入 intent、组合引用误降级为全局排除、复杂 selector 不能表达。

性能基线：

- step elapsed：min 2.1s，median 17.1s，p90 28.4s，p95 32.7s，p99 49.5s，max 78.5s。
- 长尾主要来自 `full_agent` 多次模型请求和重复工具调用；单 turn 观察到 7 次 LLM request、14.5 万 input tokens 的政策/强基路径。
- 当前质量优先原则下，30-40s p95 可暂时接受；超过 50s 的 case 后续应从 history/tool-return 压缩、重复 query 合并、policy/source 搜索预算三个方向拆。

本轮直接结论：

1. 刚修复的“高收费采纳后把高收费换成正常收费”链路在全量日志中走到 `direct_atomic_plan_action / replace_units`，没有再退回成 intent pending。
2. 生产资产 18/18 仍是更接近真实回捞的小规模质量基线；全量 423 的失败当前主要用于发现框架边界和旧 fixture 偏差。
3. 下一步不应把 56 个失败逐个字符串修掉，而应先处理 R16-R20，再清理 no-plan fixture 和 thinking/followup 断言。
4. R18 已证明应按“框架守卫 + DSL unsupported route”解决：compiler 只阻止错误 intent/atomic 执行，最终动作边界由 LocalPlanActionDsl 表达，不在 service 增加单 case 字符串分支。
5. R16 当前质量已达标但性能不达标，且 TurnDecision 仍有语义误判；后续应优先进入 model-node benchmark 和 readonly plan-support 快路径，而不是回退成 service 文本补丁。

## 7. 关闭标准

一个遗留问题只有同时满足以下条件才从本文移出：

- 有明确代码修复或明确产品/框架决策。
- 有 unit、model-node benchmark 或 dialog regression 覆盖。
- 生产回捞或同类 synthetic case 至少一轮通过。
- 回复文本、pending/card、workspace refresh 和后端状态不互相矛盾。

如果只是本轮 case 通过，但没有结构化归因和回归资产，仍保留在台账中。
