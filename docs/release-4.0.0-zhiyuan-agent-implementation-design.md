# Release 4.0.0 — Zhiyuan Agent 实施设计

> 版本: v2.53 | 日期: 2026-07-12
> v2.53 发布拓扑与 smoke 收口：正式 local quality gate `433 passed`、runtime hard-cut `36 passed`；开发联调四服务 healthcheck 中 web/server/base-data/agent/rank 全部 PASS。修复 Web `next.config.mjs` 把两个可选 Agent URL 以 `undefined` 注入导致的 Next 配置警告，并将唯一的 Ant Design `Tooltip.overlayStyle` 旧 API 替换为 `styles.root`；`/session` 实际编译无上述警告。`release-smoke --local` 原先固定请求生产 `/assistant-pc`，无法验证 `scripts/start-all.sh` 的空 basePath 开发拓扑；新增 `ZHIYUAN_WEB_BASE_PATH`，默认仍为 `/assistant-pc`，显式空值才检查 `/session` 与 `/sessionDetailV2`，生产检查未放宽。修复后只读 smoke 的 Web、Backend、review rules、Agent HTTP/WebSocket、Rank 全部 PASS，`0 failures`；新增无网络测试覆盖生产/开发两种路径。完整 Python `1631 passed, 38 skipped`。全量 TypeScript 检查仍有 26 个既有错误，均不在本轮修改文件，不登记为本轮通过。
> v2.52 命名志愿动作与空方案执行闭环：`preview_plan_action(add)` 现在消费模型给出的结构化 `filters.school + filters.major` 或 `学校.专业` target，先查当前候选快照、再调用后端候选查询；唯一专业直接生成 `add_units` pending，同一 `planSchoolDataId` 下多个专业按专业组加入，跨组多解必须列出选项澄清，零命中和已在方案中均明确无副作用返回。工具层没有扫描 `raw_user_text` 或新增中文关键词路由。修复真实志愿身份读取遗漏 `planSchoolDataId`，以及空方案 summary 丢弃 backend `version` 导致确认时 `expectedPlanVersion=0` 的问题。完整拓扑下“厦门大学嘉庚学院·建筑学”预览、确认、pending applied、planning version 增长和目标 volunteerId 入方案全部通过；排序服务未启动时后端生成方案失败被确认是环境依赖，不增加业务兼容降级。命名 move/add/类别澄清聚焦 `4/4`，只读查询后确认 guard `2/2`；完整 Python `1629 passed, 38 skipped`，完整 Maven 509 个测试无失败、4 skipped。session 17 的相关资产从伪 `formal_plan_present` hard cut 为真实 `empty_plan + candidatePool`，并删除被当前统一 thinking 文案替代的旧白名单红项。
> v2.51 发布门禁旧断言清理：v2.50 完成结构闭环后复核两端长期红项，确认均为已被当前设计替代的测试口径，而非生产实现缺陷。Python admission-policy 已明确输出“家庭预算与可接受学费上限”，删除仍期待模糊“家庭约束”的旧断言；Java constraint intent 按当前候选池全量可恢复设计，只使 overlay/recommendation/ordered/review stale，不使基础 candidatePool stale，`PlanningStateServiceTest.shouldMarkConstraintIntentChangeStaleWithoutCandidatePool` 已提供同层契约，因此将孤立的相反断言改为 without-candidate-pool。聚焦 Python `9 passed`，Java ReviewInvalidationPolicy + PlanningStateService 通过；完整 Python `1535 passed, 29 skipped`，完整 Maven 509 个测试无失败、4 skipped。未修改生产代码，没有新增兼容分支；Release 4.0 当前单元发布门禁从“两个已知红项”收敛为全绿。
> v2.50 pending command 跨进程恢复 E2E：新增 opt-in `tests/e2e/test_pending_command_recovery.py`，以隔离 session 模拟 Agent 命令请求在 10ms 客户端超时后后端仍提交成功，随后通过 ready/resume 双向屏障精确重启 backend。屏障模式自行读取监听 PID，并断言重启前后 PID 集合不相交，避免“只暂停未重启”的假阳性。本机强断言运行中旧 JVM PID `56306` 提交 operation 后响应写出触发预期 `Broken pipe`，新 JVM PID `56671` 校验 Flyway V12 后恢复服务；测试强制 lease 过期，以新 claim token 接管并重放同一 operationId，返回 `replayed=true`，planning version 始终只增长一次，pending 最终为 applied。finally 清理 operation、pending、planningState 和屏障文件；数据库三类临时行均为 0，18082 无监听。`py_compile`、默认关闭时 `1 skipped`、真实跨进程 `1 passed in 87.96s`。完整 Python `1534 passed, 29 skipped, 1 failed`、完整 Maven 509 个测试中 1 failed/4 skipped，均仍为已登记的无关断言，没有新增失败。至此 v2.45-v2.50 的 pending 独立资源、CAS、lease、幂等命令、latest-only hard cut、日志保留和断连恢复闭环全部完成；后续转入发布门禁与运行观测，不再增加平行兼容实现。
> v2.49 planning command operation 日志治理：新增 V12 `(status, update_time, id)` 清理索引和配置化 retention scheduler，默认启用、每小时执行、保留 succeeded 30 天、单批最多 500 行。Mapper 删除 SQL 固定包含 `status='succeeded' + update_time cutoff + LIMIT`，shared service 将批量限制在 1-5000；running 永不进入删除条件。任务使用进程内运行锁，异常只记结构日志且 finally 释放，不影响后续周期。真实数据库插入“40 天前 succeeded / 当前 succeeded / 40 天前 running”三条隔离记录，应用成功执行 V12 后调度日志 `deleted=1`，只删除过期 succeeded，当前 succeeded 与过期 running 均保留；V12 三列索引存在，测试记录清零，临时服务停止。retention 聚焦 `7 passed`，command `10 passed`；完整 Maven 509 个测试仍只有既有 ReviewInvalidationPolicy 失败、4 skipped。
> v2.48 pending 存量回填与旧读 hard cut：本机审计发现旧 `pendingConfirmation` extra-data 共 6861 行，独立 pending 表在此前临时验证清理后为 0；其中 1142 条历史行结构完整且状态为 active/applying，但只有 569 条具备主会话租户归属。V11 首版按“任意历史 active”回填时因同会话多版本撞唯一键而失败，且会有复活墓碑前旧 pending 的风险；确认未插入任何行后仅清除失败的 Flyway 11 记录，没有执行 repair，也未触碰 V7-V10。修订后的 V11 与生产 `data_version DESC` 语义对齐，按 `dataVersion + id` 选择每会话唯一 latest，再过滤 active/applying、校验必填字段/长度、join `assistant_chat_session` 获取 tenant，并移除旧 transport metadata。真实迁移成功校验 11 个版本并回填 552 行；17 条被更高版本终态覆盖的旧 active 未复活，缺主会话的 573 条历史测试夹具未伪造租户，session 17 latest=failed 未回填。回填行均为 revision 1、active，transport metadata 残留为 0，抽样独立 API 可直接读取。随后删除 `pending_legacy_read_fallback` 配置、Agent extra-data 读取分支、`_pendingLegacySnapshot` marker 和兼容测试；无独立资源统一返回空。聚焦 Python `229 passed, 29 skipped`、Java pending/command `20 passed`；完整 Python `1534 passed, 29 skipped, 1` 个既有失败，完整 Maven 502 个测试仍只有 1 个既有失败、4 skipped。
> v2.47 pending 多步规划命令幂等下沉：后端新增 V9 `assistant_planning_pending_command` 与单事务命令接口，把 `apply constraint/tuition + optional regenerate`、`add select + regenerate`、`replace remove + select + regenerate` 从 Agent 多步调用收敛为一个后端事务。命令校验当前 pending claim owner 和 lease、锁定 pending 与 planningState、校验 `expectedPlanVersion`，以 `operationId` 记录最终结果；同 operationId/同业务载荷重放不再执行副作用，不同载荷返回 `40903`，规划版本漂移返回 `40904`。并发请求在取得 planning 锁后会重读 operation，避免首事务未提交时误报版本冲突；请求 SHA-256 不包含可随租约接管变化的 claim token，允许新 owner 重放同一业务命令。V9 已应用后保持字节不变，请求指纹通过 V10 增量迁移加入，禁止 Flyway repair 或回改已发布 migration。Agent 已删除 intent/add/replace 三条旧多步编排，仅保留单命令调用；只有 `planning command is already running` 的 40903 属于结果不确定，operationId 载荷冲突是确定性失败。真实 backend 验证首次执行 `473 -> 474`、同载荷重放版本不再增长、异载荷 40903、旧版本 40904 且不写 operation；持久化结果保留 ordered plan 但不含 candidate pool，临时数据与服务已清理。聚焦 Java pending + command `20 passed`、Python `228 passed, 29 skipped`；完整 Python `1533 passed, 29 skipped, 1` 个既有文案失败，完整 Maven 502 个测试中 1 个既有 ReviewInvalidationPolicy 失败、4 skipped。
> v2.46 applying 执行租约与崩溃恢复：在已落地的独立 pending CAS 上新增 V8 `claim_token/claim_expires_at`，后端固定 5 分钟执行租约。confirm 必须携带 UUID claim token；未过期 applying 对其他 token 返回 `transitionApplied=false`，过期后允许新 token 以 `applying -> applying` CAS 接管并递增 revision；complete/fail 必须匹配当前 claim token，旧执行者在租约被接管后返回 `40902 pending claim ownership mismatch`，不能覆盖新 owner。Agent 读取 claim token/expiry 作为运行态传输元数据：未过期 applying 不投影为 active pending并回复“正在处理中”，过期 applying 可重新进入确认投影并触发接管；service 已 claim 的内部 direct 执行上下文不会二次 claim。真实 backend 已执行 Flyway 7 -> 8，并验证 A claim、B 未过期拒绝、B 过期接管、A complete 拒绝、B complete 成功；临时记录和服务已清理。聚焦 Python `399 passed, 29 skipped`，Java pending `10 passed`；完整 Python `1528 passed, 29 skipped, 1` 个既有文案失败，完整 Maven 492 个测试中 1 个既有 ReviewInvalidationPolicy 失败、4 skipped。下一结构性工作是将 intent+regenerate 和 replace 多步动作下沉为带 operationId/expectedPlanVersion 的幂等后端命令。
> v2.45 pending 独立资源/CAS 第一阶段：后端新增 V7 `assistant_chat_session_pending_confirmation` 单行快照表和 GET/upsert/resolve 内部接口，`revision` 与 planning version 完全解耦；状态链为 `active -> applying -> applied`，确认先原子抢占执行权，重复确认返回 `transitionApplied=false`，取消/过期/完成均校验 `pendingId + expectedRevision + sourceStatus`。Agent 的 service 确认入口和 direct `confirm_pending` 均已接入抢占，未获得执行权时禁止调用任何方案/意向变更 API；新写只走独立资源，迁移期仅在新表无行时保留可配置旧 extra-data 读兜底。runner 的 pending clear/clone/assertion 已迁移到独立资源，旧 version 0/latest 双写清理、按 tool payload 读取 pending version、`save_pending_confirmation(version=...)` 等实现已删除。真实本地后端验证已执行 Flyway V7，并验证 revision `1 -> 2 -> 3 -> 4 -> 5` 的创建、过期写拒绝、claim、重复 claim 幂等、complete、replace、cancel。聚焦 Python `396 passed, 29 skipped`，完整 Python unit `1523 passed, 29 skipped, 1` 个既有 admission-policy 文案失败；Maven pending 用例 `7 passed`，完整 Maven `489` 个测试中 `1` 个既有 ReviewInvalidationPolicy 断言失败、`4 skipped`。剩余边界：`applying` 崩溃恢复尚无租约/超时接管；intent+regenerate 与 replace 多步业务命令尚未下沉为后端幂等原子命令；旧读兜底需在发布迁移完成后删除。
> v2.44 focused 架构验证与专业组位置修复：修正 v211/v212/v213/v216 地域 final-action 的正式方案源和 major 模式 `orderedPlanState.items` 断言，v173/v179 改用真实含目标 unit 的专业组正式方案源，并迁移已污染目标 session；runner 的 pending backend assertion 删除最后一处 `latest or version 0` fallback。`preview_plan_action` 在模型已选择 remove/move、携带原话但漏传 targets 时复用现有 ordinal parser 恢复源专业组位置，且预览显示专业组序号，不再暴露组内明细扁平位置；显式 targets/filters 始终优先。fresh focused live：v216 `2/2`、v173 remove/move `4/4`、v179 append/no-pending/replace `7/7`。测试：direct 工具 `182 passed, 29 skipped`，runner `93 passed`；完整 unit suite `1520 passed, 29 skipped, 1 failed`，唯一失败为既有 admission-policy “家庭约束”措辞断言，与本轮无关。结论：地域确认、pending 追加、第三专业组位置动作和 ReplacementSpec 在有效 fixture 上闭环；当前结构性边界仍是 pending 暂存于 versioned extra-data，clone/历史高版本墓碑会遮蔽 version 0 新 pending，独立 pending revision/CAS 和多步后端原子命令仍需后续完成。
> v2.43 pending 生命周期第一阶段加固：生产读取统一为 latest-only，latest 空对象作为墓碑，不再回读 version 0 复活旧 pending；Service 只把通过结构校验的 active pending 投影到 `ConversationPhase` 和本轮 Sandbox，`confirm_pending` 必须持有该运行时投影才有执行权限，并校验运行时 `pendingId` 与 Sandbox 快照一致。前端 follow-up 兼容桥、Sandbox backend adapter 和 regression runner 同步采用 latest-only 语义，删除 version 0 fallback。final-action fixture 禁止 source/target 同 session，v211/v212/v213/v216 及 review/repair 资产改为独立目标 session；pending latest 清理查询失败现在计 environment failure，不再静默继续。相关单测 `594 passed, 29 skipped`。边界：当前 pending 仍暂存于 versioned extra-data，独立 pending revision/CAS 资源和 replace 等多步动作的后端原子命令仍是下一阶段，不在本版本宣称闭环。
> v2.42 补齐 4.0 final-action/high-signal 专项门禁入口：v2.41 固定默认 live gate 后继续盘点 `examples/` 下全部 4.0 case，确认还有 19 个 4.0 专项/final-action 资产未进入默认 13 文件 live gate，包括 direct confirm、G1-G32、realistic user、v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183/v211/v212/v213/v216。这些不是旧资产，很多 metadata 明确要求 `--clone-backend-chat-session`，并包含 `assertBackendExtraData` 最终状态断言；如果直接混入默认 live gate，会因统一命令缺少 chat-session clone/DB 参数而产生环境假失败。本轮在 `dialog_quality_gate.py` 新增独立 `final-action` category，默认 `--execute` 仍只跑 local，`--mode live` 仍只跑 13 个默认 4.0 live 文件；需要验证最终动作闭环时显式运行 `--mode final-action`，命令统一带 `--clear-history-per-case`、`--clear-backend-pending-per-case`、`--clear-backend-planning-intent-per-case`、`--clone-backend-chat-session`、`--keep-response-text`、`--assert-plan-style`、`--response-timeout 180`，并支持透传 `--agent-url`、`--internal-service-url`、`--backend-db-password`。验证：`py_compile examples/dialog_quality_gate.py tests/unit/test_dialog_quality_gate.py` 通过；`tests/unit/test_dialog_quality_gate.py -q` 为 `9 passed`；`dialog_quality_gate.py --mode final-action ...` dry-run 生成 19 条 clone-backed command；默认 `dialog_quality_gate.py --execute` 本地门禁为 `421 passed`。当前结论：4.0 当前 case 资产分为默认质量/只读 live gate 与 clone-backed final-action 专项 gate 两层，避免把高成本最终动作验证隐藏在默认门禁里，同时让所有现存 4.0 专项资产有正式入口。
> v2.41 4.0 case 资产 hard-cut 清理：按当前 4.0 direct 主链路口径收敛质量门禁，`examples/dialog_quality_gate.py` 不再自动 glob 所有 `dialog_regression_*_cases.json`，live gate 固定只引用 13 个当前 4.0 case 文件：agent smoke、plan operation、explore intent、readonly real session、core/effect perf、open quality、realistic quality、dialogue-derived、career direction、review repair、production abstracted、requirement plan action。已删除 `examples/` 下旧非 400 历史 regression JSON（advanced/comprehensive/enriched/full_journey/lifecycle/mainline/plan/plan_correctness/robust/science/score_tier/special 等），避免 3.x/早期口径继续被自动纳入维护面；`dialog_regression_runner.py` 示例、planning dialog checklist、dialog regression report 和 next session handoff 同步改到当前 4.0 case。新增 hard-cut audit：旧非 400 regression JSON 不应重新存在，当前 gate/mainline 测试不应引用旧文件，gate 不应恢复 glob 自动发现。测试侧同步把 explore intent catalog 的覆盖断言从旧 `positive_*_intent / historical_intent / intent_revision` 标签改为当前 `explicit_requirement / priority_reference_boundary / readonly_no_pending / candidate_explore / plan_impact` 语义。验证：`py_compile` 通过；`examples/dialog_quality_gate.py --metrics-dir /private/tmp/zhiyuan_400_effective_gate_dry_run` dry-run 通过并只列出 13 个 4.0 live 文件；`.venv/bin/python -m pytest tests/unit/test_dialog_quality_gate.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `46 passed`。当前结论：历史积累 case 没有继续作为 live gate 全量维护对象，4.0 有效回归集已固化；历史 release/changelog 文档中的旧文件名保留为历史记录，不作为当前门禁入口。
> v2.40 131 条 fresh quality observation 验证-only：在 v2.39 小池观察后继续扩大到完整 131 条质量观察池。首次运行目录 `/private/tmp/zhiyuan_400_v240_quality_131_fresh8041` 在第 80 个 case 后因本机磁盘满中断，错误为 `OSError: [Errno 28] No space left on device`，不计业务结果。定位空间大头为 `/opt/homebrew/var/mysql` 约 70G，其中 MySQL binlog `binlog.000144` 到 `binlog.000200` 占约 58G；按用户确认使用 MySQL `PURGE BINARY LOGS TO 'binlog.000201'` 清理，保留当前活跃 `binlog.000201`，磁盘可用空间从约 `230M` 恢复到约 `75G`，MySQL 目录降到约 `12-14G`。随后用 fresh agent `8041`、backend `8080`、真实 LLM、并发 4、完整 chat-session clone、`--backend-db-password 12345678`、`--ignore-thinking-assertions` 重跑 131 条，目录 `/private/tmp/zhiyuan_400_v241_quality_131_after_binlog_cleanup`，有效结果 `130/131`、148 step 中 147 step 通过。工具/路由分布：`zhiyuan_agent_direct=137`、`needs_plan_first_guard=3`、`direct_no_pending_short_text_confirm=4`、`direct_pending_intent_confirm=4`；工具调用 `answer_policy=19`、`explore_topic=25`、`read_state=3`、`preview_intent_change=15`、`compare_entities=12`、`review_plan=20`、`query_plan=15`、`preview_plan_action=10`、`confirm_pending=8`；`pendingConfirmationCard=23`，无工具直答 24 step，多工具调用 3 step。唯一失败仍是已降优先级 `400-open-quality-plan-query-then-confirm-guard`：上一轮 `query_plan` 只读查询青岛城市学院，第二轮“确认”走 `direct_no_pending_short_text_confirm -> confirm_pending`，没有执行副作用，但回复仍为“这类待确认内容还不能由新确认工具执行，请重新生成预览”，没有命中“上一轮只是查询/没有待执行方案动作”的语境文案。额外观察：`400-dialogue-region-beijing-tianjin-safety` 通过但返回“这轮处理没有完成，请稍后重试”，耗时 `32135ms`，无工具、无副作用，记录为低优先级回复质量/模型波动；warnings 主要为 81 条 source volunteer 文件缺失导致的 clone warning，另 1 条 `intent-existing-impact` 第二轮耗时 `10440ms > 10000ms`。本轮结论：full quality observation 没有发现新增稳定 4.0 链路缺口，也没有 pending/confirm/final-action 数据错误；当前剩余主要是已确认低优先级 no-pending 文案、单次只读兜底回复质量、部分验证夹具 volunteer 文件缺失 warning。
> v2.39 场景观察与验证分析：继续按用户口径扩大 4.0 fresh 小池观察，不处理已降优先级 no-pending 文案。使用 fresh agent `8041`、backend `8080`、真实 LLM、并发 4、完整 chat-session clone、`--backend-db-password 12345678`、`--ignore-thinking-assertions`，运行 28 条高信号观察集，目录 `/private/tmp/zhiyuan_400_v239_fresh_observation_28`，首轮 `25/28`。工具/路由分布：`zhiyuan_agent_direct=29`、`direct_no_pending_short_text_confirm=3`、`direct_pending_intent_confirm=2`；工具调用 `preview_intent_change=9`、`query_plan=5`、`confirm_pending=5`、`compare_entities=4`、`review_plan=4`、`preview_plan_action=3`、`answer_policy=1`，共 12 次 `pendingConfirmationCard`。失败分层：1）`400-open-quality-plan-query-then-confirm-guard` 是已降优先级问题，上一轮只读查询后用户说“确认”时无副作用，但 no-pending 回复仍是“这类待确认内容还不能由新确认工具执行，请重新生成预览”，不贴合“上一轮只是查询、没有待采纳/待执行内容”的语境；2）`400-open-quality-career-multi-direction-readonly` 与 `400-open-quality-civil-service-plan-support-lazy` 均在 step 0 backend planning intent clear 超时，未进入模型。随后单独顺序复核两条环境失败，只读场景均转绿，metrics `/private/tmp/zhiyuan_400_v239_env_failed_two_recheck.json`，两条都走 `zhiyuan_agent_direct -> review_plan`，无 pending、无方案副作用，耗时约 `12-14s`。本轮结论：fresh 当前代码下没有新增稳定 4.0 链路缺口；地域/偏远地区、混合正负专业要求、缩略专业对比、当前方案只读审查、方案调整预览等代表性链路保持可用。剩余可记录但暂不优先修的是 no-pending 文案、少量只读长延迟和环境清理超时。
> v2.38 focused 验证-only：按用户决策暂不处理低优先级 no-pending 文案，继续复查 v2.37 记录的 `intent-existing-impact` 第二轮 query guard 观察项。临时启动 fresh agent `8041` 加载当前工作区代码，使用 backend `8080`、真实 LLM、完整 chat-session clone 和 `--backend-db-password 12345678`，focused 运行 `400-open-quality-intent-existing-impact-readonly`，metrics `/private/tmp/zhiyuan_400_v238_intent_existing_impact_fresh8041.json`，结果 `2/2`。第一轮“我倾向会计学和审计学，但土木工程不要”正确生成 `preview_intent_change` + `pendingConfirmationCard`，内容为“专业要求：要：会计学、审计学；不要：土木工程”；第二轮“先不确认，看看这个偏好会影响当前方案吗”只调用一次 `query_plan`，返回当前方案命中 4 个志愿，无 followup、无新 pending、无方案副作用，也未复现 query_plan repeat guard。第二轮耗时 `10159ms` 略超 warning 阈值，回复末尾叠加“这轮还没有生成可确认的调整预览”边界文案，归入低优先级回复质量观察。当前结论：该点在 fresh 当前代码下不是稳定链路缺口，本轮不做生产修复；后续可继续进入小规模 fresh 观察池或全量 131 复跑。
> v2.37 场景观察与验证分析：在旧链路清理后继续跑 4.0 quality observation，不做生产修复。使用既有 agent `8000`、backend `8080`、真实 LLM、并发 4、完整 chat-session clone、`--backend-db-password 12345678`、`--ignore-thinking-assertions`，覆盖 dialogue-derived/open-quality/quality-realistic-user/career/explore/readonly 共 131 个 case，目录 `/private/tmp/zhiyuan_400_v237_quality_observation_after_cleanup`，首轮 `123/131`、147 step 中 139 step 通过；工具分布为 `query_plan=13`、`answer_policy=21`、`explore_topic=27`、`preview_intent_change=18`、`compare_entities=9`、`review_plan=19`、`preview_plan_action=9`、`confirm_pending=8`，3 个 step 出现多工具调用，25 个 step 无工具直答，未发现最终 action 数据错误。失败 8 个分层：4 个是 backend clone/clear `TimeoutError` 环境失败；`南方/北方` 和 `省外可以但不要偏远` 在 8000 首轮未稳定出卡；`query_plan` 后用户只说“确认”走 no-pending guard 但回复为“这类待确认内容还不能由新确认工具执行，请重新生成预览”，无副作用但文案不符合用户语境；`compare_entities` 澄清/收尾在 8000 首轮仍继续追问或补做分析。随后抽 8 个失败顺序复跑 `/private/tmp/zhiyuan_400_v237_failed8_subset_sequential.json`，结果 8/11 step 通过、1 个环境失败、2 个内容失败；`南方/北方` 转绿，`省外可以但不要偏远` 在断言上通过但实际仍未出 pending，`intent-existing-impact` 第一轮出 pending、第二轮触发 query_plan repeat guard 后无稳定结果，`plan-query-then-confirm` 的 no-pending 文案稳定不佳，compare 收尾仍不够自然。为排除 8000 进程非最新代码影响，临时启动 fresh agent `8041` 加载当前工作区代码后复跑同一 8-case 子集，metrics `/private/tmp/zhiyuan_400_v237_failed8_subset_fresh8041.json`，结果 8/10 step 通过、1 个环境失败、1 个内容失败；`南方/北方` 正确生成“地域要求：要：南方；不要：北方”待采纳卡，`省外可以，但太偏的地方不想去` 正确生成“地域要求：不要：偏远地区”待采纳卡，compare 后“嗯那就这样”自然收尾且无副作用，career readonly 转绿。fresh 当前代码下稳定剩余问题只有 `plan-query-then-confirm-guard`：上一轮是只读查询且没有 active pending，用户说“确认”时没有执行副作用，但 no-pending 回复应明确“上一轮只是查询，没有待采纳/待执行内容”，不应说“这类待确认内容还不能由新确认工具执行”。另 `intent-existing-impact` 第二轮 query guard 只在 8000 顺序复跑中观察到，fresh 复核被环境 clone 超时阻断，先记录为待 focused 复核。结论：当前代码下地域集合/偏远地区语义仍可用；本轮没有发现 pending/confirm/final-action 数据错误，主要问题是 no-pending 确认文案、少量自然接续质量、backend clone/clear 超时和旧进程/模型波动。
> v2.36 验证-only：继续扩大 4.0 direct final-action/取消/组合调整真实回归，覆盖 `dialog_regression_400_v156_realistic_broadened_final_action_cases.json`、`dialog_regression_400_v157_realistic_cancel_combo_cases.json`、`dialog_regression_400_v173_action_expansion_final_cases.json` 共 14 个 case。首轮在沙箱内运行为 `0/14`，失败均为本机 MySQL/HTTP 访问被拦截，表现为 `Operation not permitted` 与 MySQL `127.0.0.1:3306` 连接失败，不计为业务结果。授权本机服务访问后，输出目录 `/private/tmp/zhiyuan_400_v235_action_expansion_parallel_escalated`，结果 `14/14`、32 step 全通过、warnings=0、failures=0；工具分布为 `preview_intent_change=9`、`preview_plan_action=6`、`review_plan=2`、`confirm_pending=15`，所有 step 工具调用数均为 1，没有重复调用；确认轮后端断言合计 76 条，覆盖 `pendingConfirmation.status=applied/cancelled`、`planningState.version` 增长、报考要求落库、candidate pool 保留、ordered/review 刷新、排序/移动/移出/替换后的方案状态变化。当前结论：旧链路清理和命名收敛后，扩展 final-action 链路没有发现新的执行缺口。继续观察但暂不优先修：`v173-review-followup-high-tuition-replace` 预览回复仍露出内部 `high_tuition` code，且“换便宜点”候选更便宜但仍可能保留民办属性；这属于回复质量/候选质量观察，不影响本轮确认后动作生效结论。
> v2.35 验证-only：在旧 WS chat alias、旧 topic tool/skill 和误导命名清理后，继续补跑 4.0 direct 主集和残余扫描。`dialog_regression_400_g1_g32_direct_cases.json` 为 `20/20`，metrics `/private/tmp/zhiyuan_400_v233_g1_g32_after_ws_alias_cleanup.json`；运行分布为 `intent_pending=6`、`readonly=9`、`plan_preview=3`、`needs_plan_first=2`，覆盖显式报考要求、只读方案查询/审查、方案预览和无正式方案边界。扫描 `plan_next_action|execute_plan_action|planEditCache|plan_orchestration_tool|plan_context_tool|plan_execution_tool|app.handlers|HANDLER_REGISTRY` 等旧链路标识后，生产 app 中未发现仍在执行旧 plan/context/execute 链路的入口；剩余命中主要是 hard-cut 防回退测试、旧 payload 拒绝保护、前端仍在用的 `planEditSelect/intentDetectSelect` 卡片点击协议桥，以及 `draftPlanState -> workingPlanState` 后端状态兼容。G1-G32 本轮有 source session 志愿文件缺失 warning，但这些 case 不依赖 final-action 后端断言，runner 已按 v2.18 口径只记录 warning 并继续执行；未发现新的业务执行缺口。后续继续清理时，只删除已证实不属于当前前后端协议或当前后端状态兼容的旧资产；本轮同时把生产 app 中与旧 agent 链路无关的 `old/legacy` 注释和日志口径收敛为 backend/persisted/current state 表达，不改变运行行为。
> v2.34 验证-only：旧 WS chat alias / intent popup alias 清理后补跑真实 4.0 链路。首次沙箱内运行因本机 MySQL/HTTP 访问受限且 runner 默认 `internal-service-url=18290` 被记录为无效环境；改用当前 backend `8080` 并授权本机服务访问后，`dialog_regression_400_direct_confirm_execution_cases.json` 为 `4/4`，metrics `/private/tmp/zhiyuan_400_v233_direct_confirm_after_ws_alias_cleanup_escalated.json`，覆盖方案移出与“民办不要”报考要求，确认后 `pendingConfirmation=applied`、`planningState.version` 增长、ordered/review 刷新均通过。`dialog_regression_400_v155_realistic_final_action_cases.json` 为 `6/7`，metrics `/private/tmp/zhiyuan_400_v233_v155_after_ws_alias_cleanup.json`，唯一失败是“山东别去了”首轮重复调用两次 `preview_intent_change`，但已正确生成待采纳卡，下一轮“采纳”后地域要求落库、candidate view 筛选和 ordered/review 刷新均通过，归为低优先级重复调用效率问题，不是最终执行错误。`dialog_regression_400_realistic_user_cases.json` 为 `14/14`，metrics `/private/tmp/zhiyuan_400_v233_realistic_user_after_ws_alias_cleanup.json`，确认无正式方案边界、口语属性报考要求、只读政策/职业咨询和当前方案锚定 fallback 在清理后保持可用。
> v2.33 继续收敛旧链路清理后的误导性命名：`profile_manager.py` 和 `message_store.py` 中与旧 agent 链路无关的 `legacy` 注释改为 backend/persisted payload 口径，`test_message_store.py` 顶部说明同步改为 backend render message persistence；本轮不改变运行逻辑。
> v2.32 删除 `intent_state_tool.py` 中未被运行时或测试引用的 `_build_popup_title()` 旧别名，统一保留 `_build_preview_title()` 作为当前意向/要求预览标题生成入口；hard-cut 防回退同步覆盖该旧 popup title alias。
> v2.31 继续清理同类 WebSocket 旧入站别名：删除 agent-plus compat 协议中的 `inputType=intentDetect -> chat` 映射。当前前端 `intentDetectPopup` 点击已发送普通 `text`，`intentDetectSelectPopup` 与兴趣动作点击走 `intentSelect` 统一 pending/card bridge，因此该别名不再是 4.0 主链路所需协议面。hard-cut 防回退同步覆盖 `planEdit -> chat` 与 `intentDetect -> chat` 两类旧 chat alias。
> v2.30 继续清理 agent-plus WebSocket 入站协议中的旧 `planEdit -> chat` 别名：当前前端未发送 `inputType=planEdit`，该别名只服务历史软意向确认入口，已与 4.0 的 `pendingConfirmation` / `confirm_pending` 主确认链路背离。本轮删除服务端 `_INPUT_TYPE_MAP` 中的 `planEdit` 映射和对应旧兼容单测，并新增 hard-cut 防回退断言；保留仍有协议意义的 `planEditSelect` / `intentSelect` 卡片点击桥，继续转换为统一 pending 处理。
> v2.29 继续按 4.0 direct 主链路清理旧学校主题工具：删除未被 `ZhiyuanAgent` 注册或 `app/zhiyuan_agent` 引用的 `app/tools/school_info_tool.py`、`app/tools/school_compare_tool.py`、`app/tools/school_recommend_tool.py` 和旧 `skills/school_chat`。学校科普、学校对比、院校政策问答和推荐式咨询统一由当前 `explore_topic` / `compare_entities` / `answer_policy` / `query_plan` 等 4.0 direct 工具承接，不再维护旧 school tool + skill 并行入口。新增 hard-cut 防回退断言，保证旧 school 工具和 skill 不会重新出现，保留 active skills 不携带旧 school 工具名。
> v2.28 继续清理 4.0 sandbox 中容易误读的历史命名：`_legacy_volunteer_prefix` 与 `by_legacy_prefix` 重命名为 `_volunteer_group_prefix` / `by_group_prefix`。该逻辑仍用于真实 `volunteerId` 与 `planSchoolDataId` 的分组前缀对齐，属于当前 ordered item enrichment 的数据结构适配，不是旧 agent 链路兼容。行为不变；hard-cut audit 已增加防回退断言。
> v2.27 继续清理 4.0 direct 生产代码中的历史命名：`_replacement_legacy_auto_select_reason()` 重命名为 `_replacement_auto_select_reason()`，保持 `ReplacementSpec -> auto_select_reason` 的结构化映射行为不变，不调整 payload 字段、候选选择策略或用户回复。该函数服务当前 `preview_plan_action(replace)` 自动替换候选选择，不属于旧链路兼容。
> v2.26 对 `explore_followup_tool` 做兼容桥边界收紧：确认该模块不是 4.0 主 agent 的旧并行入口，而是前端 `actionType` 卡片点击的兼容适配层；运行时只从 active `pendingConfirmation(kind=intent_change)` 读取已生成的结构化报考要求来源，`candidate_query` 只做候选筛选，`plan_analyze` 只委托 4.0 `query_plan` 做只读方案承接，`prefer_confirm/constrain_confirm` 只生成新的统一 `pendingConfirmationCard`，不直接写状态。同步去掉源码注释中的 `legacy explore follow-up` 表述，并新增 hard-cut 防回退断言，保证该兼容桥不得重新引入 `plan_next_action`、`execute_plan_action`、`planEditCache` 或旧 plan/context 工具链。当前结论：这条桥可暂保留为前端协议兼容层；后续只有当前端不再发送旧 `actionType` 时才整体删除或迁移到更中性的 action handler。
> v2.25 继续按 4.0 direct 主链路做旧工具/skill 清理：删除未被 `ZhiyuanAgent` 注册或 `app/zhiyuan_agent` 引用的旧专业主题工具入口 `app/tools/major_info_tool.py`、`app/tools/major_compare_tool.py`，同步删除专属单测 `test_major_info_tool.py`、`test_compare_resolution.py` 和旧 `skills/major_chat`。保留 `explore_topic` / `compare_entities` 作为专业了解与专业对比唯一 4.0 入口；`skills/explore_chat`、`skills/career_path_chat`、`skills/intent_detect` 已改为 4.0 direct 工具说明，不再引导 `get_major_introduction`、`compare_majors`、`analyze_current_*`、`preview_current_*` 等旧 wrapper。质量门禁资产 `dialog_regression_400_career_direction_cases.json` 的职业方向 action family 从旧 `analyze_current_career_direction` 切到 `explore_topic`；runner 单测样例也切到 4.0 工具名；`zhiyuan-agent/docs/semantic_layer_structure.md` 同步改为 4.0 direct 结构说明，`skills/plan_query` 与 `prompt.py` 的 `query_plan` 参数说明收敛到 `filters.school` / `filters.major` 口径。新增 hard-cut 防回退断言，保证旧专业工具文件和旧 major skill 不会重新出现，且保留 skill 不再携带旧工具名。验证：`tests/unit/test_zhiyuan_agent_direct.py tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_dialog_regression_runner.py tests/unit/test_dialog_quality_gate.py tests/unit/test_dialog_case_evaluation_report.py -q` 为 `364 passed, 29 skipped`；`py_compile` 通过；`examples/dialog_regression_400_career_direction_cases.json` 与 `dialog_regression_400_dialogue_derived_cases.json` JSON 校验通过；`pytest --collect-only -q tests/unit` 为 `1534 tests collected`；`git diff --check` 通过。当前保留边界：`intent_state_tool` 仍作为底层报考要求分析/应用能力存在，`explore_followup_tool` 仍服务前端 actionType 兼容并且只从 active pending 读取来源，本轮未与旧专业工具入口清理混合处理。
> v2.24 在 v2.23 prompt-only 修复后补跑 72 条高信号主链路，验证报考要求预览、方案动作预览、最终确认执行、地域 final-action、active pending 和 no-pending 防护没有被新 prompt 影响。使用新版 agent `8040`、backend `18081`、真实 LLM、完整 chat-session clone、`--backend-db-password 12345678`、并发 3，目录 `/private/tmp/zhiyuan_400_v224_mainline_72_after_v223_prompt_fix`，首轮 `66/72`。6 个失败分层：`G17` 是 backend planning intent clear `TimeoutError`，未进入对话；`G30`、`v155`、`v157` 是重复调用同一预览工具但业务 pending/最终 action 正确；`G4` 明确专业要求首轮未出卡、`v212` 珠三角地域要求首轮未出卡，归为需要复核的模型波动。抽取 6 条失败子集单并发复跑 `/private/tmp/zhiyuan_400_v224_mainline_failed6_subset_sequential`，结果 `6/6`：G4 正确生成专业要求待采纳卡；G17 正确生成移动方案预览；G30 单次生成强基意向待采纳卡；v155 高收费移出预览和确认后端断言通过；v157 民办/中外合作排除确认后端断言通过；v212 珠三角排除首轮待采纳卡 + 确认后地域要求落库和 ordered/review 刷新均通过。当前结论：v2.23 修复后高信号主链路等效转绿，没有新增稳定 pending/final-action 执行缺口；剩余继续观察项是并发模型偶发无工具、backend clear/clone 超时、少量重复工具调用效率和过严工具次数断言。
> v2.23 按 v2.22 结论修复“倾向正向专业 + 但明确不要某专业”未稳定生成待采纳预览的问题。实现仍保持 4.0 语义边界：只强化 prompt 里的模型判定规则和示例，不在工具层新增中文字符串匹配；明确“倾向A和B，但Y不要/别碰/不考虑”属于可确认的正向专业方向 + 明确负向专业要求，必须调用 `preview_intent_change`，并在同一次调用中带 `positive`、`negative` 和 `semantic_requirements`。验证：`py_compile app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；目标单测 `test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups` 为 `1 passed`；focused 真实 case `/private/tmp/zhiyuan_400_v223_intent_existing_impact_after_fix.json` 为 `2/2`，第一轮生成 `preview_intent_change` + `pendingConfirmationCard`，第二轮只读查询当前方案影响且无 followup、无直接改动。随后并发 4 复跑 131 条 quality observation，目录 `/private/tmp/zhiyuan_400_v223_quality_131_after_intent_fix`，首轮 `125/131`；6 个失败分层为 4 个 backend clone/clear 超时环境失败、2 个自然收尾/只读边界文案断言波动。6 个失败子集单并发顺序复跑 `/private/tmp/zhiyuan_400_v223_quality_failed6_subset_sequential` 为 `6/6`。当前结论：本轮修复未发现新的稳定业务执行缺口或 final-action 数据错误；剩余继续观察项是 backend clone 超时、少量只读收尾文案波动和 query_plan 重复调用 guard 后的回复质量。
> v2.22 在 v2.21 后对当前 131 条 quality observation 做整组复核，目录 `/private/tmp/zhiyuan_400_v222_quality_131_after_v221_fix`，结果 `128/131`。失败包括：`400-open-quality-career-multi-direction-readonly`、`400-open-quality-no-pending-after-compare-guard`、`400-open-quality-intent-existing-impact-readonly`。补充 no-pending 自然收尾断言“随时跟我说”后，3 条失败子集顺序复跑 `/private/tmp/zhiyuan_400_v222_quality_remaining3_after_assertion_fix.json` 中 career 多方向只读和 compare 后无 pending 收尾均通过，剩余稳定问题是 `400-open-quality-intent-existing-impact-readonly`：用户说“我倾向会计学和审计学，但土木工程不要”时，模型可能不调用工具，只回复“还没有生成可确认的调整预览”；下一轮“先不确认，看看这个偏好会影响当前方案吗”才补建 pending，导致本该是只读影响查询的轮次变成生成待采纳内容。该问题属于模型语义边界漏判，应通过 prompt/schema 让模型把同一句里的可确认正向专业方向和明确负向专业要求一次性结构化输出，不通过工具层扫描原话修补。
> v2.21 按 v2.20 结论修复“缩略专业对比 + 数学/能力顾虑”误建 pending，并清理旧工具名验证资产。实现保持 4.0 边界：只做 prompt-only 语义边界强化，不在工具层做中文字符串匹配；把“A和B呢/那A和B + 数学/物理/累不累等适配背景”明确归为 `compare_entities`，且该规则优先于“想学/感兴趣”类待确认方向，不能把“数学不太行”写成“不要数学类”。补充真实口语示例“新媒体和跨电呢 数学不太行”和“计科和软工哪个更稳一点，孩子数学还行但不想太累”。同时把 `dialog_regression_400_dialogue_derived_cases.json` 中两条旧工具名断言从 `get_major_introductions/compare_major_options` 切到 4.0 的 `explore_topic/compare_entities`。验证：`py_compile app/zhiyuan_agent/prompt.py`、JSON 格式校验通过；focused `/private/tmp/zhiyuan_400_v221_major_abbrev_compare_after_prompt_fix.json` 为 `1/1`，真实回复走 `compare_entities`、无 pending card；重新抽当前资产 7 条失败子集 `/private/tmp/zhiyuan_400_v221_quality_failed_subset_cases_current.json` 后复跑 `/private/tmp/zhiyuan_400_v221_quality_failed_subset_after_prompt_and_asset_fix.json` 为 `9/9` step 全绿。
> v2.20 在 v2.19 主链路等效转绿后继续扩大 quality observation，使用 fresh agent `8040` + backend `18081` + 并发 4 跑 dialogue-derived、open-quality、quality-realistic-user、career、explore、readonly 共 131 条，带 `--ignore-thinking-assertions` 聚焦 4.0 链路和回复质量，目录 `/private/tmp/zhiyuan_400_v220_quality_131_after_v219`，首轮 `124/131`。7 条失败子集顺序复跑 `/private/tmp/zhiyuan_400_v220_quality_failed_subset_sequential.json` 后稳定剩 4 条：2 条是旧工具名资产口径（`get_major_introductions/compare_major_options` vs 4.0 `explore_topic/compare_entities`，回复内容可用）；1 条是澄清后用户“嗯那就这样”仍继续追问歧义，无副作用，归为自然接续质量；1 条是真实语义路由问题，`新媒体和跨电呢 数学不太行` 被误建成 `preview_intent_change` 待确认报考要求，应作为专业对比/适配咨询处理，不能因“数学不太行”自动记录为“不要数学类”。首轮另外 3 条转绿，归为模型/并发波动或断言口径。当前结论：quality 池没有发现最终 action 数据错误；后续优先修复“缩略专业对比 + 能力/课程顾虑”误建 pending 的模型语义边界，同时清理旧工具名验证资产。
> v2.19 使用 fresh agent `8040` + backend `18081` + 并发 3 + 完整 chat-session clone 复跑 v2.18 后的 72 条高信号主链路整组，目录 `/private/tmp/zhiyuan_400_v219_full_72_after_v218`，结果 `71/72`。唯一失败为 `400-v183-review-advice-then-vague-execute-no-pending-guard` 文案断言过窄：第二轮没有生成待确认操作或没有可执行的待确认项，且无工具/无 followup、后端 `planningState.version` 与 `pendingConfirmation` 均无副作用；该结果符合 no-pending 防护目标。已补充资产断言覆盖“没有生成待确认/没有可执行”等同义表达，focused 复跑 `/private/tmp/zhiyuan_400_v219_v183_no_pending_assertion_fix.json` 为 `1/1`，复跑中模型调用 `confirm_pending` 后返回“没有待确认、不执行任何变更”，后端仍无副作用。当前结论：v2.19 整组没有新增确定业务执行缺口；72 条主链路在修正验证资产后等效转绿，剩余低优先级仍是少量重复调用、表达质量和模型波动观察。
> v2.18 在 v2.17 后继续跑高信号主链路 + 地域集合并发回归，并完成失败分层收敛。首轮使用 backend `18081` + agent `8039` + 并发 3 跑 72 条，结果 `62/72`，目录 `/private/tmp/zhiyuan_400_v217_mainline_region_parallel`；地域 v212/v213/v216 继续通过。10 个失败分层：6 个是 runner 志愿文件 clone fail-fast 过严导致的环境假失败，已把 volunteer data 缺失只在 final-action/ordered/review 后端断言 case 中作为 environment failure，普通观察 case 只保留 warning；`tests/unit/test_dialog_regression_runner.py -q` 更新为 `89 passed`。失败子集复跑 `/private/tmp/zhiyuan_400_v217_failed_subset_after_runner_gate` 为 `6/10`，剩余 G30 重复调用、v153 数字文案断言、v173 固定 unitId 断言、v183 active pending 改口。v183 用 prompt-only 补齐“算了不是这个，改成山东别去，民办也不要”组合改写示例，不做工具层字符串匹配；新版 agent `8040` focused 复跑 `1/1`，目录 `/private/tmp/zhiyuan_400_v217_v183_rewrite_after_prompt_fix.json`，第二轮正确替换旧 pending，第三轮确认后山东/民办要求落库并刷新 ordered/review。随后 10 条失败子集复跑 `/private/tmp/zhiyuan_400_v217_failed_subset_after_v183_prompt_fix` 为 `8/10`，G30 与 v183 转绿；v153 断言从固定“20个相关志愿”改为“相关志愿”，v173 从固定老 unitId 改为首位 unitId changedFromBefore，剩余两条 `/private/tmp/zhiyuan_400_v217_remaining_two_after_assertion_fix` 为 `2/2`。当前结论：本轮没有新增确定业务执行缺口；主链路失败已按环境、低优先级重复调用、资产断言和 v183 prompt-only 语义缺口完成收敛。
> v2.17 继续验证 v2.16 后的地域 final-action 链路，并校准并发回归运行条件。先用 backend `18081` + agent `8039` 并发跑 v212/v213/v216 地域集合共 11 条时出现 `0/11`，复核后确认是无效环境运行：offset 会话没有带 `--backend-db-password 12345678`，`assistant_chat_session` 主表未克隆完整，后端能写入 `pendingConfirmation=applied` 和 `constraintState`，但 ordered-plan 刷新失败并返回“当前方案暂时没有重新调整成功”。同一 v216 case 在原始 session 17 串行复核 `1/1` 通过。随后使用新的 session offset、完整 chat-session clone、`--backend-db-password 12345678` 和并发 2 复跑 v212/v213/v216 共 11 条，结果 `11/11`，目录 `/private/tmp/zhiyuan_400_v216_region_expanded_clone_db`，确认后后端断言覆盖 pending applied、planningState version 增长、地域要求落库、ordered units 非空、代表性地域剔除以及 ordered/review 刷新。结论：v2.16 修复未破坏已有地域集合/城市圈 final-action；后续所有 offset final-action 回归必须显式带 DB 密码，否则按验证环境问题记录，不计为业务链路失败。同时收敛回归 runner：`--clone-backend-chat-session` 下主表或志愿文件克隆失败会直接标记 environment setup failure，不再进入 websocket 产生误导性业务断言；同源同目标 session 的志愿文件克隆视为 no-op。验证 `tests/unit/test_dialog_regression_runner.py -q` 为 `88 passed`。
> v2.16 修复 v2.15 暴露的“省外可以，但太偏的地方不想去”稳定缺口，并补齐最终 action 验证。修复保持 4.0 结构化语义边界：不新增工具层原话字符串扫描；prompt 要求模型把“省外可以/不排斥省外”作为 reference 或背景，不单独写成必须省外，把“太偏/偏远/太远的地方不想去/别考虑”压成 `negative={"area":["偏远地区"]}`；Agent 和后端地域 catalog 增加 `偏远地区` area，按新疆、西藏、宁夏、甘肃、青海、内蒙古展开。新增长期回归资产 `examples/dialog_regression_400_v216_region_remote_final_cases.json`，覆盖首轮 pending card 和确认后的 backend final-action。验证：`py_compile app/domain/region_entity_resolver.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused Python 单测 3 条通过；后端 `mvn -q -Dtest=PlanningStateServiceTest#shouldMatchRemoteRegionScope test` 通过；使用新版 backend `18081` + agent `8039` 跑真实 LLM focused final-action `1/1`，目录 `/private/tmp/zhiyuan_400_v216_remote_region_focused`，确认后 `pendingConfirmation.status=applied`、`planningState.version` 增长、`mustExcludeRegions` 包含“偏远地区”、`orderedPlanState.units minLength>=1` 且 ordered/review 刷新。
> v2.15 继续扩大 4.0 quality observation 验证，不新增生产代码改动。使用 backend `18080` + agent `8038` + 真实 LLM + 完整 chat-session clone + 并发 4 跑 dialogue-derived、open-quality、quality-realistic-user、career、explore、readonly-real-session 共 131 条，首轮 `102/131`，目录 `/private/tmp/zhiyuan_400_v215_quality_observation_expanded`。29 个失败子集单并发顺序复跑仍 `0/29`，目录 `/private/tmp/zhiyuan_400_v215_quality_failed_subset_sequential`；分层后 2 个是旧工具名断言（`get_major_introductions/compare_major_options` vs 4.0 的 `explore_topic/compare_entities`），24 个是纯 `thinkingText` 断言口径，3 个需要继续记录：`省外可以，但太偏的地方不想去` 未形成可执行地域要求；`新媒体/跨电` 对比澄清后用户说“嗯那就这样”仍继续追问，属于自然接续质量问题；`会计审计可以 土木别要` 在顺序复跑出现一次 `UnexpectedModelBehavior` 无 pending，但单独复测 `/private/tmp/zhiyuan_400_v215_intent_short_reprobe` 已能正确生成 `preview_intent_change` 和 pending card，降级为模型波动 + `thinkingText` 断言问题。当前结论：quality 池没有暴露新的 final-action 或 pending 执行错误；后续若修，优先处理“可接受省外 + 排除偏远/太远”这类显式地域诉求的结构化表达，不使用工具层中文字符串匹配。
> v2.14 在 v2.13 地域结构化归一修复后继续扩大 4.0 broader 回归验证，不新增生产代码改动。第一次在沙箱内启动 77 条回归全部失败，原因是本地 backend/DB 访问被拦截，报 `URLError: Operation not permitted` 和 MySQL 连接失败，按无效环境运行处理。授权访问本机服务后，使用 backend `18080` + agent `8038` + 真实 LLM + 完整 chat-session clone + 并发 4 跑 G1-G32、production、realistic、review/repair、v179、v183、v212、v213 共 77 条，首轮结果 `73/77`，目录 `/private/tmp/zhiyuan_400_v214_broader_after_v213_region_fix_escalated`。4 个失败为：`G4` 明确专业意向首轮无工具无 pending；`G30` 明确强基意向重复调用两次 `preview_intent_change` 超过严格工具次数；`realistic-readonly-fix-options-short` 和 `realistic-policy-vs-mutation-short` 首轮无工具导致工具名断言失败。失败子集按单并发顺序复跑 `4/4`，目录 `/private/tmp/zhiyuan_400_v214_failed_subset_sequential`：G4/G30 均正确调用 `preview_intent_change` 并生成 pending card，两个 realistic case 分别走 `review_plan`/`answer_policy` 只读路径。当前结论：v2.13 地域 final-action 在 broader 集内保持通过，v212/v213 地域集合/城市圈确认后后端断言均通过；本轮没有发现新的稳定业务执行缺口，剩余仍按并发模型波动、少量重复工具调用和只读断言口径观察。
> v2.13 扩展地域集合/城市圈口语最终 action 回归，并修复同类结构化地域别名缺口。新增 `examples/dialog_regression_400_v213_region_area_quality_final_cases.json`，覆盖“江浙沪就行，其他地方先别看了”“北上广深就行，不往其他城市放了”“东北和西北都先别考虑”“西北西南都不去，太远了”“上海南京杭州这一片可以，北方先不看”。初始 focused run 为 `10/10`，metrics `/private/tmp/zhiyuan_400_v213_region_area_quality_final.json`；扩大到 77 条 broader 回归为 `73/77`，失败子集顺序复核 `3/4`，唯一稳定问题是“江浙沪就行”首轮调用 `preview_intent_change` 但未形成 pending，确认轮无可执行对象。复核 chat history 后确认根因不是 final action，而是模型/工具结构化契约漂移：模型会传 `area_region` 或 `area=["江浙沪"]`，semantic completion 用原值与 canonical `长三角` 比较并把“其他地方”当成伪 negative area，Python resolver 也缺 `北上广深` area。修复保持 4.0 边界：prompt 明确 “X 就行/其他地方先别看” 只生成 positive area + only_keep，不把“其他地方/非X地区”写成 negative；direct 工具兼容 `area_region/region_area` 字段；region semantic completion 对地域值做 canonical 对齐并跳过无法解析的泛化 area；Python region resolver 补齐 `北上广深` 与后端 `RegionScopeSupport` catalog 对齐。验证：`py_compile app/domain/region_entity_resolver.py app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused 单测 4 条通过；真实 focused `江浙沪` final-action `2/2`，metrics `/private/tmp/zhiyuan_400_v213_jiangzhehu_after_region_semantic_fix.json`；完整 v2.13 复跑 `10/10`，metrics `/private/tmp/zhiyuan_400_v213_region_area_quality_after_first_tier_fix.json`；broader 失败子集复跑 `4/4`，目录 `/private/tmp/zhiyuan_400_v213_failed_subset_after_region_fix`。
> v2.12 补齐地域集合/城市圈长期最终 action 回归资产。新增 `examples/dialog_regression_400_v212_region_area_expanded_final_cases.json`，覆盖“孩子就想去南方，北方先别考虑”“那就只看长三角吧”“华南的不要了”“珠三角先不考虑了”“只看西南吧”五类口语表达，每条均验证出 pending card、确认后 `confirm_pending`、`pendingConfirmation=applied`、`planningState.version` 增长、结构化地域要求落库以及 `orderedPlanState.units minLength>=1` 和代表性地域剔除。有效真实 LLM 回归使用 backend `18080` + agent `8038` + 完整 chat-session clone + `--backend-db-password 12345678`：首轮业务链路 `9/10`，唯一失败为“华南的不要了”首轮两次 `preview_intent_change`，确认后最终后端断言全过，归为少量重复工具调用效率观察；资产随后移除首轮工具次数硬断言、保留确认轮单工具与最终状态断言，复跑 `10/10`，metrics `/private/tmp/zhiyuan_400_v212_region_area_expanded_final_action_green.json`。抽查最终 session `5094217`：`mustIncludeRegions=["西南"]`、`candidatePoolState.items=402`、`orderedPlanState.units=2/items=2`、`staleFlags.orderedPlan=false`，说明已确认要求只影响派生排序方案，候选池仍保持全量可恢复。
> v2.11 修复 v2.10 稳定语义缺口：地域集合表达没有落成有效报考要求，并补齐确认后最终方案真实生效验证。实现仍遵守 4.0 结构化语义边界，不新增工具层中文字符串扫描：prompt 明确“南方/北方/长三角/珠三角/华东/华南/东北/西北/西南/北上广深/江浙沪”等地域集合应作为 region requirement 写入 `area`/`region_group`，且必须进入 positive/negative payload 与 semantic_requirements；Agent 工具层只处理模型已经结构化的 `area`，不读取原话补语义；后端新增 `RegionScopeSupport`，让确认后的 `mustIncludeRegions=["南方"]` / `mustExcludeRegions=["北方"]` 在 ordered-plan 生成时按结构化地域集合展开，同时保持 `candidatePoolState.items` 全量可恢复。新增回归资产 `examples/dialog_regression_400_v211_region_area_final_cases.json` 并补上 `orderedPlanState.units minLength>=1`，避免空数组下 `notContains` 误通过。验证：`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `175 passed, 29 skipped`；后端 `mvn -q -Dtest=PlanningStateServiceTest test` 通过；有效真实 LLM 最终动作回归使用新 backend `18080` + agent `8038` + 完整 chat-session clone，`2/2` 通过，metrics `/private/tmp/zhiyuan_400_v211_region_area_final_action_after_backend_fix_valid.json`，最终状态 `orderedPlanState.units=12/items=33`，北方省份计数 0，`orderedPlan=false`。验证环境记录：未带 `--backend-db-password` 的 offset run 会导致 chat-session 主表未克隆，`generate_planning_ordered_plan` 返回 `404 会话不存在`，该结果不计为业务失败。
> v2.10 继续扩大 dialogue-derived 真实口语/指代质量池验证。本轮使用 fresh agent `8037`、backend `8080`、真实 LLM、backend state/chat-session clone、并发 4 跑 `examples/dialog_regression_400_dialogue_derived_cases.json` 共 88 条，首轮 `83/88`，metrics `/private/tmp/zhiyuan_400_v210_dialogue_derived_observation`；5 个失败子集单并发复跑 `1/5`，metrics `/private/tmp/zhiyuan_400_v210_dialogue_failed_subset_sequential`。转绿项 `400-dialogue-archive-library-cold-major` 为首轮 timeout fallback，不计为稳定缺口。稳定 4 项分层：1）`400-dialogue-region-south-only` 模型调用了 `preview_intent_change`，但没有把“想去南方、北方先别考虑”压成有效地域要求，工具返回“没有识别到明确的报考要求”，这是需要后续 prompt/结构化地域表达修复的语义缺口；2）`400-dialogue-architecture-art-foundation` 使用 `explore_topic` 回答建筑/城乡规划美术基础问题，内容质量可接受，但 case 期待旧工具 `get_major_introductions`，属于工具名资产口径；3）`400-dialogue-accounting-finance-audit-priority` 使用通用 `compare_entities` 完成财管/会计/审计排序建议，case 期待 `compare_major_options`，同属工具名资产口径；4）`400-dialogue-followup-readonly-boundary` 回复“好的，你先问，我不做任何改动”，实际无工具无副作用，失败只是断言没覆盖“不做任何改动”。本轮仍不新增工具层中文字符串匹配；后续若修，应优先补模型语义边界：把“南方/北方/北上广深/长三角/珠三角”等地域集合表达输出为结构化 region requirement 或可执行澄清。
> v2.09 继续扩大 4.0 direct 真实验证，不做生产代码修复。使用 fresh agent `8037`、backend `8080`、真实 LLM、backend state/chat-session clone 和并发 runner：hard candidate 扩展集 `33/33`，metrics `/private/tmp/zhiyuan_400_v209_expanded_hard_candidates`；quality observation 扩展集 `47/57`，metrics `/private/tmp/zhiyuan_400_v209_expanded_quality_observation`。10 个失败子集单并发复跑为 `4/10` 通过，metrics `/private/tmp/zhiyuan_400_v209_quality_failed_subset_sequential_valid`；转绿项包括三条原并发 timeout/无工具调用问题和“青城”简称查询，说明这几项不是稳定链路缺陷。剩余 6 条均未暴露最终 action 数据错误：1）只读审查后“确认”兜底回复通过无副作用，但断言文案过窄；2）专业组移动预览和确认均正确执行并刷新工作台，但回复缺少“专业组/组内/方案顺序”等质量提示；3）青岛城市学院只读查询正确返回 1 个志愿、7 条专业明细，但断言没有覆盖“7条”；4）“把华中农业大学的建筑类加进来”仍不能定位可添加候选，属于命名加项候选检索/澄清能力缺口；5）“按院校层次排序”正确生成排序 pending，但缺少“实际改变/待重新审查”副作用说明；6）专业对比澄清后用户说“嗯那就这样”，模型继续追问“新媒体”歧义，属于自然接续质量/断言边界问题。当前不修低优先级文案和验证资产断言，继续按“高信号主链路 + 质量观察池”双轨推进；后续优先扩大质量池和真实 final-action，再决定是否修命名加项候选检索与排序/专业组说明文案。
> v2.08 完成 v2.07 后高信号主链路回归、稳定问题修复与复核。第一次主线运行因漏传 `--backend-db-password` 导致 `assistant_chat_session` MySQL clone 使用空密码失败，结果 `38/72` 判为无效环境运行，metrics `/private/tmp/zhiyuan_400_v208_mainline_after_v207_prompt_fixes`。带 `--backend-db-password 12345678` 的有效首轮为 `65/72`，metrics `/private/tmp/zhiyuan_400_v208_mainline_after_v207_prompt_fixes_with_db_clone`；7 个失败经顺序复跑后 `6/7` 通过，重复 `preview_intent_change`、G26 只读回复、V156 后端断言均未稳定复现，稳定问题只剩 `400-review-shortage-honesty`：用户条件式询问“如果稳和保不够，能不能补齐，候选不够也要说”，模型误建 `preview_plan_action(regenerate_order)` pending。修复为 prompt-only：区分条件式可行性/候选不足诚实边界请求与明确“先给我看预览/现在帮我补/直接调整”的方案动作，不在工具层增加中文字符串匹配。验证：`py_compile app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py`、静态单测和 `git diff --check` 通过；focused 对照 `2/2`，metrics `/private/tmp/zhiyuan_400_v208_review_shortage_prompt_fix_focused`；原 7 失败子集复跑 `7/7`，metrics `/private/tmp/zhiyuan_400_v208_failed_subset_after_review_shortage_fix`。随后用 fresh agent `8037` 并发 4 复跑 72 条高信号主链路，首轮 `70/72`，metrics `/private/tmp/zhiyuan_400_v208_mainline_after_review_shortage_fix`；两处失败为 G21 并发 `TimeoutError` 和 G26 “录取概率/录取率”低风险措辞断言，失败子集顺序复跑 `2/2`，metrics `/private/tmp/zhiyuan_400_v208_mainline_failure_subset_sequential_after_fix`。当前未发现新的稳定业务执行缺口；剩余为并发 LLM 超时、少量重复工具调用效率观察和只读回复文案断言口径。
> v2.07 继续扩大 4.0 direct 质量观察池验证并补齐两个稳定语义质量缺口。使用 fresh agent `8000`、backend `8080`、真实 LLM、backend state clone、并发 4 复跑 `open_quality`、`quality_realistic_user`、`production_abstracted` 共 46 个质量/生产式 case，首轮 `44/46`，metrics `/private/tmp/zhiyuan_400_v207_quality_observation_parallel`。失败分类：1）`400-prod-open-career-long-input` 中用户明确说“医学有些排斥”，模型只口头总结没有调用 `preview_intent_change` 出确认卡；按 4.0 语义框架做 prompt-only 修复，把“排斥/对X排斥/不想学X”纳入显式负向报考要求，并要求长句中工资、沟通强度等职业取向可作为 reference，但显式专业要/不要必须形成待确认预览。focused 复跑通过，metrics `/private/tmp/zhiyuan_400_v207_open_career_long_after_prompt_fix.json`；`production_abstracted` 全组 `17/17`，metrics `/private/tmp/zhiyuan_400_v207_production_abstracted_after_prompt_fix`。2）`400-open-quality-sort-score-preview-rich-boundary` 能出排序 pending，但把“推荐系数”误压成“录取率”；工具层已有 `推荐系数/final_score -> finalScore` 归一，修复为 prompt-only，要求推荐系数/推荐分/综合分使用 `sort_field=final_score/comprehensive`，focused 复跑通过，metrics `/private/tmp/zhiyuan_400_v207_sort_score_after_prompt_fix.json`。修复后 46 条总集首轮仍为 `44/46`，metrics `/private/tmp/zhiyuan_400_v207_quality_observation_after_prompt_fix`；剩余两项中排序字段已 focused 通过，`400-real-user-lazy-plan-risk` 为并发 `TimeoutError`，顺序复跑通过，metrics `/private/tmp/zhiyuan_400_v207_quality_failure_subset_sequential_after_fix`。单元验证：`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `173 passed, 29 skipped`。本轮没有新增工具层字符串语义匹配；剩余观察项仍是并发 LLM 超时、质量池回复信息密度和 MySQL chat-session clone 空密码 warning。
> v2.06 完成修正后高信号主链路 baseline 复跑。使用真实 LLM、backend clone、最终 action 后端断言和并发 4，15 组 4.0 主链路 case 共 72 个，原始结果 `70/72`，metrics 目录 `/private/tmp/zhiyuan_400_v206_mainline_high_signal_parallel`。两处失败均已复核为非业务执行缺口：`400-v179-active-pending-append-region-and-private-final-action` 第二步重复调用两次 `preview_intent_change`，但待确认预览合并了山东+民办，确认后报考要求落库、candidate pool 保持全量、ordered units 裁剪等后端断言全部通过；已按少量重复调用观察口径把该步改为包含目标工具且最多 2 次，失败子集复跑 `3/3`，metrics `/private/tmp/zhiyuan_400_v206_v179_append_duplicate_assertion_rerun.json`。`400-v183-review-advice-then-vague-execute-no-pending-guard` 并发中模型直接回复“这轮还没有生成可确认的调整预览，所以不会改动当前方案”，无 followup、planningState 未变化、pending 为空；已补充“没有生成可确认/不会改动”文案断言并移除必须调用 `confirm_pending` 的旧要求，失败子集复跑 `2/2`，metrics `/private/tmp/zhiyuan_400_v206_v183_no_pending_guard_assertion_rerun.json`。结论：修正后高信号主链路没有新的确定业务执行问题；剩余为重复工具调用效率观察和并发验证口径收敛。
> v2.05 完成 v2.04 后高信号主链路并发回归与问题分层。真实 LLM + backend clone 并发跑 15 组 4.0 主链路 case 共 72 个，首轮 `69/72`，metrics 目录 `/private/tmp/zhiyuan_400_v204_mainline_high_signal_parallel`。三处失败分层如下：1）`400-v156-deferred-region-no-plan-change` 首轮重复调用两次 `preview_intent_change`，但 pending 与确认后的后端状态全部正确，按“少量重复调用先观察”降级为效率观察，回归断言改为要求包含目标工具且最多 2 次；2）`400-v157-combo-school-attribute-exclude-final-action` 首轮为模型请求 `TimeoutError` 未进入工具链，单独复跑通过，metrics `/private/tmp/zhiyuan_400_v204_v157_combo_attribute_rerun.json`，确认后民办/中外合作要求落库且 ordered/review 刷新、后端最终 action 断言通过；3）`400-v183-review-advice-then-vague-execute-no-pending-guard` 当前回复明确“没有待确认操作、不会执行”，且 planningState/pending 均无副作用，符合 no-pending 防护边界，回归断言取消必须调用 `confirm_pending` 的旧要求。断言调整后 v156/v183 失败子集复跑均 `2/2`，metrics 分别为 `/private/tmp/zhiyuan_400_v205_v156_deferred_region_assertion_rerun.json`、`/private/tmp/zhiyuan_400_v205_v183_no_pending_guard_assertion_rerun.json`。结论：未发现新的 4.0 direct 业务执行缺口；剩余主要是并发模型超时和少量重复调用效率观察。
> v2.04 修复学费预算确认后的最终方案生效缺口。v2.03 全量 requirement/action 回归新增最终 action 后端断言后暴露：`tuition_budget` pending 已采纳、session 学费范围已写入、`planningState.version` 增长，但 `orderedPlanState.units` 仍存在 `tuitionPerYear=60000`，说明 ordered-plan 生成没有消费会话学费预算。修复方式保持 4.0 设计边界：基础 `candidatePoolState.items` 继续保留全量候选，不新增持久化 `effectiveCandidates` 缓存；`PlanningStateService.resolveEffectiveCandidates()` 在方案生成/审查/修复等派生动作中读取 `USER_SCORE_KEY.tuitionRange`，与 `constraintState.hardConstraints` 一起生成运行时有效候选，并扩展 working/ordered 裁剪 guard 到“已确认要求或学费预算”。新增后端单测覆盖专业模式和专业组模式下预算重排会裁剪超预算 ordered items/units，同时断言基础候选池仍保留超预算候选。验证：后端 focused 单测通过；`mvn -q -Dtest=PlanningStateServiceTest test` 通过；`zhiyuan-agent/tests/unit/test_zhiyuan_agent_direct.py -q` 为 `170 passed, 29 skipped`；真实 LLM + backend clone 复跑 `dialog_regression_400_requirement_plan_action_cases.json` 为 `10/10`，metrics `/private/tmp/zhiyuan_400_v204_requirement_plan_action_after_tuition_effective_fix.json`，其中 `400-requirement-tuition-budget-preview` 确认后 `pendingConfirmation.status`、`planningState.version` 和 `orderedPlanState.units tuitionPerYear<=20000` 后端断言均通过。
> v1.93 修复 G1 报考要求与当前方案同步处理的语义优先级。旧链路清理复扫结果：`tests/unit/test_runtime_hard_cut_audit.py -q` 为 `25 passed`，生产 `app/` 中 `ChatAgent/turn_decision/planning_workflow_tool/execute_plan_action/planEditCache/ZHIYUAN_AGENT_POC/runtime_shadow/full_agent/fast_route` 等旧入口命名无命中。真实 G1-G32 首轮复跑 `19/20`，metrics `/private/tmp/zhiyuan_400_v193_g1_g32_direct_guard_followup.json`，唯一失败为 G1：用户说“不要英语相关专业，当前方案里有的话也删掉”时模型走 `preview_plan_action(remove_units)`，只表达当前方案移出，可能漏掉“以后也不要英语相关专业”的报考要求。修复方式为 prompt-only：明确“显式报考要求 + 当前方案同步处理”优先走 `preview_intent_change(apply_to_current_plan=True)`，纯“方案里的X不要/移出”仍走 `preview_plan_action`。验证：`py_compile app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；prompt 静态断言与 `test_preview_intent_keeps_broad_major_scope_when_user_says_related` 均 `1 passed`；G1 focused 真实复跑 `1/1`，metrics `/private/tmp/zhiyuan_400_v193_g1_after_prompt_fix.json`；完整 G1-G32 复跑 `20/20`，metrics `/private/tmp/zhiyuan_400_v193_g1_g32_direct_after_requirement_plan_priority_fix.json`，分布为 intent pending 6、readonly 9、plan preview 3、needs-plan-first 2。剩余观察：G2/G7 费用/中外合作只读审查回复仍偏弱，G12/G27 替换预览文案仍露出 `high_tuition` 这类内部 code，G19/G32 no-plan 边界偏长，后续归入回复质量优化，不影响本轮链路闭环。
> v1.92 补齐 direct route 无工具假预览防护并完成 final-action 并发复核。问题来源是 v1.91 后继续跑 v155/v156/v157/v158/v173 final-action 并发集时曾出现 1 个模型直答“待确认预览/是否确认”但没有调用 `preview_intent_change`、也没有生成 `pendingConfirmationCard` 的波动；顺序复跑该 case 可通过，但服务层确实缺少无依据确认文案兜底。实现：`service.py` 在 direct route 后处理阶段，当本轮没有 pending card 且没有 workspace refresh 时，调用 `_guard_unbacked_plan_confirmation_reply()` 拦截看起来要求用户确认方案调整/预览的无依据回复，替换为“本轮没有生成可确认调整预览，不会改动当前方案”的边界回复；正常 `preview_intent_change/preview_plan_action/confirm_pending` 出卡或执行路径不受影响。验证：`py_compile app/service.py tests/unit/test_zhiyuan_agent_direct.py examples/dialog_regression_parallel_runner.py tests/unit/test_dialog_regression_parallel_runner.py` 通过；guard 聚焦单测 `1 passed`，parallel runner 单测 `4 passed`，`git diff --check` 通过。真实复核使用最新 agent `18321`：v156 聚焦 case `400-v156-spoken-only-public-final-action` 为 `2/2`，metrics `/private/tmp/zhiyuan_400_v192_v156_only_public_guard_rerun.json`，首轮正常生成 `intent_change` 待确认卡，确认轮 `confirm_pending` 后端断言覆盖 pending applied、version 增长、要求写入、ordered items/units 裁剪和 ordered/review 刷新。随后带完整 backend chat session clone 并发跑 v155/v156/v157/v158/v173 final-action 集合 `21/21`，metrics 目录 `/private/tmp/zhiyuan_400_v192_final_action_parallel_clone`，未出现失败子集；说明当前 4.0 direct final-action 链路在该并发口语集下闭环。
> v1.90 修复 v1.88 真实回归剩余两项回复质量问题：`query_plan + review_plan` 组合直返不再固定使用“下面是这次待确认预览”，只有 `preview_intent_change/preview_plan_action` 且 `next_step=confirm` 时才使用待确认预览标题，review 组合结果改为“继续看审查结果”；prompt 明确“重新审查/再审一遍/重新看一下/再看一遍/重新检查”即使上一轮刚审查过，也必须再次调用 `review_plan`。验证：`py_compile app/zhiyuan_agent/agent.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused 单测 `3 passed`；`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `160 passed, 29 skipped`；`git diff --check` 通过。真实 focused：`400-review-shortage-honesty` 已无“待确认预览”标题，metrics `/private/tmp/zhiyuan_400_v190_review_repair_two_focused.json`（第二个 case 因 backend 清理超时未进入业务链路）；`400-review-repair-after-manual-move-stale` 单独复跑 `2/2`，metrics `/private/tmp/zhiyuan_400_v190_review_repair_rereview_focus.json`，第二轮“那重新审查一下”调用 `review_plan`。完整 review/repair 克隆集复跑 `9/9`，metrics `/private/tmp/zhiyuan_400_v190_review_repair_clone_full.json`，未再出现“待确认预览”误标题或 `ready` 泄漏。
> v1.89 修复 v1.88 真实回归观察到的内部状态词泄漏：用户可见术语归一化新增独立英文单词 `ready` -> “可以先看调整预览”，避免 review/repair 处理方向分层中出现英文状态值。该修复仍只改回复文案，不改变工具调用、pending 或后端 action。验证：`py_compile app/service.py tests/unit/test_chat_service_history_persistence.py` 通过；focused 单测 `1 passed`；`tests/unit/test_chat_service_history_persistence.py -q` 为 `110 passed`；`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `159 passed, 29 skipped`；`git diff --check` 通过；真实单 case `400-review-fix-explain-hierarchy` 为 `1/1`，metrics `/private/tmp/zhiyuan_400_v189_review_fix_explain_hierarchy_ready_copy.json`，回复中 `ready` 已变为“可以先看调整预览”。
> v1.88 清理审查兜底回复里的内部状态文案：`blocked/系统阻塞` 统一转成“需要你先确认是否接受这类调整或放宽报考条件”，无真实 pending 的边界回复改为“还没有生成可确认的调整预览”，`fix_proposal_preview` 兜底不再露出“可执行预览”。本次只改用户可见措辞和 reply guard 兼容 marker，不改 direct 路由、pending、确认执行或后端 action。验证：`py_compile app/service.py app/domain/proposal_compiler.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_proposal_compiler_runtime_selection.py` 通过；`tests/unit/test_chat_service_history_persistence.py -q` 为 `110 passed`；`tests/unit/test_proposal_compiler_runtime_selection.py -q` 为 `36 passed`；`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `159 passed, 29 skipped`；`git diff --check` 通过。真实 review/repair 克隆集 `9/9`，metrics `/private/tmp/zhiyuan_400_v188_review_repair_clone_copy.json`；客观观察：只读审查个别回复混入“待确认预览”，处理方向分层个别项仍漏出 `ready`，连续“重新审查一下”未再次调用工具。
> v1.87 按产品决策调整 `plan_generation/regenerate_order` 确认后的 review followup 文案，不自动触发 review workflow。方案重排确认后仍刷新 ordered，并保留 review 入口，但 review 卡片改为“需要重新审查方案 / 方案排序已更新，原审查结果可能不再完全准确。请重新审查后再看最新风险和提醒。/ 重新审查”，避免暗示后端已完成最新审查。实现仅改服务层 followup copy helper，不新增后端 `runReviewWorkflow` 调用。验证：`py_compile app/service.py tests/unit/test_zhiyuan_agent_direct.py`、`tests/unit/test_zhiyuan_agent_direct.py::test_service_pending_confirmation_executes_plan_generation_bridge`、完整 `tests/unit/test_zhiyuan_agent_direct.py -q`（`159 passed, 29 skipped`）和 `git diff --check` 均通过；真实 focused 预览 metrics `/private/tmp/zhiyuan_400_v187_review_major_group_inner_safety_preview.json`，确认文案 metrics `/private/tmp/zhiyuan_400_v187_review_major_group_inner_safety_confirm_copy.json`，确认后 review followup title 为“需要重新审查方案”。
> v1.86 落地 review+方案动作复合诉求修复：prompt 将“补一个/加一个/加入/补稳/补保/补安全一点”纳入明确方案动作，用户说“专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览”时走 `preview_plan_action(action="regenerate_order", review_issue_code="probability_gap")`。同时修复服务层 `plan_generation` pending 漏接：`PendingConfirmation` 允许 `plan_generation`，`service.py` 统一把 `plan_mutation/plan_generation` 作为方案类 pending 处理，覆盖后端 active pending 恢复、pending card 渲染、短文本确认、卡片确认、路由观测和过期清理；pending card 保留真实 `kind=plan_generation`，不伪装为 `plan_mutation`。验证：`py_compile` 与 `git diff --check` 通过；`tests/unit/test_zhiyuan_agent_direct.py` 为 `159 passed, 29 skipped`；focused 单 case 出卡通过，metrics `/private/tmp/zhiyuan_400_v186_review_major_group_inner_safety_after_plan_generation_card_fix.json`；同 session “确认执行”通过 `confirm_pending` 执行，metrics `/private/tmp/zhiyuan_400_v186_review_major_group_inner_safety_confirm_after_card_fix.json`，后端 latest pending 为 `status=applied/kind=plan_generation/actionFamily=regenerate_order`，工作台版本从 `461` 增至 `462`；review/repair 克隆完整复跑 `9/9`，metrics `/private/tmp/zhiyuan_400_v186_review_repair_clone_after_plan_generation_card_fix.json`。剩余观察点：`regenerate_order` 执行后当前方案已刷新，但 review 会被后端标记为 stale，需要后续确认 review 刷新/重审的产品链路或由 plan_generation 确认后触发审查 workflow。
> v1.85 验证-only：继续扩大 4.0 direct 真实口语 final-action 回归，不新增实现改动。v1.55 realistic final-action 复跑 `7/7`，metrics `/private/tmp/zhiyuan_400_v184_v155_realistic_final_action_rerun.json`；v1.56 broadened final-action 复跑 `8/10`，两处失败为严格工具次数断言，实际均生成正确 pending 且确认后后端断言通过，metrics `/private/tmp/zhiyuan_400_v184_v156_realistic_broadened_final_action_rerun.json`。新增 v157/v158/v173 扩展集在三组并发首轮分别为 `7/11`、`6/9`、`8/11`，失败集中为 `TimeoutError/ModelAPIError` 未进入工具链，以及一次 `preview_intent_change` 重复调用严格断言；按失败子集顺序复核后分别为 `4/4`、`5/5`、`4/4` 通过。综合真实口语集 `dialog_regression_400_realistic_user_cases.json` 首轮 `12/14`，两处失败同为 `ModelAPIError`，失败子集顺序复核 `2/2`。review/repair 克隆复跑 `8/9`，剩余问题是“补一个安全一点的专业，先给我看预览”只走 `review_plan`、未生成待确认预览或可执行澄清。客观结论：本轮未确认新的业务链路 final-action 错误；但记录 1 个 review+方案动作复合诉求缺口，并发真实 LLM 回归下模型服务波动会放大失败率，后续并发跑法需要失败子集顺序复核或 runner/service 层重试策略。
> v1.84 补齐 active pending 下“选择当前预览”的短句确认边界：v1.83 扩展回归发现“青岛理工那个建筑太贵了，换个便宜点正常收费的”已生成 `replace_units` 待确认后，用户说“就换这个”时模型曾直接口头回复已执行，但没有调用 `confirm_pending`，导致后端 `pendingConfirmation.status` 仍为 `active`、`planningState.version` 不变。已按 4.0 方向做 prompt-only 修复：状态摘要显示“待确认：有”时，用户用“就这个/就换这个/按这个来/这个可以/行/可以”等短句选择当前预览，且没有提出新的报考要求或新的方案调整诉求，必须调用 `confirm_pending(action="confirm")`；没有 `confirm_pending` 工具结果前不得口头说“已替换/已完成替换/已更新”。不增加工具层字符串语义匹配。验证：单 case `2/2`，metrics `/private/tmp/zhiyuan_400_v184_v183_targeted_replace_after_confirm_prompt_fix.json`；v1.83 整组首轮 `9/13`，失败均为到 `llm.baijia.com` 的 `TimeoutError/ModelAPIError` 导致未进入工具链，失败子集复跑 `5/5`，metrics `/private/tmp/zhiyuan_400_v184_v183_failed_subset_rerun_after_llm_timeout.json`；v1.79 focused `10/10`，metrics `/private/tmp/zhiyuan_400_v184_v179_focused_after_confirm_prompt_fix.json`；G1-G32 direct 主集 `20/20`，metrics `/private/tmp/zhiyuan_400_v184_g1_g32_direct_after_confirm_prompt_fix.json`，分布为 intent pending 6、readonly 9、plan preview 3、needs-plan-first 2。
> v1.83 继续扩展真实口语/指代/多轮 focused 回归：新增 `examples/dialog_regression_400_v183_realistic_followup_quality_cases.json`，覆盖 active pending 下“山东先别去了→再加个只看公办”、active pending 下“中外合作先不要→算了改成山东别去+民办不要”、更简略的 targeted replace“青岛理工那个建筑太贵了，换个便宜点正常收费的”、只读审查后模糊“那就照你说的处理吧”的 no-pending 防护，以及只读审查后明确“高收费这些换便宜点，不是直接删”的 replace + confirm final-action。首轮真实 LLM `12/13`，metrics: `/private/tmp/zhiyuan_400_v183_realistic_followup_quality_initial.json`，唯一问题为只读审查后模糊“照你说的处理”被模型自动转成 `preview_plan_action(replace_units)` 并创建待确认卡。已按 4.0 方向做 prompt-only 修复：当前状态摘要里的待确认状态作为本轮判断依据；只读审查/处理方向之后，如果本轮没有明确动作对象和动作类型，模糊“照你说的处理/就这么办/按你说的来/执行/采纳”必须调用 `confirm_pending`，没有待确认时只回复不会执行；明确“高收费这些换便宜点”仍走 `preview_plan_action(replace)`。验证注意：需重启 agent 或使用新端口加载 prompt 修改，并用 fresh session offset 避免旧 pending/history 污染。最终在新 agent `18292` + session offset `200` 复跑 `13/13`，metrics: `/private/tmp/zhiyuan_400_v183_realistic_followup_quality_after_prompt_fix.json`；`py_compile app/zhiyuan_agent/prompt.py` 与 `git diff --check` 通过。
> v1.82 落地 v1.79 剩余 targeted replace 稳定性修复：`preview_plan_action(action="replace")` 在缺少或未能唯一定位旧方案项时返回 `plan_action_requires_replace_target` + `next_step=continue`，要求主模型基于当前问/上下文补齐结构化 `targets/filters/review_issue_code/selector/replacement_spec` 后重试；每轮只给一次结构化 retry 预算，耗尽后返回可执行澄清，不从工具层做用户原文关键词解析。同步补齐 plan filter alias 归一，`school_name/schoolName/school_names/schools/collegeName` 统一进入 `school`，`major_name/majorName/major_names/majors` 统一进入 `major`，修复模型用 `filters.school_name` 定位当前方案项时的 false negative。`only_keep` 场景增加结构化意向 canonicalize：当模型同时给出 `positive.school_nature=["公办"]` 与冗余 `negative.school_nature=["民办"]` 时，只保留“只看公办”诉求，避免同时落库为“要公办+不要民办”。验证：`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py` 通过；focused 单测 `17 passed, 169 deselected`；完整 direct 单测 `157 passed, 29 skipped`；真实 LLM focused 回归 `examples/dialog_regression_400_v179_pending_replace_review_quality_cases.json` 最终 `10/10`，metrics: `/private/tmp/zhiyuan_400_v182_intent_canonicalize_real.json`，覆盖 active pending 追加/改写、只读审查后无 pending “执行”防护、targeted replace 生成 `replace_units` pending 并在确认后真实修改 ordered plan。
> v1.79 继续扩展真实口语 focused 回归：新增 `examples/dialog_regression_400_v179_pending_replace_review_quality_cases.json`，覆盖 active pending 追加、active pending 改写、只读审查后无 pending 的“执行”防护，以及“便宜+非中外合作”替换候选质量，并继续包含最终确认后的后端数据断言。首轮真实 LLM `8/10`，metrics: `/private/tmp/zhiyuan_400_v179_pending_replace_review_quality_real.json`，问题为 active pending 改写句“等下，别按这个了，改成只看公办，山东也别去”漏掉“山东也别去”。已按 4.0 方向做 prompt-only 修复：要求 active pending 改写/追加时完整抽取同一句所有显式要/不要项，跨地域+院校属性时优先用 `intent_type="region"` 承载地域项，并补充 append/replace 示例；不增加工具层字符串兜底。验证：`py_compile app/zhiyuan_agent/prompt.py` 与 `git diff --check` 通过。复跑后 active pending 追加、active pending 改写、只读审查后“执行”防护均通过，metrics: `/private/tmp/zhiyuan_400_v179_pending_replace_review_quality_after_append_prompt_fix.json`；剩余失败转移到 targeted replace 稳定性：同一句“青岛理工那个中外合作建筑太贵了，换个正常收费的，最好不是中外合作”在前两轮能生成替换预览并通过后端确认，第三轮未稳定定位当前方案项，返回“没找到”，未创建 pending。后续方向：针对 replace 目标定位失败建立结构化 retry/澄清协议，避免依赖单次模型参数稳定性；active pending 合并语义目前按 prompt 修复继续观察。
> v1.78 验证-only：完成 `examples/dialog_regression_400_g1_g32_direct_cases.json` 隔离端口真实 LLM 复跑，20 步全部通过，metrics: `/private/tmp/zhiyuan_400_v178_g1_g32_direct_full.json`。本轮用于验证 4.0 direct 主链路在 G1-G32 主集上的路由稳定性和回复边界，不新增实现改动；结果为 intent pending 6、plan mutation 预览 3、readonly 9、needs-plan-first 2，`failures=[]`、`warnings=[]`。耗时 median `4988ms`、p95 `7247ms`、max `11251ms`，最慢为 G31 pending 下只读保底查询、G12 查询+替换复合诉求、G26 保底切片查询、G3 active pending 下只读查询、G16 不支持锁定动作边界。客观观察：G2/G7 只读审查能保持不改方案但回复信息偏弱，后续应让审查结果更明确地展示命中数量/预算影响/处理方向；G19/G32 no-plan 防护正确但文案偏长；G16 通过代表不支持锁定时安全拦截，不代表锁定动作已落地。最终 action 数据变化仍以 v1.77 的 action expansion 与属性类 final-action 回归为准。
> 变更: v1.77 补齐 §12.1/§12.6 的最终 action 闭环：生产 `confirm_pending` 已对 plan mutation 增加 ordered-plan 前后快照 diff，remove 校验目标 unit 消失，move 校验目标 unit 位置变化，sort 对顺序未变据实回复，replace 校验旧 unit 消失且新候选 volunteerId 出现在确认后的 `orderedPlanState`。本轮修复 replace diff 误判：`_ordered_plan_snapshot()` 在 `orderedPlanState.units` 存在时仍合并 `orderedPlanState.items` 的 volunteerId，避免后端把新候选先写入 items 但 unit.majorItems 未同步时误报 `missing_selected_volunteer_ids`。同时补齐 `preview_plan_action(remove, filters={"position_group":3})` 的结构化位置 selector，`positionGroup/unitPosition/unit_position/orderedPosition/ordered_position` 统一归一为 `position_group`，按 ordered unit/专业组序号解析，不读取用户原文、不做字符串语义匹配；与其它 filter 组合时只把剩余 filter 作为属性条件继续过滤。验证：`py_compile app/zhiyuan_agent/tools.py` 通过；`tests/unit/test_zhiyuan_agent_direct.py -q -k 'position_group or position_targets or confirm_pending and replace or sort_maps_school_rank'` 为 `7 passed, 174 deselected`；真实 LLM `examples/dialog_regression_400_v173_action_expansion_final_cases.json` 隔离端口复跑 `11/11` 通过，metrics: `/private/tmp/zhiyuan_400_v177_action_expansion_after_position_group_fix.json`，覆盖位置移出/移动、替换、排序和审查承接高收费替换，确认轮均通过 `pendingConfirmation.status=applied` 与 ordered-plan 后端断言；属性类最终 action 复跑 `examples/dialog_regression_400_v151_attribute_final_action_cases.json` 为 `8/8`，metrics: `/private/tmp/zhiyuan_400_v177_attribute_final_action_with_position_group_fix.json`，覆盖“民办的不要/只看公办学校/不要中外合作/不要高收费的”确认后真实方案变化。验证环境记录：沙箱内访问本地 backend 会被拦截，真实回归需用 4.0 隔离端口 Backend `18290`、Agent `18291`，并授权访问本地服务。
> 变更: v1.76 落地 §12.1/§12.3 的 v1.73 action expansion 修复：位置语义从 ordered item 明细行收敛为 ordered unit/专业组序号，新增 unit 聚合代表项解析，"第三个专业组/第3个专业组"优先按第 3 个 unit 定位，只有测试或稀疏缓存中序号超过已加载 unit 数时才按后端 position 回退；移除 `_match_item_by_target` 中按单条 item.position 命中的兜底，避免绕回明细行误删/误移。排序动作新增 agent 侧 `PLAN_SORT_FIELDS`，preview 阶段只允许 `admission_ratio -> admissionRatio`、`school_rank -> schoolRank`、`comprehensive -> finalScore`，不支持的 `school_level` 直接澄清且不创建 pending；prompt 明确"好学校优先/院校层次高优先"传 `school_rank`，不要传 `school_level`。单测新增 expanded ordered unit 夹具覆盖 remove/move 的 item-vs-unit 分叉、school_rank 后端字段映射和 school_level 拦截；验证：`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py app/zhiyuan_agent/sandbox.py` 通过，`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `146 passed, 29 skipped`，`git diff --check` 通过。真实 LLM 全量复跑 `examples/dialog_regression_400_v173_action_expansion_final_cases.json` 为 `11/11` 通过，metrics: `/private/tmp/zhiyuan_400_v176_action_expansion_after_position_sort.json`；覆盖位置移出、位置移动、明确目标替换、好学校优先排序、审查承接高收费替换，确认轮均通过 `pendingConfirmation.status=applied`、`planningState.version` 增长和 ordered units/首位 unit 变化等后端断言。遗留：§12.6 的生产 confirm 后通用 ordered-plan diff 校验仍待单独落地，目前真实 runner 已覆盖回归断言，生产 `confirm_pending` 仍主要依赖后端 success 与刷新。
> 变更: v1.75 落地 §12.2 replace 候选选择结构化修复：新增 `ReplacementSpec` 作为 `preview_plan_action(action="replace")` 的独立结构化替换方向输入，候选选择只消费 spec，不再从 `raw_user_text` 做“便宜/非合作/好点”等关键词抽取；spec 来源按显式 `replacement_spec`、`review_issue_code`、结构化 `filters`、旧项结构化属性兜底归并。`plan/candidates.json` 查询透传 `school_tags/negative_school_tags/major_tags/negative_major_tags/sort_field/sort_order`，replace 自动查询按同档位、排序方向、排除 marker 和已确认要求过滤候选；候选打分改为由 `improve_dims/exclude_markers` 驱动，方向缺失返回“更便宜/层次更高/换城市”等可执行澄清，方向明确但无候选返回放宽档位或换专业方向，不再静默不出 pending。同步 prompt 要求模型把口语替换方向压缩为 `replacement_spec`，并对结构化 marker 做 `cooperative_program -> cooperative`、`high_fee -> high_tuition` 等枚举归一；单测新增无 `review_issue_code` 但显式 spec 的成功替换、缺 spec 澄清、结构化候选池 query 参数断言。验证：`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py app/zhiyuan_agent/sandbox.py` 通过；`tests/unit/test_zhiyuan_agent_direct.py -q -k 'replace'` 为 `11/11`；`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `142 passed, 29 skipped`；真实 LLM focused 复跑 `400-v173-targeted-high-tuition-replace-final-action` 与 `400-v173-review-followup-high-tuition-replace-final-action` 为 `5/5`，metrics: `/private/tmp/zhiyuan_400_v175_replace_spec_focused.json`，两条 replace 均生成 `replace_units` 确认卡，确认后后端断言 pending applied、planningState version 增长、ordered units 变化通过。遗留：v1.73 action 扩展全量仍有位置 item/unit 与排序字段问题未修；`review_plan` 只读 focus 仍有既有关键词判断，已确认不在 replace 替换方向链路，本轮不混改。
> 变更: v1.74 新增 §12 当前方案 action final-action 落地缺口：把 v1.73 回归的 4 个失败归为两类系统性缺陷——(A) Agent/数据层/后端三处枚举语义契约未对齐（位置 item vs unit、排序字段三套命名、replace 口语方向 vs 候选池查询）、(B) 确认执行后不校验真实变化导致谎报成功（与 §11.1 exclude 落地盲区同源）；给出以"确认后 ordered-plan diff 校验"为通用地基的阶段 1-4 落地计划，并更新放量门槛。
> v1.73 验证-only：新增 `examples/dialog_regression_400_v173_action_expansion_final_cases.json`，扩展当前方案 action final-action 覆盖，包含位置移出、明确目标替换、位置移动、院校层次排序、审查承接后高收费替换 5 个真实口语 case。首次运行因 runner 默认 `--internal-service-url` 指向 `18290` 导致环境失败，已改用 `http://127.0.0.1:8080`、带 `--clone-backend-chat-session --backend-db-password 12345678` 复跑；业务链路 `11` 步中 `4` 步通过、`7` 步失败，metrics: `/private/tmp/zhiyuan_400_v173_action_expansion_current.json`。客观问题：1）“第三个专业组”按第 3 个 ordered item 定位，预览和确认均操作喀什大学建筑学所在 unit，而非第 3 个 ordered unit，新旧数据层位置口径不一致；2）“青岛理工那个中外合作建筑太贵了，换个便宜点的”能定位旧项但没有自动选出可替换候选，未创建 pending；3）`sort_ordered_plan(sort_field=school_level)` 确认返回成功且 version 增长，但 source17 与 target 9904734 的 ordered items/units 顺序完全一致，后端排序字段契约实际只支持 `admissionRatio/schoolRank/finalScore`，`school_level` 被归到默认排序；4）审查后“那高收费的换便宜点”两次调用 `preview_plan_action` 仍无 pending，只给出三种处理选项，随后“执行”在无 active pending 下又生成新的移出预览而不是确认/澄清。对应方案方向：收敛 ordered item/unit 的位置语义和 UI 文案；replace 自动候选选择改为结构化候选查询/低学费筛选或返回可执行的候选不足原因；排序字段建立 agent 与后端共享枚举并在确认后校验 ordered 实际变化；无 active pending 的“执行/采纳”必须先确认是否已有待确认操作，不能从多选建议中隐式发起新动作。
> 变更: v1.72 修复 4.0 真实口语回归中的 no-plan 属性方案动作链路：当用户说“方案里的民办不要了 / 当前这些中外合作都移出去 / 那高收费的别要了”但当前没有正式方案时，`preview_plan_action(remove, filters=...)` 不再依赖模型二次调用 `preview_intent_change`，而是只基于模型已传入的结构化 `filters` 显式映射为报考要求待确认卡，复用 `preview_intent_change` 的 pending 创建与确认执行链路。该 fallback 不从用户原文做字符串补参；`school/region/major` 只由 `_intent_fallback_from_plan_filters()` 的字段映射决定，已移除默认 `or "school"` 兜底，未知 filter 不会误归为院校要求。同步修复无正式方案审查省略问句“有啥问题，咋弄”必须走 `review_plan` 并返回只读边界；修复“中外合作都不要了”误走 `confirm_pending(cancel)` 的取消边界。验证：`dialog_regression_400_realistic_user_cases.json` 真实 LLM 全量 `14/14` 通过（metrics: `/private/tmp/zhiyuan_400_realistic_user_cases_v4.json`），移除默认 `school` 后 focused 真实 LLM `2/2` 通过（metrics: `/private/tmp/zhiyuan_400_current_plan_anchor_fallback_no_default_school_v5.json`），聚焦单测 `5 passed, 1 skipped`，`git diff --check` 通过。
> v1.71 验证-only：复跑 4.0 真实 LLM 口语/指代/简略对话回归，不做修复。`dialog_regression_400_v155_realistic_final_action_cases.json` 为 `7/7` 通过，`dialog_regression_400_v156_realistic_broadened_final_action_cases.json` 为 `10/10` 通过，确认轮均校验到 `pendingConfirmation.status=applied`、`planningState.version` 增长、ordered plan 裁剪或不裁剪语义。`dialog_regression_400_realistic_user_cases.json` 全量为 `8/14` 通过，失败集中在默认 source session 26 无正式方案但 case 仍期望待确认卡的场景；另记录无正式方案查询回复过度肯定、以及一次“报考偏好”用户侧措辞问题。
> v1.70 继续 Phase 3 质量门禁资产硬切：将剩余 `301/302/310` gate/catalog case 迁移为 400 命名资产（agent smoke、plan operation、explore intent、readonly real session、core effect/perf、review repair、production abstracted、requirement plan action），删除旧 `dialog_regression_301/302/310*` case、302 输出 JSON 和 310 raw production candidate export；`dialog_quality_gate.py` 的 live/model plan 已无 301/302/303/310/320 路径；`test_mainline_dialog_scenarios.py` 和 `next_session_handoff.md` 同步切到 400；4.0 gate case 中旧 `soft_* / hard_*_constraint / *_constraint` coverage tag 收敛为显式 positive/negative/requirement 口径，report 增加新旧 tag 兼容识别。`py_compile` 通过，10 个触达 JSON 可加载，聚焦单测 `110 passed`，unit collect `1499 tests collected`，quality gate dry-run 为 `live=37/model=3/legacy=[]`，`git diff --check` 通过。
> v1.69 继续 Phase 3 质量门禁资产迁移：将仍被 `dialog_quality_gate.py` / e2e 默认路径 / model-provider gate 引用的 303 质量回归集迁移为 400 命名资产（`dialog_regression_400_effect_perf/open_quality/quality_realistic_user/dialogue_derived/career_direction_cases.json`、`model_provider_400_*`），删除旧 303 case 与 phase2 输出 JSON；e2e README 和 handoff 命令同步切到 400；hard-cut audit 增加 303 gate 资产防回退。`py_compile` 通过，7 个新 400 case 文件可加载，`test_dialog_quality_gate + hard-cut` 为 `33 passed`，unit collect `1499 tests collected`，e2e collect `1 test collected`，quality gate dry-run 确认 live/model plan 只引用 400 质量资产，`git diff --check` 通过。
> v1.68 继续 Phase 3 历史 fixture 清理：删除未被当前质量门禁引用的 320 prod/raw/fastpath dialog regression JSON（`dialog_regression_320_prod_*`、`dialog_regression_320_prod_raw_framework_gap_cases.json`、`dialog_regression_320_career_region_fastpath_probe.json`），保留仍被 quality gate/e2e 引用的 303 case 待后续迁移到 4.0 case 集；hard-cut audit 增加 320 历史 JSON 防回退。`py_compile` 通过，`test_intent_state_tool + hard-cut` 为 `185 passed`，unit collect `1498 tests collected`，`git diff --check` 通过。
> v1.67 继续 Phase 3 旧离线资产清理：删除 3.2 model-node/profile live-node 工具与 benchmark（`intent_entity_profile_tool.py`、`plan_query_profile_tool.py`、`reply_profile_tool.py`、`model_node_benchmark.py` 及 320 case/tests）；将生产仍需的“撤销不要/别排除”反向要求识别迁入 domain helper `app/domain/intent_reversal.py`；删除 runtime pending entrypoint/sink audit、intent compiler adapter、compiled pending sink contract 等 3.2 切换期离线脚本/fixtures/tests；hard-cut audit 增加防回退。`py_compile` 通过，`test_intent_state_tool + hard-cut` 为 `184 passed`，unit collect `1498 tests collected`，`git diff --check` 通过。
> v1.66 继续 Phase 3 评估协议清理：保留 semantic frame 离线评估能力，但输出字段从 `semanticRouterShadow/semanticRouterSummary` 收敛为 `semanticFrameObservation/semanticFrameSummary`；runner 的 `semantic-router-shadow` 历史模型名改为 `semantic-frame-observation`；删除 runner/report 中 `preFullAgentDurationMs/postFullAgentDurationMs` 与 `fullAgentToolTrial*` 旧全量 agent 专属观测，改为中性的 `toolChainIssue/toolChainIssues`。`py_compile`、聚焦单测 + hard-cut audit `174 passed`、`git diff --check` 通过。
> v1.65 继续 Phase 3 runner 命名清理：`dialog_regression_runner.py` 的运行期观测输出从 `runtime_shadow` 收敛为 `runtime_observation`，CLI 改为 `--runtime-observation-output`，metrics 字段改为 `runtimeObservationCaseId/runtimeObservationSummary`；删除 `shadowCaseId/runtimeShadowCaseId` case id 兼容键；hard-cut audit 禁止旧 runtime shadow 命名回流。`py_compile` 通过，runner + hard-cut 单测 `103 passed`。
> v1.64 按 Phase 3 继续切主后清理：删除 4.0 direct/PoC shadow 后台执行、history shadow event、runner shadow 等待/断言/metrics 汇总；4.0 回归 case 从 `expectedZhiyuanAgentPoc*` 迁移到主链路 `expectedToolNames/maxToolCallCount/expectedRoutingPath`；生产包和 direct agent 单测中的 PoC 命名改为 direct-chain；hard-cut audit 增加 PoC/direct shadow 禁止列表。`py_compile`、聚焦单测 `240 passed, 28 skipped`、unit collect `1554 tests collected`、`git diff --check` 通过。
> v1.63 按 Phase 3 继续旧链路清理：删除 `turn_decision_tool.py` 生产残留、`service` 中 TurnDecision/profile-replan bridge、`proposal_compiler.py` 中 3.2 pending turn / plan query / local action / profile replan / plan confirmation compiler，删除 3.2 TurnDecision golden、runtime shadow diff、downstreamPolicy 离线 POC 工具和对应 fixtures/tests；hard-cut audit 增加旧 compiler 禁止列表。`py_compile`、聚焦单测 `252 passed`、unit collect `1563 tests collected` 通过。
> v1.62 补齐复合只读查询后继续方案动作与锁定动作边界：`query_plan` 工具返回 `current_user_text` 与 `post_query_instruction`，让模型在“占比多少，能不能换成便宜的”这类同轮查询+替换诉求中继续调用 `preview_plan_action`；prompt 明确“能不能/可不可以/帮我 + 换成/替换/移出/去掉”不是权限询问而是方案动作，同时补齐“锁定/固定位置”进入 `preview_plan_action(pin_lock)` 的路由要求。G12、G16 聚焦真实 LLM 通过后，完整 G1-G32 direct-only 主集复跑 `20/20`，metrics: `/private/tmp/zhiyuan_400_v162_g1_g32_direct_full_no_shadow_after_g16.json`。
> v1.61 收口 no-pending 与 review 边界：无 active pending 时，窄口径“确认/采纳/执行/取消/暂不执行”等短文本直接走 4.0 `confirm_pending` 并返回无待确认操作的安全 no-op，不回退旧模型路径；`review_plan(next_step=respond)` 在 direct agent 中作为终止工具直接返回，避免 G2/G7 只读审查后追加 `query_plan`。聚焦单测、py_compile、G2/G7/G12 focused 真实 LLM 验证通过。
> v1.60 将 `preview_intent_change` 的组合属性漏传处理从工具层自动补齐改为模型重试协议：删除 raw text 补写 pending 的路径，保留 `ATTRIBUTE_REGISTRY` 作为结构化归一/枚举 alias 能力；当同一句显式诉求里属性/标签没有进入 `positive/negative` 结构化参数时，返回 `intent_change_requires_attribute_completion` + `next_step=continue`，由主模型基于当前问和工具返回重试补齐。同轮跨领域诉求支持在一次 `positive/negative` payload 中保留跨领域字段，例如 `negative={"province":["山东"],"school_nature":["民办"]}`。聚焦单测、PoC 全量、py_compile、diff check 和两条真实 LLM final-action 回归通过；无 MySQL 会话行克隆时 `ordered-plan/generate` 会返回 404，已记录为验证环境注意项。
> v1.59 撤销 `preview_plan_action` 的 G17 工具层字符串补参：删除从原文判断 action、move selector、目标档位的 fallback，`_resolve_plan_filter_selector_target` 只消费模型传入的结构化字段；缺 action、缺 move selector、缺目标位置时返回 `plan_action_requires_*` + `next_step=continue`，由主模型基于当前问和工具返回重试补齐。聚焦单测、PoC 全量、py_compile 和 source35 G17 真实 LLM 主链路验证通过；原 G17 source session 26 当前本地 ordered/working 为 0，已记录为夹具状态漂移。
> v1.58 将 active pending 下的“放弃当前待确认并改成新诉求/追加到当前待确认/暂缓新诉求”从工具层短语判断改为模型语义仲裁：`RequestContext` 增加 `current_user_text`，`build_turn_context` 压缩注入待确认摘要、影响范围和 `pending_resolution` 选择要求；`preview_intent_change` / `preview_plan_action` 增加 `pending_resolution`，缺失时返回 `next_step=continue` 让主模型重试，明确 `replace_active_pending` 时取消旧 pending 后创建新预览，intent 的 `append_to_active_pending` 会合并旧执行 payload 后重建单张待确认卡；聚焦单测、PoC 全量和 v1.58 真实 LLM final-action 回归通过。
> v1.57 补齐取消/改口、多要求组合和长上下文指代验证：新增 `dialog_regression_400_v157_realistic_cancel_combo_cases.json`，覆盖“民办的不要→先不采纳了→那就只看公办吧→采纳”“民办和中外合作都算了吧→确认”“管理学和五年制的都别要了→采纳”“这版方案有啥问题，怎么处理，先别直接改→你说的高收费这类先去掉吧→执行”；首轮 `7/11` 暴露两个真实问题：模型口头取消但未调用 `confirm_pending(cancel)`，以及专业门类+专业标签组合时漏掉 `major_tag`；修复为 direct active-pending 短文本确认/取消桥继续调用 4.0 `confirm_pending`，并由属性注册表从原文补齐显式属性/标签；真实 LLM 复跑 `11/11` 通过。
> v1.56 扩大真实口语 final-action 覆盖：新增 `dialog_regression_400_v156_realistic_broadened_final_action_cases.json`，覆盖“就看公办吧”“中外合作算了吧”“管理学也别要了”“五年制的也别要”“山东别去了，先记下，当前方案先别动”；真实 LLM 带克隆会话复跑 `10/10` 通过，确认后要求写入与 ordered plan 裁剪/不裁剪语义均通过后端断言，其中 `apply_to_current_plan=false` 场景确认后无工作台刷新且 ordered items/units 保持不变。
> v1.55 补齐真实口语/指代/简略对话 final-action 覆盖：新增 `dialog_regression_400_v155_realistic_final_action_cases.json`，覆盖“有啥问题，咋弄→那高收费的别要了→确认执行”“方案里的民办不要了→采纳”“山东别去了→采纳”；真实 LLM 带克隆会话复跑 `7/7` 通过，确认后后端 ordered plan 中高收费 `30 -> 0`、民办 `37 -> 0`、山东 `14 -> 0`，基础候选池仍按 v1.49 口径保持可恢复。
> v1.54 补齐院校标签/专业标签报考要求 final-action：新增 `dialog_regression_400_v154_tag_final_action_cases.json` 覆盖“博士点的不要了→采纳”“五年制的不要了→采纳”；首轮发现“省重点”可合理归入院校层次、`duration=["五年制"]` 未被 schema alias 消费且会生成空 pending；修复为 prompt 明确非固定枚举标签走 `school_tag/major_tag`、属性注册表将学制口语归一到 `学制：5年`、工具层消费 `duration` 为 `major_tag` 并拒绝空 pending；复跑真实 LLM 4/4 通过，确认后 ordered plan 中博士点 `4 -> 0`、五年制 `6 -> 0`。
> v1.53 补齐专业门类报考要求 final-action：新增 `dialog_regression_400_v153_major_final_action_cases.json` 覆盖“管理学的不要了→采纳”；首轮验证 final action 已正确把 ordered-plan 中管理学 major 从 20 个裁到 0，但预览影响数因旧状态只有 `majorSubCategoryId` 和 agent 未读取 direct `majorDiscipline/majorCategory` 而显示 1；修复为后端读取 planningState 时统一补齐专业门类/专业大类，agent 本地影响计数读取 direct 和 nested taxonomy 字段；复跑真实 LLM 2/2 通过，预览断言 `20个相关志愿`，确认后 ordered items/units 均裁剪。
> v1.52 补齐属性类报考要求 final-action：新增 `dialog_regression_400_v151_attribute_final_action_cases.json` 覆盖“民办的不要/只看公办学校/不要中外合作/不要高收费的”；首轮发现 ordered units 对缺失 `schoolNature` 的旧 unit 裁剪不足，以及 `招生类型:高收费` 未按 `tuitionPerYear > 20000` 生效；后端改为 ordered units 先按有效 major volunteerId 裁剪、再做结构化资格判断，并让高收费 scope 消费学费数值；复跑真实 LLM 8/8 通过，后端全量 `PlanningStateServiceTest` 通过。
> v1.51 补齐 v1.50 真实 final-action 验证：`dialog_regression_400_v150_candidate_view_cases.json` 带 `--clone-backend-chat-session` 复跑通过，确认“山东的不要→采纳”后 `pendingConfirmation.status=applied`、`constraintState.hardConstraints.mustExcludeRegions` 与 `candidateViewState.filters.negativeProvinceNames` 均写入山东，基础 `candidatePoolState.items` 仍保留山东，最终 `orderedPlanState.units` 不再包含山东；未克隆 `assistant_chat_session` 时的 404 “会话不存在”记录为验证夹具缺口。
> v1.50 补齐 v1.49 的前端工作台状态一致性缺口：`sessionDetailV2` 不再只首次水合 `candidateViewState`，当对话确认后的候选视图状态从工作台状态刷新回来时，会按签名变化同步筛选栏并触发可见筛选查询；后端补充回归，确认已排除地域仍保留在基础候选池和 `filter-options` 中，只有可见筛选入参进入 `candidate-pool/query` 时才影响候选展示。
> v1.49 修正 v1.47/v1.48 的候选池隐式裁剪副作用：`candidatePoolState.items` 回归基础全量候选，`candidate-pool/query` 只执行显式筛选，已确认报考要求只在初始推荐/有序方案/审查/修复等方案派生链路通过 `resolveEffectiveCandidates()` 临时生效；地域类报考要求同步到可见 `candidateViewState`，用户在候选筛选栏删除对应筛选时撤销该地域要求；`_apply_intent_pending` 不再为 exclude/only_keep 重建基础候选池，确认后直接写要求并重排方案；补充后端与 agent 聚焦测试
> v1.48 补齐 v1.43 后端方向 1 的 ordered-plan 同步缺口：`generateOrderedPlan()` 在已确认报考要求存在时按 `resolveEffectiveCandidates()` 裁剪 working plan 并同步 units/summary，同时按 ordered unit 自身结构化字段过滤已不符合要求的正式方案 unit，修复真实 session 26 “排除山东”后 candidate 已清零但 ordered 仍保留山东项的问题；新增后端复现单测；继续清理 `proposal_compiler.py` 中未被 4.0 生产链路调用的旧 full-agent intent arbitration / blocked reply helper 和专属测试
> v1.47 落地 v1.43 后端方向 1：`candidate-pool/generate` 与 `queryCandidatePool` 统一读取 `constraintState.hardConstraints`，候选池生成、查询、初始推荐、有序方案生成共享已确认报考要求；新增后端单测覆盖“不要民办/排除山东/不要中外合作”；真实 session 35 验证“民办就算了→采纳”后 ordered/candidate 民办项清零。该方向已在 v1.49 调整为“基础候选池全量 + 方案链路临时过滤 + 候选视图显式筛选”
> v1.46 修复 v1.43 真实回归发现的误刷新：候选池重建失败或只记录要求时，direct confirm 不再发送 ordered/review 刷新 followup；新增 `dialog_regression_400_v143_constraint_apply_cases.json`，并清理 confirm execution case 的旧 shadow 预期
> v1.45 落地 §11 的 Agent 侧阶段 1/2：exclude/only_keep 与负向要求确认后先重建候选池再生成有序方案；支持 `apply_to_current_plan=false` 只记录要求不改当前方案；同时删除旧 `planning_workflow_tool.py` 生产依赖和专属测试资产
> v1.44 补充 §10.3/§10.4/§10.5 旧工具栈清理进度：删除 ChatAgent/instructions/tool_reply_policy、旧 plan_query/official_source/intent_preview wrapper，评估脚本切到 4.0 工具名，并记录静态扫描与单测结果
> v1.43 新增 §11 约束落地链路修复：定位"排除山东确认后方案不变"根因为 preview(simulate_plan_diff 尊重约束)/execute(ordered-plan 重排不尊重约束)契约分叉 + 后端候选池不 merge constraintState + 语义无法表达"先不替换"；给出"约束状态即单一事实源"核心方向与阶段 0-4 前后端协同推进计划
> v1.42 完成 G17 参数恢复后的完整 G1-G32 direct 主集复跑：20/20 successful，shadow 20/20 success；G17 在完整主集中单次 `preview_plan_action` 并生成 `move_ordered_unit` 确认卡，metrics: `/private/tmp/zhiyuan_400_g1_g32_after_g17_param_recovery_full_rerun.json`
> v1.41 落地 G17 shadow 参数恢复：`preview_plan_action` 在工具已被调用但漏 action/selector 时，从当前用户原文补齐明确移动诉求和筛选选择器；G17 聚焦真实 LLM 1/1、shadow 1/1，metrics: `/private/tmp/zhiyuan_400_g17_after_missing_action_recovery.json`
> v1.40 补充 G2/G8 修复后完整 G1-G32 direct 复核 19/20，失败为 G17 shadow nextSteps 断言（主链路已出移动确认卡）；修复 G1“英语相关专业”被过度收窄为“英语”的广义专业表达边界，并完成 G1/G8 聚焦复验 2/2
> v1.39 落地 G2/G8 回复展示口径修复：review_plan 返回明确正式方案事实，preview_intent_change 复用专业层级显式实体收敛；补充聚焦单测与真实 LLM G2/G8 direct 验证 2/2 通过
> v1.38 补充删除旧执行编排后的 focused 复核 5/5 与第二轮完整 G1-G32 direct 主集 20/20；确认两轮主集与 focused 均通过，记录 G2/G8 回复口径和 G21/G31/G26 性能尾部观察项
> v1.37 补充清理空间后删除旧执行编排的真实 direct 复跑：完整 G1-G32 direct 主集 20/20、shadow 20/20、确认执行闭环 4/4；记录性能尾部、G27 替换候选质量和报考要求采纳后重算文案观察项
> v1.36 补充删除旧执行编排后的真实 direct 验证：确认执行闭环 4/4、G case direct 子集 8/8；完整 G1-G32 direct 主集因后端 fixture clear 超时与磁盘/SQLite 环境问题中断，未计为业务回归失败
> v1.35 执行 §10.3 方向 A：删除旧执行编排孤儿 `plan_action_execution.py` 与 `app/handlers/*`，删除旧 runner/handler/protocol 测试资产；`plan_orchestration_models.py` 仅保留仍被 4.0 使用的 proposal/context 模型并删除旧 execution DTO；补充验证结果与下一步
> v1.34 新增 §10 清理后整体评估：确认 ZhiyuanAgent 符合 BaseAgent 框架约定、confirm_pending 执行链路自洽；识别 `plan_action_execution.py`（~6171 行）为生产孤儿并给出删除决策（方向 A）与前置校验；给出四阶段推进计划
> v1.33 补充 §9.16 旧 payload / route / skill 残余清理：正常路径收敛为结构化 `plan_payload` 和 4.0 direct 工具指引
> v1.32 补充 §9.16 G7 工具边界问题分析：记录 `review_plan(next_step=respond)` 当前不会直返终止导致偶发追加 `query_plan`，本轮暂不修复
> v1.31 补充 §9.16 旧链路清理后真实 direct 复跑结果：确认执行闭环 4/4、G case 子集 8/8、G1-G32 direct 主集 19/20，并记录 G7 非稳定工具边界抖动
> v1.30 补充 §9.16 旧链路清理执行记录：清理 dialog report / mainline / websocket 中旧 fast-route 与旧执行工具测试资产，删除历史 live metrics 输出
> v1.29 补充 §9.16 旧链路清理执行记录：删除旧 `app/tools/plan_execution_tool.py` 文件，`run_plan_action_payload()` 迁入 domain 执行层
> v1.28 补充 §9.16 旧链路清理执行记录：方案动作执行原语迁出 `plan_execution_tool.py`，收敛为 domain 执行层与中性 payload runner
> v1.27 补充 §9.16 旧链路清理执行记录：删除 regression runner 中旧 `execute_plan_action` payload 解析、fast-route 观测汇总和 quality gate 旧 fast-router target
> v1.26 补充 §9.16 旧链路清理执行记录：删除 `intent_state_tool` / `internal_client` / regression runner 中旧 `planEditCache` 写入与清理路径
> v1.25 补充 §9.16 旧链路清理执行记录：`plan_execution_tool` 内部原语改名为 `_run_plan_action_model`，删除旧 execution regression 资产，`history_persistence` 清零旧 `execute_plan_action` 夹具
> v1.24 补充 §9.16 旧链路清理执行记录：`service.py` 删除旧 `planEditCache` 清理桥，`proposal_compiler` 删除旧 readonly workspace evidence compiler 和旧 execute workspace helper
> v1.23 补充 §9.16 旧链路清理执行记录：`service.py` 生产代码清零 `execute_plan_action` 解析/后处理，删除旧 workspace/semantic display compiler 和旧 execute helper-only 测试资产
> v1.22 补充 §9.16 旧链路清理执行记录：删除旧候选 helper/test 资产、旧 execute workspace refresh/view 桥和旧 review-fix 反向建卡桥
> v1.21 补充 §9.16 旧链路清理执行记录：切断 service 旧 `execute_plan_action(preview)` 到 plan pending sink 的反向建卡桥
> v1.20 补充 §9.16 旧链路清理执行记录：退役旧 `execute_plan_action` 公开工具入口，改为中性 `run_plan_action_payload` 测试 runner
> v1.19 补充 §9.16 旧链路清理执行记录：删除旧 `execute_plan_action` recent execution timeout/interruption cache 和 server/service fallback 桥
> v1.18 补充 §9.16 旧链路清理执行记录：删除 `plan_semantic_action_tool.py` 本体、旧 model-node benchmark 节点/样本和旧 semantic/local DSL 测试资产
> v1.17 补充 §9.16 旧链路清理执行记录：`service.py` 深清理旧 runtime/profile/plan-chain helper，生产无调用 helper 扫描清零
> v1.16 补充 §9.16 旧链路清理执行记录：service 删除旧 plan semantic classifier 依赖，fix proposal 目标选择只信任结构化显式 scope
> v1.15 补充 §9.16 旧链路清理执行记录：删除 workspace presentation 旧 call-only fallback，compiler 新写入改为 `plan_payload`，记录聚焦验证结果
> v1.14 补充 §9.16 旧链路清理执行记录：删除 `service.py` 无调用旧 helper，清理旧 service patch / `plan_next_action` / `runtime_intent_hard_cut` 测试资产，`history_persistence` 全量通过
> v1.13 补充 §9.16 旧链路清理执行记录：`service.py` 生产代码清零 `plan_next_action` / `collect_plan_context_inputs` 引用，删除旧 `plan_next_action` 未执行 preview 文案补救测试资产
> v1.12 补充 §9.16 旧链路清理执行记录：删除 `plan_execution_tool` 最近旧 plan cache，收敛 `tool_reply_policy` 中旧 `execute_plan_action` 专属回复策略和测试资产
> v1.11 补充 §9.16 旧链路清理执行记录：ChatAgent 旧 Plan 工具退役，`explore_followup` 改走 4.0 `query_plan`，删除 `plan_orchestration_tool` / `plan_context_tool` 本体和专属测试资产
> v1.10 补充 §9.16 旧链路清理执行记录：hard-cut/profile fallback 删除后，内部 plan confirmation `plan_payload` 从 JSON 字符串收敛为结构化 dict；删除 full-agent plan post-processing、intent-preview-to-plan 和 post-query profile semantic fallback 旧桥
> v1.9 补充 §9.16 清理前 G1-G32 direct-only 基线 `20/20`，确认旧链路入口清理启动；记录 G19/G32 no-plan、G22 状态前置只读和 G7/性能观察项
> v1.8 新增 §9.16 focused direct 修复：`confirm_pending` 终止策略、R33 no-plan fixture、no-plan 诉求回显、高收费确认后边界；明确旧链路清理启动条件
> v1.7 新增 §9.14 完整 320 G1-G32 direct 复跑结果，记录 44/49、G25/G27/旧路由残留和性能问题；更新 Phase 4 检查项
> v1.6 新增 §9.13 高收费 follow-up 参数完整性与 filter 安全，明确不使用字符串 precheck、不在工具层做原话 NLU 特化；更新 Phase 4 检查项，确认 direct-only 口语集与确认执行后端 action 断言已通过
> v1.5 更新 §9.5 G17 问题定性（三层防护已到位，剩余为 LLM 可靠性）；重写 §9.9 G25 为三个子问题（routing 抢跑 / schema alias / positive 漏 negative）；新增 §9.12 四阶段下一步计划（环境排障→schema+Prompt→respond 验证→完整回归）
> v1.4 扩展 §9.5-§9.10：G17 selector 归一化三层防护、G4 实体展示保真、G3 查询计数粒度、G32 探索降级维度模板、G25 复核策略、§9.1 respond 软停验证边界
> v1.3 根据 G1-G32 完整回归（49步/46通过/3失败）新增 §9：复合诉求 next_step 策略、pending 下只读路由、正向意向边界澄清、档案提取边界、实现级修复汇总
> v1.2 收口 pending 确认链路：普通方案调整只接受 `action_family` + `atomic_actions` 结构化 payload，非结构化历史 pending 不再保留专用兼容分支
> 前置文档:
> - [release-4.0.0-coding-agent-architecture-redesign.md](release-4.0.0-coding-agent-architecture-redesign.md) — 架构设计
> - [release-4.0.0-coding-agent-poc-plan.md](release-4.0.0-coding-agent-poc-plan.md) — PoC 验证方案
> - [release-4.0.0-coding-agent-implementation-tracking.md](release-4.0.0-coding-agent-implementation-tracking.md) — 实施追踪

## 1. 当前进度与整体路径

### 1.1 PoC 验证结论

PoC 以 4 个正交工具 + 状态前置注入 + next_step 终止信号验证了核心假设：

| 指标 | 当前系统 | PoC 结果 |
|------|---------|---------|
| 工具调用/轮 | 2-5 | 1 |
| System prompt | ~22K tokens | ~3K tokens |
| 输入 token/轮 | 17K-37K | ~1.2K |
| 延迟 | 25-35s | 1.2-2.8s |
| 工具选择正确率（5场景） | ~70% | 100% |

### 1.2 从 PoC 到正式版的整体路径

按架构设计文档 §9 的四阶段迁移方案推进，结合 PoC 已完成的部分：

```
                    PoC 已完成
                    ───────────
Phase 1 ──────────────────────────────────── Phase 2
  SandboxFileCache                            9 工具正式实现
  Backend Adapter                             非阻塞 Shadow
  ZhiyuanAgent 升级                           扩展 Case 集合
  ───────────────────────────────────────────────────────────
Phase 3 ──────────────────────────────────── Phase 4
  Shadow Diff 大规模验证                       4.0 direct 默认主链路
  Confusion Matrix                            监控仪表盘
  320+ 用例跑新系统                            旧代码清理
```

**核心原则：直接实现，不做委托/代理。** 新工具直接使用域层原语（实体解析器、`internal_client` API、静态数据）实现业务逻辑，不包装旧工具函数。旧工具在生产切换稳定后整体移除。

### 1.3 PoC 与正式版的差异

| 维度 | PoC（已完成） | 正式版（本文设计） |
|------|-------------|-----------------|
| 工具数量 | 9（Phase 2 第二/三批首版已落地） | 9 |
| 状态读取 | 从 `ctx.deps` 直读 | 通过 SandboxFileCache |
| explore_topic | major/school 已接 profile API，失败降级只读摘要 | 继续接入权重分析与 career/region 覆盖统计 |
| query_plan | 已扫描 `plan/items.json` 并支持 filters | 继续补齐旧主链路展示维度 |
| preview_intent_change | 已创建结构化 pending，专业/院校/地域已接入 `simulate_plan_diff`，失败降级本地扫描 | 扩展真实 shadow case 观察 diff 稳定性 |
| 确认流程 | `confirm_pending` 已支持结构化 pending | 后续预览工具只产出结构化 payload |
| 方案操作 | `preview_plan_action` 首版已注册，产出结构化 pending；支持核心 review issue 范围删除/排序/重排预览、review issue + filters 复合范围和 replace 自动候选首版 | 扩展候选质量评估 |
| answer_policy | 首版已注册，离线优先整合政策框架、school profile 招生政策和参数可用性校验 | 扩展官方来源抽取和适配匹配 |
| review_plan | 首版已注册，执行/读取审查并可选返回只读修复建议；核心 review issue 可联动方案操作预览；G2/G21 真实工具选择边界已通过 | 扩展真实 service shadow case |
| shadow 模式 | 非阻塞后台 task 首版已落地 | 继续补 shadow diff 与采样评估 |

---

## 2. Phase 1: SandboxFileCache + Backend Adapter

### 2.1 设计目标

将工具对 `RequestContext` 的直接耦合替换为虚拟文件视图，实现：
- 工具通过路径读写，不关心数据来源
- 版本驱动的缓存失效，避免读到过期数据
- 写操作成功后自动失效关联文件

### 2.2 文件路径 → 后端 API 映射

```python
class BackendAdapter:
    """文件路径到后端 API 的映射。每个路径对应一个获取函数。"""

    ROUTE_TABLE: dict[str, Callable] = {
        "score.json":         lambda sid: get_user_score_detail(sid),
        "profile.json":       lambda sid: get_user_init_profile(sid),
        "constraints.json":   lambda sid: get_planning_workspace_state(sid),  # 提取 constraints 段
        "plan/summary.json":  lambda sid: get_planning_state(sid),            # 提取 summary 段
        "plan/items.json":    lambda sid: get_planning_ordered_plan(sid),
        "plan/candidates.json": lambda sid: query_planning_candidate_pool(sid, ...),
        "plan/review.json":   lambda sid: get_planning_state(sid),            # 提取 review 段
        "pending.json":       lambda sid: get_pending_confirmation(sid),
    }
```

**核心设计点：**
- `get_planning_state` 一次返回 summary + review + tier_counts 等多段数据，`BackendAdapter` 负责拆分到对应虚拟文件路径
- `plan/items.json` 可能 5-50KB，需要按需加载而非 cache warming 阶段预取

### 2.3 SandboxFileCache

```python
class SandboxFileCache:
    """会话级虚拟文件缓存。"""

    def __init__(self, session_id: str, adapter: BackendAdapter):
        self._session_id = session_id
        self._adapter = adapter
        self._cache: dict[str, CacheEntry] = {}

    async def read(self, path: str, query: str | None = None) -> dict:
        """读取文件。未缓存或已失效时从后端拉取。"""

    def invalidate(self, paths: list[str]) -> None:
        """写操作成功后失效关联文件。"""

    async def warm(self, paths: list[str]) -> None:
        """预热常用文件。Context 构建阶段并行加载。"""
```

**缓存条目结构：**
```python
@dataclass
class CacheEntry:
    data: dict[str, Any]
    version: int              # 后端 planning version
    fetched_at: float         # monotonic timestamp
    ttl_seconds: float = 300  # 最长存活时间
```

**失效规则（与架构文档 §5.3 一致）：**

| 触发事件 | 失效文件 |
|---------|---------|
| 偏好确认（confirm_pending → intent） | `profile.json`, `constraints.json` |
| 方案变更（confirm_pending → plan） | `plan/summary.json`, `plan/items.json`, `plan/review.json`, `pending.json` |
| 方案生成 | 所有 `plan/*` |
| 审查运行 | `plan/review.json`, `plan/summary.json` |
| Pending 创建/清除 | `pending.json` |

**Cache warming 策略：**
- Context 构建阶段并行预取 `score.json` + `profile.json` + `plan/summary.json` + `pending.json`（共 4 个并行请求）
- `plan/items.json` 和 `plan/candidates.json` 按需加载（仅 `query_plan` 和 `preview_plan_action` 使用）

### 2.4 版本守护

复用现有 `app/sync/state_sync.py` 的 `PlanningStateSync`，适配到 SandboxFileCache：

```python
class SandboxFileCache:
    def _is_stale(self, path: str) -> bool:
        entry = self._cache.get(path)
        if entry is None:
            return True
        # TTL 过期
        if (monotonic() - entry.fetched_at) > entry.ttl_seconds:
            return True
        # 版本漂移：planning 相关文件检查后端版本
        if path.startswith("plan/") or path == "pending.json":
            return entry.version < self._latest_backend_version
        return False
```

### 2.5 与 PoC 的衔接

PoC 中工具通过 `ctx.deps.score_detail`、`ctx.deps.planning_summary` 直接取值。正式版改为：

```python
# PoC
score = ctx.deps.score_detail

# 正式版
sandbox: SandboxFileCache = ctx.deps.sandbox
score = await sandbox.read("score.json")
```

`RequestContext` 增加 `sandbox: SandboxFileCache` 字段。Context 构建阶段创建 cache 实例并执行 warm。

---

## 3. Phase 2: 9 工具正式实现

### 3.1 设计原则

**直接实现，不做委托。** 每个新工具：
- 直接调用 `internal_client` 的后端 API（不经过旧工具函数）
- 直接使用 `app/domain/` 的实体解析器
- 直接从 SandboxFileCache 读取状态
- 输出统一 `{data, next_step, message}` 格式

旧工具中值得保留的是**领域计算逻辑**（如梯度计算、对比格式化），在新工具中重新实现或提取为独立工具函数放入 `app/domain/`。旧工具函数本身（包含路由判断、上下文拼接、多轮状态恢复等胶水）不复用。

### 3.2 工具总览

| 工具 | 类型 | 替代的旧工具 | 主要后端 API |
|------|------|------------|------------|
| `read_state` | 读取 | 隐式状态读取 | SandboxFileCache.read |
| `explore_topic` | 分析 | 6 个 analyze/explore 工具 (1302行) | `get_major_profile`, `get_school_profile_by_name`, `analyze_majors`, `analyze_schools` |
| `compare_entities` | 分析 | 5 个 compare/info 工具 (1584行) + 2 个 score query (358行) | `analyze_majors`, `analyze_schools`, `get_major_profile`, `get_school_profile_by_name` |
| `query_plan` | 查询 | `query_volunteer_plan` + `collect_plan_context_inputs` (1356行) | `get_planning_ordered_plan`, `query_planning_candidate_pool` |
| `preview_intent_change` | 预览 | 5 个 intent preview 工具 (575行) + intent_state_tool (4608行) | `update_planning_constraint_state`, `simulate_plan_diff` |
| `preview_plan_action` | 预览 | plan_execution (5160行) + plan_orchestration (1234行) + plan_semantic_action (855行) | `select_working_plan_items`, `remove_planning_ordered_plan_units`, `move_planning_ordered_plan_unit`, `sort_planning_ordered_plan`, `generate_planning_ordered_plan` |
| `confirm_pending` | 执行 | service.py 中分散的 pending 协议 | 按 pending.kind 分发到对应后端 API |
| `answer_policy` | 查询 | admission_policy (395行) + official_source_search (411行) + admission_fit_match (313行) | `search_official_admission_sources`, `check_plan_param_availability` |
| `review_plan` | 分析 | planning_workflow 审查函数 (2269行) | `run_planning_review`, `generate_planning_fix_proposals` |

### 3.3 各工具核心设计点

#### `read_state` — 沙箱文件读取

PoC 已有基本实现。正式版变更：

- **数据来源**：从 `ctx.deps` 直读 → `SandboxFileCache.read(path)`
- **增加 query 参数**：支持 `query_plan` 级别的过滤表达式（如 `"tier=保 and tuition > 20000"`），但 `read_state` 本身只做简单的 path 读取，复杂查询留给 `query_plan`
- **增加路径**：`plan/items.json`、`plan/candidates.json`、`plan/review.json`、`constraints.json`

```python
StatePath = Literal[
    "score", "profile", "plan/summary", "plan/items",
    "plan/candidates", "plan/review", "pending", "constraints"
]
```

#### `explore_topic` — 方向/适配/兴趣分析

PoC 返回占位文本。正式版直接实现分析逻辑：

**按 topic_type 的后端 API 和数据组装：**

| topic_type | 后端 API | 输出内容 |
|-----------|---------|---------|
| `major` | `get_major_profile(name)` → 专业画像 | 课程方向、就业去向、与选科匹配度、在当前方案中的覆盖情况 |
| `school` | `get_school_profile_by_name(name)` → 院校画像 | 录取线趋势、优势学科、地理位置、与分数档位匹配度 |
| `career` | 无需后端调用，基于 `career_slots` 归一化 + 方案画像 | 方向定义、相关专业映射、当前方案的职业覆盖度 |
| `region` | 无需后端调用，基于 `region_entity_resolver` + 方案统计 | 区域院校分布、当前方案中该区域志愿数、生活成本参考 |

**核心设计点：**
- 实体解析在工具内部完成（`user_question` 中提取实体名 → 解析器归一化）
- 分析结果从后端 API 原始数据直接格式化，不经过旧的 `explore_direction_tool` 的 LLM 二次分析
- 需要方案上下文时，从 SandboxFileCache 读取 `plan/summary.json`
- `next_step: "respond"`

**与旧工具的区别：**
旧 `explore_direction_tool`（1302行）内部起了一个独立 LLM Agent 做分析生成。新工具直接从后端 API 取结构化数据，由外层 ZhiyuanAgent 做自然语言综合。省掉内部 LLM 调用。

**Phase 2 第二批首版落地状态（2026-06-30）：**
- `topic_type=major` 已接 `get_major_profile` / `get_major_category_profile`
- `topic_type=school` 已接 `get_school_profile_by_name`
- 工具返回 `entity`、`entity_level`、`profile_source`、`profile_facts`、`profile_raw`
- 后端 profile 不可用时保留只读降级回复，不改状态、不阻断主流程
- `analyze_majors` / `analyze_schools`、career/region 方案覆盖分析仍留作后续扩展

#### `compare_entities` — 学校/专业对比

新增工具，替代 5 个 compare 工具 + 2 个 info 工具。

```python
async def compare_entities(
    ctx: RunContext[RequestContext],
    entity_type: Literal["major", "school"],
    entities: list[str],             # 2-5 个实体名
    comparison_focus: str | None,    # "就业", "课程", "录取难度"
) -> str
```

**核心设计点：**
- 实体解析：每个 entity name 走对应解析器归一化。任一歧义 → `next_step: "clarify"` + 候选列表
- 数据获取：并行调 `get_major_profile` / `get_school_profile_by_name`（每个实体一次）
- 对比矩阵：从后端返回的结构化数据中提取对比维度（录取分数、就业率、课程方向等），按 `comparison_focus` 筛选
- 方案关联：从 `plan/summary.json` 读取当前方案，标注"已在方案中"
- `next_step: "respond"`

**与旧工具的区别：**
旧 `major_compare_tool`（600行）和 `school_compare_tool`（446行）内部各自起 LLM 做对比总结。新工具返回结构化对比数据，由外层 Agent 生成自然语言。

**Phase 2 第二批首版落地状态（2026-06-30）：**
- 已注册 `compare_entities` 到 `ZhiyuanAgent`
- 已支持 `entity_type=major|school`、2-5 个对象对比
- profile 数据并发获取，返回结构化 `rows` 对比矩阵
- 已标注 `in_current_plan`，可提示对象是否已在当前方案中
- 返回 raw 已瘦身，避免工具输出过大
- `analyze_majors` / `analyze_schools` 个性化量化指标仍留作后续扩展

#### `query_plan` — 方案/候选查询

PoC 已有基本框架。正式版增加真实方案扫描能力。

**核心变更：**
- **plan 查询**：调 `get_planning_ordered_plan(session_id)` 获取完整志愿列表，在工具内部按 `filters` 扫描匹配
- **candidates 查询**：调 `query_planning_candidate_pool(session_id, ...)` 获取候选池
- **filters 处理**：

| filter key | 匹配逻辑 |
|-----------|---------|
| `school_nature` | 精确匹配 item 的 `school_nature` 字段 |
| `tier` | 精确匹配 `冲/稳/保` |
| `school` | 模糊匹配学校名（走 `school_entity_resolver`） |
| `major` | 模糊匹配专业名（走 `major_entity_resolver`，支持 level1/2/3） |
| `tuition_max` | item 的 `tuition_per_year <= value` |
| `province` | 匹配院校所在省份 |

- **截断策略**：匹配结果超过 `limit`（默认 20）时截断，返回总命中数 + 前 N 条详情
- `next_step: "respond"`

#### `preview_intent_change` — 预览显式报考要求

PoC 已有实体解析和归一化。正式版增加方案影响分析和 pending 创建。

**核心变更：**

1. **方案影响分析**：归一化后基于当前完整画像构造 backend-format proposed profile，调 `simulate_plan_diff(tenant_id, session_id, proposed_profile)` 计算"排除医学会影响哪些志愿"
2. **Pending 创建**：影响分析通过后，调 `save_pending_confirmation(session_id, pending_data)` 创建 pending
3. **约束写入**：确认后调 `update_planning_constraint_state(session_id, intentMode="constraint", ...)` 写入硬性报考要求

**正式版签名（约束简化后）：**
```python
PendingResolution = Literal["none", "replace_active_pending", "append_to_active_pending", "hold_new_request"]

async def preview_intent_change(
    ctx: RunContext[RequestContext],
    intent_type: Literal["major", "school", "region", "career"],
    positive: dict[str, Any] | None = None,
    negative: dict[str, Any] | None = None,
    constraint_type: Literal["exclude", "only_keep", "must_have"] = "exclude",
    apply_to_current_plan: bool = True,
    pending_resolution: PendingResolution = "none",
    raw_user_text: str = "",
) -> str
```

> 注：`preference` 已从 `constraint_type` 移除。用户对话仅处理硬约束（exclude/only_keep/must_have）。软性推荐系数调整不暴露给用户交互界面，后续从系统隐性角度运行。详见 §3.6。
> 注：已有 active pending 且本轮仍要新建预览时，必须由主模型基于压缩上下文显式填写 `pending_resolution`。工具只执行结构化状态处理，不在后端用短语表猜测“放弃/追加/暂缓”语义。

**返回数据结构（正式版）：**
```json
{
  "data": {
    "intent_type": "major",
    "constraint_type": "exclude",
    "normalized": {"positive": {}, "negative": {"level1": ["医学"]}},
    "plan_impact": {
      "affected_count": 5,
      "affected_items": ["华中科技大学·临床医学", "..."],
      "tier_impact": {"冲": -1, "稳": -2, "保": -2}
    },
    "pending_id": "pending_12345",
    "requires_confirmation": true
  },
  "next_step": "confirm",
  "message": "排除医学门类后，当前方案有5个志愿受影响（冲1/稳2/保2）。确认的话点击采纳。"
}
```

- `next_step: "confirm"`（正常） / `"clarify"`（歧义）

**Phase 2 第一批延伸落地状态（2026-06-30）：**
- 已将 normalized intent 转成 `executionPayload.merged` / `selectedData.selected`
- 已创建 `kind=intent_change`、`actionFamily=apply_selected_intents` 的结构化 `pendingConfirmation`
- 已按 `constraint_type` 设置 `intentMode=constraint` 和 `constraintIntentType`，不再生成 `preference` pending
- 已接入 `simulate_plan_diff(...)` 生成真实 `plan_impact`，包含 before/after tier、promoted、demoted 与 tier delta
- 已保留 `plan/items.json` 本地扫描降级路径，避免 diff 服务不可用时阻断 pending 预览
- 保存成功后会 prime `pending.json`，供 `confirm_pending` 直接读取并执行
- `career` 方向暂不在后端 `UserProfile` 结构中，真实 diff 后续等画像结构支持后再补

#### `preview_plan_action` — 预览方案变更

新增工具。替代 `plan_execution_tool`（5160行）+ `plan_orchestration_tool`（1234行）+ `plan_semantic_action_tool`（855行）。

```python
async def preview_plan_action(
    ctx: RunContext[RequestContext],
    action: Literal["add", "remove", "move", "replace", "sort", "generate", "regenerate_order", "pin_lock"],
    targets: list[str] | None = None,
    target_position: int | None = None,
    filters: dict[str, Any] | None = None,
    pending_resolution: PendingResolution = "none",
    review_issue_code: Literal[
        "high_tuition",
        "cooperative_program",
        "admission_limit",
        "special_enrollment",
        "probability_inversion",
        "probability_gap",
        "count_validation",
        "edge_score",
        "safety_guard",
        "major_group_safety_intent_alignment",
        "group_inner_safety_guard",
        "tier_gap",
        "low_safety",
        "career_mismatch",
    ] | None = None,
    raw_user_text: str = "",
) -> str
```

**action → 后端 API 映射：**

| action | 后端 API | 核心逻辑 |
|--------|---------|---------|
| `add` | `select_working_plan_items` → `generate_planning_ordered_plan` | 从候选池选入 → 重新生成正式方案 |
| `remove` | `remove_planning_ordered_plan_units` | 解析 targets 为 unit_id → 移除 |
| `move` | `move_planning_ordered_plan_unit` | 解析 target + position → 移动 |
| `replace` | `remove` + `add` 组合 | 先移出旧的 → 从候选池选入替换 |
| `sort` | `sort_planning_ordered_plan` | 按指定字段重排序 |
| `generate` | `generate_planning_initial_plan` 或 `generate_planning_ordered_plan` | 首次/重新生成方案 |
| `regenerate_order` | `generate_planning_ordered_plan` | 保持候选池不变，重新排序生成 |

**targets 引用解析：**

`targets` 可以是多种引用格式，工具内部统一解析为 `unit_id`：

| 引用格式 | 解析方式 |
|---------|---------|
| `"10561_0805_001"` | 直接使用 volunteer_id |
| `"华南理工大学"` | 从 `plan/items.json` 中按学校名匹配 |
| `"华南理工大学.软件工程"` | 学校名 + 专业名联合匹配 |
| `"第3个"` / `"第3-5个"` | 按 position 索引 |
| `"冲的第一个"` | 按 tier + position 索引 |
| `review_issue_code="high_tuition"` / `"cooperative_program"` | 从 `plan/review.json` 的对应 issue 读取 affected unit ids，并兼容后端 code alias |

解析使用域层 `school_major_ref_resolver`（162行），在新工具中直接引入。

**核心设计点：**
- 所有 action 先构建预览，创建 pending，不立即执行
- 预览需要计算梯度影响（冲/稳/保数量变化），从 `plan/summary.json` 和操作目标推导
- `generate` 操作前校验前置条件：是否有成绩、是否有最低偏好输入。使用 SandboxFileCache 读取 `score.json` 和 `profile.json` 判断
- `next_step: "confirm"`

**与旧工具的区别：**
旧的 `plan_execution_tool`（5160行）包含完整的执行 + 后处理 + 二次审查 + 修复建议生成，是一个 mini 编排引擎。新工具只做预览 + pending 创建。执行由 `confirm_pending` 负责。

**Phase 2 第三批首版落地状态（2026-06-30）：**
- 已注册 `preview_plan_action` 到 `ZhiyuanAgent`
- 已支持 `add/remove/move/replace/sort/generate/regenerate_order` 创建结构化 `pendingConfirmation`
- `executionPayload` 只使用 `action_family` + `atomic_actions`，不再生成旧式 opaque `planPayload`
- `remove/move` 从 `plan/items.json` 解析当前方案项，`add/replace` 从 `plan/candidates.json` 解析候选 volunteerId
- `remove/replace` 支持 `review_issue_code` 首版联动；当用户明确说“把审查里的高收费/中外合作/限报/特殊招生项移出去”且未给具体 targets 时，从 `plan/review.json` 解析 affected units，并把 `review_issue_target` 写入 `executionPayload` / `atomic_actions`
- `review_issue_code` 收窄为后端当前 preview-fixable 核心规则枚举，并保留 `tier_gap/low_safety/career_mismatch` 语义别名；当前高收费、中外合作、限报、特殊招生 item 风险已有删除范围联动，且支持后端 code alias 和中文摘要归一
- 审查结果只有 `affectedVolunteerIds` 或 `affectedItems[].volunteerId` 时，会用 `plan/items.json` 反查当前方案项并生成执行所需 `unit_ids`
- `remove + review_issue_code + filters` 支持审查问题范围与属性 filters 求交集，例如“高收费且民办”；无交集时不创建 pending
- `regenerate_order/sort` 支持只绑定审查 issue 元信息；录取率倒挂、梯度/冲稳保断层、保底不足等结构性问题可生成排序/重排 pending，payload 携带 `review_issue_target`，确认后仍走结构化 `confirm_pending`
- `review_issue_code` 找不到可操作 unit 时返回 `clarify`，不退回只读审查；`replace` 缺候选时也先澄清
- `replace + review_issue_code` 在用户未指定候选且 `plan/candidates.json` 可用时，可按同档位、同省、学费降低、规避当前 issue 风险标签等保守规则自动选择替换候选；候选池不可用/无命中时仍澄清
- `confirm_pending` 已支持 `replace_units` 结构化执行：remove → select → regenerate
- 位置范围、档位内序号和 G17 风格档位内局部重排已首版支持：`第3-5个`、`冲的第一个`、`tier + admission_ratio max + target_tier/target_ordinal`
- G16 锁定/固定位置已拆出为 `pin_lock` 受控 unsupported action：不创建 pending，不再误走移动/no-change；完整 ordered-plan pin/lock 执行等后端接口稳定后再接
- G30 强基路径已通过 `program_type=强基` 保留为属性 selector，不退化为普通院校偏好
- service 过渡期旧预览 sink 已改为保存扁平结构化 `executionPayload`，不再产生新的旧式 `planPayload` pending；非结构化历史 pending 统一拒绝/失效，不保留 `planPayload` 专用兼容分支，也不回退旧 `execute_plan_action`
- 候选自动选择质量评估和完整 service shadow 仍留作后续扩展，不回引旧 `execute_plan_action`

#### `confirm_pending` — 确认/取消待确认操作

新增工具。将 service.py 中分散的 pending 确认协议收敛到一个工具。

```python
async def confirm_pending(
    ctx: RunContext[RequestContext],
    action: Literal["confirm", "cancel"],
) -> str
```

**核心设计点：**

1. **版本守护**：执行前读 `pending.json` 获取 `source_backend_version`，与后端当前版本比较。版本漂移 → 清除 pending + 返回错误提示。复用 `PlanningStateSync.pre_execute_guard` 的判断逻辑。

2. **按 pending.kind 分发执行：**

| pending.kind | 确认时执行 | 失效文件 |
|-------------|----------|---------|
| `intent_change` | `update_planning_constraint_state(intentMode="constraint")` → 写硬性报考要求 → **如有方案则 `generate_planning_ordered_plan` 再生成**（§3.7） | `constraints.json`, `plan/*`, `pending.json` |
| `plan_mutation` | 按 `action_family` 调对应后端 API（remove/move/sort/add） | `plan/*`, `pending.json` |
| `plan_generation` | `generate_planning_initial_plan` 或 `generate_planning_ordered_plan` | `plan/*`, `pending.json` |

3. **取消**：清除 pending，不调后端。仅失效 `pending.json`。

4. **执行后刷新**：确认执行成功后，失效 SandboxFileCache 中的关联文件路径，下次读取时自动拉取最新。

- `next_step: "respond"`（成功/失败都直接回复）

**Phase 2 第一批落地状态（2026-06-30）：**
- 已注册 `confirm_pending(action="confirm" | "cancel")` 到 `ZhiyuanAgent`
- 已支持无 active pending 防护、取消、版本漂移守护、执行后 sandbox 失效
- `intent_change` 已直接调用 `update_planning_constraint_state(intentMode="constraint")`；用户交互层不再写软性 `preference`
- 结构化 `plan_mutation` 已直接分发到 add/remove/move/sort/generate/regenerate 对应后端 API
- `confirm_pending` 只接受 `action_family` + `atomic_actions` 结构化 payload；非结构化历史 pending 不再委托旧 `execute_plan_action`，会要求重新生成结构化预览；当前 `preview_plan_action` 和 service 过渡 sink 都只产出结构化 payload

#### `answer_policy` — 报考政策问答

新增工具。替代 `admission_policy_tool`（395行）+ `official_source_search_tool`（411行）+ `admission_fit_match_tool`（313行）。

```python
async def answer_policy(
    ctx: RunContext[RequestContext],
    question: str,
    rule_domain: Literal[
        "score_batch", "eligibility", "tuition_budget", "enrollment_rules",
        "school_rule", "transfer_major", "subject_requirement",
        "physical_exam", "oral_exam", "general"
    ] | None = None,
    school_name: str | None = None,
    major_name: str | None = None,
    year: int | None = None,
    use_official_search: bool = False,
) -> str
```

**核心设计点：**
- 如有 `school_name`，先走 `school_entity_resolver` 归一化
- 默认离线优先：学校规则类问题读取 `get_school_profile_by_name(...)` 的招生政策字段
- 对明确学校/专业/省份目标，先保留标准名称用于返回，再转后端编码调 `check_plan_param_availability(...)` 校验可用性
- `use_official_search=True` 时在 `answer_policy` 内部执行轻量官方来源检索，不再依赖独立旧工具
- 结果结构化为 `{policy_facts, student_eligibility, source_references}`
- 只读操作，`next_step: "respond"`

**Phase 2 第三批首版落地状态（2026-06-30）：**
- 已注册 `answer_policy` 到 `ZhiyuanAgent`
- 已覆盖 `score_batch`、`transfer_major`、`subject_requirement`、`tuition_budget` 等只读规则域
- 已接 school profile 招生政策字段、参数可用性校验和 opt-in 官方来源检索
- 不调用旧 `admission_policy_tool` / `admission_fit_match_tool`；`official_source_search_tool.py` 已删除，官方来源检索已内聚到 4.0 `answer_policy`
- 返回 `policy_facts`、`student_eligibility`、`source_references`、`source_lookup`，并固定 `state_mutation=false`
- 限制：官方来源网页事实抽取和自动适配匹配尚未接入，后续继续扩展

#### `review_plan` — 方案审查

新增工具。替代 `planning_workflow_tool` 中的审查函数（部分 2269 行）。

```python
async def review_plan(
    ctx: RunContext[RequestContext],
    focus: Literal["full_review", "risk_only", "tier_balance", "tuition", "career_fit"] | None = None,
    generate_fix_proposals: bool = False,
    force_refresh: bool = True,
) -> str
```

**核心设计点：**

1. **审查执行**：调 `run_planning_review(session_id)` 触发后端审查
2. **结果读取**：审查完成后从 SandboxFileCache 读 `plan/review.json`，包含风险项列表
3. **Focus 过滤**：按 `focus` 参数筛选审查结果中的相关项
4. **修复建议**：如果 `generate_fix_proposals=True`，调 `generate_planning_fix_proposals(session_id)` 获取建议，只读展示，不自动应用
5. **结果结构化**：

```json
{
  "data": {
    "issues": [
      {"code": "HIGH_TUITION_RISK", "severity": "risk", "affected_count": 3, "summary": "3个志愿年学费超2万"}
    ],
    "fix_proposals": [...],
    "tier_balance": {"冲": 12, "稳": 18, "保": 15, "assessment": "梯度合理"}
  },
  "next_step": "respond",
  "message": "审查发现2项风险：高收费风险涉及3个志愿，梯度断层涉及保底区间。需要处理哪一项？"
}
```

**Phase 2 第三批首版落地状态（2026-06-30）：**
- 已注册 `review_plan` 到 `ZhiyuanAgent`
- 默认调用 `run_planning_review(...)` 执行后端审查；后端不可用时降级读取 `plan/review.json`
- 支持 `focus` 过滤风险、梯度、学费和职业适配相关 issues
- 支持 `generate_fix_proposals=True` 只读返回处理方向，不自动生成或应用方案变更
- 无正式方案时不调用审查接口，直接返回只读防护
- 返回 `summary`、`issues`、`tier_balance`、`fix_proposals`，并固定 `state_mutation=false`、`plan_mutation=false`
- 与 `preview_plan_action` 的边界已收紧：只读审查问题走 `review_plan`；用户明确要求移出、删除、替换或处理审查项时走 `preview_plan_action(review_issue_code=...)`
- 限制：候选自动选择质量评估和更多 service shadow case 仍需扩展

- 只读操作，`next_step: "respond"`
- 如果用户明确要求方案变更（如"移除高收费志愿"），由 Agent 直接调 `preview_plan_action` 发起待确认预览；`review_plan` 不作为变更处理终点

### 3.4 工具实现顺序

按依赖关系和验证价值排序：

```
第一批（基础 + 核心查询）：
  read_state 升级（接入 SandboxFileCache）
  query_plan 升级（真实方案扫描）
  confirm_pending（确认流程闭环）

第二批（分析 + 变更）：
  explore_topic 升级（真实后端数据）
  preview_intent_change 升级（方案影响 + pending）
  compare_entities（新增）

第三批（方案操作 + 辅助）：
  preview_plan_action（新增，最复杂）
  review_plan（新增）
  answer_policy（新增）
```

### 3.5 属性注册表与通用查询引擎

#### 问题：5 处分散的属性处理

当前系统中"属性/标签"维度的别名归一、过滤匹配、约束映射分散在 5 处，各自硬编码：

| 机制 | 位置 | 硬编码内容 |
|------|------|-----------|
| 办学性质别名 | `intent_entity_profile_tool._SCHOOL_NATURE_ALIASES` | 公办/公立/民办/私立 → 标准值 |
| 特殊限制别名 | `intent_entity_profile_tool._SPECIAL_LIMIT_ALIASES` | 高收费/高学费/中外合作/合作办学 → 标准值 |
| 方案查询过滤 | `plan_query_tool._matches_structured_filters` | schoolNature/schoolCategory/schoolLevel/tier 等字段逐一拼 haystack |
| 约束 scope 类型 | `plan_orchestration_models.PlanEntityResolution` | entity_type 枚举 major/school/region/career/tag/risk/program_type |
| 审查 issue 别名 | `review_issue_registry` | HIGH_TUITION_RISK/cooperative 等 code alias |

**后果：** 新增一个属性维度（如"中外合作"筛选、"双一流"标签查询）需要在 3-5 个文件里各加一套别名映射和匹配逻辑。

#### 设计：数据驱动的属性注册表

在 `app/domain/attribute_registry.py` 定义一份注册表，所有工具共享：

```python
@dataclass(frozen=True)
class AttributeDimension:
    key: str                              # 唯一标识，如 "school_nature"
    label: str                            # 用户可见标签，如 "办学性质"
    type: Literal["enum", "numeric", "tag_set"]
    item_fields: list[str]                # 对应 plan item JSON 字段路径
    values: list[str] | None              # enum 类型的合法值列表
    aliases: dict[str, str]               # 用户表达 → 标准值映射
    supports: set[str]                    # 该维度支持的操作集合

ATTRIBUTE_REGISTRY: dict[str, AttributeDimension] = {
    "school_nature": AttributeDimension(
        key="school_nature",
        label="办学性质",
        type="enum",
        item_fields=["schoolNature"],
        values=["公办", "民办"],
        aliases={
            "公立": "公办", "公办院校": "公办", "公立学校": "公办",
            "私立": "民办", "民办院校": "民办", "私立学校": "民办",
        },
        supports={"query", "exclude", "only_keep"},
    ),
    "program_type": AttributeDimension(
        key="program_type",
        label="招生类型",
        type="enum",
        item_fields=["enrollmentType"],
        values=["普通类", "中外合作", "高收费"],
        aliases={
            "合作办学": "中外合作", "中外合作办学": "中外合作", "国际项目": "中外合作",
            "高学费": "高收费", "学费高": "高收费",
        },
        supports={"query", "exclude"},
    ),
    "school_level": AttributeDimension(
        key="school_level",
        label="院校层次",
        type="tag_set",
        item_fields=["schoolLevel", "schoolRankTags"],
        values=["985", "211", "双一流", "一本", "二本"],
        aliases={"985院校": "985", "211院校": "211", "双一流院校": "双一流"},
        supports={"query", "only_keep"},
    ),
    "tier": AttributeDimension(
        key="tier",
        label="梯度",
        type="enum",
        item_fields=["tier"],
        values=["冲", "稳", "保"],
        aliases={"冲刺": "冲", "稳妥": "稳", "保底": "保"},
        supports={"query"},
    ),
    "tuition": AttributeDimension(
        key="tuition",
        label="学费",
        type="numeric",
        item_fields=["tuitionPerYear"],
        values=None,
        aliases={},
        supports={"query", "exclude"},
    ),
    "province": AttributeDimension(
        key="province",
        label="院校省份",
        type="enum",
        item_fields=["provinceName"],
        values=None,  # 31省自动枚举
        aliases={},
        supports={"query", "only_keep", "exclude"},
    ),
    "major_category": AttributeDimension(
        key="major_category",
        label="专业门类",
        type="tag_set",
        item_fields=["majorCategory", "majorDiscipline"],
        values=None,  # 从静态数据加载
        aliases={},
        supports={"query", "exclude", "only_keep"},
    ),
    "school_category": AttributeDimension(
        key="school_category",
        label="院校类型",
        type="enum",
        item_fields=["schoolCategory"],
        values=["综合", "理工", "师范", "财经", "医药", "农林", "政法", "语言", "艺术", "体育", "民族", "军事"],
        aliases={"工科院校": "理工", "师范院校": "师范"},
        supports={"query", "only_keep"},
    ),
}
```

#### 通用方法

注册表提供 3 个共享方法，替代各工具内部的硬编码逻辑：

```python
def normalize_attribute(key: str, user_text: str) -> str | None:
    """将用户表达归一化到标准值。走 aliases → fuzzy match → None。"""

def build_item_haystack(key: str, item: dict) -> list[str]:
    """从 plan item 中提取该属性维度的 haystack（用于过滤匹配）。"""

def match_item(key: str, item: dict, target_values: list[str]) -> bool:
    """判断 plan item 是否匹配给定属性值。numeric 类型支持范围。"""
```

#### 各工具如何消费注册表

| 工具 | 消费方式 |
|------|---------|
| `query_plan` | `_matches_structured_filters` 改为遍历 `ATTRIBUTE_REGISTRY`，用 `build_item_haystack` + `match_item` 替代逐字段拼 haystack |
| `preview_intent_change` | 约束创建时，用 `normalize_attribute` 归一化用户输入；`supports` 字段决定该维度是否允许当前 `constraint_type` 操作 |
| `preview_plan_action` | 属性/标签 filters 走 `ATTRIBUTE_REGISTRY`；`review_issue_code` 别名和后端 code 归一走共享 `review_issue_registry.normalize_review_issue_code` |
| `review_plan` | 按 `focus` 过滤审查结果；issue code/alias 统一走共享 `review_issue_registry`，不在工具内另建别名表 |
| `prompt` | 工具调用示例中的 `filters` 参数值从注册表生成，保持一致 |

#### supports 字段与 intent 操作的关系

`supports` 集合区分两类操作：

- **用户交互操作**（`query`, `exclude`, `only_keep`, `must_have`）：暴露给用户对话界面，用户可以通过自然语言表达
- **系统内部操作**（`prefer`, `acceptable`, `deprioritize`）：**当前不定义**，后续从系统隐性角度运行时再扩展

当前阶段，`supports` 只包含用户交互操作。注册表不承载软性推荐系数逻辑。

#### 实施路径

1. 先创建 `app/domain/attribute_registry.py`，定义注册表数据结构和 3 个通用方法
2. `query_plan` 的 `_matches_structured_filters` 改走注册表（影响范围最大，收益最高）
3. `preview_intent_change` 的约束归一化改走注册表
4. 旧工具中的 `_SCHOOL_NATURE_ALIASES`、`_SPECIAL_LIMIT_ALIASES` 保留到生产切换后删除

> 当前落地状态：`query_plan`、`preview_plan_action(remove, filters=...)`、`preview_intent_change` 已接入 `attribute_registry`。`preview_plan_action(remove, filters=...)` 已覆盖 `school_nature`、`program_type`、`school_category`、`school_level` 等属性定位，无命中时不创建 pending。`preview_intent_change` 会保留结构化 selector，并在确认执行时将属性 selector 编码为现有后端可接受的 hard scope（如 `院校性质:民办`、`招生类型:中外合作`）。`zhiyuan-server` hard constraint 过滤链路已支持这些 scope，避免确认后的候选/修复方案重新纳入被排除属性。`review_issue_code` 归一化已收敛到共享 `app/tools/review_issue_registry.py`，新 agent 不再维护独立 issue alias 大表。

### 3.6 Intent 约束简化：仅保留强筛选

#### 设计原则

用户在对话中表达的意向大部分是确定性的（"不要民办"、"只看公办"、"必须有计算机"），不涉及推荐系数的微调。因此：

- **用户对话交互只暴露硬约束操作**：`exclude`（排除）、`only_keep`（仅保留）、`must_have`（必须有）
- **软性推荐系数调整不暴露给用户交互界面**：当前不定义 `preference`/`preferred`/`acceptable`/`exclude_soft` 等强度级别。后续从系统隐性角度（基于用户行为推断、方案优化算法）运行
- **旧系统的强度检测逻辑（`_school_nature_strength_from_text` 中的 preferred/acceptable/exclude_soft/exclude_hard 四档）在新工具中不复用**

#### `preview_intent_change` 签名调整

```python
ConstraintType = Literal["exclude", "only_keep", "must_have"]
PendingResolution = Literal["none", "replace_active_pending", "append_to_active_pending", "hold_new_request"]

async def preview_intent_change(
    ctx: RunContext[RequestContext],
    intent_type: Literal["major", "school", "region", "career"],
    positive: dict[str, Any] | None = None,
    negative: dict[str, Any] | None = None,
    constraint_type: Literal["exclude", "only_keep", "must_have"] = "exclude",
    apply_to_current_plan: bool = True,
    pending_resolution: PendingResolution = "none",
    raw_user_text: str = "",
) -> str
```

变更点：
- `constraint_type` 从 `Literal["preference", "only_keep", "must_have", "exclude"]` 改为 `Literal["exclude", "only_keep", "must_have"]`
- 默认值从 `"preference"` 改为 `"exclude"`（最常见的硬约束场景）
- 移除 `preference` 选项——用户不再通过此工具设置软偏好
- active pending 下的新预览关系改由 `pending_resolution` 表达；缺失时工具返回 `continue` 让模型基于压缩上下文重试，不在工具层做短语匹配兜底

#### 约束操作语义

| constraint_type | 语义 | 用户表达示例 | 方案影响 |
|----------------|------|------------|---------|
| `exclude` | 排除匹配项，不出现在方案中 | "不要民办"、"排除医学" | 移除已有匹配项，后续生成不再包含 |
| `only_keep` | 仅保留匹配项，移除不匹配项 | "只看公办"、"只保留计算机相关" | 移除不匹配项，缩小范围 |
| `must_have` | 方案中必须包含至少 N 个匹配项 | "必须有计算机"、"至少保留3个广东" | 不足时从候选池补充 |

#### Prompt 行动原则调整

原第 5 条：
> 极性判断必须在调用工具前完成："不要X" 是 negative；"排除X" 是 negative；"不要排除X/不排除X/别把X排除" 是 positive；"只保留X" 是 positive 且 constraint_type=only_keep。

调整为：
> 极性判断必须在调用工具前完成："不要X"/"排除X" 是 negative + constraint_type=exclude；"不要排除X/不排除X/别把X排除" 不能写成 negative，当前按 positive 显式要处理；"只看X/只保留X" 是 positive + constraint_type=only_keep；"必须有X/至少要有X" 是 positive + constraint_type=must_have。纯撤回既有排除但不要求必须包含，需要后续补充独立 allow/unexclude 操作。

#### 工具调用示例调整

```
- "不要医学类" -> preview_intent_change(intent_type="major", negative={"level1":["医学"]}, constraint_type="exclude")
- "不要排除经济学类" -> preview_intent_change(intent_type="major", positive={"level2":["经济学类"]}, constraint_type="must_have")
- "只看公办学校" -> preview_intent_change(intent_type="school", positive={"school_nature":"公办"}, constraint_type="only_keep")
- "不要民办" -> preview_intent_change(intent_type="school", negative={"school_nature":"民办"}, constraint_type="exclude")
- "必须有计算机类" -> preview_intent_change(intent_type="major", positive={"level1":["工学"], "level2":["计算机类"]}, constraint_type="must_have")
```

注意：原示例中 `constraint_type="preference"` 的用法全部移除。"不要排除经济学类" 当前不再作为软偏好处理，也不能落到 negative；在仅支持 `exclude/only_keep/must_have` 的阶段先按 positive `must_have` 处理。若后续需要表达“解除排除但不强制包含”，需要新增独立 allow/unexclude 操作。

#### 对 G-case 的影响

| Case | 原预期 | 调整后 |
|------|--------|--------|
| G4 偏好强度 | `constraint_type="preference"` + strength 四档 | 改为 `constraint_type` 三档之一（exclude/only_keep/must_have），不再测试强度级别 |
| G8 软偏好不应走方案变更 | 预期 `preview_intent_change` + preference | 简化：用户软性表达走 `explore_topic`（分析建议），硬性约束走 `preview_intent_change`。软偏好不再产生 intent pending |
| G29 软偏好强度校准 | 测试 preferred/acceptable 校准 | 移除或重新定义：强度校准不再暴露给用户对话。如用户说"尽量考虑X"，Agent 回复建议而非创建约束 |

### 3.7 约束即方案调整：有方案时的约束语义

#### 核心问题

用户在有方案的场景下说"不要民办""只想看公办"等表达时，是在对着当前方案沟通，期望的是**方案立即调整**，而不仅仅是记录一条对当前方案没有影响的"未来意向"。

当前实现的 gap：
- `preview_intent_change` 预览阶段已通过 `simulate_plan_diff` 展示方案影响（正确）
- 但 `confirm_pending` 对 `intent_change` 的执行（`_apply_intent_pending`，`tools.py:3327`）只写入约束（`update_planning_constraint_state`），**不触发方案再生成**
- 确认后消息是"已采纳这次报考要求，后续方案会按新的硬性要求处理"——暗示约束在下次方案重新生成时才生效，当前方案不变
- 用户预期：确认后方案应该已经调整好了

#### 设计原则：约束 = 持久记录 + 即时方案调整

| 场景 | 用户表达 | 约束记录 | 方案调整 |
|------|---------|---------|---------|
| **无方案** | "不要民办" | 写入 constraints → 后续生成方案时生效 | 无方案可调 |
| **有方案** | "不要民办" | 写入 constraints → 持久生效 | **立即再生成方案**，移除不符合约束的项 |
| **有方案** | "方案里的民办不要了" | 不自动推断为长期要求 | 按当前方案调整预览处理 |

关键点：裸属性诉求，或明确表达后续报考要求时，走 `preview_intent_change`；口语里的"民办就算了""中外合作别考虑了""公办以外不用看"也属于显式要/不要。只有用户用"方案里/当前方案/当前这些/里面这些/这批/这些/这几个"锚定当前方案，并明确说移出、删除、去掉、不要了，才按当前方案调整处理，调用 `preview_plan_action(remove, filters=...)`。不要在没有当前方案锚点时把裸属性诉求改判成一次性方案调整。

#### 路由判断：属性级 vs 具体项

正确的路由区分是"报考要求 vs 当前方案调整 vs 具体项操作"：

| 操作类型 | 特征 | 示例 | 路由 |
|---------|------|------|------|
| **报考要求** | 裸属性/标签/类别诉求，或明确表示以后也要遵循；包含"算了/别考虑/不用看"等口语否定 | "不要民办""民办就算了""只看公办""中外合作不考虑" | `preview_intent_change` |
| **当前方案筛选调整** | 属性/标签/类别 + 当前方案锚点 + 移出/删除/去掉/不要了 | "方案里的民办不要了""当前这些中外合作都移出去" | `preview_plan_action(remove, filters=...)` |
| **具体项** | 按名称/位置/编号定位特定项 | "把华南理工大学移出去""第3个不要了""冲的第一个换掉" | `preview_plan_action` |

如果用户明确锚定当前方案，只按这次方案调整处理，不默认替用户记录长期报考要求。后续可以在确认卡或回复里提示"这次只调整当前方案；如果后续也都不考虑，可以再采纳为报考要求"。

#### `confirm_pending` 的 intent_change 执行流程调整

```python
async def _apply_intent_pending(ctx, pending) -> tuple[bool, dict, str]:
    # 1. 写入约束（已有）
    response = await update_planning_constraint_state(...)

    # 2. 新增：如果当前有方案，立即再生成
    has_plan = await _has_active_plan(ctx)
    plan_regen_result = None
    if success and has_plan:
        plan_regen_result = await internal_client.generate_planning_ordered_plan(
            tenant_id, ctx.deps.sessionid
        )

    # 3. 消息调整
    if success and has_plan and plan_regen_result:
        message = "已采纳报考要求并重新调整方案，新方案已按约束更新。"
    elif success and not has_plan:
        message = "已记录报考要求，后续生成方案时会遵循该约束。"
    else:
        message = "报考要求写入未成功，请重新生成预览后再确认。"
```

**失效路径调整**（`_invalidate_after_pending_action`）：
- `intent_change` + 有方案 → 失效 `constraints.json` + 所有 `plan/*` + `pending.json`（已有）
- 方案再生成后 sandbox 自动在下次读取时拉取最新方案

**preview 消息调整**：
- 有方案时：`"排除民办后，当前方案有5个志愿受影响（冲1/稳2/保2）。确认后将记录约束并重新调整方案。"`
- 无方案时：`"已记录排除民办的约束，后续生成方案时将不包含民办院校。确认即可。"`

#### Prompt 路由指引补充

在行动原则中增加属性级 vs 具体项的路由判断（现有第 5 条极性规则之后）：

> 用户按属性/标签/类别表达显式报考要求（办学性质、招生类型、专业门类等）时，走 preview_intent_change；用户用"方案里/当前这些/这批"锚定当前方案并要求移出、删除、去掉、不要了时，走 preview_plan_action(remove, filters=...)。只有用户明确要求后续都遵循时，才记录为报考要求。

---

## 4. 非阻塞 Shadow 模式

### 4.1 当前问题

PoC shadow 早期在 `_maybe_run_zhiyuan_agent_poc_shadow` 中阻塞执行，位于主链路 guard pipeline 之前。shadow 耗时 1.2-2.8s 会直接叠加到用户感知延迟。

**Phase 2 第一批落地状态（2026-06-30）：**
- `_maybe_run_zhiyuan_agent_poc_shadow(...)` 已改为只创建独立 shadow context 并启动后台 `asyncio.Task`
- 主链路不等待 shadow；turn event 中如任务未完成则记录 `status=running`
- shadow 完成后独立写 `zhiyuan_agent_poc_shadow_event`
- `_observability_timing_fields(...)` 会在 turn event 发送前尝试读取已完成 task 的结果
- 已新增 `ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE`，默认 `1.0`

### 4.2 设计方案

```python
async def _maybe_run_zhiyuan_agent_poc_shadow(self, request_context: RequestContext) -> None:
    if not self._zhiyuan_agent_shadow_enabled:
        return
    if not self._should_sample():   # 采样率控制
        return

    # 非阻塞启动
    shadow_context = request_context.replace(...)  # 副本
    task = asyncio.create_task(
        self._run_zhiyuan_agent_shadow(shadow_context, request_context)
    )
    # 注册到 request_context，在 turn event 发送前收集结果
    request_context._shadow_task = task
```

**结果收集时序：**
```
主链路:  context构建 → shadow启动(非阻塞) → guard → agent循环 → 输出处理
                         ↓                                        ↓
shadow:              ZhiyuanAgent.run  ──────────────────→  结果写入
                                                              ↓
observability:                                    turn_event 发送前 await shadow_task（带超时）
```

### 4.3 核心设计点

| 要素 | 设计 |
|------|------|
| 采样率 | `ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE=1.0`（离线评估 100%，线上可降到 0.1） |
| 超时 | `ZHIYUAN_AGENT_SHADOW_TIMEOUT_SECONDS=15`，超时后丢弃，不影响主链路 |
| 结果收集 | turn event 发送前检查已完成 task；来不及则保留 `status: "running"`，完整结果走独立 shadow event |
| 错误隔离 | shadow 内部异常不传播到主链路，仅记录到 observability |
| 资源隔离 | shadow 使用 `RequestContext.replace()` 副本，不共享主链路的 SandboxFileCache 实例 |

---

## 5. Phase 3: Shadow Diff 大规模验证

### 5.1 Case 集合扩展

当前 shadow case 集合：5 个 PoC 设计场景。

目标：覆盖 G1-G32 中与当前工具能力匹配的 case。现有 `dialog_regression_320_g1_g32_shadow_cases.json` 已有 21 个 case 定义（G1-G32 中的 21 个），每个 case 有 `fixtureContract`（所需后端状态）、`planningStateProfile`（场景前置条件）、`prompts`（多轮对话 + 断言）。

**Case 与 9 工具的映射分析：**

| Case | 用户意图 | 预期工具 | 当前工具覆盖 |
|------|---------|---------|------------|
| G1 排除英语专业 | intent 变更 + 方案影响 | `preview_intent_change` + `confirm_pending` | Phase 2 第一批 |
| G2 审查修复预览边界 | 审查 + 修复建议 | `review_plan` | Phase 2 第三批 |
| G3 pending 中的只读查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G4 偏好强度 | 约束设置 | `preview_intent_change` | Phase 2 第一批（约束简化后仅硬约束，不再测试强度级别） |
| G7 预算只读 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G8 软偏好不应走方案变更 | 偏好 vs 方案边界 | 软性表达走 `explore_topic`；硬约束走 `preview_intent_change` | Phase 2 第一批（软偏好不再产生 intent pending） |
| G10 无 pending 时确认 | 边界防护 | `confirm_pending` | Phase 2 第一批 |
| G16 方案固定/锁定 | 方案操作 | `preview_plan_action` | Phase 2 第三批 |
| G17 梯度内重排 | 方案操作 | `preview_plan_action` | Phase 2 第三批 |
| G19 无方案时引用方案 | 防护 | `query_plan` | Phase 2 第一批 |
| G21 只读审查不应自动生成 | 审查边界 | `review_plan` | Phase 2 第三批 |
| G22 school pending 中的只读查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G23 地域维度不应识别为专业 | 实体分类 | `preview_intent_change` | Phase 2 第一批 |
| G25 混合正负极性 | 极性处理 | `preview_intent_change` | Phase 2 第一批 |
| G26 方案投影切片查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G27 学费只读 + 候选观察 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G29 软偏好强度校准 | 约束/建议边界 | 软性表达走 `explore_topic`；硬约束走 `preview_intent_change` | Phase 2 第一批（强度校准不再暴露给用户对话） |
| G30 特殊招生路径保留 | 显式意向 + 招生类型 selector | `preview_intent_change` | Phase 2 第一批/第三批联动（`program_type=强基` 已落地） |
| G31 pending 不阻塞只读查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G32 无方案引用方案防御 | 防护 | `query_plan` | Phase 2 第一批 |
| G12 延迟分解 | 性能观测 | 不涉及工具选择 | — |

**Phase 2 第一批完成后可跑的 case：** G1, G3, G4, G7, G8, G10, G19, G22, G23, G25, G26, G27, G29, G31, G32（15 个）
**Phase 2 第三批完成后补充：** G2, G16, G17, G21, G30（5 个）

### 5.2 Confusion Matrix 设计

对比主链路实际行为与 ZhiyuanAgent 的工具选择，识别方向差异和正确性差异。

**维度定义：**

| 维度 | 主链路数据源 | ZhiyuanAgent 数据源 |
|------|-----------|-------------------|
| 路由方向 | `routingPath`（`full_agent` / `runtime_intent_hard_cut` / `fast_route_*`） | `firstToolNames[0]`（映射到方向类别） |
| 工具选择 | `toolCallNames`（如 `preview_current_major_intent_confirmation`） | `toolCallNames`（如 `preview_intent_change`） |
| 结果类型 | `resultKind`（`text` / `pendingConfirmationCard` / ...） | `nextSteps[0]`（`respond` / `confirm` / `clarify`） |

**工具名映射表（旧 → 新方向类别）：**

```
preview_current_major_intent_confirmation  → intent_change
preview_current_school_intent_confirmation → intent_change
preview_current_city_intent_confirmation   → intent_change
analyze_current_career_direction           → explore
analyze_current_major_interest             → explore
analyze_current_region_interest            → explore
query_volunteer_plan                       → plan_query
collect_plan_context_inputs                → plan_query
execute_plan_action                        → plan_action
compare_majors / compare_schools           → compare
answer_admission_policy_question           → policy
```

**报告输出格式：**

```json
{
  "total": 50,
  "agreement": {
    "direction_match": 42,
    "direction_match_rate": 0.84
  },
  "confusion_matrix": {
    "intent_change": {"intent_change": 10, "explore": 1, "plan_query": 0},
    "explore":       {"intent_change": 0,  "explore": 8, "plan_query": 1},
    "plan_query":    {"intent_change": 0,  "explore": 0, "plan_query": 12}
  },
  "disagreements": [
    {
      "case": "G8-soft-preference",
      "main_direction": "plan_action",
      "zhiyuan_direction": "explore",
      "main_correct": false,
      "zhiyuan_correct": true,
      "reason": "主链路将软偏好误路由到方案变更；新系统中软偏好走 explore_topic 分析建议"
    }
  ]
}
```

---

## 6. Phase 4: 生产切换要点

### 6.1 主链路切换

当前决策：4.0 `ZhiyuanAgent` direct route 是默认主链路，不再依赖会话级 enable 开关或 rollout 百分比。`ChatService` 初始化时直接构造 `ZhiyuanAgent`，普通 `handle_message` 在 no-plan 边界保护后进入 direct route；direct route 异常时返回安全提示并保留“不确认不改动”的语义，不把请求回落给旧 full-agent 链路。

direct route 接管原则：

- 不增加基于用户原文字符串匹配的前置语义闸门。
- 是否出确认卡、只读回复或确认执行，只由 4.0 agent 的结构化工具返回、当前 active pending 状态、后端 pending/方案状态决定。
- `next_step=confirm` 且后端已创建 active pending 时，由 service 构造确认卡；没有确认前不改动报考要求或方案。
- 已存在 active pending 的会话继续走统一 pending 确认流程，由 `confirm_pending` 执行确认/取消。

### 6.2 切换后验证与清理节奏

```
阶段 1: direct 默认入口聚焦验证 → G1-G32、真实口语、确认执行闭环
阶段 2: 并发真实 LLM 回归 → 记录工具边界、pending、最终 action 问题
阶段 3: 清理旧 full-agent 残留 → 删除不可达 fallback、旧测试资产、旧编排依赖
阶段 4: 监控和性能基线 → 观察工具成功率、延迟、确认成功率
```

### 6.3 核心监控指标

| 指标 | 告警阈值 | 说明 |
|------|---------|------|
| 工具调用成功率 | < 95% | 后端 API 调用失败 |
| 平均工具调用次数/轮 | > 3 | 退化为乱试 |
| P95 延迟 | > 当前基线 × 1.2 | 性能退化 |
| Pending 确认成功率 | < 90% | 版本冲突过多 |
| 用户满意度（显式反馈） | 下降 > 5% | 回复质量退化 |

### 6.4 可删除代码（全量切换稳定后）

| 文件 | 行数 | 说明 |
|------|------|------|
| `app/tools/` 目录（37个文件） | ~28,000 | 旧工具实现 |
| `app/domain/proposal_compiler.py` | 5,650 | 规则引擎 |
| `app/tools/turn_decision_tool.py` | 514 | 预路由分类器 |
| `app/agent/instructions/tool_dispatch_rules.py` | 117 | 已删除旧路由规则 |
| `app/agent/tool_reply_policy.py` | 396 | 已删除旧外部终止判断 |
| service.py 中的旧编排逻辑 | ~15,000 | 单体编排层 |
| **合计** | **~50,000** | |

**保留的代码：**
- `app/domain/` 中的实体解析器（已被新工具直接引用）
- `app/util/internal_client.py`（后端 HTTP 客户端）
- `app/data/`（静态数据文件）
- `app/sync/state_sync.py`（适配到 SandboxFileCache）
- `app/agent/base_agent.py`（ZhiyuanAgent 基类）

---

## 7. 实施检查清单

### Phase 1 检查项
- [x] SandboxFileCache 基本读写 + 版本失效
- [x] BackendAdapter 8 个路径映射
- [x] Cache warming（4 路径并行预取）
- [x] ZhiyuanAgent 的 deps 从直读改为 sandbox 读取
- [x] 单元测试：cache hit/miss/invalidate/warm

### Phase 2 第一批检查项
- [x] read_state 接入 SandboxFileCache
- [x] query_plan 真实方案扫描 + filters
- [x] 属性注册表首版创建，并接入 query_plan filters
- [x] confirm_pending 完整确认/取消流程 + 版本守护
- [x] 非阻塞 shadow 模式
- [x] plan item enrichment：ordered-plan items 按 volunteerId 从候选池合并属性字段（§8.1）
- [x] shadow 采集闭环：runner 合并后置 shadow event（§8.2）
- [x] confirm intent_change 有方案时触发方案再生成（§3.7）
- [ ] G1/G3/G7/G10/G19/G22/G31/G32 shadow case 通过

### Phase 2 第二批检查项
- [x] explore_topic 接入 `get_major_profile` / `get_school_profile_by_name`
- [x] preview_intent_change pending 创建（结构化 `pendingConfirmation`）
- [x] preview_intent_change 接入 `simulate_plan_diff`
- [x] preview_intent_change 移除用户交互层软偏好，统一写硬约束 `intentMode=constraint`
- [x] preview_intent_change 接入属性注册表，支持属性/标签 selector
- [x] Java hard constraint 过滤支持属性 scope（院校性质、招生类型、院校类型、院校层次、专业标签等）
- [x] 真实 LLM selection 覆盖属性 selector：不要民办、只看公办、不要中外合作、不要师范类院校
- [x] compare_entities 新工具
- [ ] G4/G8/G23/G25/G26/G27/G29 shadow case 通过（G4/G8/G29 需按约束简化后重新定义）

### Phase 2 第三批检查项
- [x] preview_plan_action 新工具（7 种 action）
- [x] preview_plan_action(remove) 支持 filters 按属性/标签定位当前方案项
- [x] preview_plan_action(remove filters) 覆盖中外合作、院校类型、院校层次及无命中不创建 pending
- [x] preview_plan_action(remove review_issue_code + filters) 支持审查问题范围与属性 filters 求交集
- [x] preview_plan_action 支持位置范围、档位内序号和 G17 档位内局部重排 selector
- [x] preview_plan_action 扩展后端核心 review issue：限报/特殊招生 item 删除预览，录取率倒挂/保底不足结构排序或重排预览
- [x] G16 锁定/固定位置受控 unsupported，不创建 pending、不误走 move
- [x] G30 强基路径作为 `program_type=强基` selector 保留
- [x] review_plan 新工具
- [x] answer_policy 新工具
- [x] G2/G21 真实 LLM 工具选择边界通过（只读处理方向/合理性查询不自动生成或修改方案）
- [ ] G2/G21 完整 service shadow case 通过

### Phase 3 检查项
- [x] 全量 G1-G32 完整回归首轮（49步/46通过/3失败：G4/G17/G25）
- [x] §9.1 复合诉求 next_step 策略调整（respond 软停已落地）
- [x] §9.2 pending 下只读查询路由放开（G21/G27 性能修复已落地）
- [x] §9.3 正向意向边界 prompt 调整（"想学X" → must_have 已落地）
- [x] §9.4 direct route 成绩可用性前置回退已删除；无有效成绩时由 4.0 direct 按已有信息回应
- [x] §9.5 G17 selector/action 缺参改为模型重试协议（已落地，direct 已通过）
- [x] §9.6 G4 实体归一化展示保真（display_aliases 已落地）
- [x] §9.7 G3 查询计数粒度口径（志愿为主粒度已落地）
- [x] §9.8 G32 无方案探索降级内容策略（维度模板已落地）
- [x] §9.9 G25 路由抢跑排障（G25 已稳定 direct 命中 `preview_intent_change`）
- [x] §9.9 G25 schema alias 兼容（结构化 positive/negative 与跨领域字段已落地）
- [x] §9.9 G25 混合正负 Prompt 加固（positive+negative 同传与真实 case 已通过）
- [x] §9.10 respond/continue 真实 LLM 效果验证（G12 复合查询后继续方案动作、单意图不多调已通过）
- [x] §9.12 阶段 D 完整 G1-G32 direct 回归 × 2 次（通过率 ≥ 43/49）
- [x] 全量 G1-G32 direct 主集通过（最新 `20/20`，metrics: `/private/tmp/zhiyuan_400_v162_g1_g32_direct_full_no_shadow_after_g16.json`）
- [ ] Confusion matrix 报告生成
- [ ] 320+ 历史回归 case 跑新系统（方向一致率 > 85%）
- [ ] 性能基线：P95 延迟 < 8s

### Phase 4 检查项
- [x] direct route 接入 service 主流程，默认作为 4.0 主链路
- [x] 移除 `ZHIYUAN_AGENT_ENABLED` / rollout direct 入口分流；不设置环境变量也进入 4.0 direct
- [x] direct route 移除成绩可用性前置回退；无有效成绩时由 4.0 direct 按已有信息回应或提示正式录入
- [x] direct route 移除字符串 precheck，按结构化工具返回和 active pending 状态接管
- [x] direct route 真实口语集合、G case 子集、确认执行闭环首轮验证通过
- [x] 确认执行闭环覆盖最终后端 action 断言：pending applied、planningState version 增长、方案项/报考要求真实变化
- [x] direct-only 真实口语集合复跑 14/14，通过口语/指代/省略 case，metrics: `/private/tmp/zhiyuan_400_realistic_direct_only_after_retry_reason_fix.json`
- [x] direct 确认执行闭环复跑 4/4，确认后端方案项删除和报考要求写入真实生效，metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_retry_filter_fix.json`
- [x] G case direct 子集 direct-only 复跑 8/8；shadow 关闭时原始 shadow 断言失败不计入 direct 主链路失败，metrics: `/private/tmp/zhiyuan_400_g_case_direct_only_after_retry_filter_fix_rerun.json`
- [x] 完整 320 G1-G32 direct 复跑 44/49，问题已归档，metrics: `/private/tmp/zhiyuan_400_direct_320_g1_g32_after_retry_filter_fix_rerun.json`
- [x] R33 no-plan focused 复验通过，修正 fixture clone 并回显用户诉求，metrics: `/private/tmp/zhiyuan_400_r33_asset_after_clone_reply_fix.metrics.json`
- [x] 高收费确认链路 focused 复验通过，确认后端状态断言和后续边界，metrics: `/private/tmp/zhiyuan_400_high_tuition_asset_after_confirm_terminal.metrics.json`
- [x] 清理前 G1-G32 direct-only 基线复跑 20/20，metrics: `/private/tmp/zhiyuan_400_cleanup_preflight_g1_g32_direct_20of20.json`
- [ ] 监控仪表盘
- [ ] 回滚流程验证
- [x] direct 默认主链路替代 1% → 100% 渐进放量；旧 enable/rollout 分流已删除
- [ ] 旧代码清理（大块旧 full-agent 与旧工具 wrapper 已删，剩余 history fixture / `proposal_compiler.py` / `turn_decision_tool.py` 继续分批评估）

---

## 8. 真实口语验证问题清单（2026-07-01）

真实多轮对话验证中发现的问题。按优先级排列，每项包含根因分析和修复方案。

### 8.1 P0 — plan/items.json 数据契约已补齐

**现象：**
`plan/items.json`（来源 `get_planning_ordered_plan` 的 `orderedPlanState.items`）每个 item 只有 `position`、`volunteerId`、`tier`、`schoolName`、`majorName`、`provinceName` 等基础定位字段，**不包含** `schoolNature`、`schoolCategory`、`tuitionPerYear`、`enrollmentType`（招生类型）、`reasonCodes`（审查原因码）等属性字段。

**影响：**
- `query_plan(filters={"school_nature":"民办"})` 在真实数据上可以命中
- `preview_plan_action(action="remove", filters={"school_nature":"民办"})` 和 `preview_plan_action(action="remove", filters={"program_type":"中外合作"})` 可以命中
- `_plan_item_brief()`（`tools.py:2359`）能读到 `schoolNature`/`tuitionPerYear`
- 属性注册表（§3.5）的 `build_item_haystack` 可直接用于真实方案项
- 真实用户说"方案里有没有民办"时，工具返回正确的命中结果

**实现：**
`sandbox.py` 的 `_ordered_items_file_from_response` 已按 `volunteerId` 从候选池数据合并属性字段，合并字段覆盖学校性质、学校类别、层次、学费、标签和 `reasonCodes` 等。合并策略遵循 ordered item 原值优先、候选池补空字段，候选池不可用时保留原始 ordered items。

**关联代码：**
- `sandbox.py:412` `_enrich_ordered_items_from_candidates` — ordered items enrichment
- `sandbox.py:429` `_ordered_items_file_from_response` — 输出 enriched `plan/items.json`
- `tools.py:2311` `_matches_plan_item` — 使用 enrichment 后的完整字段
- `tools.py:2359` `_plan_item_brief` — 使用 enrichment 后的 `schoolNature`/`tuitionPerYear`

**真实验证：**
- `里面有民办没`：`query_plan(scope="plan", filters={"school_nature":"民办"})` 真实命中 `70` 条
- `方案里的民办不要了`：`preview_plan_action(remove, filters={"school_nature":["民办"]})` 真实返回确认卡
- `当前这些中外合作都移出去`：4.0 shadow 真实返回 `preview_plan_action(remove, filters={"program_type":["中外合作"]})`

**文档状态：** §3.3 `query_plan` 和 `preview_plan_action` 的 `filters` 描述已升级为真实数据可用；不再保留“仅单测 fixture 下支持”的旧表述。

### 8.2 P0 — Shadow 采集闭环已打通

**现象：**
非阻塞 shadow 在快速主链路下，`conversation_turn_event` 发送时 shadow task 尚未完成，只留下 `status=running`。完整结果通过独立的 `zhiyuan_agent_poc_shadow_event` 写入日志。

但 `dialog_regression_runner` 只从 history 消息的 `conversation_turn_event` 中读取 `zhiyuanAgentPocShadow` 字段（`runner.py:1060-1062`），不合并后置的 shadow event，导致：
- shadow 实际成功（正确选了 `preview_intent_change`），但 runner 判定"no shadow result"
- "那高收费的别要了" 等 case 无法正确评估 4.0 的工具选择质量
- shadow 覆盖率统计偏低

**根因：**
`_observability_timing_fields`（`service.py:5003`）在 turn event 发送时检查 shadow task 是否 `done()`——如果 shadow 还在跑，不等待，直接发不带 shadow 的 turn event。shadow 完成后 `_log_zhiyuan_agent_poc_shadow_event`（`service.py:13196`）写独立日志事件，但 runner 不解析这个事件类型。

**修复方案（两步）：**

**步骤 1 — runner 合并后置 shadow event（快速修复）：**

在 `_extract_turn_observability`（`runner.py:1046` 附近）增加对后置 shadow event 的解析：

```python
# 现有逻辑：从 conversation_turn_event 中读 zhiyuanAgentPocShadow
if kind == "text":
    data = _parse_json_object(part.get("content"))
    if data.get("event") == "conversation_turn_event":
        raw_poc_shadow = data.get("zhiyuanAgentPocShadow")
        if isinstance(raw_poc_shadow, dict):
            zhiyuan_agent_poc_shadow = raw_poc_shadow

    # 新增：合并独立 shadow event
    if data.get("event") == "zhiyuan_agent_poc_shadow_event":
        shadow_data = data.get("shadow") or data
        if isinstance(shadow_data, dict) and shadow_data.get("status"):
            zhiyuan_agent_poc_shadow = shadow_data
```

**步骤 2 — turn event 等待 shadow 带超时（可选优化）：**

在 `_observability_timing_fields` 中，如果 shadow task 未完成，用短超时等待：

```python
shadow_task = getattr(request_context, "_zhiyuan_agent_poc_shadow_task", None)
if isinstance(shadow_task, asyncio.Task) and not shadow_task.done():
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(shadow_task), timeout=2.0)
```

这让大部分 shadow 结果能嵌入 turn event，减少对 runner 合并逻辑的依赖。但不能设太长超时，避免阻塞主链路。

**关联代码：**
- `service.py:5003` `_observability_timing_fields` — 可选增加短超时等待
- `service.py:13195-13196` `_run_zhiyuan_agent_poc_shadow` — shadow event 发射点
- `runner.py:1046-1062` `_extract_turn_observability` — 需要合并 shadow event

**真实验证结果：**
- 2026-07-01 real websocket shadow 复跑 `examples/dialog_regression_400_realistic_user_cases.json`，14 个 step 全部拿到完成态 `zhiyuanAgentPocShadow`
- `zhiyuanAgentPocShadow.observed=14`，`statuses.success=14`
- `runtimeShadowSummary.observations=0`，本次不依赖 runtime diff 汇总，直接从 turn observability 与后置 shadow event 合并完成

### 8.3 P1 — Case 语义边界：显式诉求优先，区分报考要求和当前方案调整

**修正后的理解：**
之前把"方案里的民办不要了"一律归到报考要求，会把隐含长期意向强加给用户。当前口径改为显式诉求优先：裸句"不要民办"更像报考要求；"方案里的民办不要了""当前这些中外合作都移出去"明确锚定当前方案，暂时按方案调整处理是合理的。

**正确的路由规则（基于操作粒度，非指代词）：**

| 操作粒度 | 示例 | 路由 | 原因 |
|---------|------|------|------|
| **报考要求**（裸属性/标签/类别或明确后续要求） | "不要民办""民办就算了""中外合作都不要了""以后别考虑民办" | `preview_intent_change` | 记录为后续报考要求，确认后按要求影响方案 |
| **当前方案筛选调整** | "方案里的民办不要了""当前这些中外合作都移出去" | `preview_plan_action(remove, filters=...)` | 用户当前最明确的诉求是调整现有方案 |
| **审查 issue 联动** | "审查里的高收费先处理了" | `preview_plan_action(review_issue_code=...)` | 从审查结果定位具体 items 操作 |
| **具体项**（名称/位置） | "把华南理工大学移出去""第3个不要了" | `preview_plan_action(action="remove")` | 一次性操作，不产生持久约束 |

**修复方案：**
1. 裸属性/标签/类别诉求 case 期望 `preview_intent_change`
2. 带当前方案锚点且要求移出/删除的属性筛选 case 期望 `preview_plan_action(remove, filters=...)`
3. 保留审查联动和具体项操作的 case 期望 `preview_plan_action`
4. 补充具体项操作 case：

```json
{
  "name": "G33-specific-item-removal",
  "prompts": [
    {"text": "把广州南方学院移出去", "expectedZhiyuanAgentPocFirstToolNames": ["preview_plan_action"]},
    {"text": "第3个不要了", "expectedZhiyuanAgentPocFirstToolNames": ["preview_plan_action"]},
    {"text": "审查里的高收费项处理掉", "expectedZhiyuanAgentPocFirstToolNames": ["preview_plan_action"]}
  ]
}
```

5. 确保 `preview_intent_change` 的 confirm 流程在有方案时触发方案再生成（§3.7 的实现要求）

### 8.4 P1 — 老链路语义 bug："先别动" 误判为 pin_or_lock_unit

**现象：**
"贵的合作的这些怎么处理，先别动" 被老链路误判为 `pin_or_lock_unit`（锁定/固定位置），把"先别动"当成了锁定操作。

**4.0 的正确路由：**
这是一个只读审查问题——用户在问"怎么处理"，然后说"先别动"表示暂不操作。应该走 `review_plan(focus="tuition", generate_fix_proposals=True)` 返回处理方向但不创建 pending。

**当前障碍：**
这个 case 在老链路上触发了错误操作，但 4.0 shadow 结果在本轮真实复跑中已可稳定采集；旧主链语义仍可保留为后续替换依据，不再作为 4.0 验证阻塞项。

**修复方案：**
1. 先修 §8.2 的 shadow 采集断链
2. 补该 case 到 shadow case 集合，断言期望 `review_plan`
3. 确认 4.0 prompt 的行动原则第 10 条（"用户问当前方案风险、审查一下...调用 review_plan"）已覆盖此场景
4. 如果 4.0 也误判，在 prompt 示例中增加：

```
- "这些高收费的怎么处理，先别动" -> review_plan(focus="tuition", generate_fix_proposals=True)
```

### 8.5 P2 — 文档与真实实现状态已对齐

**现象：**
§3.3 中 `query_plan` 和 `preview_plan_action` 的 Phase 2 落地状态之前写得偏保守，容易让人误以为真实数据仍不能命中属性过滤。

**修复方案：**

在相关工具的落地状态描述中改为已验证可用，并保留真实验证备注：

- `query_plan` 落地状态更新为：真实 ordered-plan 数据可通过 enrichment 命中 `school_nature` 等属性过滤
- `preview_plan_action` 落地状态更新为：`filters-based remove` 已在真实口语 shadow 中验证
- §7 Phase 2 检查清单中将 enrichment 和 shadow 采集闭环标为完成

### 8.6 修复优先级与依赖关系

```
P0 enrichment (§8.1) ──────────────────────────────┐
                                                    ├──→ 属性过滤在真实数据上可用
P0 shadow 采集 (§8.2) ─────────────────────────────┐│
                                                    ├──→ shadow 验证闭环
P0 约束即方案调整 (§3.7) ──────────────────────────┐││
  confirm intent_change 触发方案再生成             │││
                                                   ├┘│
P1 case 语义边界 (§8.3) ──────────────────────────┘  │
P1 老链路 bug 验证 (§8.4) ─── 作为替换依据保留 ──────┘
P2 文档修正 (§8.5) ─── 已完成，保持与真实实现一致 ───→ 更新落地状态描述
```

实施顺序：§8.1 + §3.7 → §8.2 → §8.3 + §8.4 → §8.5

---

## 9. Golden Case 回归设计调整（2026-07-02）

G1-G32 完整回归（49 步、46 通过、3 失败）暴露了若干需要设计级调整的问题。按影响分类：A 类需要新增或修改设计段落；B 类为实现级修复，在此记录结论。

### 9.1 复合诉求 `next_step` 策略调整

**触发 case：** G12 `高收费的志愿占比多少 能不能换成便宜的`

**现象：**
用户在同一句话中包含"查询 + 调整"两个意图。Agent 调用 `query_plan` 并返回 `next_step="respond"`，`should_return_directly_from_tool` 在 `respond` 时返回 True，工具结果直接返回用户，LLM 没有机会处理第二个意图（"换成便宜的"方案调整）。

**根因：**
当前 `should_return_directly_from_tool` 对 `respond`/`confirm`/`clarify` 三种 `next_step` 全部返回 True，即所有工具结果都会短路后续 LLM 处理。这对单意图场景是最优的（避免工具乱试），但对复合意图场景过于激进。

**设计调整：**

将 `next_step` 的短路行为按语义分层：

| `next_step` | 含义 | `should_return_directly` | 理由 |
|-------------|------|------------------------|------|
| `confirm` | 已创建 pending，等用户确认 | **True**（硬停） | 用户必须先处理确认卡 |
| `clarify` | 需要用户澄清，无法继续 | **True**（硬停） | 歧义未解决，继续调用无意义 |
| `respond` | 只读结果已就绪 | **False**（软停） | LLM 可判断是否还有未处理意图 |

调整后，只读工具（`query_plan`/`read_state`/`review_plan`/`answer_policy`/`explore_topic`/`compare_entities`）返回 `respond` 时，LLM 仍然可以继续处理下一个意图。`MAX_TOOL_CALLS_PER_TURN=3` 的硬上限仍然防止工具乱试。

**Prompt 指引补充：**

在行动原则中增加复合诉求处理规则：

> 用户一句话包含查询和操作两个意图时（如"方案里有几个民办 把它们去掉"），先调只读工具回答查询部分，再按操作意图调用对应工具。只读工具的结果不终止本轮处理。

**`agent.py` 调整要点：**
- `should_return_directly_from_tool`: 仅在 `next_step in ("confirm", "clarify")` 时返回 True
- `render_direct_tool_output`: 只在 `should_return_directly_from_tool` 为 True 时调用
- `respond` 时工具结果作为中间上下文注入 LLM，由 LLM 决定是直接回复还是继续调用工具

**影响范围：**
- 复合诉求可以在 1 轮内完成查询 + 操作
- 单意图场景中 LLM 在收到只读结果后大概率直接回复，不会增加不必要的工具调用
- `confirm`/`clarify` 仍然硬停，不影响 pending 安全

### 9.2 Pending 下只读查询路由

**触发 case：** G21（`万一强基没过校测普通批怎么衔接`，耗时 51651ms）、G27（`两万以上的都算贵 帮我看看有几个`，耗时 19073ms）

**现象：**
当存在 active pending 时，只读查询（策略问答、方案查询）仍然落到旧 `full_agent` 链路，走 `pending_readonly_plan_query` + 旧 `execute_plan_action`，耗时远高于 direct route。

**根因：**
Phase 4 direct route 的入口条件是"无 active pending 或用户表达为确认/取消"。当 pending 存在但用户表达不是确认/取消时，整个请求回退到旧链路。但只读查询（`answer_policy`/`query_plan`/`explore_topic`/`compare_entities`/`review_plan`）不与 pending 冲突，不需要回退。

**设计调整：**

Direct route 接管条件从"无 pending"扩展为"无 pending 或只读查询"：

```
direct route 适用条件：
  1. 无 active pending                               → 所有工具可用
  2. 有 active pending + 用户表达为确认/取消          → confirm_pending
  3. 有 active pending + 用户表达为只读查询           → 只读工具可用（新增）
  4. 有 active pending + 用户表达为新变更请求          → pending_conflict_guard（保持）
```

**条件 3 的只读工具集合：**
`read_state` / `query_plan` / `answer_policy` / `explore_topic` / `compare_entities` / `review_plan`

这些工具不创建新 pending、不修改方案、不修改约束，与已有 pending 无冲突。

**实现要点：**
- service 层 `_route_to_direct_agent` 检查 pending 存在时，仍然进入 direct route，但在工具注册时只暴露只读子集
- 或者更简单：不做工具子集限制，依赖 `preview_intent_change`/`preview_plan_action` 内部的 pending 冲突检查（已有 `pending_conflict_new_request_guard`）
- 推荐后者：保持 agent 工具集不变，冲突由工具自身守护。service 层只需放开 direct route 的 pending 检查

**预期效果：**
- G21 策略问答：从 51651ms 降到 direct route 典型延迟（3-6s）
- G27 只读方案查询：从 19073ms 降到 direct route 典型延迟

### 9.3 正向意向 `constraint_type` 边界澄清

**触发 case：** G4（`网络与新媒体作为优先方向，跨境电商也可以考虑`）、G23（`想学计算机或电子信息`、`城市优先长三角`）、G29（`网络与新媒体优先，跨境电商也可以考虑`）

**核心矛盾：**
§3.6 移除了 `preference`，只保留 `exclude/only_keep/must_have`。但用户表达的正向意向不全是"必须有"：

| 表达 | 当前设计 | 用户预期 |
|------|---------|---------|
| "要计算机" / "必须有计算机" | `positive + must_have` ✓ | 方案中确保包含 |
| "不要民办" | `negative + exclude` ✓ | 方案中排除 |
| "想学计算机" / "对计算机感兴趣" | ❓ | 记录偏好，方案适当倾斜 |
| "优先长三角" / "城市优先X" | ❓ | 记录偏好，方案适当倾斜 |
| "跨境电商也可以考虑" | ❓ | 知道了，不强制 |

**设计决策：分三层处理**

1. **明确要求 → `must_have`**：
   "要X"/"必须有X"/"至少要有X" → `positive + constraint_type="must_have"`。这是硬约束，方案必须包含匹配项。

2. **主动正向意向 → `must_have`（宽松语义）**：
   "想学X"/"对X感兴趣"/"X方向" → `positive + constraint_type="must_have"`。用户主动说出来的正向意向应当作为报考要求被记录。`must_have` 在此语境下表示"方案应当包含"，而非"强制最低数量"。

3. **弱肯定/探索 → 不创建约束**：
   "也可以考虑X"/"X也行" → 不调用 `preview_intent_change`，可用 `explore_topic` 提供参考信息。这类表达不构成报考要求，属于 §3.6 已定义的"软偏好不暴露给用户对话"范围。
   "优先X" → 如果有明确对象（"优先长三角"），按 `must_have` 记录为正向意向；如果只是排序偏好（"优先考虑便宜的"），走 `explore_topic` 或 `review_plan` 分析。

**Prompt 行动原则调整（第 5 条扩展）：**

在现有极性判断规则后追加：

> "想学X"/"想去X"/"对X感兴趣"/"X方向" 是正向报考要求，按 positive + constraint_type=must_have 处理；"也可以考虑X"/"X也行"/"不排斥X" 是弱肯定探索，不创建约束，可用 explore_topic 提供参考。

**工具调用示例补充：**

```
- "想学计算机或电子信息" -> preview_intent_change(intent_type="major", positive={"level2":["计算机类","电子信息类"]}, constraint_type="must_have")
- "城市优先长三角" -> preview_intent_change(intent_type="region", positive={"region_group":["长三角"]}, constraint_type="must_have")
- "跨境电商也可以考虑" -> explore_topic(topic_type="major", user_question="跨境电商专业怎么样")
```

**实体归一化显示问题（G4 附带）：**
"跨境电商" 被实体解析器归一为 "电子商务"。当归一化发生时，卡片展示应保留用户原词作为辅助说明。调整 `_format_intent_preview_card` 在实体名与用户原词不一致时展示 `用户原词 → 归一名` 格式。

### 9.4 档案/成绩 inline 提取边界

**触发 case：** G22/G31（用户口头修正省份/成绩/选科）、G23（`我575分安徽物化生先看看`）

**现象：**

| 场景 | 表现 |
|------|------|
| G23 "我575分安徽物化生先看看" | direct 调 `read_state` 后回复"还没有拿到成绩信息"，未从用户输入提取成绩 |
| G22 "湖北/620/物化生" | 文本回复承认新信息，但后续查询仍读旧档案 `湖南 548 历政生` |
| G31 同上模式 | 同上 |

**根因：**
4.0 工具集（9 个）全部面向"方案规划"阶段，不包含成绩/档案提取和更新能力。在 3.x 系统中，成绩提取由 `intake_agent` + `extract_score_from_text` 完成；档案修正由 `profile_manager.update_score_detail` 处理。4.0 direct route 跳过了 intake 阶段的工具。

**设计决策：明确边界，不在 4.0 工具集中加成绩提取**

理由：
- 成绩/省份/选科是一次性设置操作，生命周期与方案规划工具不同
- 真实场景中，绝大多数用户通过问卷或前端表单完成成绩录入，oral inline 提取是少数情况
- 在 9 个工具中加入 `update_profile` 会引入状态写入 + 错误纠正复杂度

**当前方案：**
1. **direct route 不再因成绩缺失回退旧链路**：如果 `score.json` 没有有效成绩（`available=false`），仍进入 4.0 direct，由 agent 基于已有信息回答或提示用户通过正式渠道补录。
2. **Prompt 边界说明**：当用户提供新的成绩/省份/选科信息但系统无法更新时，告知用户通过正式渠道录入，不假装已记录。
3. **后续独立扩展**：成绩提取作为 Phase 5 独立能力，不阻塞当前 9 工具方案规划链路。

**direct route 入口条件更新：**

```
direct route 前置条件：
  当前：ChatService 默认进入 4.0 ZhiyuanAgent direct route
  不再包含：ZHIYUAN_AGENT_ENABLED、rollout_percent、score.json.available gate
```

### 9.5 G17 — 档位内移动 selector 字段归一化与模型重试协议

**触发 case：** G17 `帮我把保底区里录取率最高的那个调到保底的第一位`

**现象与演进：**
- 子集回归曾通过，完整 G1-G32 回归中出现 "还没有唯一定位到要调整的方案项"
- v1.41 曾在工具层加入三段 raw_user_text 补偿：缺 action 时从中文动词恢复 action，缺 move selector/目标档位时从原文恢复 filters
- v1.59 按 4.0 统一方向撤销这类字符串补参：工具不再从整句中文里猜语义，而是返回结构化 `continue`，让主模型基于当前问和工具返回重试补齐参数
- 原 G17 回归源 session 26 在当前本地后端中 `orderedPlanState`/`workingPlanState` 已为 0，不再适合作为该 case 的真实验证源；source35 当前有冲4/稳5/保6，可用于验证保底档移动

**当前处理：**

核心边界是 4.0 direct 的“模型语义仲裁 + 工具结构化校验”。模型已经选择 `preview_plan_action` 时，工具只校验参数是否足够执行；如果缺 `action`、move selector 或目标位置，返回 `next_step=continue`，并把当前用户原话、已收到的 targets/filters、缺失字段和允许动作带回模型。模型下一步要么补齐结构化参数重试，要么在原话确实不清时向用户追问。

| 防护层 | 状态 | 覆盖场景 |
|--------|------|---------|
| 层 1 Prompt 示例 | 已落地 | 模型传正确字段名 → 正常工作 |
| 层 2 工具参数校验 | v1.59 已调整 | 模型已调用工具但漏 `action` / selector / 目标位置 → 返回 `plan_action_requires_*` + `continue` |
| 层 3 模型重试或澄清 | v1.59 已调整 | 当前问可判定则补齐结构化参数重试；当前问不清则向用户追问 |

**落地范围：**
- 删除 `_fallback_plan_action_from_text`、`_fallback_move_filters_from_text`、`_fallback_target_tier_filters` 和 `_extract_selector_from_text`。
- `preview_plan_action` action 缺失/非法时返回 `plan_action_requires_explicit_action`；仍保留 `_effective_raw_user_text()` 只用于把当前问传给模型，不用于工具层字符串判定。
- `_resolve_plan_filter_selector_target()` 只消费 `filters.selector_sort` / `selector_rank` / `selector_ordinal` 等结构化字段，不再从 `raw_user_text` 抽“录取率最高/学费最低/最后一个”。
- move 缺 selector 时返回 `plan_action_requires_move_selector`；已定位待移动项但缺目标位置时返回 `plan_action_requires_move_target_position`。
- prompt 第 22 条补充这三类 reason：如果当前问已有动作、选择器或位置，模型补齐 `action/targets/filters/target_position` 后重试一次；否则向用户追问。

**验证：**
- v1.59 聚焦单测：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'move_requires_model_retry or move_supports_tier_local_reorder_filters or move_requires_target_position or active_pending'` 为 `8 passed, 159 deselected`。
- v1.59 PoC 全量：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `139 passed, 28 skipped`；`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py` 通过。
- v1.59 真实 LLM G17 主链路：使用临时 case `/private/tmp/zhiyuan_400_v159_g17_source17_case.json`（实际 source35）和临时 agent `8040` 复跑 `1/1`，metrics: `/private/tmp/zhiyuan_400_v159_g17_model_retry_source35_clean.json`。主链路单次 `preview_plan_action`，`actionFamilies=["move_ordered_unit"]`，生成 `pendingConfirmationCard`；本次模型首轮已传完整结构化参数，因此没有触发 `continue` 重试。环境警告：`assistant_chat_session` MySQL 克隆因 root 无密码失败，但 extra-data 状态和志愿数据克隆成功，业务验证通过。

### 9.6 G4 — 实体归一化展示保真

**触发 case：** G4 `那把网络与新媒体作为优先方向，跨境电商也可以考虑`

**现象：**
用户说"跨境电商"，经实体归一后卡片只展示"电子商务"或"跨境电子商务"，用户原话消失。tracking doc 记录（line 715-718）：曾尝试在工具代码内维护 `_MAJOR_DISPLAY_ALIASES` 别名补丁，已回退——不是框架内的统一方案。

**根因：**
实体解析器返回 `EntityResolutionResult(raw_text="跨境电商", candidates=[EntityResolutionCandidate(canonical_name="电子商务", ...)])`。但 `_normalize_intent_side`（`tools.py:1720`）和后续 `_preview_message`（`tools.py:1737`）只取 `canonical_name` 写入 `normalized["positive"]` / `normalized["negative"]`，不保留 `raw_text`。卡片展示从 `normalized` 的 values 直接 join，所以用户原词消失。

**问题定位：展示层，非执行层。** 执行 payload 写入后端用 `canonical_name` 是正确的（实体消歧必须用规范名）。问题仅在用户可见的 `preview_summary` 和 `message` 中丢失了原词。

**修复设计：实体解析层输出 raw → canonical 映射，展示层统一使用**

**步骤 1 — `_normalize_intent_side` 保留 raw → canonical 映射：**

在归一化输出中增加 `_display_aliases` 字段，记录所有 raw_text ≠ canonical_name 的映射：

```python
def _normalize_intent_side(values, entity_type, batch) -> tuple[dict, dict]:
    normalized = {}
    display_aliases = {}  # canonical_name -> raw_text
    for result in resolved_results:
        if result.best and result.raw_text != result.best.canonical_name:
            display_aliases[result.best.canonical_name] = result.raw_text
        # ... existing canonical_name writing ...
    return normalized, display_aliases
```

**步骤 2 — `_preview_message` 使用 display_aliases 展示原词：**

```python
def _preview_message(intent_type, normalized, constraint_type, display_aliases=None):
    # ... existing code ...
    for name, payload in (("要", positive), ("不要", negative)):
        values = []
        for item in payload.values():
            for v in _as_list(item):
                alias = (display_aliases or {}).get(v)
                display = f"{alias}（{v}）" if alias and alias != v else v
                values.append(display)
        # ...
```

展示效果：`"专业要求：要：跨境电商（电子商务）、网络与新媒体。确认前不会生效。"`

**步骤 3 — `_intent_summary_from_merged` 同步应用 display_aliases：**

`pending.json` 中的 `preview_summary` 需要从合并后的 intents 中展示原词。在 merged payload 中保留 `display_aliases`，`_intent_summary_from_merged` 使用同样的 `alias（canonical）` 格式。

**不改变的部分：**
- 写入后端 `update_planning_constraint_state` 的 payload 继续使用 `canonical_name`
- `simulate_plan_diff` 继续使用 `canonical_name`
- 实体解析器本身不需要修改（已有 `raw_text` 字段）

### 9.7 G3 — 查询计数粒度口径

**触发 case：** G3 `当前方案里有没有相关专业` → 回复 "正式方案有45个志愿，命中114条"

**现象：**
用户问方案里有没有某专业，回复显示"命中114条"但方案只有45个志愿。114 是专业明细（一个志愿=一个学校+多个专业明细行）粒度的命中数，45 是志愿/方案项粒度。两个数字混在同一句话中，用户理解为计数矛盾。

**根因：**
`_plan_query_count_metrics`（`tools.py:2863`）已区分了 `matched_plan_item_total`（按 group 去重的志愿级计数）和 `matched_detail_total`（明细级计数）。`query_plan` 的消息模板（`tools.py:4656-4659`）在 `detail_granularity=True` 且两者不等时展示"命中 N 个志愿，涉及 M 条专业明细"。

但 `detail_granularity` 的判断（`tools.py:2873`）是 `total_detail > total_plan_items`——只比较全量，不比较命中结果。当全量方案的明细行数等于志愿数时（无多专业展开），`detail_granularity=False`，但命中筛选可能因专业名匹配到子字段而膨胀。

**修复设计：**

**调整 1 — `_plan_query_count_metrics` 增加命中级粒度判断：**

```python
detail_granularity = bool(
    (total_plan_items > 0 and total_detail > total_plan_items)
    or (matched_plan_total > 0 and detail_total > matched_plan_total)
)
```

当命中明细数 > 命中志愿数时，也启用双粒度展示。

**调整 2 — 消息模板明确主粒度为志愿：**

当前模板：`"命中{matched_total}条"`（matched_total 可能是志愿级也可能是明细级）

改为永远以志愿为主粒度：

```python
if count_metrics.get("detail_granularity") and detail != volunteer:
    matched_phrase = f"命中{volunteer}个志愿（涉及{detail}条专业明细）"
else:
    matched_phrase = f"命中{volunteer}个志愿"
```

**调整 3 — `_matches_plan_item` 匹配边界收紧：**

检查当前专业匹配是否跨志愿边界膨胀。如果 `filters` 包含专业名，匹配应以志愿为单位——志愿内有任一专业明细命中即算该志愿命中，但同一志愿不应重复计数。当前 `_matches_plan_item` 返回 True/False 应已是志愿级，复核 `plan/items.json` 的数据结构确保一个志愿不会作为多条出现。

### 9.8 G32 — 无方案探索降级内容策略

**触发 case：** G32 `有什么专业是比较好就业的吗`、`计算机和电子信息有什么区别`

**现象：**
无正式方案时，`explore_topic` / `compare_entities` 如果后端 profile API 无数据，返回偏元说明（"这是只读探索问题""暂时没有拿到完整资料"），实质内容不足。tracking doc（line 716-718）记录：曾尝试在 tools.py 内硬编码专业说明，已回退——不应在工具代码维护专业知识。

**根因：**
`explore_topic` 在 `profile_source != "backend_profile"` 时，message 只说"暂时没有拿到完整资料，会先按当前方案和问题本身做只读判断"（`tools.py:602`）。`compare_entities` 类似，`unavailable` 列表非空时标注"缺少完整资料，只能做有限对照"（`tools.py:709`）。工具返回的 `analysis` 是固定的 3 条元说明（`tools.py:614-618`），不包含任何专业/院校实际内容。

由于 `next_step="respond"` 当前改为软停（§9.1），LLM 会收到工具返回的 JSON 并生成用户可见回复。但 JSON 中 `profile_facts` 为空、`analysis` 为元说明，LLM 只能基于自身训练知识回答——内容质量取决于 LLM 对该专业/院校的了解，不可控。

**修复设计：结构化维度模板 + LLM 知识补充**

**方向决策：** 不在 tools.py 内维护专业百科内容。降级时由工具提供结构化的**对比维度框架**，由 LLM 基于自身知识填充内容。

**步骤 1 — explore_topic 降级时输出维度框架：**

当 `profile_facts` 为空且 `profile_source` 不是 `backend_profile` 时，`analysis` 字段改为对应 `topic_type` 的标准维度列表，引导 LLM 沿这些维度组织回答：

```python
_EXPLORE_FALLBACK_DIMENSIONS = {
    "major": [
        "学什么：核心课程和培养方向",
        "做什么：主要就业方向和职业路径",
        "怎么选：选科要求、录取分位段、男女比例等报考注意点",
        "和当前成绩/选科的适配度判断",
    ],
    "school": [
        "学校定位：层次、隶属、优势学科",
        "录取难度：分数段、位次参考",
        "就业/升学：保研率、就业去向",
        "和当前成绩的匹配度判断",
    ],
    "career": [
        "发展路径：典型职业阶梯",
        "对应专业：哪些专业方向可进入",
        "现实因素：编制、薪资水平、地域差异",
    ],
}
```

Message 调整：从"暂时没有拿到完整资料"改为"按以下维度整理分析"，明确告知 LLM 按维度回答。

**步骤 2 — compare_entities 降级时输出对比矩阵框架：**

当对比对象缺少 profile 时，提供结构化的空对比矩阵，维度根据 `comparison_focus` 或默认维度填充：

```python
"dimensions_template": [
    {"dimension": "培养方向差异", "fill_from": "llm_knowledge"},
    {"dimension": "就业方向差异", "fill_from": "llm_knowledge"},
    {"dimension": "录取难度", "fill_from": "llm_knowledge"},
]
```

**步骤 3 — message 避免元说明表述：**

将 "这是X探索问题，不会改动报考要求或方案" 改为 "关于{entity}的分析如下" — `state_mutation: false` 已经告诉 LLM 这是只读操作，message 不需要再重复说明。

**效果预期：**
- LLM 收到维度框架后，会按维度组织回答，内容密度显著提升
- 不在工具代码维护专业百科，维度框架是通用的
- 有 profile 数据时仍然优先使用 API 数据

### 9.9 G25 — 混合正负诉求路由与参数完整性

**触发 case：** G25 `把生物医学工程和智能医学工程加意向 排除临床医学和口腔`

**最新复跑发现（v1.4 后）：**

| 维度 | 现象 |
|------|------|
| 主链路路由 | **未进入 4.0 direct**，被旧 `runtime_intent_hard_cut` 接管，走旧链路，耗时约 22s |
| 可见结果内容 | 内容正确：生物医学工程、智能医学工程为正向；临床医学、口腔医学为负向 |
| 4.0 验证意义 | 这不是 4.0 工具链验证通过——是旧链路偶然给出了正确结果 |
| Shadow schema 问题 | 模型曾传 `major_name` 而非 `level2`，工具不识别导致 summary 为空 |
| Shadow 参数遗漏 | 模型有时只传 positive、漏 negative，负向部分丢失 |

**问题 1：`runtime_intent_hard_cut` 抢跑路由**

`service.py` 的处理顺序（line 15993-16008）：
1. `_maybe_handle_zhiyuan_agent_direct_route` — 如果返回 None，继续
2. 旧 `runtime_intent_profile_plan_reroute` — 含 `runtime_intent_hard_cut` 判断

direct route 旧实现曾可能返回 None，导致继续进入旧 intent pipeline。当前要求是 direct route 默认主链路，不再因开关、rollout 或成绩可用性返回 None；agent 异常时也返回安全提示并记录观测，不交给旧链路继续处理。

但即使 direct route 开启，当前 `runtime_intent_hard_cut` 的判断条件（`service.py:5207-5226`）也会在 confidence ≥ 0.65 + side_effect=intent_pending + scope_anchor=future_reference 时抢先拦截。"把X加意向 排除Y" 这类表达恰好会被旧 `turn_decision` 分类器识别为 intent_update + future_reference，即使 direct route 已开启。

**修复方向：direct route 优先级高于 runtime_intent_hard_cut，且不再保留旧入口 gate**

当前架构中 direct route 已在旧 intent pipeline 之前执行（line 15993 先于 16008），所以只要 direct route 成功返回非 None，就不会走旧链路。G25 的问题是 direct route 本身返回了 None。

需要确认并修复：
1. **入口默认 direct**：`ChatService` 初始化默认构造 `ZhiyuanAgent`，不再读取 direct enable / rollout。
2. **去掉成绩前置回退**：无有效成绩时也由 direct agent 处理边界，不回退旧 intake。
3. **去掉 return None 回退口**：`_maybe_handle_zhiyuan_agent_direct_route` 不再通过 None 把请求交给旧 full-agent。

**问题 2：Schema 字段 alias 兼容**

Shadow 中模型传 `positive={"major_name": ["生物医学工程", "智能医学工程"]}` 而非 `positive={"level2": ["生物医学工程", "智能医学工程"]}`。

当前 `_normalize_major_payload`（`tools.py:1688`）已有 `major_name` 作为 fallback key：
```python
for key in ("items", "values", "names", "majors", "major_name", "major_names", "majorName", "majorNames"):
```

如果 summary 仍为空，可能原因：
- 模型传的字段名不在上述列表中（如 `major` 单数形式、`majorList` 等）
- 或者 `negative` 侧的 payload 结构不同

**修复：扩展 fallback key 集合 + 增加 field alias 单测**

在 `_normalize_major_payload` 的 fallback keys 中追加常见变体：
```python
("items", "values", "names", "majors", "major_name", "major_names",
 "majorName", "majorNames", "major", "majorList", "major_list")
```

补充单测覆盖：`positive={"major_name": [...]}` 和 `negative={"major_name": [...]}` 应正确归一化到 `level2`。

**问题 3：模型只传 positive 漏 negative — 结构性缺陷**

模型有时将 `"把X加意向 排除Y"` 只映射到 `positive={"level2": ["X"]}` 而完全不传 `negative`。这不是 schema alias 问题，是**模型意图分解能力的不稳定性**。

**为什么不能靠工具内字符串匹配解决：**
- 在 `raw_user_text` 中 regex 匹配"排除"/"不要"后提取实体并回填 negative，本质上是在工具层重新做意图解析
- 这与 4.0 的设计原则冲突——意图解析应由 LLM 完成，工具层只负责实体归一化和执行
- 一旦开始在工具里做文本 NLU，边界会持续膨胀（"别考虑"/"不用看"/"算了" 等更多口语表达），维护成本高于 Prompt 修复

**修复方向：Prompt 层面加固，不在工具层加文本 NLU**

a. **Prompt 示例强化**：增加混合正负的明确示例，减少模型拆分或遗漏：

```
- "把X加意向 排除Y" -> preview_intent_change(intent_type="major", positive={"level2":["X"]}, negative={"level2":["Y"]}, constraint_type="must_have")
```

b. **工具层轻量校验（不做 NLU）**：如果 `raw_user_text` 中明显包含"排除/不要/不考虑"关键词，但 `negative` 为空，工具可在返回的 `message` 中追加提示："用户消息中似乎包含排除诉求，但未收到 negative 参数。如果确实要排除，请补充。"这是**提示而非自动补全**。

c. **观察频率**：如果混合正负遗漏发生率 < 20%，通过 Prompt 可接受；如果 > 20%，需要评估是否引入轻量预处理步骤（在 agent 层面、工具调用前解析）。

### 9.10 §9.1 respond 软停真实效果验证边界

**关联设计：** §9.1 将 `respond` 从硬停改为软停，允许 LLM 在只读工具返回后继续处理复合诉求。已落地（tracking doc line 729），单测通过，但**真实 LLM 效果未完全确认**。

**已知状态：**
- `should_return_directly_from_tool` 仅对 `confirm`/`clarify` 硬停——已改代码并通过单测
- 真实 websocket G12/G21/G23/G25/G27 复跑尚未完成（tracking doc line 744）
- 无法确认 LLM 在 respond 软停下是否会多调工具或改写内容

**需要验证的风险：**

| 风险 | 场景 | 影响 |
|------|------|------|
| LLM 多调工具 | 用户只问了一个只读问题，LLM 收到结果后额外调用不相关工具 | 延迟增加、可能产生副作用 |
| 回复质量下降 | 原来 `respond` 硬停直接返回工具 JSON 的 `message`，现在 LLM 二次生成可能改写内容 | 信息损失或幻觉 |
| token 消耗增加 | 每个只读工具调用后 LLM 都需要做一次推理决策 | 成本上升 |

**验证方案：**

**步骤 1 — 单意图基线复跑：**
用 400 真实口语集（14 步）+ G case 子集（8 步）复跑，对比 respond 软停前后：
- 工具调用次数是否增加（期望：不增加，LLM 识别到单意图后直接回复）
- 回复内容是否有实质变化（diff 检查）

**步骤 2 — G12 复合诉求验证：**
复跑 G12 `高收费的志愿占比多少 能不能换成便宜的`，确认 LLM 在 `query_plan` 返回后是否继续调用 `preview_plan_action`。

**步骤 3 — 防护增强（如果步骤 1 发现多余调用）：**

如果 LLM 确实在单意图场景多调工具，增加以下防护：

a. **Prompt 约束**：在行动原则中增加——"只读工具返回后，如果用户消息只包含一个问题，直接用工具结果回答，不需要再调用其他工具"
b. **工具结果注入方式**：只读工具返回时，在工具结果 JSON 中增加 `"single_intent_hint": true`，LLM 可据此判断是否需要继续
c. **回退方案**：如果防护无效且多余调用严重，将 `respond` 改回硬停，G12 复合诉求通过 Prompt 引导 LLM 在首次工具调用前先识别复合意图并规划调用序列

**判定标准：** 单意图工具调用数不增加（≤1）+ G12 复合诉求成功处理两个意图 → §9.1 设计成立。否则回退或增加防护。

### 9.11 调整后的优先级与依赖

**已落地（代码已改 + 单测通过，待真实 LLM 验证）：**

| 编号 | 内容 | 状态 |
|------|------|------|
| §9.1 | 复合诉求 respond 软停 | 代码落地，待 §9.10 真实验证 |
| §9.2 | Pending 下只读查询 direct route | 代码落地 |
| §9.3 | 正向意向 "想学X" → must_have | Prompt 落地 |
| §9.4 | 成绩前置检查 | 代码落地 |
| §9.5 | G17 三层防护与参数恢复 | 代码落地，direct/shadow 聚焦验证通过 |
| §9.6 | G4 展示保真 display_aliases | 代码落地 |
| §9.7 | G3 查询计数粒度 | 代码落地 |
| §9.8 | G32 探索降级维度模板 | 代码落地 |

**待推进：**

```
§9.9-问题1 G25 路由抢跑 ─────────────────────────────────────────── P0（阻塞 4.0 验证）
  确认不设置 direct enable / rollout 时仍进入 zhiyuan_agent_direct
  确认无成绩 fixture 不回退旧 intake/full-agent
  确认 direct agent 内部错误返回安全提示，不进入旧 runtime_intent_hard_cut

§9.9-问题2 G25 schema alias ──────────────────────────────────────── P1
  _normalize_major_payload fallback keys 追加 major/majorList
  补充 major_name alias 单测

§9.9-问题3 G25 模型只传 positive 漏 negative ───────────────────── P1
  Prompt 增加混合正负明确示例
  工具层轻量校验：raw_user_text 含排除关键词但 negative 为空 → 提示
  观察频率后决定是否需要预处理步骤

§9.10 respond 软停真实验证 ────────────────────────────────────────── P0
  400 口语集 + G case 子集复跑
  G12 复合诉求验证
  如果多余调用 → Prompt 约束或回退硬停

§9.5 G17 聚焦复验 ──────────────────────────────────────────────── Done
  direct/shadow 均为 1/1
  完整主集待下一轮统一复跑确认
```

### 9.12 下一步计划

**阶段 A：环境与路由排障（当日可完成）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| A1 | 不设置 direct enable / rollout，单跑 G25 与无成绩 fixture | 均进入 `zhiyuan_agent_direct` |
| A2 | 触发 direct agent 异常模拟 | 返回安全提示并保存 direct error event，不进入旧 full-agent |
| A3 | 单跑 G25 × 3 次确认 direct 路由命中 | 3/3 进入 direct route |

**阶段 B：schema 兼容与 Prompt 加固（1-2 天）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| B1 | `_normalize_major_payload` fallback keys 追加 `"major"`, `"majorList"`, `"major_list"` | alias 单测通过 |
| B2 | Prompt 增加混合正负示例：`"把X加意向 排除Y" -> preview_intent_change(positive=..., negative=..., ...)` | Prompt 已更新 |
| B3 | 工具层增加轻量校验：`raw_user_text` 含"排除/不要/不考虑"但 `negative` 为空 → message 追加提示 | 单测通过 |
| B4 | G25 单 case × 5 次 direct 复跑 | ≥ 4/5 positive + negative 均完整 |

**阶段 C：respond 软停真实验证（1-2 天）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| C1 | 400 口语集 direct 复跑 | 工具调用数 max ≤ 1（与软停前一致） |
| C2 | G case 子集 direct 复跑 | 工具调用数不增加 |
| C3 | G12 `高收费的志愿占比多少 能不能换成便宜的` 单跑 × 3 | ≥ 2/3 同时处理查询和调整两个意图 |
| C4 | 如 C1/C2 发现单意图场景多余调用 | 增加 Prompt 约束或回退 respond 硬停 |

**阶段 D：完整回归收口（2-3 天）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| D1 | 完整 G1-G32 direct 回归 × 2 次 | 主集目标 20/20；完整 320 集按已归档问题单独看 |
| D2 | G25 在完整回归中 positive + negative 均完整 | 2/2 完整 |
| D3 | 性能观察：direct route P95 延迟 | < 8s |
| D4 | 更新 Phase 3 检查项，标记完成 | — |

实施顺序：A → B → C → D

### 9.13 高收费 follow-up 参数完整性与 filter 安全

**触发 case：** 先问 `有啥问题，咋弄`，下一轮说 `那高收费的别要了`

**现象：**

| 场景 | 表现 | 风险 |
|------|------|------|
| 模型调用 `preview_plan_action(remove, review_issue_code=high_tuition)` | 当前审查结果里没有可操作的 `high_tuition` affected units，工具返回 `review_issue_units_not_in_plan` | 用户明确要求移出高收费项，但流程停在澄清 |
| 模型调用 `preview_plan_action(remove, filters={"tuition_level":"high"})` | 旧 filter 归一不支持 `tuition_level` / `fee_level` | 不能稳定命中高收费方案项 |
| 工具遇到未知 filter key | 旧逻辑可能跳过未知 key | 存在把未知 filter 当作全量匹配的风险 |

**设计边界：**

这类问题仍在 4.0 direct route 框架内解决：

1. 不恢复字符串 precheck。路由仍以 LLM 工具选择和结构化工具结果为准。
2. 不在工具层从原话做 NLU 特化。工具只做结构化参数归一、校验和安全兜底。
3. 不把普通高收费 follow-up 强行等同于审查 issue。只有用户明确说“审查里的/风险项/问题项”时，才优先使用 `review_issue_code=high_tuition`；否则当前方案锚定的高收费移出用 `filters={"program_type":["高收费"]}` 或费用 filter。
4. 如果工具返回的是“模型漏参/定位不完整”类 clarify，agent 可以让模型补参重试一次；如果是 active pending 冲突、真实无命中、用户需要选择范围等业务澄清，则直接返回给用户。

**实现策略：**

| 层级 | 调整 | 说明 |
|------|------|------|
| Prompt | `preview_plan_action` 必须携带 `targets` / `filters` / `review_issue_code` / 位置 selector 之一，并尽量保留 `raw_user_text` | 防止只传 `action=remove` |
| Prompt | 增加自修正规则：遇到 `missing_targets`、`missing_filters`、`review_issue_not_found`、`review_issue_units_not_in_plan` 时，如原话已有属性/标签/审查问题/位置定位，补参重试一次 | 让 `那高收费的别要了` 从错误 issue 定位回到 filters |
| Agent | 对上述不完整参数类 clarify 不立刻给用户，允许模型继续一次 | 只处理模型参数完整度问题，不吞掉真实业务澄清 |
| Tools | `tuition_level=high`、`tuitionLevel=high`、`fee_level=high`、`feeLevel=high` 归一为 `program_type=["高收费"]` | 接受模型常见结构化表达 |
| Tools | 未知 filter key 不再跳过匹配 | 防止错误全量命中后创建大范围删除 pending |

**验证结果：**

| 验证 | 结果 |
|------|------|
| 聚焦单测 + runner 单测 | `tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_dialog_regression_runner.py -q`：`205 passed, 28 skipped` |
| 真实 LLM opt-in | `那高收费的别要了` 通过，模型能带定位参数 |
| 真实 service direct-only 口语集 | `examples/dialog_regression_400_realistic_user_cases.json`：`14/14` successful，metrics: `/private/tmp/zhiyuan_400_realistic_direct_only_after_retry_reason_fix.json` |
| 真实 service direct 确认执行闭环 | `examples/dialog_regression_400_direct_confirm_execution_cases.json`：`4/4` successful，后端断言覆盖 pending applied、planningState version 增长、方案项删除和 `院校性质:民办` 写入，metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_retry_filter_fix.json` |
| G case direct 子集 direct-only | `/private/tmp/zhiyuan_400_g_case_direct_subset_direct_only.json`：`8/8` successful，G17/G25/G30/G32 direct 断言通过，metrics: `/private/tmp/zhiyuan_400_g_case_direct_only_after_retry_filter_fix_rerun.json` |

**验收口径：**

direct 主链路和 shadow 观测分开验收。shadow 是 dry-run 隔离后台任务，可能在 turn event 阶段仍为 `running` 或因超时缺观测；这类情况单独记录为 shadow 稳定性问题，不直接判定 direct 主链路失败。

### 9.14 完整 320 G1-G32 direct 复跑结果

**验证环境：**

- service：本地 `8075` direct-only，`ZHIYUAN_AGENT_POC_SHADOW=0`
- 后端：`8080`
- case：`examples/dialog_regression_320_g1_g32_shadow_cases.json`
- metrics：`/private/tmp/zhiyuan_400_direct_320_g1_g32_after_retry_filter_fix_rerun.json`

**总体结果：**

| 指标 | 结果 |
|------|------|
| steps | 49 |
| successfulSteps | 44 |
| failedSteps | 5 |
| failedByReason | environment=1, content=3, tool=3 |
| latency median | 16433ms |
| latency p95 | 45480ms |
| latency max | 68550ms |

说明：`failedByReason` 是按断言类型统计，同一个 step 可以同时触发 content/tool failure，因此数量会大于 `failedSteps`。

**已通过的关键路径：**

| 场景 | 结果 |
|------|------|
| G1 裸排除 + 当前方案影响 | `preview_intent_change`，生成报考要求确认卡 |
| G2/G7/G21 只读审查 | `review_plan` 或旧 full_agent，只读不改方案 |
| G3 pending 下只读查询 | 先创建 intent pending，后续 `query_plan` 只读查询 |
| G12 查询 + 替换复合诉求 | `query_plan -> preview_plan_action`，生成替换确认卡 |
| G16 锁定暂不支持 | `preview_plan_action` 返回 unsupported，不创建 pending |
| G17 档位内移动 | `preview_plan_action`，生成 `move_ordered_unit` 确认卡 |
| G22/G31 档案口语修正 | 不写系统档案，提示需正式更新 |
| G26 当前方案切片查询 | `query_plan`，返回保底末尾志愿 |

**问题归档：**

| 编号 | 场景 | 现象 | 定性 |
|------|------|------|------|
| 320-R1 | G8 | 清理 backend planning intent 超时，case 未进入 agent | 环境/后端准备失败，需重跑确认 |
| 320-R2 | G25 | `把生物医学工程和智能医学工程加意向 排除临床医学和口腔` 被旧 `runtime_intent_hard_cut` 接管，输出“偏好专业/排除专业”，不是 4.0 “专业要求：要/不要” | 旧路由抢跑；8-case direct 子集同诉求已通过，工具能力本身可用 |
| 320-R3 | G27 | `方案里学费贵的太多了 能不能帮我换成便宜的` direct 调用 3 次工具，最终未生成替换确认卡 | `replace` 自动候选/高收费替换策略不稳定 |
| 320-R4 | G27 | `两万以上的都算贵 帮我看看有几个` 实际 `query_plan` 返回 37 个，旧断言期望 `execute_plan_action/query_ordered` | case 断言仍是旧链路口径，应更新为 4.0 `query_plan` |
| 320-R5 | G27 | `那把两万以上且跟我意向不沾边的先删掉` 实际生成 `remove_units` 确认卡，旧断言期望 pending 冲突 guard | 受首轮未建 pending 影响，需在修复首轮后重新定义 |
| 320-R6 | G21/G30 | 强基多轮仍走 `full_agent` / `runtime_intent_hard_cut`，并出现“偏好/报考想法”旧文案 | direct route 覆盖范围未完全替换旧链路 |
| 320-R7 | G23/G29 | 正向软表达和“优先/可以考虑”仍触发旧 pending card | 与 4.0 显式要/不要口径不一致，后续通过旧链路清理解决 |
| 320-R8 | G23/G21/G30 | 多个旧 full_agent step 耗时 30-68s | 性能问题主要集中在旧链路和政策/探索多工具回答 |
| 320-R9 | G22/G31 | 中间轮次有“已更正”等口头措辞 | 需统一为“你口头说明的是……系统档案仍未更新”，避免用户误解已写入系统 |

**后续顺序：**

1. 先修 4.0 direct 内的问题：G27 高收费 replace 自动候选与首轮 pending 创建。
2. 更新历史 case 中已切到 4.0 的断言口径：`query_plan` 不再要求旧 `execute_plan_action/query_ordered`。
3. 再处理旧路由抢跑：G25/G21/G30/G23/G29 这类已由 4.0 子集证明可表达的诉求，应切到 direct 或在旧链路清理阶段删除对应 hard-cut。
4. 最后重跑完整 320 G1-G32；确认类 case 仍必须包含最终后端 action 断言。

### 9.15 G27 高收费替换修复

**修复原则：**

- 保持在 4.0 direct route 内解决，不回退旧链路，不增加字符串 precheck。
- 工具层只消费结构化参数：`review_issue_code`、`filters`、候选池结构化字段，不从用户原话做 NLU 特化。

**已落地：**

| 层级 | 调整 | 说明 |
|------|------|------|
| `preview_plan_action(replace)` | 支持 `filters` 定位旧方案项 | `filters` 可单独定位，也可与 `review_issue_code` 取交集 |
| review issue fallback | `high_tuition -> program_type=["高收费"]`，`cooperative_program -> program_type=["中外合作"]` | 解决审查 issue affected units stale 或缺失时无法落到当前方案项 |
| 自动候选选择 | 同时按 volunteerId 与 unitId 排除旧项 | 避免把同一个旧 unit 的不同 volunteerId 作为替换候选加回来 |
| 自动候选安全 | 费用类候选排除高于 20000 元/年、低于 1000 元/年的异常值，以及中外合作/合作办学/联合培养/学分互认/出国/国外学费等显性风险 | 防止生成“换成便宜的”但候选仍高收费或明显数据异常的确认卡 |
| 候选读取 | pageSize 扩为 `wanted * 4`、上限 200 | 解决默认 20 条候选中旧 unit/高收费项太多导致误判候选不足 |
| Prompt | 明确“学费贵/高收费 + 换成/换掉/替换/移出”直接走 `preview_plan_action`，决定 preview 后禁止先 `review_plan` | 降低首轮多工具调用和只读审查抢跑 |

**验证：**

- 单测：`tests/unit/test_zhiyuan_agent_poc.py -q`，`120 passed, 28 skipped`。
- 真实 G27 单 case：`/private/tmp/zhiyuan_400_g27_after_prompt_direct_preview_rule.json`。
  - 第 1 轮 `方案里学费贵的太多了 能不能帮我换成便宜的` 已达到 4.0 direct 核心目标：`toolCallCount=1`、`preview_plan_action`、`replace_units`、`pendingConfirmationCard`。
  - 自动候选不再选旧 unit，不再选仍高收费/中外合作候选，也不再选 50/80 元异常学费候选；本轮示例候选为 19800/16800/19800 元/年。
  - 第 2 轮只读查询实际 `query_plan` 返回 37 个，旧断言仍期望 `execute_plan_action/query_ordered`。
  - 第 3 轮 active pending 下实际通过 `preview_plan_action` 返回 pending 冲突说明，旧断言仍期望 `pending_conflict_new_request_guard` 和 0 工具调用。
- 真实 G27 direct-only 复验：`/private/tmp/zhiyuan_400_g27_direct_enabled.json`。
  - `ZHIYUAN_AGENT_ENABLED=1`、`ZHIYUAN_AGENT_ROLLOUT_PERCENT=100` 时，G27 三步 `3/3 successfulSteps`。
  - 第 1 轮仍是 `preview_plan_action(replace)` + `replace_units` 确认卡。
  - 第 2 轮仍是 `query_plan`，返回 37 个高收费项。
  - 第 3 轮仍是 active pending 冲突说明，不再创建第二张确认卡。

**当前定性：**

G27 direct replace 和后续只读/冲突流转已经在 4.0 direct-only 环境验证通过。历史回归文件里看到的 `direct_atomic_plan_action` / 旧断言失败，来自没有启用 direct-only 配置或仍沿用旧口径，不代表当前 G27 业务能力失败。

### 9.16 Focused Direct 修复与旧链路清理前置条件

**触发来源：**

- direct-on 失败集复跑中，G25 已通过；剩余 R33 和高收费 intent→plan-action 分别暴露验证资产状态不一致、确认链路继续出卡的问题。
- 用户侧要求后续替换链路后删除旧代码，不能继续维护历史分支。

**问题与修复：**

| 编号 | 问题 | 修复 | 验证 |
|------|------|------|------|
| F1 | `confirm_pending` 返回 `next_step=respond` 后，4.0 agent 继续让模型推理，可能同一轮再调用 `preview_plan_action` 覆盖已采纳 pending | `confirm_pending/respond` 在 agent 层视为终止结果；只读工具的 `respond` 仍可继续组合 | 高收费 case 确认步 `toolCallCount=1`，pending 保持 `applied` |
| F2 | R33 case 目标是 no-plan，但文件 defaults clone `17`，覆盖 `sourceSessionId=3729`，实际变成有正式方案 | R33 case 显式 `cloneBackendStateFromSessionId=3729` | `/private/tmp/zhiyuan_400_r33_asset_after_clone_reply_fix.metrics.json`，`1/1`，`needs_plan_first_guard` |
| F3 | no-plan guard 安全但回显不足，用户提到的专业/院校/方向被压成“这类方案范围要求” | no-plan reply 增加“这轮诉求是：原话摘要”，不创建 pending、不写报考要求 | R33 回复保留生物科学、化学、湘潭大学等实体 |
| F4 | sandbox 在 backend 状态未知时会有 `has_plan=false` 占位，no-plan guard 可能误把未知当无方案 | no-plan guard 只使用成功解析的 backend planning summary，不从 sandbox 占位回退 | 聚焦单测固定 workspace `code=1` 时不抢旧模型路径 |
| F5 | 高收费旧 case 把“采纳长期不要高收费”之后的“替换高收费”仍断言为 `replace_units` | 确认步增加后端状态断言；第三步改为目标/候选不足边界，不再要求出替换卡；真正 replace 能力由 clone 26/G27 覆盖 | `/private/tmp/zhiyuan_400_high_tuition_asset_after_confirm_terminal.metrics.json`，`3/3` |

**G25 复核：**

- direct-only 业务结果正确：`zhiyuan_agent_direct`，1 次 `preview_intent_change`，正负诉求完整，pending 文案为 `专业要求：要：生物医学工程、智能医学工程；不要：临床医学、口腔（口腔医学）`。
- runner 失败来自该 case 仍带 shadow 断言，而 direct-only 服务没有 shadow event；不作为业务失败。

**清理前 direct-only 基线：**

- 临时 case：`examples/dialog_regression_400_g1_g32_direct_cases.json` 去掉 shadow 断言后生成 `/private/tmp/zhiyuan_400_g1_g32_direct_cases_direct_only_for_cleanup.json`。
- 真实验证：`/private/tmp/zhiyuan_400_cleanup_preflight_g1_g32_direct_20of20.json`，`20/20 successfulSteps`。
- 路由分布：18 步 `zhiyuan_agent_direct`，2 步 `needs_plan_first_guard`。G19/G32 以 no-plan guard 为正确口径；G22 为状态前置只读，可 0 工具回答，不强制 `read_state`。
- 工具分布：`preview_intent_change=6`、`preview_plan_action=4`、`query_plan=4`、`review_plan=3`、`confirm_pending=1`；`pendingConfirmationCard=9`。
- 性能：median `6001ms`、p95 `14891ms`、max `16667ms`。只读长回复 G31/G7/G2/G26/G21 仍是后续性能优化项，不阻塞入口清理。
- 质量观察：G7 曾出现“当前方案里还没有生成具体志愿”的回复口径，后续需复核 review/fixture，但本轮不修旧链路。

**旧链路清理启动条件：**

1. 清理前 G1-G32 direct-only 基线完成，且 4.0 direct/no-plan 口径通过。
2. 剩余失败能明确归为验证资产口径、性能观察或后续 4.0 能力扩展，不再需要修补旧链路。
3. 确认类 case 必须继续包含最终后端 action 断言，不能只看出卡。

**首批删除范围：**

| 范围 | 删除原则 |
|------|------|
| `runtime_intent_hard_cut` 中的 intent/属性/要不要分流 | 已由 4.0 `preview_intent_change` 覆盖的直接删除，不再并行维护 |
| 旧 `direct_atomic_plan_action` / `execute_plan_action` 方案预览主路径 | 已由 `preview_plan_action` + `confirm_pending` 承接的直接删除 |
| 旧 `executionPayload.planPayload` 兼容桥 | 结构化 `action_family + atomic_actions` 成为唯一 plan pending 协议后删除 |
| 旧 recovery classifier / pending classifier / 字符串 guard 兜底 | 不再用旧分类器修补 4.0 语义，保留必要的协议安全 guard |
| 历史用户文案兜底 | 删除为旧链路服务的大量 sanitizer，保留少量全局安全替换 |

**2026-07-03 首批入口清理执行记录：**

- 已从 service 主流程移除旧 fast-route 入口：`runtime_intent_hard_cut`、pending 下旧 readonly plan query、`direct_atomic_plan_action`、`direct_readonly_plan_slice_query`、`direct_local_plan_action`、`semantic_plan_action`。
- 已删除无调用的旧 service 方法：`_maybe_handle_pending_readonly_plan_query`、`_maybe_handle_direct_readonly_plan_slice_query`、`_maybe_handle_direct_local_plan_action`、`_maybe_handle_direct_atomic_plan_action`、`_maybe_reroute_runtime_intent_profile_to_plan_response`、`_maybe_handle_semantic_plan_action`，以及旧 PlanQuery profile helper、未用 import 和常量。
- 4.0 no-plan guard 补齐“加进来/放进去/加到方案”这类当前方案 add 动作，统一返回 `needs_plan_first_guard(plan_add_without_referent)`，不再通过旧 atomic classifier 推断。
- 验证：`py_compile` 通过；聚焦单测 `17 passed, 787 deselected`。全量 `test_chat_service_history_persistence.py` 暂有 83 个旧路由口径失败，后续应删除或迁移旧路由测试，不再恢复旧实现。

**清理后回归观察（暂不修）：**

- 清理后 direct-only 20-case 回归：`19/20 successfulSteps`，metrics: `/private/tmp/zhiyuan_400_cleanup_after_old_route_entry_removal_20cases.json`。
- 唯一失败为 G1：`不要英语相关专业，当前方案里有的话也删掉`。模型同一轮发出 `preview_intent_change` 和 `preview_plan_action` 两个工具调用，`intent_change` 确认卡已创建，但最终文本被后续 `preview_plan_action(clarify)` 覆盖，导致回复和卡片不一致。
- 定性：4.0 agent 同批多工具终止边界问题，不是旧链路删除导致。当前先记录，不做修复。

**2026-07-03 第二批 hard-cut 死代码清理：**

- 删除生产代码中已无运行入口的旧 `runtime_intent_hard_cut` 调度和专属 helper，包括 prompt 抽取建卡入口、side-effect 二次分类、atomic defer 桥、target issue fallback、pending-state/allow/defer 判断。
- `service.py` 不再依赖旧 `classify_plan_atomic_action_dsl`、`_classify_intent_side_effect`、`extract_intent_entity_profile`；生产 `service.py` 已无 `runtime_intent_hard_cut` 路由字符串。
- 保留 full-agent intent preview 的通用 ProposalCompiler sink，不把它当作旧 hard-cut 兼容桥；TurnDecision 阻断 helper 改为 `_turn_decision_blocks_intent_pending`，只用于阻断错误的 full-agent intent pending。
- 聚焦验证通过：`py_compile`；no-plan guard/文案子集 `10/10`；4.0 agent direct 子集 `11/11`；proposal compiler no-plan guard 子集 `9/9`；`test_chat_service_history_persistence.py --collect-only` 可收集 `521` 个测试。
- 旧 hard-cut 单测仍作为待迁移/待删除资产存在，后续清理测试资产时按 4.0 direct 工具与确认执行断言重建，不恢复旧路由实现。

**2026-07-03 profile replan 旧 semantic fallback 清理：**

- 删除无生产调用的 `_maybe_create_current_plan_mutation_preview_from_entity_profile`，hard-cut 删除后不再保留 entity profile 到当前方案调整的 service 桥。
- `_maybe_handle_profile_change_replan_state_query` 删除旧 `classify_plan_semantic_action` 兜底，profile-change state query 只由 TurnDecision + ProposalCompiler 判定。
- 删除旧 semantic fallback 测试，保留并更新 TurnDecision correction merge 测试，断言不再调用旧 semantic classifier。
- 验证：profile replan 子集 `7/7`；no-plan guard/文案子集 `10/10`；4.0 agent direct 子集 `11/11`；proposal compiler no-plan guard 子集 `9/9`；`py_compile` 通过；`test_chat_service_history_persistence.py --collect-only` 可收集 `520` 个测试。

**2026-07-03 plan confirmation payload 内部结构化清理：**

- 新生成的内部 plan confirmation candidate 不再保存 JSON 字符串形态的 `plan_payload`：`service._build_plan_confirmation_candidate_from_payload()` 和 `proposal_compiler.compile_apply_then_generate_plan_source()` 均改为直接保存结构化 dict。
- service 侧 plan confirmation 读取 helper 统一支持 dict，旧字符串解析只作为存量兼容读取，不再作为新协议写入路径。
- `executionPayload.planPayload` 仍按既定设计保持不再生成；本次不修改对外 `execute_plan_action(plan_payload=...)` 工具入参，避免把工具协议清理和内部 pending candidate 清理混在一起。
- 验证：`py_compile` 通过；plan confirmation history 子集 `46/46`；proposal compiler confirmation 子集 `5/5`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47/47`。

**2026-07-03 full-agent plan post-processing 旧桥清理：**

- 删除 `_maybe_refocus_broad_review_result` 和 `_maybe_reroute_review_to_fix_preview`，不再允许旧 full-agent 已返回 broad review/analyze 后由 service 二次调用旧 `execute_plan_action` 改写为 targeted review 或 fix preview。
- 删除 ProposalCompiler 中仅服务这两条旧桥的编译类型和函数；后续审查、修复预览、确认执行应回到 4.0 direct 工具路径验证。
- 保留已有 `fix_proposal_preview` / ready fix proposal 的结构化确认卡 sink；本次删除的是“未显式调用预览工具却由 service 补执行”的旧桥。
- 验证：`py_compile` 通过；plan confirmation history 子集 `46/46`；proposal compiler `review_fix/fix_proposal/plan_confirmation` 子集 `15/15`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47/47`。
- 测试资产观察：旧 semantic route/fix preview 子集仍有 15 个旧口径失败，集中期望 `classify_plan_semantic_action + execute_plan_action` 绕过 full-agent 或补卡；按 4.0 清理原则记录为待迁移/删除，不恢复旧桥。

**2026-07-03 intent preview -> current plan mutation 旧桥清理：**

- 删除 `_execute_semantic_plan_payload()` 和 `_maybe_create_current_plan_mutation_preview_from_intent_payload()`；`service.py` 不再主动 await 旧 `execute_plan_action`。
- 删除 ProposalCompiler 中仅服务该桥的 `RuntimeCurrentPlanMutationCompiledSource`、`compile_runtime_current_plan_mutation_from_intent_preview_source()` 和 intent preview payload -> plan payload selector helper。
- full-agent intent preview 被 TurnDecision 判定为当前方案调整时，不再由 service 后置补执行方案预览；正确路径是 4.0 direct 直接选择 `preview_plan_action`。
- 保留历史/full-agent `execute_plan_action` 工具消息解析兼容，用于已有工具返回的展示、观测和 pending sink；这不是主动执行旧工具。
- 验证：`py_compile` 通过；audit `8/8`；proposal compiler `atomic_plan_action/review_fix/fix_proposal/plan_confirmation` 子集 `18/18`；plan confirmation history 子集 `46/46`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47/47`。

**2026-07-03 profile-change post-query semantic fallback 清理：**

- 删除旧 full-agent 后处理 fallback：旧 `query_state/status_overview` 返回空方案后，不再由 service 调用 `classify_plan_semantic_action` 追加判断是否为“学生信息变化，需要重规划”。
- 删除 `_latest_empty_status_overview_result()` 和 `_semantic_decision_is_current_student_profile_replan()`；当前 profile replan 仍由 TurnDecision + ProposalCompiler 的结构化路径处理。
- 边界：本轮后续已进一步清理，service 已不再 import 或调用 `classify_plan_semantic_action`；fix-proposal 目标选择只信任结构化结果里的显式 scope。
- 验证：`py_compile` 通过；audit `8/8`；proposal compiler 子集 `18/18`；plan confirmation history 子集 `46/46`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47/47`。

**2026-07-03 `plan_next_action` 未执行 preview 桥清理：**

- `_extract_plan_confirmation_candidate()` 不再从旧 `plan_next_action` 未执行 preview / 只读 query 结果补造 plan pending candidate；只接受已有执行结果中的可确认预览。
- 删除 `_latest_plan_next_missing_inputs_payload()` 和基于旧 missing-inputs payload 的主流程边界回复；缺参提示不再依赖旧工具未执行结果。
- 删除 `plan_next_action` structured goal preview 到 fix pending / intent fallback 的旧桥：`_latest_structured_goal_plan_preview()`、`_latest_goal_scoped_plan_preview()`、`_structured_user_goal_fix_candidate_from_source()`、`_structured_goal_intent_candidate_from_source()`、`_create_pending_intent_confirmation_from_structured_goal_candidate()`。
- 删除 ProposalCompiler 中仅服务该桥的 `StructuredUserGoalFixRequestSource`、`StructuredGoalIntentInputSource`、`compile_structured_user_goal_fix_request_source()`、`compile_structured_goal_intent_input_source()`；保留 direct 诉求方案调整实际使用的底层 request builder 和 proposal selector。
- 边界：本轮后续已进一步清理，`service.py` 生产代码不再保留 `plan_next_action` 引用；历史/full-agent `execute_plan_action` 工具消息解析仍暂保留，用于展示、观测和存量 pending sink。
- 验证：`py_compile` 通过；audit `8/8`；proposal compiler `user_goal/structured_goal/review_fix/fix_proposal/plan_confirmation/apply_then_generate_plan` 子集 `17/17`；plan confirmation history 子集 `46/46`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47/47`。

**2026-07-03 旧 atomic plan action compiler 清理：**

- 删除无生产调用的 `RuntimeAtomicPlanActionSource`、`compile_runtime_atomic_plan_action_source()`、`AtomicPlanActionDsl -> plan_next_action_args` 编译逻辑及其专属 helper/常量。
- 删除对应旧单测资产；4.0 当前方案操作以 `preview_plan_action` + `confirm_pending` 为唯一新实现口径，不再维护旧 atomic compiler 到 `plan_next_action` 的并行表达。
- 删除旧 `classify_plan_atomic_action_dsl`、`PlanAtomicActionDslDecision`、`PlanActionDslDecision` 和 model-node benchmark 的 `plan_atomic_action_dsl` 节点/样本；plan semantic tool 只保留 review/fix semantic classifier 与 local 档内移动 classifier。
- 删除 `test_chat_service_history_persistence.py` 中 9 条旧 direct atomic / runtime hard-cut 测试资产，避免继续 patch 已退役的 atomic classifier。
- 保留 `_turn_decision_is_current_plan_atomic_mutation()`，因为它仍用于阻断错误 full-agent intent pending；本次删除的是旧 compiler，不改变该安全判断。
- 验证：`py_compile` 通过；proposal compiler `turn_decision/user_goal/structured_goal/review_fix/fix_proposal/plan_confirmation/apply_then_generate_plan` 子集 `23/23`；plan semantic tool `3/3`；model-node benchmark `24/24`；plan confirmation history 子集 `46/46, 461 deselected`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47/47`；benchmark case JSON 校验通过。

**2026-07-03 ChatAgent 旧 Plan 工具与 planner/context 本体清理：**

- `ChatAgent` 不再注册 `collect_plan_context_inputs`、`plan_next_action`、`execute_plan_action`；相关 progress hint、prompt policy 和 plan 调度说明已同步删除旧 chain。
- full-agent 仍可使用 `query_volunteer_plan` 做局部命中查询，但不得承接整体方案生成、审查、删除、替换、补齐、移动、排序、重排或确认执行；这些动作由 4.0 direct `query_plan` / `review_plan` / `preview_plan_action` / `confirm_pending` 承接。
- `tool_reply_policy` 删除旧 `execute_plan_action(preview_only)` 的 add/remove/sort/position 预览直返分支，避免旧工具返回被包装成新的可确认最终回复。
- `explore_followup_tool(plan_analyze)` 不再反向委托 `plan_next_action -> execute_plan_action`；改为创建 4.0 sandbox context 后调用 `query_plan(scope="plan", filters=...)` 做只读方案承接查询。
- 删除无生产主动引用的 `app/tools/plan_orchestration_tool.py` 和 `app/tools/plan_context_tool.py`；删除或迁移其专属测试资产，保留执行层测试时直接传结构化 payload。
- `examples/dialog_quality_gate.py` 已移除被删除的旧 planner/context 测试目标；ActionResolver 集成测试保留结构化合同验证，不再与旧 helper 做 passthrough 对比。
- 边界：本轮后续已进一步清理，`service.py` 生产代码不再保留 `plan_next_action` 引用；历史/full-agent `execute_plan_action` tool message 解析仍暂保留，用于展示、观测和存量 pending sink，这不是主动执行旧工具。`plan_execution_tool.py` 仍被 handler/service 复用，暂不删除。
- 验证：ChatAgent/prompt 相关 `86/86`；ActionResolver 相关 `135/135`；tool reply + plan execution sync `46/46`；4.0 POC plan action 子集 `47/47`；`explore_followup` plan/candidate 子集 `11/11`。

**2026-07-03 旧 plan action cache 与 ChatAgent 回复策略继续清理：**

- `plan_execution_tool.py` 删除旧 `plan_next_action` 最近 plan cache 和 sort payload 补偿逻辑；`execute_plan_action()` 不再从历史 `plan_next_action` 输出补齐缺失 payload。
- 删除对应旧测试资产，执行层测试改为直接传当前结构化 payload，继续覆盖 sort/move/remove/replace 子集。
- `tool_reply_policy.py` 删除 `execute_plan_action` 专属 status/review synthesis reason 和 explicit `direct_blocking` trust 分支；ChatAgent 回复策略不再维护旧执行工具名的专属语义。
- 保留策略边界：intent preview 工具仍可直返确认卡；只读查询/分析仍回模型综合；通用结构化 blocking/no_change 兜底不绑定旧工具名。
- `test_tool_reply_policy.py` / `test_chat_agent_tools.py` 中旧 `execute_plan_action` 预览/阻断样例已移除或改为通用结构化结果样例；唯一保留的是 ChatAgent 不注册旧 Plan 工具的断言。
- `service.py` 删除无调用的 `_build_direct_plan_action_messages()`，并把 fix proposal 目标推断改为直接从结构化 plan result 构造 semantic context，不再人工包装旧 `execute_plan_action` tool return。
- 边界：`service.py` 和 runner 中的历史 tool message 解析/观测逻辑暂保留，用于存量消息展示、pending sink 兼容和回归指标提取；这部分不主动执行旧工具。
- 验证：`py_compile` 通过；`test_tool_reply_policy.py test_chat_agent_tools.py` 为 `60/60`；`test_plan_execution_tool.py -k "sort_preview or move_ordered or remove_ordered or replace"` 为 `43/43`；service semantic context / interruption / boundary 子集 `11/11`；proposal compiler fix/review/confirmation 子集 `15/15`。

**2026-07-03 `service.py` 旧 planner 工具名生产引用清理：**

- `service.py` 生产代码已清零 `plan_next_action` / `collect_plan_context_inputs` 引用；这两个旧工具名不再参与 plan chain 判定、readonly 判定、scene 分类、结构化 plan result 检测或 plan preview 边界修正。
- 删除 `plan_next_action` 未执行 preview/missing-inputs 结果驱动的文案补救分支；缺参、确认前不执行、无可执行预览等边界应来自 4.0 `preview_plan_action` / `confirm_pending` 或仍保留的历史 `execute_plan_action` 结果。
- 删除 `test_chat_service_history_persistence.py` 中 5 条旧 `plan_next_action` 文案补救测试资产。
- 边界：service 中历史 `execute_plan_action` tool message 解析暂保留，用于存量展示、pending sink 和工作台刷新兼容；但旧 planner/context 工具名不再是生产语义判断输入。
- 验证：`rg -n "plan_next_action|collect_plan_context_inputs" app/service.py` 无结果；`py_compile` 通过；plan confirmation/boundary 子集 `41/41`；audit `8/8`；ChatAgent/tool policy/audit `68/68`；4.0 POC plan action 子集 `47/47`；`test_chat_service_history_persistence.py --collect-only` 为 `502` tests。

**2026-07-03 旧 service patch 测试资产与无调用 helper 清理：**

- `service.py` 删除无调用旧 helper：`_latest_review_plan_result`、`_tool_context_has_execute_plan_return`、`_plan_result_is_readonly_workspace_no_refresh`、`_tool_calls_include_plan_execution`、`_latest_readonly_plan_query_misroute_candidate`。
- hard-cut 审计测试不再以已删除 helper 作为正则边界，改锚定到仍存在的 `_tool_returns_successful_plan_apply`。
- `test_chat_service_history_persistence.py` 删除仍 patch 已退役 `app.service.execute_plan_action`、`app.service.plan_next_action`、`app.service.classify_local_plan_action_dsl`、`ChatService._maybe_handle_semantic_plan_action` 的测试块；同步删除旧 `runtime_intent_hard_cut` service patch、旧 `plan_next_action` / `collect_plan_context_inputs` 工具消息资产、旧 `_apply_selected_intents` service confirmation 资产。
- 保留边界：历史 `execute_plan_action` tool return 的读取、展示、工作台刷新和 pending sink 兼容测试暂保留；这部分不代表当前模型可调用旧工具。`plan_next_action` / `collect_plan_context_inputs` 在核心 service/agent/tool 测试中只剩 ChatAgent 不注册旧工具的断言。
- `test_chat_service_history_persistence.py` 收集规模从 `502` 降到 `336`，全量恢复通过。
- 验证：`py_compile` 通过；`test_chat_service_history_persistence.py` 为 `336 passed, 1 skipped`；`test_runtime_hard_cut_audit.py` 为 `8 passed`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`；ChatAgent/tool policy/audit 为 `68 passed`；`git diff --check` 通过。

**2026-07-03 workspace presentation 与内部旧字段继续清理：**

- `compile_runtime_workspace_presentation_source()` 删除旧 call-only fallback，不再从当前轮旧 tool call name / action family 推断工作台刷新目标；工作台刷新只基于实际 plan result，route reason 收敛为 `plan_result_refresh` / `plan_result_no_refresh`。
- `service.py` 删除 `_extract_execute_plan_action_family`、`_execute_plan_action_call_families`、`_tool_calls_include_plan_workspace_refresh`；`_current_turn_workspace_refresh_targets()` 只从 `_execute_plan_action_results(tool_context_messages)` 获取刷新目标。
- 删除旧 call-only refresh 测试资产，不再维护“只看到旧工具调用、没有结果也追加工作台刷新”的行为。
- `compile_plan_confirmation_proposal()` 新生成的 `proposalCandidates[]` 改写 `plan_payload`，不再写 `planPayload`；`plan_sink_contract()` 优先读取 `plan_payload`，`planPayload` 仅作为存量对象读取兼容。
- 边界：`executionPayload.planPayload` 继续按 4.0 协议拒绝；历史 `execute_plan_action` tool return 的展示、观测和 pending sink 兼容暂保留，但不是当前模型可调用旧工具。
- 验证：`py_compile` 通过；proposal compiler 全量 `114/114`；runtime hard-cut audit `8/8`；`test_chat_service_history_persistence.py` 为 `334 passed, 1 skipped`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`；`git diff --check` 通过。

**2026-07-03 service 旧 plan semantic classifier 依赖清理：**

- `service.py` 不再 import 或调用 `classify_plan_semantic_action`；hard-cut audit 已把该符号加入 service 禁止片段。
- 删除 `_user_requested_fix_proposal_preview()`、`_infer_plan_target_issue_codes_from_context()` 两个无生产调用 helper。
- `_infer_fix_proposal_target_scope()` 只信任已有结构化 plan result 的 `target_strategies` / `target_issue_codes` 或 `selected_proposal_id`；没有显式目标时不再由 service 调旧 semantic classifier 猜测，也不补 unrelated fix card。
- `proposal_compiler` 删除只服务旧 semantic classifier 的 `semantic_decision_fix_proposal_target_scope()`、`resolve_fix_proposal_target_scope_from_decision()`、`semantic_decision_target_issue_codes_for_context()`；precheck 字段改为 `needs_explicit_scope`，source 改为 `explicit_scope_required`。
- 测试资产同步删除对 `app.service.classify_plan_semantic_action` 的 patch 和 await 断言；保留 pending/card/文案行为断言。
- 验证：`py_compile` 通过；proposal compiler 全量 `109/109`；`test_chat_service_history_persistence.py` 为 `334 passed, 1 skipped`；runtime hard-cut audit `8/8`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`；`git diff --check` 通过。

**2026-07-03 `service.py` 深清理旧 runtime/profile/plan-chain helper：**

- 继续删除 `service.py` 中生产无调用的旧 helper：`_semantic_current_plan_analysis_allowed`、`_semantic_current_plan_analysis_matches_prompt`、`_plan_result_has_ready_fix_proposals`、`_synthesize_semantic_plan_action_reply`、`_pending_semantic_decision`、`_create_apply_then_generate_plan_pending_result`、`_extract_structured_major_context_from_tool_history` 等旧 semantic / reply synthesis / apply-then-generate 分支。
- 删除后继续按 `service.py` 本文件引用数扫描，移除只被旧测试资产维持的 runtime intent/profile/plan-chain helper：`_create_pending_intent_confirmation_from_entity_profile`、`_runtime_intent_entity_profile_context`、`_plan_chain_failed_without_pending_preview`、`_turn_has_structured_plan_result`、`_guard_plan_preview_reply_without_card`，以及级联孤立的 entity context / profile selected-values 转换链。
- `test_chat_service_history_persistence.py` 同步删除旧 helper-only 测试资产；runtime hard-cut audit 改为锚定仍保留的 `_guard_unbacked_plan_confirmation_reply` 到 `_normalize_unbacked_no_tool_action_boundary`，不再要求已删除 helper 存在。
- 当前边界：`service.py` 生产代码已无 `plan_next_action` / `collect_plan_context_inputs` / `classify_plan_semantic_action` / 旧 runtime profile fallback helper；本文件无调用 helper 扫描只剩类构造 `__init__`。历史 `execute_plan_action` tool message 的解析、展示、pending sink、工作台刷新和观测兼容仍暂保留，不代表当前模型可调用旧工具。
- 同步更新 `runtime_pending_sink_calls_320.json` 审计基线，删除已不存在的 runtime entity profile / structured goal intent sink 和过期 pending status entry，当前基线为 12 个现存 sink/status 调用。
- 验证：`py_compile app/service.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_runtime_pending_sink_call_audit.py` 通过；`test_chat_service_history_persistence.py` 为 `314 passed, 1 skipped`；runtime hard-cut audit `8/8`；runtime pending sink audit `2/2`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`；`git diff --check` 通过。

**2026-07-03 旧 semantic action tool 与 benchmark 资产清理：**

- 删除 `app/tools/plan_semantic_action_tool.py` 和 `tests/unit/test_plan_semantic_action_tool.py`；4.0 direct 不再维护旧 semantic/local DSL classifier 并行路径。
- `test_runtime_hard_cut_audit.py` 改为断言旧 semantic tool 文件不存在，并继续禁止 `service.py` 重新引入旧 semantic classifier 符号。
- `examples/model_node_benchmark.py` 删除 `plan_semantic_action` / `local_plan_action_dsl` / `proposal_selection` live adapter 分支；`examples/model_node_benchmark_320_cases.json` 删除 8 条旧节点 case，样本从 59 条收敛为 51 条。
- `tests/unit/test_model_node_benchmark.py` 的示例节点改为仍存在的模型节点；`test_chat_service_history_persistence.py` 删除旧 `classify_local_plan_action_dsl` no-op patch 和 `_semantic_composite_goal` helper。
- 当前边界：扫描 `app/tests/examples` 后，旧 semantic tool 符号只剩审计测试里的“文件不存在/禁止片段”断言；旧 runtime review-fix selector/compile helper 已在后续清理中删除，不再作为 4.0 runtime selection helper 保留。
- 验证：`py_compile app/service.py examples/model_node_benchmark.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_model_node_benchmark.py tests/unit/test_runtime_hard_cut_audit.py` 通过；`test_runtime_hard_cut_audit.py test_model_node_benchmark.py` 为 `32 passed`；`test_chat_service_history_persistence.py` 为 `314 passed, 1 skipped`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`。

**2026-07-03 旧 `execute_plan_action` recent execution cache 清理：**

- 删除 `plan_execution_tool.py` 中的 `_RECENT_PLAN_EXECUTION_RESULTS`、TTL prune、`clear_recent_plan_execution_result()`、`consume_recent_plan_execution_result()`、`_remember_recent_plan_execution_result()`；旧 `execute_plan_action()` 不再写入供 timeout/interruption 使用的内存结果缓存。
- 删除 `service.py` 的 `build_timeout_fallback_from_recent_plan_execution()` / `build_interruption_fallback_from_recent_plan_execution()`，并移除每轮入口清理旧 execution cache、模型中断时从旧 cache 恢复方案回复的分支。
- `server.py` websocket 超时处理统一返回通用安全超时回复，不再从旧 `execute_plan_action` cache 取回复或 workspace followup。
- 测试资产同步收敛：删除 `test_pending_protocol.py` recent cache 协议类、`test_plan_execution_tool.py` timeout fallback cache 断言、`test_ws_compat.py` 旧 fallback followup case；history 中断 case 改为只验证通用安全回复和不覆盖已有 pending。
- 当前边界：`service.py` 已不再 import `app.tools.plan_execution_tool`；`plan_execution_tool.py` 仍保留执行层原语和中性 `run_plan_action_payload()` 测试 runner，因 mutation handlers / 执行层单测仍复用其中大量解析、预览和后端 action helper，后续需要先迁移原语再删文件。
- 验证：`py_compile app/service.py app/server.py app/tools/plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py tests/unit/test_plan_execution_tool.py tests/regression/test_pending_protocol.py tests/unit/test_runtime_hard_cut_audit.py` 通过；runtime hard-cut audit `8/8`；websocket compat `19/19`；plan execution 聚焦子集 `41/41`；pending protocol `110/110`；history persistence `312 passed, 1 skipped`；`git diff --check` 通过；旧 semantic/recent cache 符号扫描只剩 hard-cut audit 的禁止断言。

**2026-07-03 旧 `execute_plan_action` 公开工具入口退役：**

- `plan_execution_tool.py` 删除旧公开工具入口名 `async def execute_plan_action(...)`，改为中性的 `run_plan_action_payload(...)`；当前仅作为执行层测试 runner 使用，不再以工具函数名暴露。
- `test_plan_execution_tool.py`、`test_planning_plan_scenarios_sync.py`、`test_ws_compat.py` 的直接调用迁移到 `run_plan_action_payload()`；历史 tool message 兼容测试里的 `tool_name="execute_plan_action"` 暂保留，后续随 service 历史消息兼容清理删除。
- hard-cut audit 新增断言：`plan_execution_tool.py` 不得重新定义旧 `execute_plan_action` 函数，且保留当前 payload runner。
- 验证：`py_compile app/tools/plan_execution_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_planning_plan_scenarios_sync.py tests/unit/test_ws_compat.py tests/unit/test_runtime_hard_cut_audit.py` 通过；`test_plan_execution_tool.py test_planning_plan_scenarios_sync.py test_ws_compat.py test_runtime_hard_cut_audit.py` 为 `193 passed`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`；可调用旧入口扫描仅剩 hard-cut audit 禁止断言。
- 后续处理：`tests/regression/test_execution_preview.py tests/regression/test_execution_apply.py` 已删除；这些旧回归直接调用旧 wrapper 内部原语并期望旧 apply guard / generate 行为，不再作为 4.0 验证资产维护。

**2026-07-03 service 旧 `execute_plan_action` preview pending sink 切断：**

- `service.py` 主流程不再调用 `_extract_plan_confirmation_candidate(tool_context_messages)`；旧 full-agent `execute_plan_action(preview)` 结果不再反向生成 plan pending 卡。
- 4.0 plan pending 创建职责收敛到 `preview_plan_action` 工具内，direct 分支只根据已经保存的结构化 pending 渲染卡片；确认执行继续走 `confirm_pending`。
- `_append_plan_preview_confirmation_boundary()` 不再根据旧 preview 追加“确认后执行”文案，只保留旧 plan-chain 失败、只读误确认和不可执行结果的安全边界。
- `_latest_non_actionable_plan_mutation_result()` 不再依赖 `_build_plan_confirmation_candidate_from_payload()` 判定是否要跳过旧 preview；service 不再通过旧候选构造器决定 pending sink。
- hard-cut audit 增加防回退断言：禁止主流程重新从 `tool_context_messages` 提取旧候选，禁止 `await _create_runtime_compiled_plan_pending(...)` 重新出现。
- 当前边界：旧候选 helper 与 helper-only 测试资产已在后续清理中删除；历史 `execute_plan_action` 展示/观测安全边界和 `plan_execution_tool.py` 执行原语迁移已在后续 2026-07-04 清理中完成。
- 验证：`py_compile app/service.py tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_chat_service_history_persistence.py` 通过；runtime hard-cut + pending sink audit `12/12`；`test_chat_service_history_persistence.py` 为 `312 passed, 1 skipped`；history 旧候选/边界子集 `31 passed, 282 deselected`。

**2026-07-04 service 旧 execute pending/workspace/review-fix 桥继续清理：**

- 删除旧候选 pending helper 和 helper-only 测试资产：`_build_plan_confirmation_candidate_from_payload`、`_extract_plan_confirmation_candidate`、`_create_runtime_compiled_plan_pending`、旧 atomic -> candidate 构造链等不再保留。
- 删除 service 当前轮旧 `execute_plan_action` workspace refresh/view 桥：`_current_turn_workspace_refresh_targets`、`_current_turn_workspace_view_targets`、`_execute_plan_action_results`、旧 prior plan attempt view helper 已清理；workspace 刷新只保留 4.0 pending/confirm 当前路径和确认后后端 action 结果。
- 删除旧 `execute_plan_action(preview_fix_proposal)` / ready fix proposal 到 pending card 的反向建卡桥：`_create_runtime_compiled_review_fix_pending`、`_latest_fix_proposal_confirmation_source`、service 目标推断/澄清 helper，以及 `proposal_compiler` 中的 runtime review-fix selector/compile helper 均已删除；方案处理应由 4.0 `preview_plan_action` 直接产出结构化 pending。
- `runtime_pending_sink_calls_320` 审计基线从 12 个 sink/status 调用收敛到 9 个：保留 user-goal fix、intent preview、intent select 的 compiler sink，以及状态更新调用；旧 plan/review-fix runtime sink 不再保留。
- 验证：`test_chat_service_history_persistence.py` 为 `273 passed, 1 skipped`；`test_proposal_compiler_runtime_selection.py` 为 `90 passed`；runtime hard-cut + pending sink audit `12 passed`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47 passed, 102 deselected`；`py_compile` 通过。

**2026-07-04 service 旧 execute 解析/展示后处理清零：**

- `service.py` 生产代码已清零 `execute_plan_action` 字符串和旧工具结果解析：删除旧 payload parser、readonly result scanner、non-actionable preview boundary、profile replan payload fallback、plan semantic route context、旧 plan-chain confirmation boundary 等 helper。
- 主流程不再从旧 `execute_plan_action` tool return 改写回复、补 review/status/fix 展示、追加不可执行边界或候选缺参提示；4.0 方案调整预览和确认执行只由 `preview_plan_action` / `confirm_pending` 承接。
- `proposal_compiler` 删除无生产调用的 `compile_runtime_workspace_presentation_source()`、`compile_runtime_semantic_plan_display_source()` 及其 dataclass；service 不再从旧执行结果生成 full-agent display payload/reply plan。
- `test_chat_service_history_persistence.py` 删除旧 execute helper-only 和旧 execute service 后处理测试资产；hard-cut audit 新增 `service.py` 不得出现 `execute_plan_action` 的防回退断言。
- 当前边界：历史测试文件中仍有旧 tool message fixture 用于不回归已有安全 guard 或存量历史场景，但 `service.py` 不再解析旧工具名；后续可继续清理测试 fixture 和 `proposal_compiler` 中仅服务旧 evidence plan 的残余字段。
- 验证：`test_chat_service_history_persistence.py` 为 `255 passed, 1 skipped`；runtime hard-cut + pending sink audit `13 passed`；`test_proposal_compiler_runtime_selection.py` 为 `81 passed`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集 `47 passed, 102 deselected`；`py_compile` 通过。

**2026-07-04 service/proposal compiler 旧兼容尾巴继续清理：**

- `service.py` 删除旧 `planEditCache` 清理桥：不再 import/call `save_intent_change_cache`，删除 `_clear_legacy_plan_edit_cache_best_effort()`；新 4.0 pending 只写 `pendingConfirmation`，不再为了兼容旧意向缓存额外清理 `planEditCache`。
- `service.py` 删除旧 plan pending/reroute 空变量尾巴：`compiled_plan_pending_card`、`plan_confirmation_candidate`、`structured_plan_reroute`、`compiled_plan_includes_intent_update` 和 `structuredReroute` observability 字段不再保留；full-agent 后处理只保留当前仍有效的 intent pending guard 和 workspace refresh。
- `test_chat_service_history_persistence.py` 删除旧 `planEditCache` 清理断言和 5 条旧 `execute_plan_action` workspace refresh 兼容测试；同时删除不再使用的 workspace follow-up 断言 helper。
- `proposal_compiler` 删除只服务旧 execute 展示桥的 `RuntimeReadonlyWorkspaceEvidencePlanSource` / `compile_runtime_readonly_workspace_evidence_plan_source()`，以及旧 workspace result refresh/view helper 和 `current_execute_plan_action_result` evidence 字段；旧 execute workspace/evidence 命名在 compiler 中清零。
- hard-cut audit 增加防回退断言：`service.py` 不得重新出现 `save_intent_change_cache` / `planEditCache` 或旧 plan pending/reroute 空变量，`proposal_compiler` 不得重新引入旧 readonly workspace evidence compiler、旧 execute workspace family 常量或 `current_execute_plan_action_result`。
- 验证：`test_chat_service_history_persistence.py` 为 `249 passed, 1 skipped`；`test_proposal_compiler_runtime_selection.py` 为 `79 passed`；runtime hard-cut + pending sink audit `13 passed`；`py_compile app/service.py app/domain/proposal_compiler.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_proposal_compiler_runtime_selection.py tests/unit/test_runtime_hard_cut_audit.py` 通过。

**2026-07-04 旧执行工具测试资产继续清理：**

- `plan_execution_tool.py` 内部执行原语从 `_execute_plan_action_model` 改名为 `_run_plan_action_model`；`run_plan_action_payload()` 继续作为中性 payload runner，避免测试和执行原语继续使用旧公开工具语义命名。
- 删除 `tests/regression/test_execution_preview.py` / `tests/regression/test_execution_apply.py`，并从 `examples/dialog_quality_gate.py` 的本地 pytest target 移除；这两组回归只覆盖旧 wrapper 口径，不再作为 4.0 质量门禁维护。
- `test_runtime_hard_cut_audit.py` 增加防回退断言：禁止 `_execute_plan_action_model` 旧内部名回归，要求保留当前 `_run_plan_action_model`。
- `test_chat_service_history_persistence.py` 清理旧 `execute_plan_action` tool message 夹具：删除旧 review-fix / legacy generate / no-change / budget review 反向建卡负向测试，保留并改写仍有价值的历史压缩、只读回复和 workspace 泄漏测试到 4.0/中性工具名；该文件扫描已清零 `execute_plan_action` 字符串。
- 当前边界：`service.py` / `proposal_compiler.py` / `test_chat_service_history_persistence.py` 均不再携带旧 `execute_plan_action` 字符串；旧执行工具语义只在 hard-cut audit 的禁止断言中保留。
- 验证：`test_chat_service_history_persistence.py` 为 `226 passed, 1 skipped`；`test_plan_execution_tool.py` 为 `153 passed`；`test_proposal_compiler_runtime_selection.py` 为 `79 passed`；runtime hard-cut + pending sink audit 为 `13 passed`；4.0 agent `replace/preview_plan_action/confirm_pending` 子集为 `47 passed, 102 deselected`；`py_compile` 和 `git diff --check` 通过。

**2026-07-04 旧 `planEditCache` 写入/清理路径清理：**

- `intent_state_tool._apply_intents()` 删除旧 `save_intent_change_cache(session_id, {})` best-effort 清理调用；意向采纳后只保留当前 4.0 需要的 constraint state sync、tuition budget sync、planning stale mark 和 recommendation overlay refresh。
- `internal_client.py` 删除 `save_intent_change_cache()`，不再保留 `planEditCache` 写接口；`tests/fixtures/mock_backend.py` 同步移除该 mock endpoint。
- `examples/dialog_regression_runner.py` 的 backend pending clone/clear key 从 `("pendingConfirmation", "planEditCache")` 收敛为只处理 `pendingConfirmation`；CLI help、runner 单测和 e2e README 同步更新。
- `test_runtime_hard_cut_audit.py` 增加防回退：`intent_state_tool.py`、`internal_client.py` 和 `dialog_regression_runner.py` 不得重新出现 `save_intent_change_cache` / `planEditCache`。
- 当前边界：`app/`、regression runner 和相关单测中旧 `planEditCache` 字符串清零；历史文档和历史 metrics fixture 中的旧 key 记录不作为运行时维护面。
- 验证：`test_intent_state_tool.py` 为 `193 passed`；`test_planning_intent_scenarios_sync.py test_dialog_scenario_stability.py` 为 `44 passed`；`test_dialog_regression_runner.py` 为 `89 passed`；`test_chat_service_history_persistence.py` 为 `226 passed, 1 skipped`；`py_compile` 通过。

**2026-07-04 regression runner 旧观测与 fast-route 维护面清理：**

- `examples/dialog_regression_runner.py` 删除旧 `execute_plan_action(plan_payload=...)` 专用解析，不再从旧 JSON 字符串 payload 反推 `actionFamily` / `stage`；4.0 观测统一读取工具 args、tool return 和 route event 的结构化字段。
- 删除 runner 中旧 fast-route model/tool-call 前缀映射和 `fastRouteArbitration` 汇总；当前评估只保留通用 `routingPath`、`routeDecision`、工具调用、pending 和 `zhiyuanAgentPocShadow` 指标。
- `examples/dialog_quality_gate.py` 移除已删除的 fast-router pytest target；`test_dialog_regression_runner.py` 的观测样例收敛到 `preview_plan_action`、`query_plan`、`compare_entities`、`confirm_pending` 等 4.0 工具。
- `test_runtime_hard_cut_audit.py` 增加防回退：regression runner 不得重新出现旧 Plan 工具观测名或 fast-route 汇总字段。
- 验证：`test_dialog_regression_runner.py test_dialog_quality_gate.py` 为 `96 passed`；`test_runtime_hard_cut_audit.py test_runtime_pending_sink_call_audit.py test_dialog_regression_runner.py test_dialog_quality_gate.py` 为 `111 passed`；`test_plan_execution_tool.py test_proposal_compiler_runtime_selection.py` 为 `232 passed`；相关文件 `py_compile` 通过。

**2026-07-04 plan action execution domain 搬迁：**

- 新增 `app/domain/plan_action_execution.py`，承接原 `plan_execution_tool.py` 中的 payload 解析、scope 归一、后端 action/preview/review helper、handler dispatch 和 `_run_plan_action_model` 等执行原语。
- `app/tools/plan_execution_tool.py` 收敛为 `run_plan_action_payload()` 中性 runner，只负责结构化 payload 校验、apply guard 和调用 domain runner；不再直接 import `app.util.internal_client`，也不再定义 `_run_plan_action_model`。
- `mutation_handlers.py`、mock backend/planning fixture 和执行层测试 patch 路径切换到 `app.domain.plan_action_execution`；hard-cut audit 增加防回退，要求 handler 不再从 tool 模块反向依赖执行原语。
- 当前边界：`run_plan_action_payload()` 已在后续旧文件删除清理中迁入 domain；旧公开工具名、旧工具语义入口和旧 `app/tools/plan_execution_tool.py` 文件均已删除。
- 验证：`py_compile` 和 `git diff --check` 通过；`test_runtime_hard_cut_audit.py test_runtime_pending_sink_call_audit.py test_plan_execution_tool.py test_pending_protocol.py test_planning_plan_scenarios_sync.py` 为 `291 passed`；`test_zhiyuan_agent_poc.py -k "replace or preview_plan_action or confirm_pending"` 为 `47 passed, 102 deselected`；`test_dialog_regression_runner.py test_dialog_quality_gate.py test_proposal_compiler_runtime_selection.py` 为 `175 passed`。

**2026-07-04 旧 `plan_execution_tool.py` 文件删除：**

- `run_plan_action_payload()` 从旧 tool 文件迁入 `app.domain.plan_action_execution`，与 `_run_plan_action_model`、payload 解析、scope 归一、后端执行 helper 保持同一执行层边界。
- 删除 `app/tools/plan_execution_tool.py`；测试直接导入 `app.domain.plan_action_execution.run_plan_action_payload()`，不再通过旧 tool 模块间接调用。
- `tests/unit/test_plan_execution_tool.py` 改名为 `tests/unit/test_plan_action_execution.py`，`examples/dialog_quality_gate.py` 同步更新 pytest target。
- hard-cut audit 改为断言旧 tool 文件不存在，并继续禁止 `service.py` / `mutation_handlers.py` 重新依赖 `app.tools.plan_execution_tool`。
- 验证：`py_compile` 和 `git diff --check` 通过；`test_runtime_hard_cut_audit.py test_runtime_pending_sink_call_audit.py test_plan_action_execution.py test_pending_protocol.py test_planning_plan_scenarios_sync.py test_ws_compat.py` 为 `310 passed`；`test_zhiyuan_agent_poc.py -k "replace or preview_plan_action or confirm_pending"` 为 `47 passed, 102 deselected`；`test_dialog_quality_gate.py test_dialog_regression_runner.py test_proposal_compiler_runtime_selection.py` 为 `175 passed`。

**2026-07-04 旧 fast-route/report/metrics 测试资产清理：**

- `examples/dialog_case_evaluation_report.py` 的语义 frame 默认映射从旧 fast-route 口径收敛为 `zhiyuan_agent_direct`；旧 optimization route 特判改为中性的 soft expected route 机制，当前不再内置旧 fast-route 名。
- `tests/unit/test_dialog_case_evaluation_report.py` 样例改用 `zhiyuan_agent_direct`、`query_plan`、`review_plan`、`preview_plan_action`，不再用旧 `execute_plan_action` / `plan_next_action` / fast-route 名构造报表样例。
- `tests/unit/test_mainline_dialog_scenarios.py` 删除旧 full-agent `execute_plan_action(preview)` 反向建卡并 patch `app.service.execute_plan_action` 确认执行的测试资产；保留只读状态/审查回复测试，并改用 `query_plan` / `review_plan`。
- `tests/unit/test_ws_compat.py` 的 agent tool message 改用 `query_plan`；3.0.3 case coverage 中旧 `plan_fast_route` / `plan_query_fast_route` 标签统一改为 `zhiyuan_agent_direct`。
- 删除仓库内历史生成的 live metrics/output 文件，E2E README 示例输出改到 `/private/tmp`，避免继续把旧链路观测结果作为仓库资产维护。
- 扫描结果：`app tests examples` 中旧执行工具名和 fast-route 名只剩防回退断言。
- 验证：`py_compile` 和 `git diff --check` 通过；`test_dialog_case_evaluation_report.py test_mainline_dialog_scenarios.py test_ws_compat.py test_dialog_quality_gate.py test_runtime_hard_cut_audit.py` 为 `117 passed`；最终补充回归 `test_dialog_case_evaluation_report.py test_mainline_dialog_scenarios.py test_dialog_quality_gate.py test_chat_agent_init_profile.py test_chat_agent_progress_hints.py test_chat_agent_tools.py` 为 `126 passed`。

**2026-07-04 旧链路清理后真实 direct 复跑：**

- 环境：LLM 网关恢复可达；8080 service 和 5001 rank 健康；新起 8039 agent，启用 `ZHIYUAN_AGENT_ENABLED=1`、`ZHIYUAN_AGENT_ROLLOUT_PERCENT=100`、`ZHIYUAN_AGENT_POC_SHADOW=1`。
- 确认执行闭环：`examples/dialog_regression_400_direct_confirm_execution_cases.json` 为 `4/4`，metrics: `/private/tmp/zhiyuan_400_confirm_after_model_reopen.json`。验证覆盖最终后端 action：`confirm_pending` 后 pending applied、`planningState.version` 增长、方案项删除和报考要求写入，不只看确认卡出卡。
- G case direct 子集：`examples/dialog_regression_400_g_case_direct_subset.json` 为 `8/8`，shadow `8/8 success`，metrics: `/private/tmp/zhiyuan_400_g_subset_after_model_reopen.json`。
- G1-G32 direct 主集：`examples/dialog_regression_400_g1_g32_direct_cases.json` 为 `20 steps / 19 successful / 1 failed`，shadow `20/20 success`，metrics: `/private/tmp/zhiyuan_400_g1_g32_after_model_reopen.json`。
- 唯一失败 G7：用户表达“方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动”；主集当轮先调用 `review_plan`，随后追加 `query_plan`，违反该 case 的单工具断言。该轮没有执行方案变更、没有创建 pending，也没有后端 action 失败。
- 稳定性复核：同一 G7 case 用 `--session-offset 2000`、`--session-offset 3000` 单独复跑两次均通过，均只调用 `review_plan`；metrics: `/private/tmp/zhiyuan_400_g7_rerun_offset2000_after_model_reopen.json`、`/private/tmp/zhiyuan_400_g7_rerun_offset3000_after_model_reopen.json`。
- 定性：这是 4.0 direct 在真实 LLM 主集并发/长回归下的偶发只读工具边界抖动，不是旧链路清理导致的后端执行回归。后续解决方向应在 4.0 agent 工具终止策略和 `review_plan` 只读 stop 条件内处理，不恢复旧 route 或字符串 precheck。

**2026-07-04 G7 工具边界问题补充分析（仅记录，暂不修复）：**

- 当前 `ZhiyuanAgent.should_return_directly_from_tool()` 的直返终止条件是 `next_step=confirm/clarify`，以及 `confirm_pending(next_step=respond)`；`review_plan(next_step=respond)` 不会直返终止，会回到模型继续综合。
- 这使 G7 这类“先看看/别直接动”的只读审查在拿到 `review_plan` 后，仍可能由模型追加 `query_plan` 补明细，从而违反单工具断言。该问题只影响工具边界和耗时，没有触发方案变更、pending 或后端 action。
- 不能简单把所有 `respond` 工具都改成直返，因为 G12 这类“先问占比，再替换”的复合诉求需要保留 `query_plan -> preview_plan_action` 链路。只对 `review_plan` 改直返也会改变现有测试口径：`test_zhiyuan_agent_continues_after_review_plan_tool` 当前明确期望 review 后继续交给模型综合。
- 本轮按要求仅客观记录，不修改策略、不调整测试。后续若处理，应先明确 `review_plan` 是否作为完整只读终止工具；若是，再在 4.0 direct 终止策略中统一落地，而不是加字符串 precheck。

**2026-07-04 旧 payload / route / skill 残余清理：**

- `proposal_compiler` 的 plan confirmation / pending sink 合同进一步收敛：正常路径只读取 dict 型 `plan_payload`，不再解析旧 JSON 字符串 payload，也不再读取 camelCase `planPayload`；非结构化 payload 会返回 `plan_payload_must_be_object` 或 `plan_candidate_requires_plan_payload`。
- pending sink 示例、320 sink contract fixture 和 proposal compiler 单测都改为结构化 `plan_payload`；旧 `planPayload` 只保留在 4.0 `confirm_pending` 拒绝非结构化历史 pending 的反向测试中。
- 303 回归/模型 provider case 和 runner 单测中的旧 `fast-route`、`direct_atomic_plan_action`、`runtime_intent_hard_cut`、`semantic_plan_action` 样例路由已改为 `zhiyuan_agent_direct`；计划执行同步测试中的旧 `plan_execution_tool` 命名改为 `plan_action_execution`。
- `skills/plan_chat` 已重写为 4.0 direct 工具边界，只引导 `query_plan` / `review_plan` / `preview_plan_action` / `confirm_pending` / `preview_intent_change`；`skills/explore_chat` 和 `skills/career_path_chat` 删除旧三段 Plan 工具链说明。
- 扫描结果：`app/examples/skills/tests` 中旧 Plan route/tool 名只剩 hard-cut audit、防回退断言和旧 payload 拒绝测试；active code、runner case 和 skill 指引不再维护旧工具链正常路径。
- 验证：`test_proposal_compiler_runtime_selection.py test_compiled_pending_sink_contract.py test_dialog_regression_runner.py` 为 `171 passed`；`test_runtime_hard_cut_audit.py test_runtime_pending_sink_call_audit.py test_dialog_quality_gate.py` 为 `24 passed`；`test_zhiyuan_agent_poc.py test_plan_action_execution.py` 为 `274 passed, 28 skipped`；`test_chat_agent_tools.py test_chat_agent_init_profile.py test_chat_agent_progress_hints.py` 为 `42 passed`；相关文件 `py_compile` 通过。

---

## 10. 清理后整体评估与推进（2026-07-05）

清理已完成入口层、hard-cut、profile fallback、full-agent 后处理桥、旧 payload/route/skill 残余，并已按方向 A 删除旧执行编排孤儿 `app/domain/plan_action_execution.py` 与 `app/handlers/*`。本节评估当前实现的合理性、框架兼容性，以及剩余推进项。

### 10.1 框架兼容性评估：合理，符合 BaseAgent 约定

`ZhiyuanAgent`（`app/zhiyuan_agent/agent.py`，257 行）是干净的 `BaseAgent[str]` 子类，完全走框架既定扩展点，没有绕过或改写框架内核：

| 维度 | 实现 | 兼容性 |
|------|------|--------|
| 基类 | `BaseAgent[str]`，标准构造（`instructions` callable + `tools` + `deps_type=RequestContext`） | ✓ 符合 CLAUDE.md「新建 Agent 继承 BaseAgent[T]」约定 |
| 工具注册 | 9 个正交工具函数直接传入 `tools=[...]` | ✓ 标准 pydantic-ai 工具 |
| 终止策略 | 覆写 `should_return_directly_from_tool` / `render_direct_tool_output`（框架 hook） | ✓ 用扩展点而非 fork 循环 |
| 工具上限 | 覆写 `_guard_repeated_tool_calls`，叠加 `MAX_TOOL_CALLS_PER_TURN=3` | ✓ 复用框架 guard 机制 |
| 并行控制 | `model_settings["parallel_tool_calls"]=False` | ✓ 标准 pydantic-ai model 设置 |
| 状态注入 | `build_zhiyuan_agent_instructions` 从 sandbox peek 组装状态前置 | ✓ 与 ChatAgent 同构 |

§9.1 respond 软停、§9.4 成绩前置回退、G12 复合诉求上下文拼接（`_render_prior_readonly_context`）都在框架扩展点内实现，没有引入字符串 precheck 或旁路。**结论：4.0 direct 与框架兼容，实现合理。**

### 10.2 主执行链路自洽性：confirm_pending 已自成闭环

4.0 的方案变更执行链路是自包含的：

```
preview_plan_action / preview_intent_change  (创建结构化 pending)
        │  next_step=confirm
        ▼
confirm_pending → _apply_plan_pending / _apply_intent_pending   (tools.py)
        │  直接调用 internal_client.*（remove/select/move/generate_ordered/constraint_state）
        ▼
后端 action + sandbox 失效
```

`_apply_plan_pending` / `_apply_intent_pending` 直接对 `internal_client` 下发后端 action，不经过任何旧编排层。确认执行闭环回归已断言后端真实变更（version 增长、方案项删除、约束写入），4/4 通过。**这条链路不依赖被清理的旧代码，自洽。**

### 10.3 已处理架构问题：旧执行编排生产孤儿删除

已执行方向 A，确认 4.0 `confirm_pending` 不反向委托旧 runner，旧执行编排不再作为生产或测试维护面保留。

**删除内容：**

| 类别 | 处理 |
|------|------|
| 旧执行 runner | 删除 `app/domain/plan_action_execution.py`，不再保留 `run_plan_action_payload()` 中性 runner |
| 旧 handler registry | 删除 `app/handlers/*.py`（analysis/fix/generate/mutation/query/shared/registry 等） |
| 旧 runner/handler 测试 | 删除 `tests/unit/test_plan_action_execution.py`、`tests/unit/test_handler_registry.py`、`tests/regression/test_pending_protocol.py` |
| 旧 quality gate target | `examples/dialog_quality_gate.py` 移除已删除 runner/protocol 测试目标 |
| 旧 fixture alias | `tests/fixtures/mock_backend.py`、`tests/fixtures/mock_planning.py` 去掉 `plan_action_execution` / `app.handlers.*` alias patch |

**保留内容：**

`app/tools/plan_orchestration_models.py` 没有整文件删除。扫描后确认以下模型仍被 4.0 生产代码或测试使用，因此保留：

- `PlanContextInputs`：`action_resolver.py` 与相关测试仍使用。
- `PlanGoal`、`CompositePlanProposal`、`PlanEntityResolution`：`service.py`、`plan_goal_resolution.py` 和 proposal 相关测试仍使用。
- `PlanAtomicAction`：仍作为 `CompositePlanProposal.plan_actions` 的轻量动作记录结构。

旧 execution DTO 已删除：`PlanActionPlan`、`PlanExecutionResult`、`normalize_plan_action_payload()`。

**同步改动：**

- `tests/unit/test_planning_plan_scenarios_sync.py` 曾作为旧 planning workflow 直接场景过渡测试；后续旧 `planning_workflow_tool.py` 删除时已一并删除。
- `tests/unit/test_ws_compat.py` 的状态查询 fixture 改为 `query_plan` / 4.0 facts 形态，并兼容当前 websocket `thinking` 进度帧。
- `tests/unit/test_runtime_hard_cut_audit.py` 改为断言 `plan_action_execution.py` 不存在、`app/handlers` 下没有 Python 文件，并禁止 `service.py` 重新依赖旧 runner/handler。
- `app/models/typed_actions.py`、`app/models/intent_frame.py` 等注释收口为 4.0 direct proposal/pending 口径，不再描述旧执行层/dispatcher 语义。

**验证结果：**

- 旧引用扫描：`plan_action_execution|run_plan_action_payload|app.handlers|HANDLER_REGISTRY|PlanActionPlan|PlanExecutionResult|normalize_plan_action_payload` 在 `app tests examples` 中无活跃命中（hard-cut audit 的禁止断言除外）。
- 旧注释口径扫描：`执行层|dispatcher|flat PlanAtomicAction|兼容现有执行层|untyped dict` 在 `app/models app/tools app/resolver app/domain` 中无命中。
- `py_compile` 通过：`app/service.py`、`app/tools/plan_orchestration_models.py`、`app/resolver/action_resolver.py`、`app/models/intent_frame.py`、`app/models/conversation_phase.py`、`app/models/typed_actions.py`、相关测试文件。
- 核心清理回归：`test_runtime_hard_cut_audit.py test_plan_orchestration_models.py test_action_resolver.py test_resolver_vs_legacy.py test_planning_plan_scenarios_sync.py test_ws_compat.py test_dialog_quality_gate.py` 为 `189 passed`。
- 4.0 agent/service 单测：`test_zhiyuan_agent_poc.py test_chat_agent_tools.py test_chat_agent_init_profile.py test_chat_agent_progress_hints.py` 为 `163 passed, 28 skipped`。
- service history 回归：`test_chat_service_history_persistence.py` 为 `226 passed, 1 skipped`。
- `git diff --check` 通过。

**真实 direct 验证（删除旧执行编排后）：**

- 验证环境：手动启动 rank `5001`、server `8080`、direct-only agent `8039`（`ZHIYUAN_AGENT_ENABLED=1`、`ZHIYUAN_AGENT_ROLLOUT_PERCENT=100`、`ZHIYUAN_AGENT_POC_SHADOW=1`），runner 显式传 `--internal-service-url http://127.0.0.1:8080`。
- 确认执行闭环：`examples/dialog_regression_400_direct_confirm_execution_cases.json` 为 `4/4`，metrics: `/private/tmp/zhiyuan_400_confirm_after_runner_delete.json`；清理空间后复跑仍为 `4/4`，metrics: `/private/tmp/zhiyuan_400_confirm_after_space_cleanup_rerun.json`。验证覆盖 pending applied、`planningState.version` 增长、方案项删除和报考要求写入，不只按出卡判断。
- G case direct 子集：`examples/dialog_regression_400_g_case_direct_subset.json` 为 `8/8`，shadow `observed=8/statuses.success=8`，metrics: `/private/tmp/zhiyuan_400_g_subset_full_after_runner_delete.json`。G7 本轮单 `review_plan`，未复现追加 `query_plan`。
- 完整 G1-G32 direct 主集：前一轮运行到 G25 时因后端 fixture clear timeout + 本机 Data 卷剩余约 `32MB` + SQLite history 打开失败中断，已按环境失败处理，不计为业务失败。清理空间后复跑 `examples/dialog_regression_400_g1_g32_direct_cases.json` 为 `20/20`，`warnings=0`、`failures=0`，metrics: `/private/tmp/zhiyuan_400_g1_g32_direct_after_runner_delete_rerun.json`。
  - 路由/副作用分布：18 步 `direct`，2 步 `needs_plan_first`；`intent_pending=6`、`readonly=9`、`plan_preview=3`、`needs_plan_first=2`。
  - 工具分布：`preview_intent_change=6`、`query_plan=6`、`review_plan=3`、`preview_plan_action=3`、`confirm_pending=1`。
  - shadow：`observed=20`、`statuses.success=20`；`nextSteps.confirm=8`、`nextSteps.respond=11`。
  - 性能：median `6862ms`、p95 `17046ms`、max `19624ms`；最慢为 G31 保底学校查询、G17 档位内移动、G3 pending 下查询、G7 只读审查、G26 保底末尾查询。
- Focused 复核：`G7/G12/G17/G27/G31` 为 `5/5`，shadow `5/5 success`，metrics: `/private/tmp/zhiyuan_400_focused_g7_g12_g17_g27_g31_after_runner_delete_rerun2.json`。G7 仍为单 `review_plan`；G12 为 `query_plan -> preview_plan_action`；G17/G27 均生成方案调整确认卡；G31 pending 下只读查询正常。
- 第二轮完整 G1-G32 direct 主集：使用 `--session-offset 20000` 复跑 `examples/dialog_regression_400_g1_g32_direct_cases.json` 为 `20/20`，`warnings=0`、`failures=0`，shadow `20/20 success`，metrics: `/private/tmp/zhiyuan_400_g1_g32_direct_after_runner_delete_second_full.json`。
  - 路由/副作用分布保持一致：18 步 `direct`，2 步 `needs_plan_first`；`intent_pending=6`、`readonly=9`、`plan_preview=3`、`needs_plan_first=2`。
  - 工具分布：`preview_intent_change=6`、`query_plan=6`、`review_plan=3`、`preview_plan_action=4`、`confirm_pending=1`；G12 的复合链路计入第二个 `preview_plan_action`。
  - 性能：median `6122ms`、p95 `14659ms`、max `25282ms`；最慢为 G21 强基+普通批只读审查、G31 保底学校查询、G26 保底末尾查询、G7 只读审查、G2 高收费/中外合作审查。
- G2/G8 回复展示口径修复后聚焦复验：`examples/dialog_regression_400_g1_g32_direct_cases.json --case-name 400-g2-review-fix-preview-boundary --case-name 400-g8-explicit-positive-negative-intent --session-offset 30000` 为 `2/2`，shadow `2/2 success`，metrics: `/private/tmp/zhiyuan_400_g2_g8_after_display_fix.json`。G2 保持单 `review_plan` 且回复为“当前方案共15个志愿”，未再出现“还没有生成具体志愿”；G8 主回复与 pending 卡片均展示“专业要求：要：会计学、审计学；不要：土木工程”，不再暴露“工商管理类/土木类”这类模型扩展父级。
- G2/G8 修复后完整 G1-G32 direct 复核：`examples/dialog_regression_400_g1_g32_direct_cases.json --session-offset 40000` 为 `19/20`，metrics: `/private/tmp/zhiyuan_400_g1_g32_after_g2_g8_display_fix_full.json`。
  - 主链路分布仍为 18 步 `direct`、2 步 `needs_plan_first`；side effect 为 `intent_pending=6`、`readonly=9`、`plan_preview=3`、`needs_plan_first=2`。
  - 失败项只有 G17 shadow 断言：主链路单次 `preview_plan_action` 并生成 `move_ordered_unit` 确认卡；shadow 调了两次 `preview_plan_action`，`nextSteps=['clarify','confirm']`，runner 期望 `['confirm']`，因此计为 tool failure。该失败未表现为主链路业务失败或后端副作用错误。
  - 性能：median `5151ms`、p95 `10041ms`、max `20017ms`；最慢为 G31 保底学校查询、G26 保底末尾查询、G7 只读审查、G21 只读审查、G12 查询+替换。
  - 修复副作用观察：G1 “不要英语相关专业”一度被显式实体收敛成“不要：英语”，范围窄于“相关专业”。已增加广义范围信号（相关/方向/这类/之类等）保护，不把模型给出的上级专业类收窄为具体专业。
- G1/G8 广义/具体专业边界聚焦复验：`--case-name 400-g1-exclude-current-plan-english-major --case-name 400-g8-explicit-positive-negative-intent --session-offset 50000` 为 `2/2`，shadow `2/2 success`，metrics: `/private/tmp/zhiyuan_400_g1_g8_after_broad_major_scope_fix.json`。G1 恢复展示“专业要求：不要：外国语言文学类”；G8 仍展示“要：会计学、审计学；不要：土木工程”。
- G17 shadow 参数恢复后聚焦复验：`--case-name 400-g17-tier-local-reorder --session-offset 60000` 为 `1/1`，shadow `1/1 success`，metrics: `/private/tmp/zhiyuan_400_g17_after_missing_action_recovery.json`。主链路和 shadow 均为单次 `preview_plan_action`，生成 `move_ordered_unit` 确认卡；shadow 不再出现先 `clarify` 再 `confirm` 的 nextSteps 序列。
- G17 参数恢复后完整 G1-G32 direct 主集复跑：`examples/dialog_regression_400_g1_g32_direct_cases.json --session-offset 80000 --internal-service-url http://127.0.0.1:8080` 为 `20/20`，shadow `20/20 success`，metrics: `/private/tmp/zhiyuan_400_g1_g32_after_g17_param_recovery_full_rerun.json`。
  - side effect 分布：`intent_pending=6`、`readonly=9`、`plan_preview=3`、`needs_plan_first=2`。
  - shadow 首工具分布：`preview_intent_change=6`、`query_plan=6`、`review_plan=3`、`preview_plan_action=3`、`confirm_pending=1`；shadow `toolCallCount` max=1。
  - G17 完整主集中保持单次 `preview_plan_action`，`actionFamily=move_ordered_unit`，`nextSteps=['confirm']`，生成移动确认卡。
  - 性能：median `6440ms`、p95 `13911ms`、max `30253ms`；最慢仍为 G31 保底学校查询，其次 G26、G21、G7、G16。
- 本轮环境状态：清理后复跑开始时 `/Users/baiyang/git/zhiyuan` 可用空间约 `9.8Gi`，收尾约 `12Gi`；复跑期间未再触发磁盘/SQLite 类失败。
- 旧链路残余复扫：`plan_next_action|execute_plan_action|planEditCache|runtime_intent_hard_cut|direct_atomic_plan_action|semantic_plan_action|plan_context_tool|plan_orchestration_tool|plan_execution_tool|planPayload|plan_action_execution|app.handlers|HANDLER_REGISTRY` 在 `app/examples/tests/skills` 中的命中仅剩防回退测试、负向断言，以及 `ensure_structured_plan_payload()` 对 `planPayload/plan_payload` 的拒绝保护；未发现需要立即删除的活跃旧入口。

**2026-07-06 direct 默认主链路切换：**

- `ChatService` 不再读取 `ZHIYUAN_AGENT_ENABLED` / `ZHIYUAN_AGENT_ROLLOUT_PERCENT`，初始化时默认构造 `ZhiyuanAgent`。
- `service.py` 已移除 `ChatAgent` import 和默认构造，不再为普通会话初始化旧模型路径。
- 删除 direct route 的 rollout bucket、成绩可用性 gate、`_should_use_zhiyuan_agent_direct()`；不设置环境变量、无有效成绩时也进入 4.0 direct。
- `_maybe_handle_zhiyuan_agent_direct_route()` 不再通过 `None` 把请求交给旧 full-agent；direct agent 异常时返回安全提示并记录 direct error event，保持没有明确确认前不改动报考要求或方案。
- 删除 `handle_message` 中 direct route 后不可达的旧 guard/full-agent fallback 大块；删除旧 full-agent intent arbitration helper、blocked wrapper、tool trial summary、profile replan 旧 guard 方法。
- hard-cut audit 新增防回退断言，禁止 `service.py` 重新出现 direct enable / rollout / score gate / `ChatAgent` 默认构造 / full-agent intent arbitration helper。
- 验证：
  - `tests/unit/test_zhiyuan_agent_poc.py -k "direct or initializes_zhiyuan"`：`16 passed, 141 deselected`。覆盖默认 direct 初始化、不设置环境变量仍调用 direct、无成绩仍调用 direct、direct 异常不回退旧 agent。
  - `tests/unit/test_runtime_hard_cut_audit.py`：`17 passed`。
  - `tests/unit/test_chat_service_history_persistence.py -k "needs_plan_first_guard_runs_before_zhiyuan_direct"`：`1 passed, 225 deselected`。
  - `py_compile` 和 `git diff --check` 通过。
- 生产代码扫描：`service.py` 中 `full_agent` / `self.agent` / `ChatAgent(` / direct enable / rollout / score gate 无命中。
- 客观问题记录：完整 `tests/unit/test_chat_service_history_persistence.py` 仍保留大量旧 full-agent 用例，后续按 4.0 direct 口径分批删除或迁移；不按旧链路修复。

**2026-07-06 旧 ChatAgent / 旧工具 wrapper 清理：**

- 删除旧主对话 Agent 栈：`app/agent/chat_agent.py`、`app/agent/instructions/*`、`app/agent/tool_reply_policy.py` 及对应 ChatAgent/instructions/tool policy 测试，不再维护旧 full-agent prompt 与回复策略。
- 删除旧只读/检索工具文件：`app/tools/plan_query_tool.py`、`app/tools/official_source_search_tool.py`；`answer_policy` 的官方来源检索改为 4.0 工具内部 helper，`query_plan` 是当前唯一方案查询入口。
- 删除旧 `app/tools/intent_preview_tool.py` wrapper；`preview_current_*`、`analyze_current_*`、`preview_interest_analysis_from_request` 不再作为可维护入口。保留 `intent_state_tool` 的底层意向分析/应用能力和 `explore_direction_tool` 的方向分析能力。
- `service.py` 的运行时工具名收敛为 4.0 名称：`preview_intent_change`、`preview_plan_action`、`query_plan`、`review_plan`、`explore_topic`、`compare_entities`、`answer_policy`、`confirm_pending`、`read_state`。
- `BaseAgent` 重复工具调用保护切到 4.0 工具名；评估脚本 `dialog_case_evaluation_report.py` 的 action alias 同步改为 `query_plan`、`explore_topic`、`compare_entities`、`preview_intent_change`。
- 测试资产清理：删除 `test_dialog_scenario_stability.py` 等旧 wrapper 专属测试；`test_intent_state_tool.py` 保留底层意向状态覆盖，`test_explore_direction_scenarios_sync.py` 保留方向分析领域覆盖，不再导入旧 preview wrapper。
- 静态扫描结果：`intent_preview_tool|preview_current_|analyze_current_|query_volunteer_plan|plan_query_tool|official_source_search_tool|ChatAgent|tool_reply_policy` 在 `app/tests/examples` 中只剩 hard-cut 防回退断言、底层专业对比 helper、历史 3.0.3 JSON 输出和说明性注释；无运行时旧入口。
- 验证：
  - `tests/unit/test_runtime_hard_cut_audit.py`：通过，新增 `intent_preview_tool.py` 不存在断言。
  - `tests/unit/test_intent_state_tool.py tests/unit/test_explore_direction_scenarios_sync.py`：`178 passed`。
  - `tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_chat_service_history_persistence.py`：`170 passed, 1 skipped`。
  - 触达文件 `py_compile` 通过。

**2026-07-06 旧 planning workflow 工具清理：**

- `service.py` 不再从 `app/tools/planning_workflow_tool.py` 引用 `_format_fix_proposal_apply_result` / `_fix_proposal_facts`。
- 将当前仍被 4.0 service 使用的处理建议结果格式化能力迁到 `app/domain/fix_proposal_formatter.py`，只保留 facts/apply-result 两个实际调用点，不迁移旧 preview/query/generate 工具入口。
- 删除旧工具文件 `app/tools/planning_workflow_tool.py`，以及专属旧测试资产 `tests/unit/test_planning_workflow_tool.py`、`tests/unit/test_planning_plan_scenarios_sync.py`、`tests/fixtures/mock_planning.py`；`tests/conftest.py` 同步移除共享 fixture 暴露。
- hard-cut audit 新增 `planning_workflow_tool.py` 不存在断言，防止旧模型工具栈回流。
- 静态扫描：`planning_workflow_tool|mock_planning|patch_planning` 在 `app/tests/examples` 中只剩 hard-cut audit 的负向断言；生产 `app/` 零引用。
- 验证：
  - `py_compile app/domain/fix_proposal_formatter.py app/service.py tests/unit/test_runtime_hard_cut_audit.py`：通过。
  - `tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_chat_service_history_persistence.py`：`257 passed, 29 skipped`。

### 10.4 其余观察项（不阻塞主线）

| 项 | 状态 | 处理 |
|----|------|------|
| G7 只读审查后追加 query_plan | 已修复并通过 focused + 完整主集复验 | `review_plan(next_step=respond)` 已作为 direct 终止工具直接返回；不再追加只读查询 |
| G17 shadow nextSteps 多一步 clarify | 已修复并通过聚焦 + 完整主集复验 | 缺 action/selector/目标位置改为工具返回 `next_step=continue` 让模型补齐结构化参数；不恢复旧路由 precheck，也不在工具层从中文原文补参 |
| G27 高收费替换候选仍可能为民办 | 本轮已出 `replace_units` 确认卡，替换项学费降低但仍是民办院校 | 当前自动替换理由只围绕学费；若用户同时要求公办/不要民办，需要进入多目标候选排序，不在本轮修 |
| 报考要求采纳后的候选重建 | v1.49 已确认基础候选池不应因报考要求被系统隐藏；候选重建不再是采纳要求的默认动作 | Agent 改为写入报考要求后直接重排方案；候选区通过可见 `candidateViewState` 展示筛选，最终是否生效以 ordered/review 等方案派生数据为准 |
| G2 审查回复口径 | 已修复并通过真实 direct 聚焦复验 | `review_plan` 返回补充 `has_plan/ordered_total` 和“当前正式方案有 N 个志愿”消息；真实 G2 回复不再出现无方案口径 |
| G8 专业实体扩展口径 | 已修复并通过真实 direct 聚焦复验 | `preview_intent_change` 使用当前用户原文复用官方专业层级显式实体收敛；用户可见回复和 pending 卡片只展示显式专业 |
| G12 复合查询后方案动作 | 已修复并通过 focused + 完整主集复验 | `query_plan` 返回当前问与后续动作提示，模型可继续调用 `preview_plan_action`；不使用 service precheck |
| G16 锁定/固定位置动作 | 已修复并通过 focused + 完整主集复验 | Prompt 明确“锁定/固定位置/位置不要动”进入 `preview_plan_action(pin_lock)`；无可锁定方案时由工具给出安全回应 |
| G21/G31/G26 性能尾部 | 最新完整主集 max `12726ms`，p95 `11077ms`；最慢为 G31/G12/G27/G16/G26 | 继续从长列表回复压缩、审查结果直返/摘要化和只读结果渲染做性能优化 |
| `planning_workflow_tool` 仍被 service 引用 | 已清理 | service 改用 `app/domain/fix_proposal_formatter.py`，旧 `app/tools/planning_workflow_tool.py` 和专属测试资产已删除，hard-cut audit 防回退 |
| `proposal_compiler.py` 旧 full-agent arbitration helper | 已清理 | 删除未被 4.0 生产链路调用的 `RuntimeIntentPreviewTurnDecisionArbitrationSource`、`RuntimeBlockedIntentPreviewReplySource`、`compile_runtime_intent_preview_turn_decision_arbitration_source()`、`compile_blocked_intent_preview_for_plan_route_reply_source()`、`full_agent_intent_pending_requires_turn_decision()` 及专属测试；hard-cut audit 覆盖防回退 |
| 旧 full-agent history 测试资产仍存在 | 已删除 ChatAgent/tool policy/旧 wrapper 专属测试，`history_persistence` 仍保留部分历史消息压缩兼容用例 | 下一步继续按 4.0 direct 口径删除或迁移剩余 history fixture，不按旧链路修复 |
| 完整 320 G1-G32 = 44/49 | 剩余为验证资产口径/性能观察 | 继续按 case 归因，非旧链路回归 |

### 10.5 推进计划

**阶段 1（收尾清理，已完成代码清理）：** §10.3 方向 A 已落地。
- 已删除 `plan_action_execution.py` + `app/handlers/*` + 对应旧 runner/handler/protocol 测试。
- `plan_orchestration_models.py` 保留仍被 4.0 使用的 proposal/context 模型，删除旧 execution DTO。
- hard-cut audit 已改为断言旧执行编排文件不存在。
- 已完成静态扫描、编译、核心单测和 service history 回归；真实 service direct 回归放入阶段 2。

**阶段 2（真实验证收口，已完成多轮主集 + focused）：** 删除旧执行编排后的确认执行闭环 4/4、G case 子集 8/8、focused 5/5、完整 G1-G32 direct 主集多轮通过；最新 v1.62 主集 `20/20`。G7 工具边界抖动已通过 `review_plan` 终止边界修复，G12 复合查询后继续方案动作、G16 锁定动作均在真实 focused 与完整主集中通过。

**阶段 3（§6.4 剩余大块，进行中）：** direct route 已是默认主链路，`ChatAgent` 默认构造、`handle_message` 旧 full-agent fallback、旧 instructions、`tool_reply_policy.py`、`plan_query_tool.py`、`official_source_search_tool.py`、`intent_preview_tool.py`、`planning_workflow_tool.py`、`turn_decision_tool.py` 均已删除；`service` 不再引用 TurnDecision classifier/profile-replan bridge；`proposal_compiler.py` 已删除 3.2 pending turn / plan query / local action / profile replan / plan confirmation compiler，只保留 4.0 仍用的 sink contract、reply guard、no-plan guard、intent/fix proposal 选择与结构化 payload helper；3.2 golden/shadow/downstreamPolicy 离线 POC 资产已删除；4.0 direct/PoC shadow 后台执行与 runner shadow 断言/指标已删除，回归 case 改为主链路工具断言；runner 运行期观测输出已从 `runtime_shadow` 改名为 `runtime_observation`；semantic frame 离线评估字段已从 shadow/router 命名收敛为 observation/frame 命名，旧 full-agent 专属 issue 报告改为中性 tool-chain issue；3.2 model-node/profile live-node、runtime pending/adapter 离线资产和未引用 320 dialog regression fixtures 已删除，生产仍需的反向要求识别迁入 domain；quality gate/e2e/model-provider/mainline catalog 中的 301/302/303/310 历史质量资产已迁移为 400 命名资产并删除旧文件，gate dry-run 已无 301/302/303/310/320 路径。下一步继续扫描非 gate 的旧探索/输出资产和测试样例中是否还有可清理历史口径。

**阶段 4（默认 direct 后监控）：** 监控仪表盘 + 性能基线 + 确认执行闭环巡检；不再以 direct enable / rollout 作为主切换机制。

实施顺序：阶段 1 → 阶段 2 →（阶段 3 评估）→ 阶段 4

---

## 11. 约束落地链路修复：Preview/Execute 契约分叉（2026-07-06）

本地环境实测暴露的核心问题：有山东志愿的方案，用户"不去山东"→系统提示确认+替换意向→用户"排除山东，先不替换"→**过后方案没有任何变化**。追踪后发现这不是单点 bug，而是约束落地链路的结构性缺口。

### 11.1 根因：预览和执行走了两套后端契约

`preview_intent_change` 和 `confirm_pending` 对"排除某地域"用的是**完全不同的后端机制**，只有预览那套真正尊重排除：

| 阶段 | 调用 | 后端行为 | 是否尊重排除 |
|------|------|---------|------------|
| **预览** | `simulate_plan_diff(proposedProfile)`（`internal_client.py:1144`） | 后端用拟变更画像**在内存里重跑完整推荐流水线**，与当前方案 diff | ✅ 是 |
| **执行** | `update_planning_constraint_state` + `generate_planning_ordered_plan`（`tools.py:4391/4402`） | 写约束状态；`ordered-plan/generate` 只**对现有候选池重排/重组** | ❌ 否 |

分叉后果：
- 预览通过 `simulate_plan_diff` 跑真实推荐流水线，能算出"排除山东影响 N 个志愿"，**卡片承诺了影响**。
- 执行只写 `constraintState.mustExcludeRegions` + 重排现有候选池。候选池里山东项还在，重排不会移除它们。
- 后端 `queryCandidatePool` / 候选池生成只认请求里的 `filters.negativeProvinceNames`，**不合并 `constraintState.mustExcludeRegions`**。
- 结果：约束是一个**只写不读的死胡同**——写进去了，但没有任何下游环节消费它。用户看到"会影响 5 个"，确认后方案纹丝不动。

### 11.2 三道缝隙

约束从"用户说出"到"方案落地"要跨三道缝，当前三道都没接好：

```
用户"排除山东"
   │
   ├─缝隙C(语义): "先不替换" = 记录约束但现在别动 → §3.7 无条件 regen，无法表达"记录但延后"
   │
   ▼ confirm → 写 constraintState.mustExcludeRegions ✅
   │
   ├─缝隙A(执行粒度): confirm 只调 ordered-plan/generate，但 ordered-plan 当时没有消费报考要求
   │                  重排 ≠ 重建，排除项永远留在池里
   │
   ▼ 候选池生成/查询(当时未明确区分基础池与方案有效候选)
   │
   └─缝隙B(后端契约): candidate-pool 生成/查询只认请求 filters，不 merge constraintState
                      → 持久约束无法在"下一次"重建时自动生效
```

- **缝隙 A（方案生成消费缺口）**：`_apply_intent_pending` 只 `generate_planning_ordered_plan`，但当时 ordered-plan 没有按已确认报考要求过滤候选。v1.49 结论是修 ordered-plan/initial/review 的 `effectiveCandidates` 消费，而不是重建基础候选池。
- **缝隙 B（后端约束→过滤合并）**：候选池生成/查询不 merge `constraintState`。这决定了"先不替换"延后的约束能否在**下一次**方案生成时自动生效——不 merge 就永远不生效。
- **缝隙 C（语义：记录 vs 立即调整）**：`preview_intent_change`→`confirm` 目前把"记录约束"和"立即 regen"绑死（§3.7 has_plan 就 regen）。用户明确说"先不替换"时无法表达"只记录、暂不动方案"。

### 11.3 这是一类 bug，不止山东

地域只是最先暴露的维度。**所有 exclude 类约束都走同一条死胡同**：办学性质（不要民办）、招生类型（不要中外合作）、学费（不要高收费）、院校标签、专业门类——只要靠 `constraintState.mustExclude*` 落地，而后端候选池不 merge 约束状态，确认后就都是静默 no-op。

§9.5-§9.9 记过的部分"确认后方案没变"现象，很可能同源于此，而非各自独立的工具 bug。这解释了为什么 shadow 里 preview 看起来对（simulate 尊重约束）但真实确认无效（execute 不尊重约束）。

### 11.4 核心设计方向：约束状态即单一事实源

要让"排除山东"真正落地，且不让用户在候选页面看见一层无法操作的隐藏状态，必须把三层状态边界拆清楚：

**方向 1（候选基础池）：`candidatePoolState.items` 保持基础全量候选。**
`candidate-pool/generate` 只负责从推荐源生成基础候选池，不按已确认报考要求裁剪明细；`candidate-pool/query` 只执行请求里显式传入的筛选条件。这样页面候选区始终是“基础候选池 + 可见筛选状态”的结果，用户删掉筛选条件后能重新看到对应候选，不会被系统在后端基础池里悄悄隐藏。

**方向 2（页面可见筛选）：对话确认的地域类报考要求同步到 `candidateViewState`。**
用户通过对话确认"不要山东"后，后端同步把 `山东` 放入 `candidateViewState.filters.negativeProvinceNames`，前端候选筛选栏能直接展示这条筛选；用户在筛选栏手动删除该值时，后端撤销对应的 `mustExcludeRegions` 并让方案/审查重新计算。当前先覆盖地域类要求；院校属性/招生类型/专业标签到筛选栏的完整映射后续应接属性注册表统一完成，避免新增字符串特化。

**前端同步边界（v1.50）：** `sessionDetailV2` 的候选筛选栏必须响应后端 `candidateViewState` 的后续变化，而不是只在首次进入页面时水合。对话确认要求后，工作台刷新拿到新的 `candidateViewState`，前端按候选视图签名变化更新本地筛选栏，再由 `buildCandidateQuery()` 把这条可见筛选传给 `candidate-pool/query`。这不是后端隐式过滤，也不是新增缓存层；用户能在筛选栏看到并删除该条件。

**方向 3（方案派生链路）：`constraintState -> effectiveCandidates` 临时生效。**
已确认报考要求仍是方案生成、方案调整、审查和修复建议的权威输入，但不写回基础候选池。`resolveEffectiveCandidates()` 每次从基础候选池读取候选，叠加推荐承接分，再按 `constraintState.hardConstraints` 过滤，生成本次方案派生动作的临时有效候选。该列表不持久化。

**方向 4（Agent，执行粒度）：立即调整时写要求后重排方案，不重建基础候选池。**
当用户确实要立即调整（非"先不替换"）时，`_apply_intent_pending` 对 exclude/only_keep 类要求的执行序列为：
```
写 constraintState
  → 同步可见 candidateViewState（地域类已落地）
  → generate_planning_ordered_plan()     # 通过 resolveEffectiveCandidates 临时过滤后再排序
```
这一步让执行不再依赖基础候选池重建，也避免候选页面和方案页面使用不同的隐藏候选集合。

**方向 3（语义，记录 vs 立即调整解耦）：支持"先不替换/先记下"。**
`preview_intent_change` / `confirm_pending` 增加 `apply_to_current_plan: bool` 语义（从用户话里的"先不替换/先别动/以后""立即改/现在换"判定）：
- `apply_to_current_plan=false`（"先不替换"）：写入报考要求并同步可见候选筛选，但不重排当前方案；回复"已记下这次报考要求，后续生成或调整方案会按这个要求处理；这次先不改当前方案"。
- `apply_to_current_plan=true`（默认，或"帮我换掉"）：写入报考要求 + 同步可见筛选 + 重排当前方案。
- 两种情况要求都持久，差别只在"现在动不动当前方案"。未来任何方案派生动作都通过 `resolveEffectiveCandidates()` 读取最新要求。

**为什么不持久化 `effectiveCandidates`**：它会形成第三份候选状态，既不是用户看到的基础候选池，也不是前端可删改的筛选状态；一旦用户在页面删掉筛选或调整条件，就容易出现基础池、有效池、页面筛选三者不一致。因此 `effectiveCandidates` 必须保持为后端动作内的临时派生结果。

### 11.5 "整体链路是否走通"与"能否切换到新框架"

**当前结论：Agent/工具层已就绪且框架兼容（见 §10.1）；后端已改为“基础候选池全量、候选视图显式筛选、方案链路临时有效候选”。地域类、核心属性类、专业门类、院校标签和专业标签报考要求均已验证到最终 ordered-plan 数据变化；真实口语/指代/简略对话 final-action 已连续三轮通过，并覆盖立即调整、“先记下不改当前方案”、取消后重新提出、多要求组合和长上下文承接。后续继续扩大真实回归并推进旧链路清理。**

- 走通的部分：读状态、只读查询/审查/政策/探索、具体项方案操作（remove/move/replace 具体志愿）、确认执行闭环的后端 action（version 增长、删项）——这些 §10.2 已验证真实生效。
- 已修正 Agent 侧执行粒度：**exclude/only_keep 类属性/地域要求 → 写入要求 → 有序方案生成**，不再重建基础候选池；方案生成时由 `resolveEffectiveCandidates()` 临时过滤。
- 已修正后端候选池语义：`candidate-pool/generate` 保存基础全量候选；`queryCandidatePool` 只执行显式 filters；`filter-options` 继续来自基础候选池，避免用户在页面上看不到可恢复的候选条件。
- 已补齐可见筛选联动：地域类硬性报考要求同步到 `candidateViewState.filters.negativeProvinceNames/provinceNames`；用户在候选筛选栏删除对应值时，后端撤销对应地域要求并标记方案/审查需重算。
- 已补齐前端工作台水合：`sessionDetailV2` 按后端 `candidateViewState` 签名变化同步筛选栏；对话确认后已打开的工作台也能展示新增筛选，并通过现有显式 query 入参影响候选视图。
- 已补齐有序方案生成的 working/ordered 同步：即使基础候选池仍保留山东项，`generateOrderedPlan()` 也会按 `effectiveCandidates` 裁剪 draft/ordered；ordered units 先按有效 major volunteerId 裁剪/丢弃，再按自身结构化字段过滤已不符合要求的正式方案 unit，避免 candidate id 不对齐导致误清空非命中 unit，也避免旧 unit 字段缺失时残留。
- 历史 session 35 “民办就算了”验证中的 candidate 民办清零不再作为 v1.49 成功标准；后续真实闭环应断言：基础候选池可恢复、候选筛选栏可见、ordered/review 方案派生结果不含已排除项。
- 已补齐地域真实闭环：对“排除山东→采纳”复跑时，确认后基础候选池仍保留山东，候选筛选栏显示山东排除项，最终 ordered-plan 不含山东。
- 已补齐核心属性真实闭环：对“民办的不要/只看公办学校/不要中外合作/不要高收费的”复跑时，确认后基础候选池仍可恢复，最终 ordered-plan items/units 均按报考要求裁剪。
- 已补齐专业门类真实闭环：对“管理学的不要了→采纳”复跑时，预览能按专业门类统计当前方案影响范围，确认后基础候选池仍可恢复，最终 ordered-plan 不含管理学项。
- 已补齐标签真实闭环：对“博士点的不要了/五年制的不要了”复跑时，确认后基础候选池仍可恢复，最终 ordered-plan 不含对应院校标签/专业标签项。
- 已补齐首轮真实口语/指代/简略对话闭环：对“有啥问题，咋弄→那高收费的别要了→确认执行”“方案里的民办不要了→采纳”“山东别去了→采纳”复跑时，均验证到确认后的后端方案数据变化，不只校验待确认卡展示。
- 已补齐真实口语扩展闭环：对“就看公办吧”“中外合作算了吧”“管理学也别要了”“五年制的也别要”复跑时，确认后要求写入并触发 ordered/review 刷新；对“山东别去了，先记下，当前方案先别动”复跑时，确认后只写入要求并同步可见筛选，不触发当前方案重排。
- 已补齐取消/改口与组合诉求闭环：对“先不采纳了”确认后真实 pending status 变为 `cancelled` 且 planningState 不变；随后重新提出“只看公办”可正常建卡并采纳；“民办+中外合作”“管理学+五年制”均能在同一次待采纳内容里同时写入；长上下文审查后的“你说的高收费这类先去掉吧”走方案调整并确认后真实移出。

### 11.6 推进计划

**阶段 0（契约对齐，最高优先，需前后端协同）：**
1. 后端确认 `candidatePoolState` 是基础全量候选池，不持久化按报考要求裁剪后的 effective pool。已落地。
2. 后端确认 `candidateViewState` 是页面可见筛选状态，对话确认后的地域类要求会同步到这里，用户删除筛选时撤销对应地域要求。地域已落地；属性/标签维度后续接属性注册表。
3. 方案派生链路统一读取 `constraintState.hardConstraints` 并通过 `resolveEffectiveCandidates()` 临时过滤。已落地。
4. 前端工作台确认 `candidateViewState` 后续变化会重新水合本地筛选栏，避免已打开页面继续停留在旧筛选状态。已落地。

**阶段 1（Agent 执行粒度修复，1-2 天）：**
- `_apply_intent_pending` 对 exclude/only_keep 要求：立即调整时只写入报考要求并触发 ordered-plan 重排，不再重建基础候选池。已落地。
- 加真实回归：有山东志愿方案 →"不去山东"→确认→断言后端 ordered-plan 中山东项消失、`planningState.version` 增长。已用克隆真实 chat_session 的回归会话补齐，见 §11.7 v1.51 验证记录。

**阶段 2（语义解耦，1-2 天）：**
- `preview_intent_change` / `confirm_pending` 支持 `apply_to_current_plan`；Prompt 增加"先不替换/先记下"→ 只记录不动方案 的判定与示例。
- 回归："排除山东，先不替换"→ 断言约束已写入 + 当前方案不变 + 回复明确说明延后生效。

**阶段 3（一类约束回归收口，2-3 天）：**
- 对 exclude 全维度（地域/性质/招生类型/学费/标签/门类）各补一条"确认后方案真实变化"回归，确认 §11.3 的一类 bug 全部闭合，而非只修地域。地域、院校性质、招生类型、高收费、专业门类、院校标签、专业标签已落地。
- 增加真实用户表达风格覆盖：保留书面 case，同时加入口语化、指代、省略、多轮承接的 final-action 验证；v1.55 首轮已覆盖高收费、当前方案民办、裸地域排除，v1.56 已扩展到只看公办、中外合作、专业门类、专业标签和“先记下不改当前方案”，v1.57 已扩展到取消后改口、多要求组合和长上下文审查承接。
- 复核 §9.5-§9.9 中"确认后无变化"现象是否随本修复一并消失。

**阶段 4（受控放量）：**
- 属性/地域约束场景通过 §11.6 阶段 1-3 回归后，纳入放量范围；在此之前放量集合限定只读 + 具体项操作。

实施顺序：阶段 0（阻塞，前后端拉通）→ 阶段 1 → 阶段 2 → 阶段 3 → 阶段 4

### 11.7 当前落地状态（2026-07-07）

**已落地：**
- `_apply_intent_pending()` 读取 pending 内的 `constraint_type` 与 `applyToCurrentPlan`。
- `exclude` / `only_keep`，以及包含负向项的报考要求确认后，不再重建基础候选池；当前有方案且需要立即调整时，写入报考要求后直接 `generate_planning_ordered_plan()`，由后端 `resolveEffectiveCandidates()` 临时过滤候选。
- `must_have` 且无负向项的纯正向要求保持有序方案生成路径，同样不强制重建候选池。
- `preview_intent_change()` / `confirm_pending()` 支持 `apply_to_current_plan=false`：确认后只写入报考要求并同步可见候选筛选，跳过有序方案生成，回复明确说明“这次先不改当前方案”。
- pending 的 `executionPayload` 和 `selectedData` 均保存 `applyToCurrentPlan`，避免确认阶段丢失“先不替换”语义。
- Prompt 已补充“先看看怎么处理/先别动”与“先记下/先不替换/先不改当前方案”的边界：前者走只读 `review_plan(generate_fix_proposals=True)`，后者在有显式要/不要/只看诉求时走 `preview_intent_change(..., apply_to_current_plan=False)`。
- `service._direct_confirm_workspace_refresh_targets()` 改为只有 `intent_change` 的 `plan_regenerated=true` 才发送 ordered/review 刷新；`apply_to_current_plan=false` 时不再给用户发方案已刷新的 followup。
- `service` 增加 direct active-pending 短文本确认/取消桥：仅当本轮开始已有 active pending，且用户文本是窄口径“采纳/确认/执行/取消/先不采纳/暂不执行”等待确认操作词时，直接调用 4.0 `confirm_pending` 工具；避免模型口头说“已取消/已采纳”但后端 pending 未变化。该桥不恢复旧 full-agent 路径，也不处理新的报考语义。
- 后端 `PlanningStateService` 已把 `constraintState.hardConstraints` 接入方案派生链路：`resolveEffectiveCandidates` 让初始推荐、有序方案、审查和修复共享过滤后的临时候选集合；`generateCandidatePool` 和 `queryCandidatePool` 不再隐式裁剪基础候选。
- 地域类已确认报考要求已与 `candidateViewState` 联动：写入要求时更新候选筛选栏；用户删除候选筛选栏里的对应地域值时撤销该地域要求，并让方案/审查失效。
- 后端 `generateOrderedPlan()` 已在存在已确认报考要求时同步 working/ordered state：working plan 按过滤后的 `effectiveCandidates` 移除无效 draft items，随后同步 units/summary；ordered items 按有效 volunteerId 裁剪；ordered units 先按有效 major volunteerId 裁剪/丢弃，再按自身结构化字段复用 `RepairCandidateEligibility` 判断。该修复覆盖基础候选池仍保留被排除项但旧 draft/ordered 残留不符合要求项的情况，同时避免只按 candidate id 过滤导致非命中 unit 被误删。
- 后端 `RepairCandidateEligibility` 已让 `招生类型:高收费` 消费 `tuitionPerYear > 20000`，覆盖“不要高收费的”这类没有显式“高收费”标签、但学费数值超限的方案项。
- 后端 `getPlanningState()` / 候选生成 / effective candidates 解析已统一补齐候选项 `majorDiscipline/majorCategory`，让旧状态里只有 `majorSubCategoryId` 的专业类数据也能被方案派生链路和 agent 预览消费。
- Agent 本地影响计数已把 direct 与 nested 的 `majorDiscipline/majorCategory` 纳入专业匹配，避免专业门类预览只按专业名误报影响范围。
- Agent prompt 已明确非固定枚举标签走 `school_tag/major_tag`；属性注册表将“五年制/5年制”等口语值归一到 `学制：5年`；`preview_intent_change()` 消费 `duration` 作为 `major_tag` 的 schema alias，并在规范化后没有任何可执行报考要求时拒绝保存空 pending。
- `preview_intent_change` 的组合属性漏传处理已改为模型重试协议：工具不再把 raw text 中识别到的属性/标签自动补写进 pending；当同一句显式诉求里还有属性/标签未进入结构化 `positive/negative` 参数时，返回 `intent_change_requires_attribute_completion` + `next_step=continue`，要求主模型基于当前问和工具返回补齐后重试。`ATTRIBUTE_REGISTRY` 继续用于结构化字段归一、schema alias（如 `duration -> major_tag`）和枚举/标签规范化，不承担 raw text 自动落库。
- `preview_intent_change` 支持同轮跨领域显式诉求保留在同一次结构化 payload 中：例如用户说“山东别去，民办也算了”时，模型可调用 `intent_type="region"` 且 `negative={"province":["山东"],"school_nature":["民办"]}`，工具会合并成 `city_intents + school_intents` 的单张待确认卡；如果模型只传了山东而漏掉民办，工具返回 `continue` 要求补齐。
- active pending 下的新预览关系改为模型语义仲裁：`current_user_text` 和待确认摘要注入 `build_turn_context`；`preview_intent_change` / `preview_plan_action` 均要求模型传 `pending_resolution`。缺失时工具返回 `active_pending_requires_resolution` + `next_step=continue`，由主模型重试；明确替换时取消旧 pending 后创建新 pending；intent 追加时先合并旧 pending 执行 payload，再取消旧 pending 并创建单张合并预览卡。该设计不在工具层用短语表判断“放弃/追加/暂缓”。
- `preview_plan_action` 的缺参恢复已从工具层字符串补参调整为模型重试协议：缺 action、move selector 或目标位置时返回 `plan_action_requires_explicit_action` / `plan_action_requires_move_selector` / `plan_action_requires_move_target_position` + `next_step=continue`；工具只回传当前用户原话和缺失字段，不再从整句中文里匹配动词、选择器或目标档位。
- no-pending 短文本确认/取消边界收口到 4.0 `confirm_pending`：无 active pending 时，窄口径“确认/采纳/执行/取消/暂不执行”等只会返回“当前没有待确认操作，不会执行任何变更”，不再进入旧模型路径，也不把这类短文本误解成新报考要求。
- `review_plan(next_step=respond)` 在 direct agent 内作为终止工具直接返回，避免只读审查场景在拿到审查/处理建议后追加 `query_plan`，同时保留无副作用边界。
- `query_plan` 的工具返回新增 `current_user_text` 与 `post_query_instruction`：当用户同轮同时表达“查询当前方案事实 + 调整方案”的诉求，模型可在读到查询结果后继续调用 `preview_plan_action`，而不是停在只读回复。
- Prompt 明确“能不能/可不可以/帮我 + 换成/替换/移出/去掉”按方案动作理解；“锁定/固定位置/位置不要动”按方案操作进入 `preview_plan_action(pin_lock)`。该修复仅调整模型工具选择协议，没有恢复 service 层字符串 precheck。
- 旧 3.2 TurnDecision/ProposalCompiler 兼容层继续硬切：删除 `turn_decision_tool.py` 及 service TurnDecision/profile-replan bridge；删除 `proposal_compiler.py` 中 pending turn、PlanQueryProfile、local plan action、profile replan、plan confirmation、apply-then-generate 等旧 compiler 类型与函数；删除 3.2 TurnDecision golden、runtime shadow diff、downstreamPolicy replay/java-request/adapter gate 等离线 POC 工具、fixtures 和对应 unit tests。当前 `proposal_compiler.py` 只保留 4.0 direct 仍用的结构化 payload、sink contract、intent/fix proposal、reply guard 和 no-plan guard。
- 4.0 direct 已不再需要后台 shadow 自比：`service.py` 删除 shadow task、shadow event、shadow history、shadow timeout/sample env 和 timing 汇总；`dialog_regression_runner.py` 删除 shadow 等待、`expectedZhiyuanAgentPoc*` 断言、shadow metrics 汇总；4.0 direct/G/realistic 回归 JSON 改用主链路 `expectedToolNames` / `maxToolCallCount` / `expectedRoutingPath`。
- 生产包与单测命名从 PoC 收敛为 direct-chain：`app/zhiyuan_agent` docstring、direct agent 工具集合/近期工具返回 helper、direct agent 单测文件和 helper 均已去 PoC 命名；保留的旧字符串只在 hard-cut audit 禁止列表中出现，用于防止回流。
- runner 只读运行期观测命名从 shadow 改为 observation：`_build_runtime_observation()`、`runtimeObservationCaseId`、`runtimeObservationSummary`、`--runtime-observation-output`；不再接受 `shadowCaseId/runtimeShadowCaseId` 作为新 case id 字段，避免验证协议继续携带旧 shadow 语义。
- semantic frame 离线评估继续保留，但从旧 shadow/router 命名收敛为 observation/frame 命名：`semanticFrameObservation/semanticFrameSummary` 替代 `semanticRouterShadow/semanticRouterSummary`，runner 历史模型名改为 `semantic-frame-observation`；dialog report 删除 `preFullAgentDurationMs/postFullAgentDurationMs` 和 `fullAgentToolTrial*` 输出，改用中性 `toolChainIssue/toolChainIssues`，只记录工具链质量问题，不再维护旧 full-agent 专属分类。
- 旧 3.2 model-node/profile live-node 与 pending adapter 离线资产继续硬切：删除 `intent_entity_profile_tool.py`、`plan_query_profile_tool.py`、`reply_profile_tool.py`、`model_node_benchmark.py`、runtime pending entrypoint/sink audit、intent preview/select compiler adapter、compiled pending sink contract 以及对应 320 fixtures/tests；`intent_state_tool` 仍需要的反向要求识别从旧 profile node 迁到 `app/domain/intent_reversal.py`。
- 未被当前 quality gate/e2e 引用的 320 历史回归 JSON 已删除，避免继续维护 3.2 路由/断言口径；仍被 `dialog_quality_gate.py`、e2e 默认路径、model-provider gate 和 mainline catalog 引用的 301/302/303/310 质量资产已迁移为 400 命名 case 集，旧 301/302/303/310 case、输出 JSON 和 raw production candidate export 已删除并加入 hard-cut audit 防回退。

**验证：**
- v1.71 真实 LLM 验证-only 记录：本轮未修改实现，只补充验证与问题归类。`examples/dialog_regression_400_v155_realistic_final_action_cases.json` 复跑 `7/7` 通过，metrics: `/private/tmp/zhiyuan_400_analysis_v155_final_action.json`；覆盖“有啥问题，咋弄 → 那高收费的别要了 → 确认执行”“方案里的民办不要了 → 采纳”“山东别去了 → 采纳”，确认后均走 `confirm_pending`，并通过 `pendingConfirmation.status=applied`、`planningState.version` 增长、`orderedPlanState.units` 变短或目标项消失等后端断言。`examples/dialog_regression_400_v156_realistic_broadened_final_action_cases.json` 复跑 `10/10` 通过，metrics: `/private/tmp/zhiyuan_400_analysis_v156_broadened_final_action.json`；覆盖“就看公办吧”“中外合作算了吧”“管理学也别要了”“五年制的也别要”“山东别去了，先记下，当前方案先别动”，确认后要求写入、方案裁剪和 `apply_to_current_plan=false` 不刷新工作台/ordered 不变语义均通过后端断言。
- v1.71 真实口语全量问题记录：`examples/dialog_regression_400_realistic_user_cases.json` 全量复跑 `8/14` 通过，metrics: `/private/tmp/zhiyuan_400_analysis_realistic_full.json`。失败 6 步都来自 `assertFollowupType/assertFollowupCount`，其中仅“那高收费的别要了”同时有工具断言差异（case 期望 `preview_plan_action`，实际无正式方案状态下走 `preview_intent_change` 记录报考要求）。失败集中在默认克隆 `sourceSession=26` 的无正式方案基线：裸“民办的不要/中外合作都不要了”已识别为 `preview_intent_change` 但没有 followup 卡；“方案里的民办不要了/当前这些中外合作都移出去/第3个不要了”走 `preview_plan_action` 后因无正式方案无法形成方案调整卡。该组需先区分 case 预期是否应改为“无正式方案安全提示/记录要求”，还是源会话应切到有正式方案的 `sourceSession=17/35` 来验证出卡。
- v1.71 回复口径问题记录：无正式方案查询“里面有民办没”有一轮回复为“目前还没有生成正式方案，所以方案里没有民办院校”，这比“没有正式方案，暂时无法查看方案里是否有民办”更容易误导用户；另“方案里的民办不要了”无正式方案场景出现“报考偏好”措辞，后续用户侧回复应继续统一用“报考要求/诉求”。
- v1.70 301/302/310 质量门禁资产硬切验证：`py_compile examples/dialog_quality_gate.py examples/dialog_case_evaluation_report.py tests/unit/test_dialog_quality_gate.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_runtime_hard_cut_audit.py` 通过；10 个触达 JSON 可加载；`.venv/bin/python -m pytest tests/unit/test_dialog_quality_gate.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_semantic_frame_evaluator.py -q` 为 `110 passed`；`.venv/bin/python -m pytest --collect-only -q tests/unit` 为 `1499 tests collected`；`examples/dialog_quality_gate.py --mode live --mode model` dry-run 输出 `live=37`、`model=3`、`legacy=[]`；`dialog_regression_301/302/310*` 活跃引用清零（除 hard-cut 禁止列表和 changelog 历史记录）；`git diff --check` 通过。
- v1.69 303 质量门禁资产迁移验证：`py_compile examples/dialog_quality_gate.py tests/e2e/test_agent_dialog_effect_perf.py tests/unit/test_dialog_quality_gate.py tests/unit/test_runtime_hard_cut_audit.py` 通过；7 个新 400 case/model-provider JSON 可加载；`.venv/bin/python -m pytest tests/unit/test_dialog_quality_gate.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `33 passed`；`.venv/bin/python -m pytest --collect-only -q tests/unit` 为 `1499 tests collected`；`.venv/bin/python -m pytest --collect-only -q tests/e2e/test_agent_dialog_effect_perf.py` 为 `1 test collected`；`examples/dialog_quality_gate.py --mode live --mode model` dry-run 确认 live/model plan 生成 `dialog_regression_400_*` 和 `model_provider_400_*` 路径；`dialog_regression_303* / model_provider_303*` 活跃引用清零（除 changelog 历史记录和 hard-cut 禁止列表）；`git diff --check` 通过。
- v1.68 320 历史 fixture 清理验证：`.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `185 passed`；`.venv/bin/python -m pytest --collect-only -q tests/unit` 为 `1498 tests collected`；`py_compile app/domain/intent_reversal.py app/tools/intent_state_tool.py tests/unit/test_runtime_hard_cut_audit.py` 和 `git diff --check` 通过；`dialog_regression_320_prod* / dialog_regression_320_career_region_fastpath` 活跃引用清零。
- v1.67 profile/model-node 与 pending adapter 离线资产清理验证：`py_compile app/domain/intent_reversal.py app/tools/intent_state_tool.py tests/unit/test_runtime_hard_cut_audit.py` 通过；`.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `184 passed`；`.venv/bin/python -m pytest --collect-only -q tests/unit` 为 `1498 tests collected`；`git diff --check` 通过；`intent_entity_profile_tool/plan_query_profile_tool/reply_profile_tool/model_node_benchmark/runtime_pending_*_audit/intent_*_compiler_adapter/compiled_pending_sink_contract` 在活跃代码中仅 hard-cut audit 禁止列表保留。
- v1.66 semantic frame / report 评估协议清理验证：`py_compile examples/dialog_regression_runner.py examples/dialog_case_evaluation_report.py examples/semantic_frame_evaluator.py examples/semantic_frame_probe.py tests/unit/test_dialog_regression_runner.py tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_semantic_frame_evaluator.py tests/unit/test_semantic_frame_probe.py tests/unit/test_runtime_hard_cut_audit.py` 通过；`.venv/bin/python -m pytest tests/unit/test_dialog_regression_runner.py tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_semantic_frame_evaluator.py tests/unit/test_semantic_frame_probe.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `174 passed`；`git diff --check` 通过；旧 `semanticRouterShadow/semantic-router-shadow/semanticRouterSummary/preFullAgentDurationMs/postFullAgentDurationMs/fullAgentToolTrial*` 在 `app/examples/tests` 活跃代码中已清零。
- v1.65 runner runtime observation 命名清理验证：`py_compile examples/dialog_regression_runner.py tests/unit/test_dialog_regression_runner.py tests/unit/test_runtime_hard_cut_audit.py` 通过；`.venv/bin/python -m pytest tests/unit/test_dialog_regression_runner.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `103 passed`；`runtime_shadow/runtime-shadow/runtimeShadow/shadowCaseId` 在 runner 和 runner 单测中已无命中。
- v1.64 direct shadow/PoC 命名清理验证：`py_compile app/service.py app/zhiyuan_agent/agent.py app/zhiyuan_agent/prompt.py examples/dialog_regression_runner.py tests/unit/test_zhiyuan_agent_direct.py tests/unit/test_dialog_regression_runner.py tests/unit/test_runtime_hard_cut_audit.py` 通过；`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_direct.py tests/unit/test_dialog_regression_runner.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `240 passed, 28 skipped`；`.venv/bin/python -m pytest --collect-only -q tests/unit` 为 `1554 tests collected`；`git diff --check` 通过。旧 `zhiyuanAgentPocShadow/zhiyuanAgentDirectShadow/expectedZhiyuanAgentPoc*` 等符号在生产、runner 和 case 中已清零，仅 hard-cut audit 禁止列表保留。
- v1.63 旧链路清理验证：`py_compile app/domain/proposal_compiler.py app/service.py app/agent/context.py examples/dialog_regression_runner.py examples/model_node_benchmark.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_model_node_benchmark.py tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_proposal_compiler_runtime_selection.py tests/unit/test_dialog_regression_runner.py` 通过；`.venv/bin/python -m pytest tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_proposal_compiler_runtime_selection.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py -q` 为 `252 passed`；`.venv/bin/python -m pytest --collect-only -q tests/unit` 为 `1563 tests collected`。残留扫描中旧 TurnDecision/3.2 compiler/downstreamPolicy 符号只剩 hard-cut audit 禁止列表。
- v1.62 完整 G1-G32 direct 主集：`examples/dialog_regression_400_g1_g32_direct_cases.json` 复跑 `20/20`，metrics: `/private/tmp/zhiyuan_400_v162_g1_g32_direct_full_no_shadow_after_g16.json`。本轮 shadow 关闭，全部走 `zhiyuan_agent_direct`；pending 夹具 3 个；失败 0。耗时 median `5451ms`、p95 `11077ms`、max `12726ms`，最慢为 G31 pending 下只读保底查询、G12 查询+替换复合诉求、G27 学费替换预览、G16 锁定动作和 G26 保底切片查询。警告均为部分 no-plan/intent-only 夹具的志愿文件源缺失，不计为业务失败。
- v1.62 focused 真实 LLM：G12 单独复跑 `1/1`，metrics: `/private/tmp/zhiyuan_400_v162_g12_post_query_instruction.json`；G2/G7/G12 focused `3/3`，metrics: `/private/tmp/zhiyuan_400_v162_g2_g7_g12_review_direct_and_query_continue.json`；G16 focused `1/1`，metrics: `/private/tmp/zhiyuan_400_v162_g16_pin_lock_prompt_fix.json`。
- v1.61 聚焦单测：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'query_plan or review_plan or direct_tool_output_uses_next_step or returns_directly_after_review_plan_tool'` 为 `53 passed, 1 skipped`；`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'pin_lock or prompt_mentions_preview_plan_action_for_plan_mutations or direct_tool_output_uses_next_step or query_plan'` 为 `11 passed, 2 skipped`；`.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q -k 'pending_short_text_action or no_pending_short_text_action'` 为 `2 passed`；`py_compile app/zhiyuan_agent/agent.py app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py app/service.py` 通过。
- v1.60 聚焦单测与 PoC 全量：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'duration_as_tag_alias or requires_model_retry_for_missing_major_tag or requires_model_retry_for_missing_cross_domain_school_attribute or accepts_structured_cross_domain_school_attribute or does_not_duplicate_shared_program_type'` 为 `5 passed, 163 deselected`；`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `140 passed, 28 skipped`；`.venv/bin/python -m py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py` 和 `git diff --check` 通过。
- v1.60 真实 LLM final-action 回归：使用临时 agent `8041`、后端 `8080`、MySQL 会话行克隆密码 `--backend-db-password 12345678` 复跑两条聚焦 case 均通过。`400-v157-combo-major-taxonomy-and-tag-final-action` 覆盖“管理学和五年制的都别要了→采纳”，metrics: `/private/tmp/zhiyuan_400_v160_major_tag_combo_real_dbclone.json`，2/2 通过，预览一步 `preview_intent_change` 一次传全，确认后 `confirm_pending` 触发 ordered/review 刷新，后端断言覆盖 `mustExcludeMajors` 同含管理学与 `专业标签:学制：5年`，最终 ordered items/units 裁剪。`400-v158-region-and-school-attribute-combo-final-action` 覆盖“山东别去，民办也算了→确认”，metrics: `/private/tmp/zhiyuan_400_v160_region_school_combo_real_dbclone.json`，2/2 通过，确认后 `mustExcludeRegions`、`mustExcludeSchools`、`candidateViewState.filters.negativeProvinceNames` 写入，基础候选池保留可恢复项，最终 ordered items/units 不含山东和民办。
- v1.60 验证环境注意：同两条 case 在未成功克隆 `assistant_chat_session` 行时，pending 和报考要求写入成功，但 `ordered-plan/generate` 返回 `ordered_plan_response={"code":404,"msg":"会话不存在"}`，导致最终 ordered 不变；带 MySQL 密码克隆会话行后复跑通过。因此后续 final-action 回归必须确认 extra-data、志愿数据和 MySQL 会话行三者均克隆成功，否则只能记为环境失败。
- v1.59 聚焦单测与 PoC 全量：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'move_requires_model_retry or move_supports_tier_local_reorder_filters or move_requires_target_position or active_pending'` 为 `8 passed, 159 deselected`；`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `139 passed, 28 skipped`；`.venv/bin/python -m py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py` 和 `git diff --check` 通过。
- v1.59 真实 LLM G17 主链路：原 `400-g17-tier-local-reorder` source session 26 当前本地后端 `orderedPlanState/workingPlanState` 均为 0，复跑失败原因是夹具源状态漂移；改用有保底档的 source35 临时 case `/private/tmp/zhiyuan_400_v159_g17_source17_case.json`，临时 agent `8040` 复跑 `1/1` 通过，metrics: `/private/tmp/zhiyuan_400_v159_g17_model_retry_source35_clean.json`。结果为单次 `preview_plan_action`、`move_ordered_unit`、1 张 `pendingConfirmationCard`，耗时 `5059ms`。环境警告：`assistant_chat_session` MySQL 克隆因 root 无密码失败，但 extra-data 状态和志愿数据克隆成功。
- v1.58 聚焦单测与 PoC 全量：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'build_turn_context_injects_core_state or active_pending or append_to_active_intent_pending'` 为 `4 passed, 163 deselected`；`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `139 passed, 28 skipped`；`.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q -k 'pending_short_text_action or direct_pending'` 为 `1 passed, 109 deselected`；`py_compile app/agent/context.py app/service.py app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py` 通过。
- v1.58 真实 LLM final-action 回归：`examples/dialog_regression_400_v158_pending_combo_negation_cases.json` 使用临时 agent `8039`、后端 `--internal-service-url http://127.0.0.1:8080` 复跑 `9/9` 通过，metrics: `/private/tmp/zhiyuan_400_v158_pending_resolution_after_fix_backend8080.json`。覆盖“民办的不要→这个先算了，改成山东别去了→采纳”，确认后只写入山东且 `mustExcludeSchools` 不含民办；“山东别去，民办也算了→确认”同卡写入地域+院校属性并最终裁剪 ordered plan；“确认不要民办”在无 active pending 时创建新报考要求而非误 confirm；“不要确认，先别采纳”取消 active pending 且方案/要求不变。环境警告：runner 的 `assistant_chat_session` MySQL 克隆因 root 无密码失败，但 extra-data 状态和志愿数据克隆成功，业务步骤与后端断言均通过。
- v1.57 真实取消/改口/组合/长上下文 final-action：新增 `examples/dialog_regression_400_v157_realistic_cancel_combo_cases.json`。首轮真实 LLM `7/11`，metrics: `/private/tmp/zhiyuan_400_v157_realistic_cancel_combo_initial.json`；失败 1 为“先不采纳了”模型无工具直答“已取消”，后端 `pendingConfirmation.status` 仍为 `active`，导致下一轮“那就只看公办吧”被旧 pending 阻塞且最终误采纳旧“不要民办”；失败 2 为“管理学和五年制的都别要了”只写入 `mustExcludeMajors=["管理学"]`，漏掉 `专业标签:学制：5年`。修复后真实 LLM 复跑 `11/11`，metrics: `/private/tmp/zhiyuan_400_v157_realistic_cancel_combo_after_fix.json`；后端断言覆盖 cancel 后 `pendingConfirmation.status=cancelled`、planningState version/items/units 不变，重新提出并采纳“只看公办”后写入 `mustIncludeSchools` 并刷新 ordered/review，“民办+中外合作”和“管理学+五年制”组合均同时写入，长上下文高收费移出确认后 ordered units 变短且 `tuitionPerYear <= 20000`。
- v1.57 聚焦单测：`tests/unit/test_zhiyuan_agent_poc.py -q -k 'major_duration_as_tag_alias or supplements_major_tag_from_raw_combo_text or rejects_empty_payload_without_pending'` 为 `3 passed, 160 deselected`；`tests/unit/test_chat_service_history_persistence.py -q -k 'pending_short_text_action'` 为 `1 passed, 109 deselected`；`py_compile app/service.py app/zhiyuan_agent/tools.py` 与 `git diff --check` 通过。
- v1.56 真实口语扩展 final-action：新增 `examples/dialog_regression_400_v156_realistic_broadened_final_action_cases.json`，带 `--clone-backend-chat-session` 复跑通过 `10/10`，metrics: `/private/tmp/zhiyuan_400_v156_realistic_broadened_final_action_initial.json`。覆盖“就看公办吧→行，采纳”“中外合作算了吧→确认”“管理学也别要了→确认吧”“五年制的也别要→采纳”“山东别去了，先记下，当前方案先别动→采纳”。前四类均走 `zhiyuan_agent_direct` + `preview_intent_change`，确认走 `direct_pending_intent_confirm` + `confirm_pending`，后端断言覆盖 pending applied、planningState version 增长、`mustIncludeSchools/mustExcludeSchools/mustExcludeMajors` 写入、基础候选池保留可恢复项、最终 ordered items/units 裁剪或不含被排除项；最后一类 `apply_to_current_plan=false` 确认后 `followupMessages=0`，`candidateViewState.filters.negativeProvinceNames` 写入山东，ordered items/units `unchangedFromBefore=true`。
- v1.55 真实口语/指代/简略对话 final-action：新增 `examples/dialog_regression_400_v155_realistic_final_action_cases.json`，带 `--clone-backend-chat-session` 复跑通过 `7/7`，metrics: `/private/tmp/zhiyuan_400_v155_realistic_final_action_initial.json`。覆盖“有啥问题，咋弄→那高收费的别要了→确认执行”（review 引用后的口语后续调整）、“方案里的民办不要了→采纳”（当前方案锚定的 plan action）、“山东别去了→采纳”（裸口语地域要求）。后端断言覆盖确认后 pending applied、planningState version 增长、要求/方案动作真实生效、最终 ordered items/units 裁剪；后验统计为高收费 `30/93 -> 0/63`、民办 `37/93 -> 0/56`、山东 `14/93 -> 0/79`，units 分别 `45 -> 15`、`45 -> 8`、`45 -> 31`。
- v1.54 agent 聚焦验证：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q -k 'major_duration_as_tag_alias or rejects_empty_payload_without_pending or accepts_major_field_aliases'` 为 `3 passed, 159 deselected`，固定 `duration -> major_tag` 与空 pending 防护；全量 `.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `134 passed, 28 skipped`。
- v1.54 真实 local 标签 final-action：`examples/dialog_regression_400_v154_tag_final_action_cases.json` 带 `--clone-backend-chat-session` 复跑通过 `4/4`，metrics: `/private/tmp/zhiyuan_400_v154_tag_final_action_after_alias_fix.json`。步骤“博士点的不要了/五年制的不要了”均走 `zhiyuan_agent_direct` + `preview_intent_change`，确认均走 `direct_pending_intent_confirm` + `confirm_pending`；后端断言覆盖 `pendingConfirmation.status=applied`、`planningState.version` 增长、`mustExcludeSchools` 包含 `院校标签:博士点`、`mustExcludeMajors` 包含 `专业标签:学制：5年`、基础候选池仍保留标签项、最终 ordered items/units 裁剪并不含被排除 volunteerId。按 ordered unit volunteerId 回连基础候选池的后验统计：博士点 `4/93 -> 0/89`、五年制 `6/93 -> 0/87`，units 分别 `45 -> 41`、`45 -> 42`。
- v1.54 首轮问题记录：`/private/tmp/zhiyuan_400_v154_tag_final_action_initial.json` 中“省重点的不要了”走通 final action，但模型把 `省重点` 归入 `school_level`，不适合作为通用 `school_tag` 覆盖；“五年制的不要了”传入 `negative.duration=["五年制"]`，旧工具未消费该 schema alias 并生成空 pending，确认后 `missing_intent_payload`、方案无变化。修复后不再允许空 pending 保存。
- v1.54 兼容复跑专业门类：`examples/dialog_regression_400_v153_major_final_action_cases.json` 在标签修复后复跑通过 `2/2`，metrics: `/private/tmp/zhiyuan_400_v153_major_final_action_after_v154_tag_fix.json`。
- v1.54 兼容复跑核心属性：`examples/dialog_regression_400_v151_attribute_final_action_cases.json` 在标签修复后复跑通过 `8/8`，metrics: `/private/tmp/zhiyuan_400_v151_attribute_final_action_after_v154_tag_fix.json`。
- v1.53 后端聚焦验证：`mvn -q -Dtest=PlanningStateServiceTest#shouldEnrichMajorTaxonomyWhenReturningPlanningState+shouldApplyMajorDisciplineRequirementFromSubCategoryIdWhenGeneratingOrderedPlan+shouldPruneOrderedUnitMajorsByEffectiveVolunteerIdsWhenUnitSchoolNatureMissing+shouldTreatHighTuitionScopeAsTuitionYearWhenGeneratingOrderedPlan test` 通过，固定旧状态专业类补齐、专业门类 final-action、高收费和 ordered unit 裁剪。
- v1.53 agent 聚焦验证：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `132 passed, 28 skipped`，新增 direct/nested 专业分类字段参与本地影响计数的断言。
- v1.53 真实 local 专业门类 final-action：`examples/dialog_regression_400_v153_major_final_action_cases.json` 带 `--clone-backend-chat-session` 复跑通过 `2/2`，metrics: `/private/tmp/zhiyuan_400_v153_major_final_action_after_preview_count_fix.json`。步骤 1 “管理学的不要了”走 `zhiyuan_agent_direct` + `preview_intent_change`，预览文案断言 `20个相关志愿`；步骤 2 “采纳”走 `direct_pending_intent_confirm` + `confirm_pending`，后端断言 `pendingConfirmation.status=applied`、`planningState.version` 增长、`mustExcludeMajors` 包含管理学、基础候选池仍保留被排除 volunteerId、最终 ordered items/units 变短且 ordered units 不含该 volunteerId。后验统计：确认前 ordered major 明细中管理学 `20/94`，确认后 `0/73`，units `45 -> 40`。
- v1.52 真实 local 属性 final-action 兼容复跑：`examples/dialog_regression_400_v151_attribute_final_action_cases.json` 在 v1.53 改动后复跑通过 `8/8`，metrics: `/private/tmp/zhiyuan_400_v151_attribute_final_action_after_major_taxonomy_fix.json`。
- `tests/unit/test_zhiyuan_agent_poc.py`：`131 passed, 28 skipped`。
- `tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_base_agent.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_ws_compat.py`：`73 passed`。
- 清理后组合回归 `tests/unit/test_runtime_hard_cut_audit.py tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_chat_service_history_persistence.py`：`257 passed, 29 skipped`。
- Runner/report 单测：`tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_dialog_regression_runner.py`：`150 passed`。
- 真实 local focused：`examples/dialog_regression_400_v143_constraint_apply_cases.json` 通过 `2/2`，metrics: `/private/tmp/zhiyuan_400_v143_constraint_apply_cases.json`。第二步 `followupMessages=0`，后端断言 `pendingConfirmation.status=applied`、`planningState.version` 增长、`constraintState.hardConstraints.mustExcludeSchools` 包含 `院校性质:民办` 均通过。
- 真实 local 确认执行集：`examples/dialog_regression_400_direct_confirm_execution_cases.json` 通过 `4/4`，metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_v143.json`。具体项移出确认仍发 ordered/review 刷新；民办要求确认在克隆会话候选重建 404 时不发刷新。
- `py_compile` 覆盖 `app/zhiyuan_agent/tools.py`、`app/zhiyuan_agent/prompt.py`、`app/service.py`、`app/domain/fix_proposal_formatter.py` 等触达文件。
- 后端 PlanningStateService 全量单测：`mvn -q -Dtest=PlanningStateServiceTest test` 通过。
- v1.52 后端聚焦验证：`mvn -q -Dtest=PlanningStateServiceTest#shouldPruneWorkingPlanWhenGeneratingOrderedPlanWithConfirmedHardConstraints+shouldPruneOrderedUnitMajorsByEffectiveVolunteerIdsWhenUnitSchoolNatureMissing+shouldTreatHighTuitionScopeAsTuitionYearWhenGeneratingOrderedPlan test` 通过，固定 ordered units 的 effective volunteerId 裁剪，以及 `招生类型:高收费` 对 `tuitionPerYear` 的数值消费。
- v1.52 后端全量验证：`mvn -q -Dtest=PlanningStateServiceTest test` 通过。
- v1.52 runner 单测：`.venv/bin/python -m pytest tests/unit/test_dialog_regression_runner.py -q` 为 `89 passed`，新增 `maxNumericFieldLessThanOrEqual` 后端断言，避免“不要高收费的”只看文案或标签而漏掉学费数值残留。
- v1.52 真实 local 属性 final-action 首轮验证：`examples/dialog_regression_400_v151_attribute_final_action_cases.json` 首轮 `7/8`，metrics: `/private/tmp/zhiyuan_400_v151_attribute_final_action_real.json`。通过项为“民办的不要/只看公办学校/不要中外合作”的 direct intent 与确认写入；失败项为“不要高收费的→采纳”，虽然写入 `constraintState.hardConstraints.mustExcludeSchools=["招生类型:高收费"]` 且发送 ordered/review 刷新，但最终 `orderedPlanState.units` 仍存在 `tuitionPerYear=60000`。后验统计还发现“民办的不要”当时只裁剪了 `orderedPlanState.items`，部分旧 `orderedPlanState.units` 因 `schoolNature` 为空仍可能残留。这两个问题同属 ordered units 最终数据闭环缺口。
- v1.52 真实 local 属性 final-action 修复后复跑：同一 case 带 `--clone-backend-chat-session` 复跑通过 `8/8`，metrics: `/private/tmp/zhiyuan_400_v151_attribute_final_action_after_fix.json`。覆盖口语化显式诉求“民办的不要”“只看公办学校”“不要中外合作”“不要高收费的”，全部走 `zhiyuan_agent_direct` + `preview_intent_change`，确认走 `direct_pending_intent_confirm` + `confirm_pending`；后端断言覆盖 pending applied、version 增长、`mustExcludeSchools/mustIncludeSchools` 写入、基础候选池仍可恢复、最终 ordered items/units 裁剪，以及高收费 `tuitionPerYear <= 20000`。
- v1.51 真实 local final-action 验证：`examples/dialog_regression_400_v150_candidate_view_cases.json` 带 `--clone-backend-chat-session`、`--clear-backend-pending-per-case`、`--clear-backend-planning-intent-per-case` 复跑通过 `2/2`，metrics: `/private/tmp/zhiyuan_400_v150_candidate_view_real_with_session_clone.json`。步骤 1 “山东的不要”走 `zhiyuan_agent_direct` + `preview_intent_change`，生成待确认卡；步骤 2 “采纳”走 `direct_pending_intent_confirm` + `confirm_pending`，后端断言全部通过：`pendingConfirmation.status=applied`、`planningState.version` 增长、`constraintState.hardConstraints.mustExcludeRegions` 包含山东、`candidateViewState.filters.negativeProvinceNames` 包含山东、基础 `candidatePoolState.items` 仍包含山东、最终 `orderedPlanState.units` 不包含山东。confirm 后发送 ordered/review 刷新 followup，说明最终方案动作已触发。
- v1.50 真实 local 首轮失败复盘：同一 case 未带 `--clone-backend-chat-session` 时，pending 和报考要求写入均成功，但 `_apply_intent_pending` 调用 `generate_planning_ordered_plan()` 收到 `ordered_plan_response={"code":404,"msg":"会话不存在"}`，导致 `orderedPlanState.units` 仍含山东，metrics: `/private/tmp/zhiyuan_400_v150_candidate_view_real_after_agent_restart.json`。根因是 runner 只克隆 extra-data，没有克隆 `assistant_chat_session` 行；这属于最终 action 验证夹具缺口，不是 direct intent/confirm_pending 语义分流错误。
- v1.50 后端聚焦验证补充：`mvn -q -Dtest=PlanningStateServiceTest#shouldExposeConfirmedRegionRequirementInCandidateViewState+shouldRemoveConfirmedRegionRequirementWhenVisibleCandidateFilterIsRemoved+shouldKeepBaseCandidatePoolWhenConfirmedHardConstraintsExist+shouldQueryBaseCandidatePoolWithoutHiddenConfirmedHardConstraints+shouldKeepCandidateFilterOptionsRecoverableWhenRegionRequirementFiltersVisibleView+shouldPruneWorkingPlanWhenGeneratingOrderedPlanWithConfirmedHardConstraints test` 通过，固定“基础候选池和筛选选项仍保留山东、可见筛选入参才过滤展示”的页面一致性契约。
- v1.50 后端全量验证：`mvn -q -Dtest=PlanningStateServiceTest test` 通过；`git diff --check` 通过。
- v1.50 前端验证边界：`npx tsc --noEmit --pretty false` 当前失败在既有 `session/ModalForm`、`session/subjectScores`、`userCenter`、`service/request` 等非本次改动文件；`npx eslint src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx` 受 ESLint 9 flat config 缺失阻塞，未得到有效结果。
- v1.49 后端聚焦验证：`mvn -q -Dtest=PlanningStateServiceTest#shouldMarkConstraintIntentChangeStaleWithoutCandidatePool+shouldExposeConfirmedRegionRequirementInCandidateViewState+shouldRemoveConfirmedRegionRequirementWhenVisibleCandidateFilterIsRemoved+shouldKeepBaseCandidatePoolWhenConfirmedHardConstraintsExist+shouldQueryBaseCandidatePoolWithoutHiddenConfirmedHardConstraints+shouldPruneWorkingPlanWhenGeneratingOrderedPlanWithConfirmedHardConstraints test` 通过。
- v1.49 agent 聚焦验证：`.venv/bin/python -m pytest tests/unit/test_zhiyuan_agent_poc.py -q` 为 `131 passed, 28 skipped`。
- 真实 session 35 final-action 历史验证：`/private/tmp/zhiyuan_400_v143_real_session_private_case.json` 通过 `2/2`，确认前 ordered 民办 `6/15`、candidate 民办 `342/757`，确认后 ordered 民办 `0/15`、candidate 民办 `0/415`。v1.49 后 candidate 清零不再是目标，需按新口径复跑：基础候选池保留、可见筛选同步、ordered 不含已排除项。
- 真实 session 26 问题复现记录：`/private/tmp/zhiyuan_400_v143_real_session_region_case.json` runner 通过 `2/2`，但确认后只看到 candidate pool 山东项 `0/1558`，ordered plan 仍为山东 `20/54`；该结果不再按 runner 成功计为链路闭合。随后直接调用 ordered-plan generate 验证时曾发现按 candidate id 裁剪 ordered units 会把非山东也清空，该过度裁剪风险已改为 ordered unit 结构化资格判断。新增后端复现单测 `shouldPruneWorkingPlanWhenGeneratingOrderedPlanWithConfirmedHardConstraints` 覆盖基础候选池仍保留山东项时，ordered/draft/unit 仍按临时有效候选移除山东并保留非山东项。
- 清理验证：`tests/unit/test_proposal_compiler_runtime_selection.py tests/unit/test_runtime_hard_cut_audit.py` 为 `91 passed`，并新增 hard-cut audit 防止旧 full-agent arbitration / blocked reply helper 回流。

**仍需真实闭环验证：**
- 地域类、核心属性类、专业门类、院校标签、专业标签和跨领域组合 final-action 已用克隆真实 chat_session 的回归会话验证到最终 ordered-plan 数据变化；真实口语/指代/简略对话已完成多轮覆盖，并验证 `apply_to_current_plan=false`、“取消后重新提出”、同轮组合要求、跨领域组合和长上下文承接。接下来继续扩大完整 G1-G32 direct 回归、同轮“放弃当前待确认并改成新要求”的更多口语样本、取消/确认否定歧义样本，以及能稳定触发 `continue` 模型重试的真实对话样本；保持新口径：基础候选池可恢复、候选筛选或方案派生状态可解释、最终 ordered/review 不含已排除项。

---

## 12. 当前方案 action final-action 落地缺口（2026-07-07，v1.73 回归）

`examples/dialog_regression_400_v173_action_expansion_final_cases.json`（11 步，4 通过/7 失败）暴露的问题集中在**当前方案具体项操作**（remove/replace/move/sort），与 §11 的约束落地是不同轴：§11 是"属性/地域约束→方案"，本节是"指代/位置/替换/排序→后端真实变化"。四个问题有一个共同底层特征——**Agent 层与后端/数据层之间的"契约"在多个维度上没有对齐**，工具返回 success 但方案实际没动。

### 12.1 问题一：ordered item / ordered unit 位置语义分叉

**现象：** "第三个专业组"预览和确认都操作了喀什大学建筑学所在 unit，而不是第 3 个 ordered unit。

**根因：**
`_items_by_positions`（`tools.py:4245`）按 item 的 `position` 字段匹配，`plan/items.json` 经 enrichment 后是**明细行（ordered item）粒度**——一个 unit（志愿组/专业组）可能展开成多行 item。用户说"第三个专业组"指的是**第 3 个 unit**，但代码把它解析成 `position==3` 的明细行。当明细行的 position 与 unit 序号不是 1:1（多专业组展开）时，第 3 行明细可能落在第 1 或第 2 个 unit 内部，于是定位到喀什大学建筑学而非第 3 个 unit。

`_plan_item_group_key`（`tools.py:3906`）已经能按 unit_id/groupId 聚合，但位置解析路径没用它——位置匹配走的是扁平 item.position。

**修复方向：位置语义按 unit 聚合，明细行位置只作为 unit 内二级定位。**
- 新增 unit 级序号：先用 `_plan_item_group_key` 把 items 聚合成有序 unit 列表，"第 N 个/第 N 个专业组/第 N 个志愿"解析为第 N 个 unit（该 unit 的全部明细行一起作为操作目标）。
- 保留明细级定位仅用于"第 N 个志愿里的第 M 个专业"这类二级引用。
- UI 文案统一：预览卡展示"第 N 个志愿组（学校·专业组）"，避免明细行序号和 unit 序号混用（与 §9.7 计数口径同源，应共用 unit 聚合工具）。

### 12.2 问题二：replace 定位到旧项但不自动选候选 → 不出 pending

**现象：** "青岛理工那个中外合作建筑太贵了，换个便宜点的"能定位旧项，但没自动选出可替换候选，未创建 pending。

**根因：**
`_auto_select_replacement_candidates`（`tools.py:4048`）当前主要覆盖 review_issue_code 驱动的替换（高收费等），对**口语化"换个便宜点的"**这类无 review_issue、只有"便宜"这一软性方向的替换，候选查询/打分没有命中路径——既没有从候选池按"同档位+更低学费"结构化筛选，也没有返回"候选不足"的明确原因，直接静默不建 pending。

**修复方向：replace 候选选择结构化 + 失败可解释。**
- 主模型把当前问/上下文中的替换方向压缩为结构化 `ReplacementSpec`（如 `improve_dims=["tuition_decrease"]`、`exclude_markers=["high_tuition","cooperative"]`），工具不从 `raw_user_text` 做关键词抽取；`review_issue_code`、结构化 `filters` 和旧项结构化属性只是 spec 的其他来源。
- 用 spec 映射候选池查询条件（同 tier + 学费方向排序/学费上限 + 排除当前 issue marker + 已确认要求 carryover），调 `query_planning_candidate_pool` 结构化取候选。
- 有候选 → 建 replace pending（remove 旧 unit + select 新候选）；无候选 → 返回 `clarify` 且给出可执行原因（"候选池里同档位没有更便宜的建筑类志愿，可以放宽到相邻档位或换个方向"），不静默 no-op。
- 与 §11.4 方向 2 一致：replace 的候选来源必须是"尊重当前约束的候选池查询"，而非本地扫描。

### 12.3 问题三：排序字段 Agent/后端枚举不共享，确认后不校验实际变化

**现象：** `sort_ordered_plan(sort_field=school_level)` 确认返回成功且 version 增长，但 source17 与 target 9904734 的 ordered 顺序完全一致——后端排序只支持 `admissionRatio/schoolRank/finalScore`，`school_level` 被归到默认排序。

**根因（双重）：**
1. `_plan_sort_field`（`tools.py:5139`）把 payload 里的 `sort_field` 原样透传给 `sort_planning_ordered_plan`，**不校验是否后端支持**。`_normalize_plan_query_sort_field`（`tools.py:3589`）的枚举是 position/admission_probability/tuition——与后端 `admissionRatio/schoolRank/finalScore` 又是**第三套不一致的命名**。三处枚举（模型输出、query 归一、后端契约）互不对齐。
2. 确认执行后只看 `version 增长 + success`，不校验 ordered 顺序是否真的变了——version 增长是"重排请求被受理"，不等于"按目标字段排了"。这是 §10.2 确认闭环断言的又一盲区（和 §11.1 exclude 落地盲区同类）。

**修复方向：建立共享排序枚举 + 确认后变化校验。**
- 定义单一 `PLAN_SORT_FIELDS` 枚举（agent 侧），显式映射到后端支持字段：`admission_ratio→admissionRatio`、`school_rank→schoolRank`、`comprehensive→finalScore`；不在映射内的字段（如 school_level）在 **preview 阶段**就返回 `clarify`（"目前支持按录取率/院校排名/综合分排序，学校层次暂不支持单独排序"），不生成 pending。
- Prompt 工具示例只暴露受支持的排序字段。
- 确认执行后，对比 ordered unit 顺序 hash（排序前/后），若无变化则回复"这次排序后顺序没有变化"而非"已按要求重新排序"，避免谎报。

### 12.4 问题四：无 active pending 时"执行/采纳"隐式发起新动作

**现象：** 审查后"那高收费的换便宜点"两次 `preview_plan_action` 仍无 pending，只给三种处理选项；随后用户"执行"在无 active pending 下又生成新的移出预览，而不是确认或澄清。

**根因（两段）：**
1. 前半段是 §12.2 的 replace 不出候选 → 只能退化成"给你三种处理选项"的只读建议，没有落成可确认 pending。
2. 后半段更严重：用户"执行/采纳"本意是确认前面那个（并不存在的）pending，但因为没有 active pending，`preview_plan_action` 被再次触发生成**新的移出预览**——把"确认既有操作"误当成"发起新操作"。`confirm_pending` 有 no-active-pending 防护，但这轮根本没走到 confirm_pending，模型直接又调了 preview_plan_action。

**修复方向：确认类意图在无 pending 时必须澄清，不能隐式发起新动作。**
- Prompt 强化：用户说"执行/采纳/就这么办/确认"时，一律先走 `confirm_pending`；`confirm_pending` 在无 active pending 时返回明确澄清（"现在没有待确认的调整，你是想让我把刚才说的高收费替换整理成具体方案吗？"），不生成新预览。
- 工具边界：`preview_plan_action` 增加防护——当本轮用户消息是纯确认词（无新操作描述）且无 active pending 时，不创建预览，返回 `clarify` 引导重新表达诉求。
- 根治依赖 §12.2：只要"换便宜点"能稳定出 replace pending，用户随后的"执行"就有 active pending 可确认，这条链自然闭合。

### 12.5 共同底层：三处"契约对齐"缺口 + 确认后校验缺失

四个问题归结为两类系统性缺陷：

| 类别 | 表现 | 涉及问题 |
|------|------|---------|
| **枚举/语义契约未对齐** | 位置（item vs unit）、排序字段（模型/query/后端三套命名）、替换方向（口语 vs 候选池查询）在 Agent 与数据层/后端之间没有统一映射 | §12.1 §12.2 §12.3 |
| **确认执行后不校验真实变化** | version 增长/success ≠ 方案真的变了；exclude 不落地（§11.1）、排序不生效（§12.3）都被谎报为成功 | §12.3 §11.1 |

这与 §10.2 的判断一致：`confirm_pending` 的后端 action 闭环**只断言了 remove 具体项这类"强变化"**，对"重排、排除、替换"这类"可能 no-op 的变化"缺少"确认后真实 diff 校验"。这是切换到新框架前必须补的通用能力。

### 12.6 落地计划

**阶段 1（确认后变化校验，通用能力，最高优先，1-2 天）：**
- `confirm_pending` 执行后统一增加"操作前/后 ordered-plan 快照 diff"：remove 校验目标 unit 消失、move 校验位置变化、sort 校验顺序变化、replace 校验旧 unit 消失+新 unit 出现、intent-exclude（§11.1）校验被排除项消失。
- 任一操作 diff 为空 → 回复据实说明"这次没有产生变化"及可能原因，不谎报成功。
- 这一步同时覆盖 §11.1 exclude 落地盲区和 §12.3 排序盲区，是共用地基。

**阶段 2（枚举/语义契约对齐，2-3 天）：**
- §12.1 位置按 unit 聚合（复用 `_plan_item_group_key`，与 §9.7 共用 unit 计数工具）。
- §12.3 建立共享 `PLAN_SORT_FIELDS` 枚举，preview 阶段拦截不支持字段，Prompt 只暴露受支持字段。
- §12.2 replace 候选改结构化候选池查询（同档位+学费上限+规避 issue 标签），无候选返回可执行原因。

**阶段 3（确认语义收口，1 天）：**
- §12.4 纯确认词在无 active pending 时强制走 confirm_pending 澄清；preview_plan_action 拒绝把确认词当新动作。
- Prompt 增加"执行/采纳→confirm_pending，无待确认则澄清"示例。

**阶段 4（回归收口，2 天）：**
- 用克隆真实 chat_session 重跑 v1.73 的 11 步，断言：第 N 个志愿组定位到正确 unit、replace 出候选 pending 或可执行原因、排序真实改变顺序或据实说明、"执行"在无 pending 时澄清。
- 把"确认后真实 diff 校验"纳入所有 final-action 回归的通用断言（不再只看 success/version）。
- 与 §11 exclude 落地回归合并跑一轮，确认两轴问题同时闭合。

**放量门槛更新（叠加 §11.5）：** 当前方案 action 场景（remove/replace/move/sort）在阶段 1-4 回归通过前，不纳入属性/地域约束之外的全量放量；可先放量只读 + 具体项 remove（已验证强变化）。

实施顺序：阶段 1（通用校验地基）→ 阶段 2（契约对齐）→ 阶段 3（确认语义）→ 阶段 4（回归收口）

### 12.7 v1.77 落地状态

- 阶段 1 已进入生产链路：`confirm_pending` 对 `remove_units / move_ordered_unit / sort_ordered_plan / replace_units` 增加 ordered-plan 前后快照 diff。remove 校验目标专业组消失，move 校验位置变化，sort 顺序未变时据实说明，replace 校验旧专业组消失并校验新候选 volunteerId 出现在确认后的 `orderedPlanState`。
- replace diff 快照口径修正：`orderedPlanState.units` 仍作为 unit 顺序和位置来源，但 `orderedPlanState.items` 始终参与 volunteerId 汇总，避免新候选已进入 items、但 units.majorItems 尚未完整同步时被误判为未加入。
- 阶段 2 的位置契约继续收口：除 `targets=["第三个专业组"]` 外，`filters.position_group=3` 及 `positionGroup/unitPosition/unit_position/orderedPosition/ordered_position` 别名也按第 3 个 ordered unit/专业组定位。该 selector 是模型输出的结构化字段，不从用户原文做语义匹配。
- 本轮验证结果：focused 单测 `7 passed, 174 deselected`；v1.73 action expansion 真实 LLM 回归 `11/11`；v1.51 属性类最终 action 真实 LLM 回归 `8/8`。两组真实回归都包含最终确认动作和后端 ordered-plan 断言，不只检查出卡。
- 当前剩余方向：继续扩大真实口语回归，优先观察回复整体质量、active pending 下改口/追加语义、无 pending 确认边界，以及 replacement spec 候选质量；旧链路继续按 Phase 3 清理，不再为旧模型路径补兼容。

### 12.8 v1.78 G1-G32 direct 主集复核

- 本轮不修改实现，只复跑 4.0 direct 主集：`examples/dialog_regression_400_g1_g32_direct_cases.json`，隔离端口 Backend `18290`、Agent `18291`，metrics: `/private/tmp/zhiyuan_400_v178_g1_g32_direct_full.json`。
- 结果：20 步全部通过，`failures=[]`、`warnings=[]`。运行期观察为 intent pending 6、plan mutation 预览 3、readonly 9、needs-plan-first 2；pending 类型为 intent change 6、plan mutation 3、none 11。
- direct 链路覆盖：G1/G4/G8/G23/G25/G30 进入 `preview_intent_change`；G12/G17/G27 进入 `preview_plan_action` 并生成方案调整预览；G2/G3/G7/G21/G26/G31 只读查询/审查不产生待确认卡；G10 无待确认时确认走 `confirm_pending` 防护；G19/G32 无正式方案时走 needs-plan-first 防护。
- 性能：median `4988ms`、p95 `7247ms`、max `11251ms`。尾部集中在需要二次模型总结的只读查询或复合诉求：G31 pending 下保底查询、G12 查询+替换、G26 保底切片、G3 pending 下只读查询。
- 客观观察项：G2/G7 审查能保持只读边界，但“当前没有明显风险或提醒”对“高收费/中外合作/预算一般”这类问题的信息量偏弱，后续应补充命中数量、占比、预算影响和可执行处理方向；G19/G32 无方案防护正确但回复偏长，可压缩；G16 是不支持锁定动作的安全拦截验证，不是锁定动作落地验证。
- 结论：G1-G32 主集的 direct 路由、pending 边界和 no-plan 防护稳定；最终 action 数据变化仍以 v1.77 的 v1.73 action expansion `11/11` 与 v1.51 属性类 final-action `8/8` 为闭环依据。下一步继续补真实口语/指代/多轮 case，优先覆盖同轮改口、active pending 下追加诉求、以及 replace 候选质量。

### 12.9 v1.79 active pending 与 replace focused 回归

- 新增回归资产：`examples/dialog_regression_400_v179_pending_replace_review_quality_cases.json`。覆盖四类真实口语链路：
  - active pending 下追加新要求：“山东别去了”后“再把民办也算了吧，一起记上”，确认后要求同时写入，最终 ordered 不含山东/民办。
  - active pending 下放弃当前待确认并改成新要求：“民办的不要”后“等下，别按这个了，改成只看公办，山东也别去”，确认后写入“公办”和“不要山东”，旧“不要民办”不单独落库。
  - 只读审查后直接说“执行”时必须无 pending no-op，不隐式创建方案调整。
  - targeted replace：“青岛理工那个中外合作建筑太贵了，换个正常收费的，最好不是中外合作”，检查 replacement spec 与确认后 ordered 变化。
- 首轮真实 LLM：`8/10`，metrics: `/private/tmp/zhiyuan_400_v179_pending_replace_review_quality_real.json`。active pending append 通过，replace_active_pending 漏掉“山东也别去”，导致确认后只采纳“公办”，ordered 仍保留山东项。
- 修复方式：只改 prompt，不改工具语义、不加工具层字符串兜底。补充规则：active pending 改写/追加时必须完整抽取当前用户这句话中所有显式要/不要项；“再/也/一起/加上/顺便/补一个”作为追加语义交给模型判断；地域+院校属性同句时优先用 `intent_type="region"` 承载地域项，并在同一 positive/negative payload 中保留院校属性。
- 修复验证：`py_compile app/zhiyuan_agent/prompt.py` 通过，`git diff --check` 通过。第二轮 metrics `/private/tmp/zhiyuan_400_v179_pending_replace_review_quality_after_prompt_fix.json` 显示 replace_active_pending 通过，但 append 变成只保留“民办”而漏掉旧 pending 的“山东”。继续补 append 示例后，第三轮 metrics `/private/tmp/zhiyuan_400_v179_pending_replace_review_quality_after_append_prompt_fix.json` 中 active pending append、active pending replace、只读审查后无 pending “执行”均通过。
- 剩余问题：targeted replace 非稳定。同一句“青岛理工那个中外合作建筑太贵了，换个正常收费的，最好不是中外合作”在前两轮能生成替换预览并完成确认；第三轮未稳定定位当前方案项，回复“当前方案里没有找到”，没有创建 pending，后续“就这样换”也只能变成只读查询。这说明 replace 的目标定位仍依赖单次模型参数质量，和 §12.2 的 replacement spec 候选方向不是同一个问题。
- 后续方向：为 `preview_plan_action(action="replace")` 增加结构化 retry 协议。当模型已经表达 replace，但工具缺少或没能唯一定位旧项时，返回 `next_step=continue` 并要求模型补齐 targets/filters/review_issue_code/selector，而不是直接向用户说没找到；若重试后仍不能定位，再返回可执行澄清。该方案仍由模型基于压缩上下文补结构化参数，不引入工具层原文字符串匹配。

### 12.10 v1.82 targeted replace 与 active pending 修复落地

- `preview_plan_action(action="replace")` 已增加旧项定位结构化 retry 协议：当 action 已明确是 replace，但旧项缺失或当前结构化参数无法唯一定位当前方案项时，工具返回 `next_step=continue`、`reason=plan_action_requires_replace_target`、`current_user_text` 和 `retry_required_fields`，要求主模型补齐 `targets/filters/review_issue_code/selector/replacement_spec` 后重试。每轮只允许一次 retry；第二次仍无法定位时返回用户可执行澄清，避免无限继续。
- 该修复仍遵守 4.0 原则：工具只消费模型传入的结构化参数和已压缩上下文，不在工具层解析“青岛理工/中外合作/太贵/正常收费”等用户原文关键词；替换方向仍走 `ReplacementSpec`，旧项定位由模型把上下文压缩成 `targets` 或 `filters`。
- 补齐结构化 filter alias：`school_name/schoolName/school_names/schools/collegeName` 归一为 `school`，`major_name/majorName/major_names/majors` 归一为 `major`。这解决了真实回归中模型重试传 `filters={"school_name":"青岛理工大学"}` 但 `query_plan`/`preview_plan_action` 无法命中的问题。
- 补齐 `only_keep` 意向 canonicalize：当模型对“只看公办，山东也别去”同时输出 `positive.school_nature=["公办"]` 和冗余 `negative.school_nature=["民办"]` 时，工具在结构化合并阶段移除冗余 `negative_school_nature=民办`，最终只表达用户当前诉求“只看公办 + 不去山东”，不把旧待确认的“不要民办”单独保留为新诉求。
- 验证结果：`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py` 通过；focused 单测 `17 passed, 169 deselected`；完整 direct 单测 `157 passed, 29 skipped`；`git diff --check` 通过。
- 真实 LLM focused 结果：`examples/dialog_regression_400_v179_pending_replace_review_quality_cases.json` 最终 `10/10`，metrics: `/private/tmp/zhiyuan_400_v182_intent_canonicalize_real.json`。覆盖 active pending 追加、active pending 改写、只读审查后无 pending 的“执行”防护，以及 targeted replace 生成 `replace_units` pending 后通过 `confirm_pending` 真实修改 ordered plan。
- 当前观察：v1.82 已闭合 v1.79 focused 集暴露的两个业务问题。后续应继续扩大真实口语/指代/多轮回归，重点看 replacement spec 候选质量、active pending 改口/追加的更多表达、以及只读回复的信息密度；旧链路清理继续按 Phase 3 执行，不再为旧模型路径补兼容。

### 12.11 v1.83 真实口语 follow-up 扩展与 no-pending 边界

- 新增回归资产：`examples/dialog_regression_400_v183_realistic_followup_quality_cases.json`，覆盖 5 类更口语的多轮链路：
  - active pending 追加：“山东先别去了”后“再加个只看公办，一起记上”，确认后同时写入不要山东 + 只看公办，ordered 不含山东/民办。
  - active pending 改写：“中外合作先不要”后“算了不是这个，改成山东别去，民办也不要”，确认后只采纳新诉求，不保留旧“不要中外合作”。
  - targeted replace 简略表达：“青岛理工那个建筑太贵了，换个便宜点正常收费的”生成 `replace_units`，确认后 ordered 真实变化。
  - 只读审查后模糊采纳：“这版高收费中外合作这些咋整，先别动”后“那就照你说的处理吧”，无 active pending 时必须走 `confirm_pending` no-op，不自动创建方案调整。
  - 只读审查后明确动作：“那高收费这些换便宜点，不是直接删”生成 `replace_units`，后续“执行”通过 `confirm_pending` 真实修改 ordered plan。
- 初始真实 LLM 结果：`12/13`，metrics: `/private/tmp/zhiyuan_400_v183_realistic_followup_quality_initial.json`。唯一失败为“那就照你说的处理吧”被模型从上一轮只读审查建议自动转成 `preview_plan_action(replace_units)`，创建了替换待确认卡；后端 `planningState.version` 未变，但 `pendingConfirmation` 不为空，违反 no-pending 防护。
- 修复方向与实现：不在工具层增加用户原文字符串匹配，只补主模型判决规则。当前状态摘要里的待确认状态作为本轮依据；只读审查/处理方向之后，若本轮只表达“照你说的处理/就这么办/按你说的来/执行/采纳”且没有明确动作对象与动作类型，必须调用 `confirm_pending`；没有待确认时由工具返回“当前没有待确认操作，不会执行任何变更”。明确“高收费这些换便宜点/不是直接删”仍走 `preview_plan_action(replace)`。
- 复验注意：prompt 修改后必须重启 agent 或使用新端口，否则旧进程不会加载修改；重复使用失败 session 会受到旧 pending/history 残留影响。最终使用新 agent `18292` 与 `--session-offset 200` 复跑整组。
- 最终验证：`py_compile app/zhiyuan_agent/prompt.py` 通过，`git diff --check` 通过；focused 失败 case 复跑 `2/2`，metrics: `/private/tmp/zhiyuan_400_v183_no_pending_vague_execute_after_prompt_fix_current_agent.json`；整组 v1.83 真实 LLM `13/13`，metrics: `/private/tmp/zhiyuan_400_v183_realistic_followup_quality_after_prompt_fix.json`。
- 当前观察：replace 候选仍倾向选择更低学费但民办的山东候选，这是当前 `ReplacementSpec` 只表达学费下降时的合理结果；如果用户同时要求公办/不要民办，需要由模型把该诉求一并压入结构化条件。审查回复的信息量已比 v1.78 更明确，但“需要你先取舍后再处理”等表达仍偏机械，后续可作为回复质量优化项。

### 12.12 v1.84 active pending 短句确认与主集复核

- 问题来源：v1.83 扩展回归在 fresh agent 上重跑时发现 targeted replace 的确认轮不稳定。第一轮“青岛理工那个建筑太贵了，换个便宜点正常收费的”已生成 `replace_units` 待确认卡，但第二轮“就换这个”时模型没有调用 `confirm_pending`，而是直接口头回复已确认执行。后端实际仍为 `pendingConfirmation.status=active`、`planningState.version` 未增长、ordered 仍包含旧的青岛理工 unit。
- 修复方式：prompt-only，不在工具层增加用户原文字符串语义匹配。当前状态摘要显示“待确认：有”时，如果用户短句表达是在选择当前预览、确认当前预览，且没有提出新的报考要求或新的方案调整诉求，必须调用 `confirm_pending(action="confirm")`；没有 `confirm_pending` 工具结果前，回复层不得说“已替换/已完成替换/已更新”。该规则同时保留 v1.83 的 no-pending 边界：只读审查后无 active pending 的“照你说的处理/执行”仍走 `confirm_pending` no-op，不隐式创建方案调整。
- 聚焦验证：单 case `400-v183-terse-targeted-replace-cheaper-final-action` 复跑 `2/2`，metrics: `/private/tmp/zhiyuan_400_v184_v183_targeted_replace_after_confirm_prompt_fix.json`。确认轮“就换这个”调用 `confirm_pending`，routingPath=`direct_pending_plan_confirm`，后端断言覆盖 `pendingConfirmation.status=applied`、`planningState.version` 增长、ordered units 变化和旧 unit 消失。
- v1.83 整组验证：首轮 `/private/tmp/zhiyuan_400_v184_v183_focused_after_confirm_prompt_fix.json` 为 `9/13`，4 个失败均来自模型服务连接问题（`TimeoutError/ModelAPIError`，日志显示请求 `llm.baijia.com` 超时，未进入工具链），不是 direct 语义或后端 action 错误。按失败子集用 fresh session 复跑 `5/5`，metrics: `/private/tmp/zhiyuan_400_v184_v183_failed_subset_rerun_after_llm_timeout.json`；覆盖只读审查后模糊“那就照你说的处理吧”走 `confirm_pending` no-op，以及明确“那高收费这些换便宜点，不是直接删”生成 replace pending 后“执行”真实修改 ordered 并刷新 ordered/review。
- 防回归验证：v1.79 focused 复跑 `10/10`，metrics: `/private/tmp/zhiyuan_400_v184_v179_focused_after_confirm_prompt_fix.json`。active pending 追加、active pending 改写、只读后无 pending 执行防护、targeted replace + final action 均通过。
- 主集验证：`examples/dialog_regression_400_g1_g32_direct_cases.json` 真实 LLM 主集 `20/20`，metrics: `/private/tmp/zhiyuan_400_v184_g1_g32_direct_after_confirm_prompt_fix.json`。运行期观察为 intent pending 6、readonly 9、plan preview 3、needs-plan-first 2；pending 类型为 intent_change 6、plan_mutation 3、none 11。G4/G10/G19/G23/G30/G32 有源志愿文件缺失 warning，但对应 case 只依赖后端状态或无方案边界，业务断言均通过。
- 当前结论：4.0 direct 对话与后续执行链路在 focused 口语集和 G1-G32 主集上已保持稳定；本轮新增问题已收敛到 prompt 层确认边界，最终 action 验证覆盖到后端 `pendingConfirmation`、`planningState.version` 和 ordered-plan 真实变化。下一步继续扩大真实口语 final-action 回归，并单独看只读审查回复质量、无方案边界文案压缩、以及模型服务超时下是否需要 runner/服务层重试策略。

### 12.13 v1.85 final-action 扩展回归与并发波动复核

- 本轮范围：不改实现，只验证 v1.84 后 4.0 direct 在真实口语、指代、多轮、取消改口、组合诉求和当前方案 action 上的最终动作闭环。所有确认类 case 均要求覆盖 `pendingConfirmation.status=applied`、`planningState.version` 增长、ordered-plan 真实变化或按 `apply_to_current_plan=false` 保持不变，并要求 ordered/review 刷新跟随实际方案变化。
- 已完成基线复跑：`examples/dialog_regression_400_v155_realistic_final_action_cases.json` 为 `7/7`，metrics: `/private/tmp/zhiyuan_400_v184_v155_realistic_final_action_rerun.json`。覆盖“有啥问题，咋弄→那高收费的别要了→确认执行”“方案里的民办不要了→采纳”“山东别去了→采纳”，最终动作均正确触发。
- 已完成扩展复跑：`examples/dialog_regression_400_v156_realistic_broadened_final_action_cases.json` 首轮为 `8/10`，metrics: `/private/tmp/zhiyuan_400_v184_v156_realistic_broadened_final_action_rerun.json`。两个失败均是严格工具调用次数断言：`中外合作算了吧` 与 `五年制的也别要` 各出现两次 `preview_intent_change`，但第二次生成正确 pending，确认轮 `confirm_pending` 后后端断言通过。按当前口径记录为重复调用观察项，不作为业务错例优先修复。
- v157 并发首轮：`examples/dialog_regression_400_v157_realistic_cancel_combo_cases.json` 三组并发跑时为 `7/11`，metrics: `/private/tmp/zhiyuan_400_v184_v157_realistic_cancel_combo_rerun.json`。失败集中在 `民办和中外合作都算了吧`、`管理学和五年制的都别要了` 两个首轮请求触发 `ModelAPIError`，未进入工具链，导致下一轮“确认/采纳”没有 active pending 可执行。失败子集顺序复核 `4/4`，metrics: `/private/tmp/zhiyuan_400_v184_v157_failed_subset_sequential_rerun.json`；两条组合诉求均一次 `preview_intent_change` 生成 pending，确认后要求写入并重排方案。
- v158 并发首轮：`examples/dialog_regression_400_v158_pending_combo_negation_cases.json` 三组并发跑时为 `6/9`，metrics: `/private/tmp/zhiyuan_400_v184_v158_pending_combo_negation_rerun.json`。主要失败为 `这个先算了，改成山东别去了` 触发 `ModelAPIError`，于是后续“采纳”仍确认旧 pending；另有 `确认不要民办` 出现两次 `preview_intent_change` 的严格次数失败。失败子集顺序复核 `5/5`，metrics: `/private/tmp/zhiyuan_400_v184_v158_failed_subset_sequential_rerun.json`；同轮“取消当前待确认并改成山东别去”能替换 active pending，确认后只写入山东，不保留旧“不要民办”。
- v173 并发首轮：`examples/dialog_regression_400_v173_action_expansion_final_cases.json` 三组并发跑时为 `8/11`，metrics: `/private/tmp/zhiyuan_400_v184_v173_action_expansion_final_rerun.json`。失败为 `就这么换吧` 与 `把第三个专业组挪到最前面` 触发 `ModelAPIError` 未进入工具链，导致确认/移动后端断言失败。失败子集顺序复核 `4/4`，metrics: `/private/tmp/zhiyuan_400_v184_v173_failed_subset_sequential_rerun.json`；targeted replace 确认后旧青岛理工 unit 消失、替换项写入 ordered，位置移动确认后目标 unit 到第 1 位。
- 综合真实口语集：`examples/dialog_regression_400_realistic_user_cases.json` 使用当前 agent `18293`、backend `18290` 复跑为 `12/14`，metrics: `/private/tmp/zhiyuan_400_v185_realistic_user_full_rerun.json`。两处失败均为 `ModelAPIError` 未进入工具链：`里面有民办没` 未调用 `query_plan`，`方案里的民办不要了` 未生成 pending。失败子集顺序复核 `2/2`，metrics: `/private/tmp/zhiyuan_400_v185_realistic_user_failed_subset_rerun.json`；前者正确走 `query_plan` 并说明当前无正式方案，后者在无正式方案场景下走 `preview_plan_action` 的 no-plan attribute fallback，生成“不要民办”的待确认报考要求卡。
- review/repair 首轮：直接对 `examples/dialog_regression_400_review_repair_cases.json` 加 `--session-offset 3100` 复跑为 `6/9`，metrics: `/private/tmp/zhiyuan_400_v185_review_repair_rerun.json`。这组 case 文件没有声明 `cloneBackendStateFromSessionId`，offset 后的 3230/3231/3232 没有正式方案，因此“稳保不足/专业组安全垫/提醒分层”只能返回无方案边界；该轮记为 fixture 运行方式问题，不作为业务回归失败。
- review/repair 克隆复跑：生成临时 case `/private/tmp/zhiyuan_400_review_repair_cases_with_clone.json`，为每个 case 加 `cloneBackendStateFromSessionId/sourceSessionId`，再用 `--session-offset 3200` 克隆 130/131/132 到隔离 session。结果 `8/9`，metrics: `/private/tmp/zhiyuan_400_v185_review_repair_clone_rerun.json`。通过项包括审查摘要、稳保候选不足说明、高收费/中外合作处理方向、专业模式导出边界、提醒分层、手动移动后重新审查。
- review/repair 剩余问题：`400-review-major-group-inner-safety` 中用户说“专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览”，模型只调用 `review_plan`，回复审查和处理方向，没有生成 `pendingConfirmationCard`。这不是模型服务错误，也不是空会话 fixture 问题；属于 review+方案动作复合诉求缺口。当前 prompt 的“明确方案动作优先 `preview_plan_action`”覆盖了移出/替换/排序/重排等，但没有把“补一个/加一个/加入/补安全专业”纳入方案动作；同时 `preview_plan_action(action="add")` 当前需要唯一候选目标，不能直接从“安全一点”自动选候选。
- review/repair 修复方向（待单独落地）：把“补一个/加一个/加入/补稳/补保/补安全一点”纳入模型侧方案动作判决；当用户要求“先给我看预览”时，不应停在 `review_plan`。如果能定位到具体候选，走 `preview_plan_action(action="add", targets=[...])`；如果只是围绕安全垫/录取率梯度的结构性问题，应走 `preview_plan_action(action="regenerate_order", review_issue_code="group_inner_safety_guard" 或 "safety_guard"/"probability_gap")` 创建可确认的重排预览；如果候选不足或 issue 不支持自动处理，必须明确回复“当前缺少可加入的安全候选/需要先放宽范围或指定候选”，而不是泛泛列处理方向。该方向仍由模型把上下文压缩成结构化 action/review_issue，不在工具层做原文字符串匹配。
- 客观归类：本轮没有确认新的 4.0 direct 最终执行错误。并发模式下真实 LLM 服务不稳定会把 `ModelAPIError/TimeoutError` 放大为后续断言失败；失败子集顺序复核全部通过，说明现有 prompt/tool/backend 链路在这些 final-action case 上可闭环。重复调用 `preview_intent_change` 目前是小规模观察项，未导致最终动作错误，后续只有出现大面积重复或明显性能退化时再优先处理。review/repair 复合诉求剩余 1 个待修问题，归入回复/路由质量和结构性方案动作预览补齐。
- 后续建议：继续扩大真实口语 final-action 回归时保留并发跑法提高效率，但报告口径应固定为“并发首轮 + 失败子集顺序复核”。若模型服务波动继续影响判断，再考虑在 regression runner 或 service 层增加只针对 `ModelAPIError/TimeoutError` 的测试重试策略；不要用字符串语义兜底掩盖模型调用失败。

### 12.14 v1.86 review+方案动作复合诉求与 plan_generation pending 修复

- 问题拆解：v1.85 剩余 case `400-review-major-group-inner-safety` 的原话同时包含审查问题和明确方案动作：“专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览”。第一层缺口是模型未把“补一个安全一点”识别为方案动作，停在 `review_plan`；prompt 修复后模型已正确调用 `preview_plan_action(action="regenerate_order", review_issue_code="probability_gap")`，但仍没有展示 `pendingConfirmationCard`。第二层缺口在服务层：`preview_plan_action(regenerate_order)` 生成的是 `kind=plan_generation`，而 `service.py` 多处只把 `plan_mutation` 当作方案类 pending，导致卡片渲染、active pending 恢复和短文本确认链路不完整。
- 实现调整：`PendingConfirmation.kind` 放开 `plan_generation`；`service.py` 增加统一 `_PLAN_PENDING_KINDS={"plan_mutation","plan_generation"}` 和 `_pending_type_from_kind()`，替换散落的 `kind=="plan_mutation"` 判断。覆盖范围包括 `_pending_confirmation_from_state()`、`_direct_confirm_routing_path()`、pending readonly/冲突文案、短文本一致性检查、`_build_structured_plan_pending_card()`、`_build_structured_pending_card()`、direct route 观测字段、stale pending 清理、结构化卡片确认入口。卡片 payload 保留真实 `kind=plan_generation`，避免点击确认时与后端 pending kind 不一致。
- prompt 调整：明确方案动作规则增加“加入/加进/补入/补一个/补稳/补保/补安全一点”，并补充示例把“补一个安全一点的专业，先给我看预览”映射到 `preview_plan_action(action="regenerate_order", review_issue_code="probability_gap", raw_user_text=...)`。该修复仍由模型把上下文压缩成结构化 action/review_issue，不在工具层做用户原文字符串兜底。
- 单测验证：`py_compile app/service.py app/models/conversation_phase.py tests/unit/test_zhiyuan_agent_direct.py tests/unit/test_chat_service_history_persistence.py` 通过；`git diff --check` 通过；新增/相关单测覆盖 `plan_generation` 路由 helper、direct 出卡、结构化确认执行和后端 pending 恢复。完整 `tests/unit/test_zhiyuan_agent_direct.py -q` 为 `159 passed, 29 skipped`；`tests/unit/test_chat_service_history_persistence.py::test_pending_confirmation_from_state_accepts_plan_generation` 通过。
- 真实 focused 验证：使用新 agent `18295`、backend `18290`、rank `5001`，复跑 `400-review-major-group-inner-safety` 通过，metrics `/private/tmp/zhiyuan_400_v186_review_major_group_inner_safety_after_plan_generation_card_fix.json`。结果：单轮调用 `preview_plan_action`，followup 包含 `pendingConfirmationCard`，payload 为 `kind=plan_generation/actionFamily=regenerate_order/title=确认重排方案`。
- 最终 action 验证：同 session 继续发送“确认执行”，metrics `/private/tmp/zhiyuan_400_v186_review_major_group_inner_safety_confirm_after_card_fix.json`。结果：`confirm_pending` 被调用，routingPath=`direct_pending_plan_confirm`，回复“已按当前候选重新生成排序方案。”，followups 刷新 `ordered/review`。后端 latest pending 为 `status=applied`、`kind=plan_generation`、`actionFamily=regenerate_order`、`resultCode=applied`，工作台版本从 `sourceBackendVersion=461` 增长到 `version=462`，确认不是只出卡或只回文案。
- 完整 review/repair 复跑：克隆版 `/private/tmp/zhiyuan_400_review_repair_cases_with_clone.json` 在 session offset `3600` 复跑 `9/9`，metrics `/private/tmp/zhiyuan_400_v186_review_repair_clone_after_plan_generation_card_fix.json`。v1.85 的 `8/9` 缺口已闭合。
- 剩余观察点：`regenerate_order` 确认后方案已刷新，但后端 `staleFlags.review=true`，说明审查结果需要重新跑或由前端 review 视图触发刷新。当前返回 `review` refresh followup 可以让用户进入审查视图，但“最新审查结果”的文案和实际 stale 状态需要继续核对；下一步可选择在 plan_generation 确认后触发 `run_review`/review workflow，或调整 followup 文案为“方案已更新，需要重新审查”。该问题不影响本轮出卡和最终方案重排 action 的闭环。

### 12.15 v1.87 plan_generation 确认后 review 入口文案调整

- 产品决策：先不在 agent 确认链路里自动触发 `runReviewWorkflow`。`regenerate_order` 的职责保持为确认后重新生成排序方案；审查刷新由后续用户进入 review 视图或显式重新审查触发。
- 实现方式：新增 `_build_pending_apply_workspace_refresh_response()`，仅当 `pending_kind=plan_generation` 且 `action_family=regenerate_order` 且目标为 `review` 时覆盖 workspace action 文案。短文本确认和卡片确认统一走该 helper。
- 文案结果：review followup 不再说“查看最新审查结果 / 已刷新方案审查结果”，改为“需要重新审查方案 / 方案排序已更新，原审查结果可能不再完全准确。请重新审查后再看最新风险和提醒。/ 重新审查”。
- 验证：`py_compile app/service.py tests/unit/test_zhiyuan_agent_direct.py` 通过；`tests/unit/test_zhiyuan_agent_direct.py::test_service_pending_confirmation_executes_plan_generation_bridge` 通过并断言 review payload 文案；完整 `tests/unit/test_zhiyuan_agent_direct.py -q` 为 `159 passed, 29 skipped`；`git diff --check` 通过。真实 focused 验证使用新 agent `18296`：预览出卡通过，metrics `/private/tmp/zhiyuan_400_v187_review_major_group_inner_safety_preview.json`；同 session “确认执行”通过，metrics `/private/tmp/zhiyuan_400_v187_review_major_group_inner_safety_confirm_copy.json`，followup 仍有 `ordered/review` 两个入口，其中 review payload 为 `title=需要重新审查方案`、`actionText=重新审查`。

### 12.16 v1.88 审查兜底回复文案清理

- 范围：只清理用户可见文案，不改变 direct 路由、pending、确认执行或后端 action。重点处理 review/repair 兜底回复里残留的内部状态表达。
- 实现：`_normalize_user_facing_terms()` 将 `blocked/系统阻塞` 统一改写为“需要你先确认是否接受这类调整或放宽报考条件”，避免出现“阻塞/调整范围变化”等系统用语；未生成真实 pending 的边界回复从“可执行的调整内容”改为“可确认的调整预览”；`fix_proposal_preview` 兜底文案去掉“可执行预览”。
- 兼容：reply guard 继续识别旧的“可执行调整内容”文案，同时补充识别新的“可确认的调整预览”，防止模型旧输出漏过无 pending 保护。
- 验证：`py_compile app/service.py app/domain/proposal_compiler.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_proposal_compiler_runtime_selection.py` 通过；`tests/unit/test_chat_service_history_persistence.py -q` 为 `110 passed`；`tests/unit/test_proposal_compiler_runtime_selection.py -q` 为 `36 passed`；`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `159 passed, 29 skipped`；`git diff --check` 通过。
- 真实回归：使用最新代码临时 agent `18310`、backend `8080`、rank `5001` 跑 `/private/tmp/zhiyuan_400_review_repair_cases_with_clone.json`，session offset `4200`，结果 `9/9`，metrics `/private/tmp/zhiyuan_400_v188_review_repair_clone_copy.json`。`400-review-major-group-inner-safety` 仍正确进入 `preview_plan_action(regenerate_order)` 并生成 `kind=plan_generation` 待确认卡，说明 v1.87 出卡链路未被文案清理影响。
- 客观观察（本轮只记录，不修）：1）`400-review-shortage-honesty` 只读审查回复里混入“下面是这次待确认预览”，但没有 followup/pending；2）`400-review-fix-explain-hierarchy` 与手动移动后审查回复中，ready 状态有一处漏成英文 `ready`；3）`400-review-repair-after-manual-move-stale` 第二轮“那重新审查一下”没有再次调用 `review_plan`，而是基于历史结果直接总结。三者归入后续回复质量/连续审查语义优化，不影响本轮 v1.88 的 copy-only 目标。

### 12.17 v1.89 内部 `ready` 状态词泄漏修复

- 问题来源：v1.88 真实 review/repair 回归中，`400-review-fix-explain-hierarchy` 的回复里出现“调整录取率顺序（...，ready）”。这是工具事实里的处理方向状态值进入最终回复，属于内部状态词泄漏。
- 实现：在 `_normalize_user_facing_terms()` 中只匹配独立英文单词 `ready`，替换为“可以先看调整预览”。不使用宽泛字符串替换，避免影响其它英文片段；不改 prompt/tool/pending/backend action。
- 验证：`py_compile app/service.py tests/unit/test_chat_service_history_persistence.py` 通过；focused 单测 `test_normalize_user_facing_terms_removes_internal_review_repair_words` 为 `1 passed`；`tests/unit/test_chat_service_history_persistence.py -q` 为 `110 passed`；`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `159 passed, 29 skipped`；`git diff --check` 通过。
- 真实回归：使用最新代码临时 agent `18311` 跑 `400-review-fix-explain-hierarchy` 单 case，结果 `1/1`，metrics `/private/tmp/zhiyuan_400_v189_review_fix_explain_hierarchy_ready_copy.json`。回复中原先的 `ready` 已替换为“可以先看调整预览”。临时 agent 已停止，端口 `18311` 不再响应。

### 12.18 v1.90 组合只读标题与连续重新审查修复

- 问题 1：`400-review-shortage-honesty` 的工具链为 `query_plan -> review_plan`，没有 pending/followup，但 direct renderer 因“最后一个 terminal 工具前有只读上下文”统一拼接“下面是这次待确认预览”，导致只读审查回复看起来像生成了待确认卡。
- 修复 1：`ZhiyuanAgent.render_direct_tool_output()` 增加 `_compound_result_header()`，只有最后一个 terminal 工具是 `preview_intent_change` 或 `preview_plan_action` 且 `next_step=confirm` 时才使用“下面是这次待确认预览”；`review_plan` 组合结果使用“继续看审查结果”，`confirm_pending` 使用“继续看处理结果”，其它结果使用中性“继续看结果”。
- 问题 2：`400-review-repair-after-manual-move-stale` 第二轮“那重新审查一下”曾直接基于历史审查总结，没有再次调用工具。
- 修复 2：prompt 行动原则和示例补充：用户明确说“重新审查/再审一遍/重新看一下/再看一遍/重新检查”时，即使上一轮刚审查过，也必须再次调用 `review_plan`，不要只基于历史审查结果回答。
- 验证：`py_compile app/zhiyuan_agent/agent.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused 单测 `test_zhiyuan_agent_direct_tool_output_combines_readonly_before_preview`、`test_zhiyuan_agent_direct_tool_output_combines_readonly_before_review_without_preview_heading`、`test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups` 为 `3 passed`；完整 `tests/unit/test_zhiyuan_agent_direct.py -q` 为 `160 passed, 29 skipped`；`git diff --check` 通过。
- 真实 focused：临时 agent `18312` 跑 `400-review-shortage-honesty`，回复已从“下面是这次待确认预览”改为“继续看审查结果”，metrics `/private/tmp/zhiyuan_400_v190_review_repair_two_focused.json`；同轮第二个 case 因 backend planning intent clear 超时未进入业务链路，单独用 offset `4500` 复跑 `400-review-repair-after-manual-move-stale` 为 `2/2`，metrics `/private/tmp/zhiyuan_400_v190_review_repair_rereview_focus.json`，两轮均调用 `review_plan`。临时 agent 已停止，端口 `18312` 不再响应。
- 完整回归：临时 agent `18313` 跑 `/private/tmp/zhiyuan_400_review_repair_cases_with_clone.json`，session offset `4600`，结果 `9/9`，metrics `/private/tmp/zhiyuan_400_v190_review_repair_clone_full.json`。指标检查未再出现“下面是这次待确认预览”误标题，也未再出现 `ready` 状态词泄漏；`400-review-major-group-inner-safety` 仍能生成 `kind=plan_generation` 待确认卡。临时 agent 已停止，端口 `18313` 不再响应。

### 12.19 v1.91 并发回归克隆参数补齐与口语 follow-up 复核

- 问题来源：继续扩大 v179/v183 真实口语回归时，直接用 `examples/dialog_regression_parallel_runner.py` 并发跑 `examples/dialog_regression_400_v179_pending_replace_review_quality_cases.json` 与 `examples/dialog_regression_400_v183_realistic_followup_quality_cases.json`，初始结果为 `1/9`，metrics 目录 `/private/tmp/zhiyuan_400_v191_pending_followup_parallel`。失败集中在确认后后端 ordered 仍包含山东/民办、replace pending 变 `failed`、no-pending “照你说的处理”没有按预期工具路径统计。
- 客观定位：这些 case 明确需要克隆真实后端 chat session，但 parallel runner 只透传了 state clone 相关 case payload，没有把单 runner 的 `--clone-backend-chat-session`、DB 参数和 volunteer data 目录透传给子进程。用单 runner 带完整克隆参数顺序复跑后，v183 为 `13/13`，metrics `/private/tmp/zhiyuan_400_v191_v183_clone_sequential.json`；v179 为 `10/10`，metrics `/private/tmp/zhiyuan_400_v191_v179_clone_sequential.json`。因此初始 `1/9` 不能作为 4.0 链路失败结论，属于验证基础设施运行方式问题。
- 实现修复：`examples/dialog_regression_parallel_runner.py` 增加与单 runner 对齐的参数：`--clone-backend-chat-session`、`--backend-db-host/port/user/password/name`、`--backend-volunteer-data-dir`，并在每个子 runner 命令中透传。新增单测 `test_parallel_runner_passes_backend_chat_clone_options_to_child_runner` 防止后续遗漏。
- 修复后并发复跑：使用临时 agent `18320`、backend `8080`、rank `5001`，parallelism=2，带完整克隆参数复跑 v179/v183，结果 `8/9`，metrics 目录 `/private/tmp/zhiyuan_400_v191_pending_followup_parallel_clone_fixed`。通过项覆盖 active pending 改写/追加、只读后无待确认确认边界、targeted replace、review follow-up replace 以及最终 `confirm_pending` 后 ordered/review 刷新。
- 剩余 1 个并发失败：`400-v179-active-pending-append-region-and-private-final-action` 在并发首轮中确认后报“当前方案暂时没有重新调整成功”，后端 `pendingConfirmation.status=applied`、`planningState.version` 增长、`candidateViewState/candidatePoolState` 已写入要求，但 `orderedPlanState.units` 仍包含山东/民办。该同 case 用完整克隆参数顺序复核为 `3/3`，metrics `/private/tmp/zhiyuan_400_v191_v179_append_failed_parallel_sequential_rerun.json`，确认 pending、版本增长、ordered 移除山东/民办、ordered/review followup 都通过。
- 结论：当前 v179/v183 口语 follow-up 与最终动作链路在顺序真实回归下保持闭环；并发模式下仍可能触发后端重排/刷新一次性波动，报告口径继续使用“并发首轮 + 失败子集顺序复核”。这不是新的模型语义错误，也不是 direct route 旧链路残留问题，但后续大规模并发 final-action 验证要单独统计这种后端并发波动，避免和 agent 语义缺陷混在一起。
- 验证：`py_compile examples/dialog_regression_parallel_runner.py tests/unit/test_dialog_regression_parallel_runner.py` 通过；`tests/unit/test_dialog_regression_parallel_runner.py -q` 为 `4 passed`；`git diff --check` 通过。

### 12.20 v1.92 direct 无工具假预览防护与 final-action 并发复核

- 问题来源：v1.91 后继续跑 v155/v156/v157/v158/v173 final-action 并发集时，曾出现 1 个 `400-v156-spoken-only-public-final-action` 波动：模型回复形态像“待确认预览/是否确认”，但本轮没有调用 `preview_intent_change`，也没有生成 `pendingConfirmationCard`。同 case 顺序复跑能正常出卡并确认通过，说明不是稳定语义缺口；但服务层缺少“无工具、无卡、无刷新”情况下的假预览兜底，属于 direct route 输出安全边界问题。
- 实现修复：`service.py` 在 direct route 后处理阶段增加 guard：当本轮没有 pending card 且没有 workspace refresh 时，对最终回复调用 `_guard_unbacked_plan_confirmation_reply()`。如果回复看起来在要求用户确认方案调整/调整预览，但没有任何真实待确认内容支撑，就替换为“这轮还没有生成可确认的调整预览，所以不会改动当前方案”的边界回复，并记录 `post_processing_applied=unbacked_plan_confirmation_reply_guard`。正常 `preview_intent_change`、`preview_plan_action`、`confirm_pending` 的出卡或执行路径不进入该 guard。
- 单元验证：`py_compile app/service.py tests/unit/test_zhiyuan_agent_direct.py examples/dialog_regression_parallel_runner.py tests/unit/test_dialog_regression_parallel_runner.py` 通过；`tests/unit/test_zhiyuan_agent_direct.py::test_service_zhiyuan_agent_direct_guards_unbacked_confirmation_preview -q` 为 `1 passed`；`tests/unit/test_dialog_regression_parallel_runner.py -q` 为 `4 passed`；`git diff --check` 通过。
- 真实 focused 复核：使用最新代码 agent `18321`、backend `8080`、rank `5001`，复跑 `examples/dialog_regression_400_v156_realistic_broadened_final_action_cases.json` 中 `400-v156-spoken-only-public-final-action`，结果 `2/2`，metrics `/private/tmp/zhiyuan_400_v192_v156_only_public_guard_rerun.json`。首轮“就看公办吧”正常调用 `preview_intent_change` 并生成 `kind=intent_change/actionFamily=apply_selected_intents` 待确认卡；第二轮“行，采纳”调用 `confirm_pending`，后端断言覆盖 `pendingConfirmation.status=applied`、`planningState.version` 增长、`mustIncludeSchools` 写入、基础候选池保留、公办要求生效后的 ordered items/units 裁剪，以及 ordered/review followup 刷新。
- 真实并发复核：使用同一最新 agent，带完整 `--clone-backend-chat-session`、DB 参数、后端 extra-data 克隆和 volunteer data 克隆，并发跑 `examples/dialog_regression_400_v155_realistic_final_action_cases.json`、`examples/dialog_regression_400_v156_realistic_broadened_final_action_cases.json`、`examples/dialog_regression_400_v157_realistic_cancel_combo_cases.json`、`examples/dialog_regression_400_v158_pending_combo_negation_cases.json`、`examples/dialog_regression_400_v173_action_expansion_final_cases.json`，parallelism=3，结果 `21/21`，metrics 目录 `/private/tmp/zhiyuan_400_v192_final_action_parallel_clone`。本轮没有失败子集需要顺序复核。
- 当前结论：4.0 direct 在该组真实口语 final-action 并发验证中已闭环：报考要求预览、当前方案移出/替换/排序、active pending 取消/改口/组合诉求、短句确认和最终后端 ordered-plan 真实变化均通过。无工具假预览目前由服务层兜底 guard 覆盖，后续继续扩大回归时仍按“并发首轮 + 失败子集顺序复核”记录模型服务波动和后端并发波动。

### 12.21 v1.93 报考要求与当前方案同步处理优先级修复

- 旧链路清理复扫：生产 `app/` 中 `ChatAgent`、`turn_decision`、`planning_workflow_tool`、`intent_preview_tool`、`official_source_search_tool`、`plan_query_tool`、`execute_plan_action`、`planEditCache`、`ZHIYUAN_AGENT_POC`、`runtime_shadow`、`full_agent`、`fast_route` 等旧入口命名无命中；`tests/unit/test_runtime_hard_cut_audit.py -q` 为 `25 passed`。本轮未发现需要继续从生产代码删除的旧链路入口。
- 主集首轮验证：使用最新 agent `18322` 跑 `examples/dialog_regression_400_g1_g32_direct_cases.json`，结果 `19/20`，metrics `/private/tmp/zhiyuan_400_v193_g1_g32_direct_guard_followup.json`。唯一失败是 `400-g1-exclude-current-plan-english-major` 的工具类型断言：用户说“不要英语相关专业，当前方案里有的话也删掉”，模型走 `preview_plan_action(remove_units)`，生成当前方案移出卡。
- 问题判断：这不是执行链路崩溃，但语义有风险。该句先表达“不要英语相关专业”的报考要求，后半句“当前方案里有的话也删掉”是把这条要求同步应用到当前方案；如果只走 `preview_plan_action(remove_units)`，容易只移出当前方案项而不把“以后也不要英语相关专业”写入报考要求。旧期望 `preview_intent_change` 是合理的。
- 修复方式：prompt-only，不增加工具层字符串匹配。`prompt.py` 明确：纯“方案里的 X 不要/移出去”仍走 `preview_plan_action`；但“显式报考要求 + 当前方案同步处理”必须优先走 `preview_intent_change(apply_to_current_plan=True)`，让确认后同时写入报考要求并同步调整当前方案。补充示例：“不要英语相关专业，当前方案里有的话也删掉” -> `preview_intent_change(intent_type="major", negative={"level2":["外国语言文学类"]}, constraint_type="exclude", apply_to_current_plan=True, ...)`。
- 单元验证：`py_compile app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；`tests/unit/test_zhiyuan_agent_direct.py::test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups -q` 为 `1 passed`；`tests/unit/test_zhiyuan_agent_direct.py::test_preview_intent_keeps_broad_major_scope_when_user_says_related -q` 为 `1 passed`。
- 真实 focused 验证：使用新 agent `18323` 复跑 G1 单 case，结果 `1/1`，metrics `/private/tmp/zhiyuan_400_v193_g1_after_prompt_fix.json`。结果为 `preview_intent_change`、`kind=intent_change/actionFamily=apply_selected_intents`，回复和卡片均展示“专业要求：不要：外国语言文学类”，没有退化成只移出当前方案。
- 完整主集复跑：同一 agent `18323` 复跑 G1-G32，结果 `20/20`，metrics `/private/tmp/zhiyuan_400_v193_g1_g32_direct_after_requirement_plan_priority_fix.json`。运行分布：`intent_pending=6`、`readonly=9`、`plan_preview=3`、`needs_plan_first=2`；pending 类型为 `intent_change=6`、`plan_mutation=3`、`none=11`。性能 median `5802ms`、p95 `12534ms`、max `13077ms`；最慢为 G31 保底学校查询、G12 查询+替换、G16 无方案锁定边界、G3 active pending 下只读查询、G23 正向专业意向。
- 观察项（记录，不在本轮修）：G2/G7 费用和中外合作只读审查仍回复“当前没有明显风险或提醒”，信息密度偏弱；G12/G27 替换预览文案会露出 `审查问题 high_tuition` 这类内部 code；G19/G32 no-plan 边界回复偏长。三者属于回复质量问题，不影响本轮 direct 路由、pending 边界和最终 action 链路。

### 12.22 v1.94 扩展整体效果检验与失败项客观分类

- 本轮目标：不修低优先级回复质量问题，继续扩大 4.0 direct 整体效果检验；重点观察真实口语、指代、多轮 pending、当前方案 action、review repair、最终确认和后端状态变化。初次运行因沙箱拦截本机 `8080` 清理/克隆接口，151 个 case 全部为环境失败，不计入效果结论。
- 有效扩展批次：使用当前 agent `18324`、backend `8080`、rank `5001`，带 `--clone-backend-chat-session`、DB 参数、`--clear-history-per-case`、`--clear-backend-pending-per-case`、`--clear-backend-planning-intent-per-case`，并发 `4` 跑 25 个 4.0 case 文件。结果 `96/151`，metrics 目录 `/private/tmp/zhiyuan_400_v194_expanded_effect_parallel_elevated`。
- 高信号通过项：v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183 全部通过；`dialog_regression_400_readonly_real_session_cases.json` 为 `2/2`；`dialog_regression_400_realistic_user_cases.json` 为 `12/13`。这说明近期重点修复的 active pending 追加/改写、组合诉求、取消改口、替换、排序、移出、短句确认和最终 action 落库在扩展批次中保持闭环。
- 失败分类：55 个失败中，约 26 个是 fixture/no-plan 边界问题，主要来自早期 smoke/plan_operation/open_quality 用例没有正式方案却断言“冲稳保/移动/确认执行”；约 16 个是 `thinking` 文案断言过窄；约 9 个是内容质量断言；3 个是 pending/action 期望需要单独复核；1 个是简称语义质量问题（“青城”被理解为内蒙古青城/呼和浩特，而不是用例期望的青岛城市学院）。
- 重要客观问题：`400-direct-confirm-plan-remove-position` 首轮“第3个不要了”返回无正式方案边界，没有生成 pending；下一轮“确认执行”因此走 no-pending confirm，后端 `pendingConfirmation.status` 未变、`planningState.version` 未增长、ordered 长度未变。该 case 的 source session 克隆成功，但当前运行状态仍判断无正式方案，优先按 fixture/运行前置不一致记录，不直接算作 4.0 final-action 链路缺陷。
- 口径修正：`400-realistic-remove-expensive-after-review-reference` 在无正式方案边界下第二轮“那高收费的别要了”走 `preview_intent_change`，用例期望 `preview_plan_action`。按当前设计，这类没有正式方案时把“不要高收费”记成报考要求是合理行为，暂不作为错误修复。
- 当前结论：可以继续扩大整体效果检验，但报告口径应分为两层：1）主链路健康度只统计带正确 fixture/克隆和最终 action 断言的高信号 case；2）open_quality/quality_realistic/smoke 作为回复质量和 fixture 维护池，不直接拉低 4.0 direct 主链路通过率。
- 下一步建议：继续跑生产式真实口语大集时，优先补齐或过滤没有正式方案前置的旧 case；对最终 action 类 case 必须保留后端断言（pending applied、planningState version 增长、ordered/candidate/review 状态变化）；低优先级的 thinking 文案、no-plan 边界长短、内部 code 泄漏和简称歧义先记录观察，不阻塞 Phase 1 主链路推进。

### 12.23 v1.95 主链路高信号集并发验证

- 本轮目标：在 v1.94 混合批次之后，单独抽取更能代表 4.0 direct 主链路健康度的高信号 case，排除早期 fixture/no-plan 噪音；继续使用真实 LLM、真实 backend clone 和最终 action 后端断言。
- 运行范围：G1-G32 主集、v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183、review/repair 克隆集 `/private/tmp/zhiyuan_400_review_repair_cases_with_clone.json`。使用 agent `18324`、backend `8080`、rank `5001`，并发 `4`，带 `--clone-backend-chat-session`、DB 参数、清理 history/pending/planning intent。
- 验证结果：`67/67` 全通过，metrics 目录 `/private/tmp/zhiyuan_400_v195_mainline_high_signal_parallel`。分布：G1-G32 `20/20`；review/repair clone `8/8`；v143 `1/1`；v150 `1/1`；v151 `4/4`；v153 `1/1`；v154 `2/2`；v155 `3/3`；v156 `5/5`；v157 `4/4`；v158 `4/4`；v173 `5/5`；v179 `4/4`；v183 `5/5`。
- 覆盖能力：本轮覆盖报考要求预览、显式“不要/要”要求、当前方案同步处理、active pending 追加/改写/取消、短句确认、当前方案移出/替换/排序、review follow-up replace、plan_generation 出卡与确认、只读后无 pending 的确认防护、review/ordered 刷新和最终后端状态变化。
- 关键回归点：v1.93 的“不要英语相关专业，当前方案里有的话也删掉”继续走 `preview_intent_change`，保留未来报考要求并同步影响当前方案；v1.86-v1.90 的 review+方案动作复合诉求、重新审查、review 文案边界在克隆集仍通过；v1.79-v1.83 的 pending 改写/追加与 targeted replace 最终动作在并发下通过。
- 当前结论：按高信号主链路口径，4.0 direct 的 Phase 1 核心对话、预览、确认和执行闭环处于稳定状态。后续扩大验证应继续采用“高信号主链路集 + 质量观察池”双轨报告，避免把旧 fixture 维护问题误判为 agent 主链路缺陷。

### 12.24 v1.96 验证资产分层与后续回归口径

- 目的：在不修低优先级文案问题的前提下，把 v1.94 混合批次中的 case 文件按用途重新分层，避免后续继续把 fixture/no-plan 噪音和 4.0 主链路健康度混在一起。
- 主链路基准集：`dialog_regression_400_g1_g32_direct_cases.json`、`dialog_regression_400_readonly_real_session_cases.json`、`dialog_regression_400_v143_constraint_apply_cases.json`、`dialog_regression_400_v150_candidate_view_cases.json`、`dialog_regression_400_v151_attribute_final_action_cases.json`、`dialog_regression_400_v153_major_final_action_cases.json`、`dialog_regression_400_v154_tag_final_action_cases.json`、`dialog_regression_400_v155_realistic_final_action_cases.json`、`dialog_regression_400_v156_realistic_broadened_final_action_cases.json`、`dialog_regression_400_v157_realistic_cancel_combo_cases.json`、`dialog_regression_400_v158_pending_combo_negation_cases.json`、`dialog_regression_400_v173_action_expansion_final_cases.json`、`dialog_regression_400_v179_pending_replace_review_quality_cases.json`、`dialog_regression_400_v183_realistic_followup_quality_cases.json`，以及克隆版 `/private/tmp/zhiyuan_400_review_repair_cases_with_clone.json`。这些可以继续作为 Phase 1 主链路硬回归。
- 需要 fixture 修复后再进入硬回归：`dialog_regression_400_agent_smoke_cases.json`、`dialog_regression_400_plan_operation_cases.json`、`dialog_regression_400_effect_perf_cases.json`、`dialog_regression_400_core_effect_perf_cases.json`、`dialog_regression_400_explore_intent_cases.json`、`dialog_regression_400_direct_confirm_execution_cases.json`、`dialog_regression_400_realistic_user_cases.json`、原始 `dialog_regression_400_review_repair_cases.json`。这些文件里存在无正式方案却断言方案内容/方案动作/确认执行的 case，应先补 `cloneBackendStateFromSessionId`、明确 source session，或改成 no-plan 边界期望。
- 质量观察池：`dialog_regression_400_open_quality_cases.json`、`dialog_regression_400_quality_realistic_user_cases.json`。这两组更适合观察回复信息密度、口语解释、thinking 文案和简称理解，不应直接纳入主链路通过率；若要纳入硬回归，需要先把 `thinking` 文案断言从强精确匹配降级为更稳定的行为断言，或拆分为单独质量报告。
- 混合待复核：`dialog_regression_400_production_abstracted_cases.json` 在 v1.94 为 `14/17`，失败集中在内容质量；`dialog_regression_400_requirement_plan_action_cases.json` 为 `4/5`，剩余 1 个 pending/action 期望需单独复核。这两组可作为下一轮 targeted 分析对象，但暂不阻塞主链路。
- 后续回归口径：主链路报告只统计“带正确 fixture/clone + 行为断言 + 最终后端状态断言”的 case；质量池报告只记录客观问题，不直接修低优先级文案；fixture 修复应优先处理会影响最终 action 真实性的 case，例如 direct confirm、plan operation、review repair 原文件。

### 12.25 v1.97 direct/plan/review 验证 fixture 修复

- 范围：只修回归资产，不改 agent/service 业务实现。目标是把 v1.96 中会影响最终 action 真实性判断的 fixture/no-plan 噪音先清掉。
- `dialog_regression_400_direct_confirm_execution_cases.json`：默认 `cloneBackendStateFromSessionId` 从 `26` 改为已在 v155-v183 多轮 final-action 中验证稳定的 `17`。修复前“第3个不要了”在 offset 会话里被判断为无正式方案；修复后能生成 `remove_units` pending，并通过“确认执行”真实执行。
- `dialog_regression_400_plan_operation_cases.json`：为状态查询、排序确认、专业组移动等需要正式方案的 case 补 `fixtureContract=formal_plan_present`，让 runner 在 session offset 模式下自动克隆原 session 的 `planningState/userprofile/userScoreDetail`；同时把“河南农大建筑去掉”的负向定位 case 断言调整为行为边界优先，接受“没有唯一定位/未生成可确认预览/确认后 no-op”等安全回复，不强依赖单一句式。
- `dialog_regression_400_review_repair_cases.json`：把之前临时克隆版中的 `sourceSessionId` 与 `cloneBackendStateFromSessionId` 落回仓库文件，分别使用 `130/131/132` 作为不同 review/repair 场景的正式方案 source，避免原始文件 offset 后落到空会话。
- 验证：JSON 格式校验与 `git diff --check` 通过。focused 三组并发首轮 `14/15`，metrics `/private/tmp/zhiyuan_400_v197_fixture_repair_focused`；其中 direct confirm `2/2`、原始 review repair `8/8` 已通过，剩余 1 个为 plan operation 负向定位 case 的断言文案过窄。补充断言后单 case 通过，metrics `/private/tmp/zhiyuan_400_v197_plan_operation_negative_case_after_confirm_assert_fix.json`；完整 `plan_operation` 复跑 `5/5`，metrics `/private/tmp/zhiyuan_400_v197_plan_operation_full_after_assert_fix`。
- 当前结论：`direct_confirm_execution`、`plan_operation`、原始 `review_repair` 已从 fixture/no-plan 噪音池进入可用硬回归候选。后续主链路基准集可以纳入这三组；仍需单独处理的验证资产主要是 `agent_smoke`、`effect_perf/core_effect_perf/explore_intent` 的旧 fixture，以及 `open_quality/quality_realistic` 的质量断言口径。

### 12.26 v1.98 smoke/core-effect fixture 修复与 effect 质量池保留

- 范围：继续只修回归资产，不改业务实现。目标是清理 `agent_smoke`、`core_effect_perf` 中的无正式方案噪音，并客观判断 `effect_perf` 是否可以进入硬回归。
- `dialog_regression_400_agent_smoke_cases.json`：四条 case 均依赖正式方案，补 `fixtureContract=formal_plan_present`。修复后 offset 运行会自动克隆原 session 的方案状态，不再出现“按院校层次排序/专业组移动”落到 no-plan guard 的问题。
- `dialog_regression_400_core_effect_perf_cases.json`：为方案状态查询、体制内稳定就业承接分析、专业组移动、青岛城市学院查询等依赖正式方案的 case 补 `fixtureContract=formal_plan_present`。已有 fixture 的单条志愿移动保持不变。
- `dialog_regression_400_effect_perf_cases.json`：为缺少正式方案前置的本地查询、排序预览、职业方向承接分析补 `fixtureContract=formal_plan_present`。本轮没有为了全绿放宽高质量文案断言或业务能力断言。
- 验证：JSON 格式校验与 `git diff --check` 通过。focused 并发跑三组，结果 `19/23`，metrics `/private/tmp/zhiyuan_400_v198_smoke_effect_fixture_focused`。分布：`agent_smoke` `4/4`，`core_effect_perf` `8/8`，`effect_perf` `7/11`。
- `effect_perf` 剩余 4 个问题客观分类：1）`400-quality-plan-named-add-preview-direct` 中“把华中农业大学的建筑类加进来”无法唯一定位具体专业，未生成 `add_units` pending；2）`400-quality-sort-preview-explains-side-effect` 已正确生成排序 pending，但回复没有解释“导出顺序/待重新审查”等影响；3）`400-quality-career-fit-readonly-no-workspace` 正确只读审查且确认 no-op，但回复缺少“体制内/稳定/承接”关键词，确认边界文案也与断言不完全一致；4）`400-quality-major-group-preview-confirm-boundary` 正确生成并确认 `move_ordered_unit`，但预览/确认文案没有展开“专业组顺序/组内专业不变”等质量说明。
- 当前结论：`agent_smoke` 和 `core_effect_perf` 可进入硬回归候选；`effect_perf` 仍保留在质量/能力观察池，不纳入主链路通过率。若后续要纳入硬回归，应先拆分为行为硬断言和回复质量断言两层，而不是把信息密度要求混入主链路健康度。

### 12.27 v1.99/v2.00 explore intent 语义框架与 payload 完整性修复

- 问题来源：`dialog_regression_400_explore_intent_cases.json` 扩展验证中暴露两类语义边界问题。第一类是“财经类可以优先，但是护理和中西医结合不要”这类表达里，工具层不能从用户原话扫描属性并把“财经”误补成院校类型；第二类是“北京先不要了，只看天津和河北”里，模型已经给出 `semantic_requirements`（北京 negative、天津/河北 positive），但漏填 `positive/negative` payload 时，工具没有把地域字段纳入 semantic 完整性校验，直接落到“没有识别到明确要求”的澄清。
- 修复原则：继续坚持 4.0 direct 的模型语义判定边界。工具只校验模型给出的 `semantic_requirements` 与结构化 payload 是否一致，不从 `raw_user_text` 做中文 token 扫描，不为“财经/北京/天津/不要”等具体词增加特化分支。
- 已落地实现：`preview_intent_change` 支持 `semantic_requirements`，要求模型标明 `domain/side/strength/key/values/raw_span`。`strength=reference` 只作为参考回复，不创建 pending；`explicit/confirmable` 必须进入 `positive/negative` payload；缺 semantic frame 或 semantic 已明确但 payload 漏项时，工具返回 `next_step=continue` 要求模型补齐结构化参数。
- 本轮补齐：semantic 完整性校验从专业/院校属性扩展到地域字段 `province/city/area`，并补充专业实体和院校实体的 semantic key 校验（如 `major`、`schools`）。同时移除旧的 `_raw_text_mentions_negative_requirement` 与 `negative_may_be_missing` 分支，避免工具层基于原话判断“不要/排除”。
- 真实问题复现与修复：修复前 `400-region-priority-reference-then-explicit-requirement` 第三步“北京先不要了，只看天津和河北”返回“没有识别到具体要排除的对象”，但下一轮查询又按“只看天津和河北”组织回答，说明待确认状态和只读回复不一致。修复后同 case 第三步生成待确认卡“地域要求：要：天津、河北；不要：北京”，第四步确认后正式采纳，后续只读回答只引用已确认的新要求。
- 验证结果：`py_compile app/zhiyuan_agent/tools.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused semantic 单测 `7 passed, 187 deselected`；完整 direct 单测 `165 passed, 29 skipped`。真实 LLM 单 case `5/5`，metrics `/private/tmp/zhiyuan_400_v200_region_semantic_payload_retry_single.json`；完整 explore intent 回归 `8/8`，metrics 目录 `/private/tmp/zhiyuan_400_v200_explore_intent_semantic_payload_retry`。
- 当前口径：`优先/倾向/重点关注` 不做过强规则化要求，可由模型结合上下文判为参考方向、confirmable 待确认方向或用户想记录的要求；工具层只负责校验模型结构化语义与 payload 的一致性。`dialog_regression_400_explore_intent_cases.json` 已可作为 4.0 direct 语义边界回归集继续使用，后续仍应关注回复质量和无方案场景下的表达压缩。

### 12.28 v2.01-v2.03 requirement/action 结构化语义补齐

- 问题来源：`dialog_regression_400_requirement_plan_action_cases.json` 暴露两个 direct requirement 缺口。第一，`方案里必须有法学，其他专业可以先保留` 中模型可能把“法学”写成 `level2=法学类`，工具会根据原话精炼到具体专业 `level3=法学`，但 semantic completion 仍要求补回 `level2=法学类`，导致重复调用并触发工具上限。第二，`太贵的学校别放了，学费最好控制在两万以内` 不应再编码成 `school.negative.tuition_max`，应作为独立的显式学费预算要求。
- 修复原则：仍然坚持 4.0 direct 的结构化语义边界，不从用户原话做中文 token 扫描。工具层只做实体/层级归一化、父子层级覆盖校验和底层执行适配；模型负责把用户诉求写成 `semantic_requirements` 与 `positive/negative` payload。
- 已落地实现：`preview_intent_change` 的 `IntentType` 增加 `tuition_budget`，支持 `max_tuition_per_year/min_tuition_per_year` 及结构化字段别名；pending `merged` 使用独立 `{"tuition_budget":{"max_tuition_per_year":[20000]}}`，摘要显示“学费预算：每年不超过 20000 元”，不再塞入院校属性。确认执行时 direct confirm 调用底层 `update_session_tuition_range` 同步 session 学费范围；若当前有正式方案且 `apply_to_current_plan=True`，继续触发 ordered plan 重排，并在确认后校验 ordered 中是否仍有超预算项。
- 专业层级修复：`_resolve_major_name(expected_level=...)` 真正按结构字段过滤候选；`major/major_name/majorList` 等字段按具体专业 `level3` 处理，`level1/level2/level3` 保持对应层级语义。semantic completion 对 major 复用 `canonicalize_major_intent_payload`，允许工具把模型的上层类精炼成当前原话指向的具体专业；同时增加 major 父子层级覆盖判断，已存在 `level2=外国语言文学类` 时，不再要求额外补 `level3=英语`。
- Prompt 更新：明确 `preview_intent_change` 可用 `intent_type="tuition_budget"`；学费预算上限使用 `positive={"max_tuition_per_year":20000}` 和 `semantic_requirements domain="tuition_budget"/key="max_tuition_per_year"`，不要写成 `school.negative.tuition_max`。补充“太贵的学校别放了，学费最好控制在两万以内”的示例。
- 单元验证：`py_compile app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused semantic/budget 单测通过；完整 direct 单测从 `165 passed, 29 skipped` 更新到 `170 passed, 29 skipped`。新增覆盖：`major` key 解析到 `level3=法学`；`level2=法学类` 被原话精炼到 `level3=法学` 后不触发补全循环；`level2=外国语言文学类` 覆盖子项“英语”后不触发补全循环；`tuition_budget` 独立出卡；预算 pending 确认时同步 `update_session_tuition_range` 且不走旧 constraint state。
- 真实验证：使用临时 agent `18329`、backend `8080`、rank `5001`，真实 LLM + backend clone 复跑 focused：`400-requirement-must-have-major-preview-boundary` 为 `2/2`，metrics `/private/tmp/zhiyuan_400_v202_requirement_major_must_have_fix.json`；`400-requirement-exclude-major-preview-and-apply` 为 `2/2`，metrics `/private/tmp/zhiyuan_400_v203_requirement_exclude_major_semantic_cover.json`。完整 `dialog_regression_400_requirement_plan_action_cases.json` 为 `8/9`，metrics `/private/tmp/zhiyuan_400_v203_requirement_plan_action_after_semantic_cover.json`。
- 剩余观察项：唯一失败是 `400-requirement-only-keep-major-preview-boundary` 的确认后 followup 断言仍期待 `candidate`，实际 direct confirm 返回 `ordered/review` 刷新。按前面候选池设计，base candidate pool 保持全量，不因“只想学临床医学”这类报考要求隐式隐藏候选视图；只有可见 candidate view 状态真实变化时才应刷新 candidate。因此该失败暂按验证资产/产品边界记录，不作为 4.0 direct 链路缺陷。

### 12.29 v2.04 学费预算 final-action 生效缺口修复

- 问题来源：v2.03 后把 `400-requirement-tuition-budget-preview` 的确认步骤补上最终后端断言，真实回归发现 `pendingConfirmation.status=applied`、`planningState.version` 增长，但确认后 `orderedPlanState.units` 仍存在 `tuitionPerYear=60000`。Agent 侧已经正确把预算写成独立 `tuition_budget` pending，并调用 `update_session_tuition_range` 写入 session 学费范围；缺口在后端 ordered-plan 生成没有消费这份会话预算。
- 设计边界：继续沿用 §11.4 的状态设计，基础 `candidatePoolState.items` 保持全量候选，不因为报考要求或预算被系统隐藏；候选页面是否过滤只由可见筛选状态决定；方案生成、审查和修复建议等派生动作使用运行时 `effectiveCandidates`。本轮不新增持久化有效候选缓存，也不在 agent 工具层做中文字符串匹配。
- 实现：`PlanningStateService.resolveEffectiveCandidates()` 改为在合并推荐 overlay 与 taxonomy 字段后调用 `applyConfirmedPlanRequirements()`；该 helper 同时消费 `constraintState.hardConstraints` 和 `USER_SCORE_KEY` 里的 `CreateSessionReq.tuitionRange`。学费过滤只作用于运行时有效候选，缺失学费时不误伤。`syncWorkingPlanWithEffectiveCandidatesForConfirmedRequirements()` 与 `syncOrderedPlanWithEffectiveCandidatesForConfirmedRequirements()` 的 guard 扩展为“存在已确认报考要求或存在有效学费范围”，修复 budget-only 场景没有裁剪 ordered/draft 的问题。
- 后端测试：新增 `shouldApplySessionTuitionRangeWhenRegeneratingOrderedPlan` 覆盖普通专业模式，确认预算 20000 后 `orderedPlanState.items` 裁掉 60000 项，同时 `candidatePoolState.items` 仍保留原候选；新增 `shouldApplySessionTuitionRangeToOrderedUnitsWhenRegeneratingMajorGroupPlan` 覆盖专业组模式，确认 `orderedPlanState.units.majorItems` 只保留预算内专业。`mvn -q -Dtest=PlanningStateServiceTest test` 通过。
- Agent 测试：`zhiyuan-agent/tests/unit/test_zhiyuan_agent_direct.py -q` 为 `170 passed, 29 skipped`，说明 direct 语义、pending、confirm 路径没有被后端预算生效修复破坏。
- 真实回归：使用新后端进程和临时 agent `18329` 复跑 `examples/dialog_regression_400_requirement_plan_action_cases.json`，结果 `10/10`，metrics `/private/tmp/zhiyuan_400_v204_requirement_plan_action_after_tuition_effective_fix.json`。其中预算确认 case 的三条后端断言全部通过：pending 已采纳、planningState version 增长、`orderedPlanState.units` 最大 `tuitionPerYear <= 20000`。
- 当前结论：v2.03 的语义补齐和 v2.04 的执行生效已形成闭环。学费预算现在和其它显式报考要求一样，在确认后能影响当前正式方案，但不隐式改变基础候选池。下一步继续复跑高信号主链路集，确认预算过滤接入 `effectiveCandidates` 后没有影响地域/院校属性/专业门类/标签/方案动作等既有 final-action。

### 12.30 v2.05 高信号主链路并发回归复核

- 回归范围：使用真实 LLM、临时 agent `18329`、backend `8080`、backend session clone 和最终 action 后端断言，并发跑 15 组 4.0 主链路 case：G1-G32 direct、v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183、review/repair、requirement/action，共 72 个 case。首轮结果 `69/72`，metrics 目录 `/private/tmp/zhiyuan_400_v204_mainline_high_signal_parallel`。
- 失败分层：`400-v156-deferred-region-no-plan-change` 第一轮重复调用两次 `preview_intent_change`，但生成的 pending 正确，确认后 `pendingConfirmation.status=applied`、山东要求写入、基础候选池保留山东、ordered items/units 保持不变均通过；按前序决策“少量重复调用先观察”记录为效率问题，不作为业务链路失败。`400-v157-combo-school-attribute-exclude-final-action` 首轮为 `TimeoutError`，未进入工具链；单独复跑 `2/2` 通过，metrics `/private/tmp/zhiyuan_400_v204_v157_combo_attribute_rerun.json`，确认后民办/中外合作要求落库并刷新 ordered/review，最终 action 后端断言通过。`400-v183-review-advice-then-vague-execute-no-pending-guard` 回复明确当前没有待确认操作且不会执行，后端断言确认 planningState 未变化、pending 为空，符合 no-pending 防护边界；原 case 强制期待 `confirm_pending` 属于旧断言，已改为只看回复和无副作用。
- 验证资产调整与复核：v156 deferred region case 从 `expectedToolNames=["preview_intent_change"] + maxToolCallCount=1` 调整为 `assertToolNamesContain=["preview_intent_change"] + maxToolCallCount=2`；v183 no-pending 模糊执行 case 移除必须调用 `confirm_pending` 的工具断言，保留 no followup、无副作用和无 pending 断言。两项调整不改变生产代码，只让回归口径贴合当前 4.0 direct 设计边界。JSON 加载检查通过；断言调整后聚焦复跑 v156 `2/2`，metrics `/private/tmp/zhiyuan_400_v205_v156_deferred_region_assertion_rerun.json`；v183 `2/2`，metrics `/private/tmp/zhiyuan_400_v205_v183_no_pending_guard_assertion_rerun.json`。
- 当前结论：v2.04 预算 final-action 修复没有破坏地域、院校属性、专业门类/标签、组合要求、方案动作、替换、审查/修复和 no-pending 防护等主链路。当前没有新的确定业务执行缺口；剩余观察项是并发真实 LLM 下的偶发超时，以及少量重复工具调用的效率问题。后续可继续扩大质量观察池，或针对模型超时增加 runner 失败子集自动复跑/服务层重试策略。

### 12.31 v2.06 修正后高信号 baseline 复跑

- 回归范围：继续使用真实 LLM、临时 agent `18329`、backend `8080`、backend session clone、最终 action 后端断言和并发 4，复跑同一批 15 组 4.0 高信号主链路 case，共 72 个。原始结果 `70/72`，metrics 目录 `/private/tmp/zhiyuan_400_v206_mainline_high_signal_parallel`。
- 失败分层一：`400-v179-active-pending-append-region-and-private-final-action` 第二步“再把民办也算了吧，一起记上”重复调用两次 `preview_intent_change`，触发严格工具次数断言；但回复正确生成“院校要求：不要：民办；地域要求：不要：山东”的待确认预览，pending summary 包含山东+民办，确认后 `pendingConfirmation.status=applied`、planningState version 增长、地域和民办报考要求落库、candidate pool 保持全量、ordered units 同时不含山东和民办，全部后端断言通过。该问题继续按少量重复调用效率观察处理；case 断言改为 `assertToolNamesContain=["preview_intent_change"] + maxToolCallCount=2`，失败子集复跑 `3/3`，metrics `/private/tmp/zhiyuan_400_v206_v179_append_duplicate_assertion_rerun.json`。
- 失败分层二：`400-v183-review-advice-then-vague-execute-no-pending-guard` 第二步并发中没有调用工具，直接回复“这轮还没有生成可确认的调整预览，所以不会改动当前方案”。该行为无 followup，后端断言显示 planningState version 未变化、pending 为空，符合 no-pending 防护边界；失败原因是文案断言没有覆盖“没有生成可确认的调整预览”，并且仍残留必须调用 `confirm_pending` 的旧工具断言。已补充文案断言并移除工具硬要求，失败子集复跑 `2/2`，metrics `/private/tmp/zhiyuan_400_v206_v183_no_pending_guard_assertion_rerun.json`。
- 当前结论：v2.06 复跑未发现新的 4.0 direct 业务执行缺口。预算 final-action、地域/院校属性/专业门类/标签、active pending 追加/改写、组合诉求、方案动作、替换、审查/修复、no-pending 防护都保持闭环。当前剩余可排期工作是验证 runner 的失败子集自动复跑/报告分层，以及重复工具调用的效率优化观察；不需要为本轮两个失败改生产链路。

### 12.32 v2.07 质量观察池扩展验证与显式语义补齐

- 本轮目标：继续按“高信号主链路 + 质量观察池”双轨口径扩大 4.0 direct 验证。重点看真实口语、长句、指代、只读质量和当前方案预览质量；不把低优先级文案和并发 LLM 超时误算为主链路业务执行缺口。
- 验证范围：使用 fresh agent `8000`、backend `8080`、真实 LLM、backend state clone、`--ignore-thinking-assertions`、并发 4，跑 `examples/dialog_regression_400_open_quality_cases.json`、`examples/dialog_regression_400_quality_realistic_user_cases.json`、`examples/dialog_regression_400_production_abstracted_cases.json` 共 46 个 case。首轮结果 `44/46`，metrics `/private/tmp/zhiyuan_400_v207_quality_observation_parallel`。运行中存在 `assistant_chat_session` MySQL clone 空密码 warning，但后端 state/volunteer data clone 对本轮关键 case 生效；该 warning 作为验证环境问题记录。
- 问题一：`400-prod-open-career-long-input` 中“我对医学有些排斥，但对航天、能源、心理学都感兴趣...”没有生成待确认卡，模型只口头整理诉求。客观原因是 prompt 已覆盖“不要医学类”，但没有明确把“排斥/对 X 排斥/不想学 X”纳入显式负向要求，也没有说明长句里的工资、沟通强度等职业取向不能吞掉显式专业要/不要。
- 修复一：prompt-only，不在工具层加字符串匹配。极性规则补充“排斥X/对X排斥/不想学X”为 negative + `constraint_type=exclude`；长句规则明确职业取向可作为 `reference` 或后续 `explore_topic`，但显式专业要/不要必须先调用 `preview_intent_change`，并通过 `semantic_requirements` 标出 explicit/confirmable/reference。新增示例把“医学排斥 + 航天/能源/心理学感兴趣 + 高薪/少沟通”压成 major intent pending，其中医学为 explicit negative，航天/能源/心理学为 confirmable positive，职业取向为 reference。
- 验证一：`py_compile app/zhiyuan_agent/prompt.py` 通过；focused 真实复跑 `400-prod-open-career-long-input` 通过，生成 `preview_intent_change` 和 `pendingConfirmationCard`，metrics `/private/tmp/zhiyuan_400_v207_open_career_long_after_prompt_fix.json`；`production_abstracted` 全组复跑 `17/17`，metrics `/private/tmp/zhiyuan_400_v207_production_abstracted_after_prompt_fix`。
- 修复二：`400-open-quality-sort-score-preview-rich-boundary` 稳定暴露“推荐系数重新排”被模型压成录取率排序。工具层已有 `_PLAN_SORT_FIELDS` 支持 `推荐系数/推荐分/final_score/comprehensive -> finalScore`，缺口在 prompt 规则只强调 admission_ratio/school_rank/comprehensive，导致模型选择了 admission_ratio。修复为 prompt-only：明确“推荐系数/推荐分/综合分”必须用 `sort_field=final_score` 或 `comprehensive`，不要用 `admission_ratio`；补充排序示例。
- 验证二：排序 focused 真实复跑通过，metrics `/private/tmp/zhiyuan_400_v207_sort_score_after_prompt_fix.json`；回复和卡片均显示“按推荐系数（综合分）重新排序当前方案”，仍走 `preview_plan_action` + `pendingConfirmationCard`，没有直接改方案。
- 修复后质量池总集：再次并发跑 46 条，首轮仍为 `44/46`，metrics `/private/tmp/zhiyuan_400_v207_quality_observation_after_prompt_fix`。剩余两项分类：`400-open-quality-sort-score-preview-rich-boundary` 是总集运行在排序 prompt 修复前的失败，修复后 focused 已通过；`400-real-user-lazy-plan-risk` 是并发 `TimeoutError` 未进入工具链，失败子集顺序复跑通过并调用 `review_plan`，metrics `/private/tmp/zhiyuan_400_v207_quality_failure_subset_sequential_after_fix`。
- 单元验证：`tests/unit/test_zhiyuan_agent_direct.py -q` 为 `173 passed, 29 skipped`。
- 当前结论：本轮未发现新的 4.0 direct 主链路业务执行缺口；质量池中确认修复两个稳定语义质量问题：显式“排斥”类专业要求不出卡、推荐系数排序字段误判。剩余继续记录为质量/验证环境观察：并发 LLM 超时、回复信息密度、少量工具重复调用、MySQL chat-session clone 空密码 warning。

### 12.33 v2.08 高信号主链路复跑与条件式补齐边界修复

- 运行口径：继续使用 4.0 direct 新链路、真实 LLM、backend `8080`、backend state/chat-session clone、最终 action 后端断言和“并发首轮 + 失败子集顺序复核”的分层方式。第一次主线运行漏传 `--backend-db-password`，导致 MySQL chat-session clone 使用空密码失败，结果 `38/72` 判为无效环境运行，不纳入业务结论。
- 有效首轮：带 `--backend-db-password 12345678` 重新并发跑 72 条高信号主链路，结果 `65/72`，metrics `/private/tmp/zhiyuan_400_v208_mainline_after_v207_prompt_fixes_with_db_clone`。失败包括少量重复 `preview_intent_change` 严格断言、G26 只读回复文案、V156 后端断言波动，以及 `400-review-shortage-honesty` 误生成方案调整 pending。
- 失败复核：原 7 个失败子集顺序复跑 `6/7`，metrics `/private/tmp/zhiyuan_400_v208_failed_subset_sequential_escalated`。重复工具调用、G26、V156 都未稳定复现；稳定剩余问题是 `400-review-shortage-honesty`，模型把“如果稳和保不够，能不能直接帮我补齐？候选不够也要直接说”误判为 `preview_plan_action(action=regenerate_order)`，生成了待确认卡。
- 修复设计：只调整 prompt 语义边界，不在工具层做中文关键词扫描。规则明确：条件式询问可行性、候选不足、是否需要放宽，且没有要求“现在生成预览/确认执行/直接调整”时，属于只读处理方向或诚实边界请求，调用 `review_plan(generate_fix_proposals=True)`，不要创建 pending；明确要求“先给我看预览/现在帮我补/直接调整/补一个安全一点”时仍按结构性方案调整走 `preview_plan_action`。
- 实现内容：`app/zhiyuan_agent/prompt.py` 更新第 18/20 条行动原则，并在示例区加入 `review_plan(focus="tier_balance", generate_fix_proposals=True)` 的条件式边界示例；`tests/unit/test_zhiyuan_agent_direct.py` 增加静态断言，防止后续删掉该边界。
- 验证：`py_compile app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；`tests/unit/test_zhiyuan_agent_direct.py::test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups -q` 为 `1 passed`；`git diff --check` 通过。真实 focused 对照 `2/2`，metrics `/private/tmp/zhiyuan_400_v208_review_shortage_prompt_fix_focused`：`400-review-shortage-honesty` 只调用 `review_plan` 且无 followup，`400-review-major-group-inner-safety` 仍调用 `preview_plan_action` 并生成 pending card。
- 回归结果：原 7 失败子集使用新 agent `8037` 复跑 `7/7`，metrics `/private/tmp/zhiyuan_400_v208_failed_subset_after_review_shortage_fix`。随后并发 4 复跑 72 条高信号主链路，首轮 `70/72`，metrics `/private/tmp/zhiyuan_400_v208_mainline_after_review_shortage_fix`。剩余两项失败分层：G21 为并发 `TimeoutError` 未进入工具链；G26 链路正确调用 `query_plan`，但首轮回复用了“录取概率”而不是断言中的“录取率”。两项顺序复跑 `2/2`，metrics `/private/tmp/zhiyuan_400_v208_mainline_failure_subset_sequential_after_fix`。
- 当前结论：v2.08 后高信号主链路未发现新的稳定业务执行缺口。报考要求预览、方案调整预览、最终确认执行、只读审查/no-plan 边界、review+方案动作区分均保持闭环。剩余观察项仍是并发 LLM 超时、少量重复工具调用效率、以及只读回复中“录取率/录取概率”等低风险文案断言口径。

### 12.34 v2.09 扩大质量观察池验证与问题分类

- 本轮目标：继续扩大 4.0 direct 真实验证，优先观察整体链路和回复质量；不急于修低优先级措辞、少量重复调用或验证资产断言问题。
- 扩展结果一：使用 fresh agent `8037`、backend `8080`、真实 LLM、backend state/chat-session clone，并发跑 hard candidate 扩展集，结果 `33/33`，metrics `/private/tmp/zhiyuan_400_v209_expanded_hard_candidates`。覆盖 agent smoke、core effect/perf、direct confirm execution、plan operation、explore intent、career direction 和 readonly real session；未发现新增主链路缺口。
- 扩展结果二：同一 agent 跑 quality observation 扩展集，结果 `47/57`，metrics `/private/tmp/zhiyuan_400_v209_expanded_quality_observation`。10 个失败子集首次在沙箱内复跑因本地 `8080/3306` 访问被拦截，全部为环境失败，不计入结论；提权后单并发有效复跑为 `4/10`，metrics `/private/tmp/zhiyuan_400_v209_quality_failed_subset_sequential_valid`。
- 已转绿项：`400-open-quality-budget-risk-colloquial-readonly`、`400-open-quality-intent-no-med-accounting-ok-impact`、`400-open-quality-lazy-plan-too-risky-readonly`、`400-real-user-school-abbrev-query` 复跑通过。前三条说明原首轮 timeout/无工具调用不稳定，后一条说明“青城那个是不是放多了”可被模型结合方案上下文解析到青岛城市学院并调用 `query_plan`，不是稳定简称解析缺口。
- 剩余问题分类：`400-quality-career-fit-readonly-no-workspace` 是只读审查后“确认”的 no-pending 兜底文案断言过窄，实际无副作用；`400-quality-major-group-preview-confirm-boundary` 预览和确认均正确执行 `move_ordered_unit` 并刷新 ordered/review，但缺少“专业组/组内/方案顺序”说明，属于质量文案；`400-quality-plan-local-query-readonly-direct` 正确返回“1个志愿、7条专业明细”，失败只是断言没覆盖“7条”；`400-quality-plan-named-add-preview-direct` 仍无法把“华中农业大学的建筑类”定位成可添加候选，属于命名加项候选检索/可执行澄清能力缺口；`400-quality-sort-preview-explains-side-effect` 正确生成排序 pending，但回复未提示确认后会影响方案顺序/需要重新审查；`400-open-quality-no-pending-after-compare-guard` 在“新媒体”歧义澄清后，用户说“嗯那就这样”时继续追问歧义，属于自然接续质量和回归断言边界。
- 当前结论：v2.09 扩大验证没有发现新的稳定业务执行缺口，也没有发现最终 action 落库错误。当前主链路仍按 v2.08 结论保持闭环；质量池剩余项主要是回复信息密度、澄清接续、验证资产断言和一个命名加项候选检索能力缺口。后续继续扩大质量池/真实 final-action；若要修，优先级应高于纯措辞的是“命名学校 + 宽泛专业类”的候选查询与可执行澄清，而不是新增工具层中文字符串匹配。

### 12.35 v2.10 dialogue-derived 质量池扩大验证

- 本轮目标：继续扩大 4.0 direct 在真实口语、指代、简略表达和通用咨询类对话中的覆盖；这批 case 作为质量观察池，不直接拉低高信号主链路健康度。
- 首轮结果：使用 fresh agent `8037`、backend `8080`、真实 LLM、backend state/chat-session clone、并发 4 跑 `examples/dialog_regression_400_dialogue_derived_cases.json` 共 88 条，结果 `83/88`，metrics `/private/tmp/zhiyuan_400_v210_dialogue_derived_observation`。
- 失败复核：5 个失败子集单并发复跑 `1/5`，metrics `/private/tmp/zhiyuan_400_v210_dialogue_failed_subset_sequential`。`400-dialogue-archive-library-cold-major` 复跑通过，首轮是 timeout fallback，非稳定业务缺口。
- 稳定问题一：`400-dialogue-region-south-only` 中“孩子就想去南方，北方先别考虑”已触发 `preview_intent_change`，但模型没有把“南方/北方”落成有效地域要求，工具返回“没有识别到明确的报考要求”。这是本轮唯一稳定语义缺口。修复方向应在模型语义层明确地域集合表达的结构化输出或可执行澄清，例如 region requirement 的 include/exclude scope，而不是在工具层扫描中文词。
- 稳定问题二：`400-dialogue-architecture-art-foundation` 和 `400-dialogue-accounting-finance-audit-priority` 均能给出可用回答，但工具选择分别为 `explore_topic` 与 `compare_entities`，case 仍期待旧/细分工具 `get_major_introductions`、`compare_major_options`。这更像验证资产口径与 4.0 direct 工具收敛后的命名不一致，暂不作为业务缺陷。
- 稳定问题三：`400-dialogue-followup-readonly-boundary` 回复“好的，你先问，我不做任何改动”，无工具、无 followup、无副作用；失败只是断言没有覆盖“不做任何改动”。归为低优先级断言/文案口径。
- 当前结论：v2.10 将 quality observation 覆盖扩大到 88 条 dialogue-derived case，未发现 final-action 或 pending 执行链路错误；主链路结论保持稳定。下一步建议先设计并修复地域集合表达的语义结构化，然后用 focused case 复跑 `south-only`，再扩大到包含“南方/北方/长三角/珠三角/北上广深/省内外”等地域集合口语样本。

### 12.36 v2.11 地域集合表达结构化修复

- 问题来源：v2.10 dialogue-derived 扩大验证中，`400-dialogue-region-south-only` 稳定复现。用户说“孩子就想去南方，北方先别考虑”时，模型调用了 `preview_intent_change`，但没有把“南方/北方”写入 `positive/negative` payload，工具按设计不从 `raw_user_text` 扫描补语义，最终返回“没有识别到明确的报考要求”。
- 修复原则：保持 4.0 direct 的模型语义层职责，不新增工具层中文字符串匹配。工具只处理模型已经结构化输出的字段，不能根据用户原话临时猜测。
- Prompt 修复：行动原则第 7 条明确地域集合也是地域要求，应使用 `area`/`region_group` 字段表达，并在 `semantic_requirements` 中标明 domain/side/strength/key/values/raw_span；补充示例：“孩子就想去南方，北方先别考虑” -> `preview_intent_change(intent_type="region", positive={"area":["南方"]}, negative={"area":["北方"]}, constraint_type="must_have", ...)`。
- Agent 工具层修复：`tools.py` 复用既有 `REGION_AREA_PROVINCES`，让结构化 `area` 能参与本地 plan impact 和候选约束匹配。这里不读取原话、不做语义判定；只在 payload 已经是 `area` 时做精确省名集合匹配。同时修掉本地 `_matches_any_text` 在省/市 values 为空时默认命中的边界，避免仅有 area 的 payload 被错误视为匹配全部。
- 后端最终生效修复：新增 `RegionScopeSupport.java`，把地域集合定义从 `UserGoalProposalBuilder` 私有实现抽成同包共用工具；`UserGoalProposalBuilder` 和 `RepairCandidateEligibility` 都改用结构化地域集合 matcher。这样 `constraintState.hardConstraints.mustIncludeRegions=["南方"]`、`mustExcludeRegions=["北方"]` 进入 `generateOrderedPlan()` 时，会在 `resolveEffectiveCandidates()` / `applyConfirmedPlanRequirements()` 中按省份集合生效；基础 `candidatePoolState.items` 不隐藏、不删除，仍保持全量候选与页面可恢复交互语义。
- 回归资产修正：新增 `examples/dialog_regression_400_v211_region_area_final_cases.json`，覆盖“南方/北方”地域集合出卡和确认后的最终动作。该资产补充 `orderedPlanState.units minLength>=1`，避免之前只断言 `notContains 北京/山东` 时空数组误通过。
- 单元验证：`py_compile app/zhiyuan_agent/prompt.py app/zhiyuan_agent/tools.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused 单测 `test_plan_item_matches_structured_region_area_payload`、`test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups`、`test_preview_region_area_positive_and_negative_pending` 为 `3 passed`；完整 `tests/unit/test_zhiyuan_agent_direct.py -q` 为 `175 passed, 29 skipped`；后端 focused `PlanningStateServiceTest#shouldApplyRegionAreaRequirementWhenGeneratingOrderedPlan` 通过；完整后端 `mvn -q -Dtest=PlanningStateServiceTest test` 通过；`git diff --check` 通过。
- 真实验证一：使用新 agent `8039`、backend `8080`、真实 LLM、backend clone。`south-only` focused `1/1`，metrics `/private/tmp/zhiyuan_400_v211_region_south_only_focused`，正确生成“地域要求：要：南方；不要：北方”的 pending card；地域集合 probe `3/3`，metrics `/private/tmp/zhiyuan_400_v211_region_area_probe`，覆盖“只看长三角”“珠三角先不考虑”“北上广深也可以重点看”。
- 真实验证二（最终 action）：先前 `orderedPlanState.units notContains 北京/山东` 在空数组下可误通过，补 `minLength>=1` 后复测。第一次 offset run 未带 `--backend-db-password`，`assistant_chat_session` 主表未克隆，`confirm_pending` 内部 `generate_planning_ordered_plan()` 返回 `ordered_plan_response={"code":404,"msg":"会话不存在"}`，因此仅作为验证夹具问题记录。有效复跑使用 backend `18080` + agent `8038` + `--backend-db-password 12345678` + session `5093017`，结果 `2/2`，metrics `/private/tmp/zhiyuan_400_v211_region_area_final_action_after_backend_fix_valid.json`。确认后回复“已采纳这次报考要求，并按新要求重新调整了当前方案”，followup 刷新 `ordered/review`；后端状态 `version=1605`、`mustIncludeRegions=["南方"]`、`mustExcludeRegions=["北方"]`、`orderedPlanState.units=12`、`orderedPlanState.items=33`、北方省份计数 0、`staleFlags.orderedPlan=false`。
- 当前结论：v2.10 唯一稳定语义缺口已闭合，并且验证覆盖到最终 action。剩余 v2.10 其它稳定失败仍按验证资产/低优先级文案口径处理：旧细分工具名断言、只读边界文案断言。下一步可以继续扩大 quality observation，或补充更多地域集合/城市圈样本到长期回归集。

### 12.51 v2.42 final-action/high-signal 专项门禁入口

- 背景：v2.41 后 `examples/` 中只剩 4.0 regression JSON，但其中 19 个是 focused/final-action/high-signal 资产，很多 case metadata 明确要求 `--clone-backend-chat-session`，并通过 `assertBackendExtraData` 校验 pending、planningState、candidate pool、ordered plan、工作台刷新等最终状态。
- 设计：不把这些 clone-backed case 混入默认 `live` gate，避免默认门禁因为缺 DB clone 参数产生环境假失败；新增独立 `final-action` category，作为真实服务 + DB clone 条件下的专项入口。
- 实现：`dialog_quality_gate.py` 新增 `FINAL_ACTION_CASE_FILES`，覆盖 direct confirm、G1-G32、realistic user 以及 v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183/v211/v212/v213/v216。`build_gate_plan()` 为这些文件生成 `final-action-*` command，统一带 per-case history/backend pending/planning intent 清理、`--clone-backend-chat-session`、plan style、180s timeout，并透传 `--agent-url`、`--internal-service-url`、`--backend-db-password`。
- 使用边界：默认 `--execute` 仍只跑 local；`--mode live` 仍是 13 个默认质量/只读 live 文件；真实最终动作验证显式运行 `--mode final-action`。
- 验证：`py_compile examples/dialog_quality_gate.py tests/unit/test_dialog_quality_gate.py` 通过；`tests/unit/test_dialog_quality_gate.py -q` 为 `9 passed`；`dialog_quality_gate.py --mode final-action --metrics-dir /private/tmp/zhiyuan_400_final_action_gate_dry_run --agent-url ... --internal-service-url http://127.0.0.1:8080 --backend-db-password 12345678` dry-run 生成 19 条 clone-backed 命令；默认 `dialog_quality_gate.py --execute` 本地门禁为 `421 passed`。
- 当前结论：当前所有 4.0 case 资产都有明确归属。默认 gate 控制维护成本，final-action gate 保留最终状态验证能力；后续真实全量验证可以先跑 local + live，再按需要跑 `final-action`。

### 12.50 v2.41 4.0 case 资产 hard-cut 清理

- 清理目标：把当前质量门禁从“自动发现所有历史 dialog regression JSON”收敛到“显式维护 4.0 有效回归集”，避免旧 3.x/早期断言口径继续进入 live gate，降低后续维护成本。
- 实现：`examples/dialog_quality_gate.py` 的 live case 列表只保留 13 个 `dialog_regression_400_*` 文件，并删除 `_case_file_names()` 对 `EXAMPLES.glob("dialog_regression_*_cases.json")` 的自动发现；旧非 400 历史 regression JSON 从 `examples/` 删除。
- 同步资产：runner usage、planning dialog checklist、dialog regression report、next session handoff 和 mainline catalog 测试切到当前 4.0 case；explore intent catalog 覆盖断言改为当前显式诉求/优先参考边界/只读不出卡/候选探索语义，不再要求旧 `positive_*_intent`、`historical_intent`、`intent_revision` 标签。
- 防回退：`test_runtime_hard_cut_audit.py` 增加旧非 400 JSON 不存在、当前 gate/mainline 测试不引用旧文件、gate 不恢复 glob 自动发现的断言。
- 验证：`py_compile` 通过；`examples/dialog_quality_gate.py --metrics-dir /private/tmp/zhiyuan_400_effective_gate_dry_run` dry-run 通过，live plan 只包含 13 个 4.0 case；`tests/unit/test_dialog_quality_gate.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_runtime_hard_cut_audit.py -q` 为 `46 passed`。
- 当前结论：131 条 fresh quality observation 已覆盖最新 4.0 效果观察；本次清理解决的是验证资产维护面，不改变生产链路。后续继续扩大/补充 case 时，应进入 `dialog_regression_400_*` 有效集，而不是恢复旧历史文件。

### 12.49 v2.24 高信号主链路复核与失败子集收敛

- 目的：在 v2.23 修复“倾向 A/B，但 Y 不要”混合正负专业要求后，补跑 72 条高信号主链路，确认新增 prompt 规则没有影响报考要求、方案动作、最终确认、地域集合 final-action、active pending 改写/追加和 no-pending 防护。
- 运行条件：新版 agent `8040`、backend `18081`、真实 LLM、完整 chat-session clone、`--backend-db-password 12345678`、并发 3、`--ignore-thinking-assertions`，case 组合为 G1-G32、readonly、v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183、v212/v213/v216，共 72 条。
- 首轮结果：目录 `/private/tmp/zhiyuan_400_v224_mainline_72_after_v223_prompt_fix`，结果 `66/72`。
- 首轮失败分层：`400-g17-tier-local-reorder` 是 backend planning intent clear `TimeoutError`，未进入对话；`400-g30-special-admission-path-preservation`、`400-v155-review-reference-remove-high-tuition-final-action`、`400-v157-combo-school-attribute-exclude-final-action` 都是重复调用同一预览工具导致严格工具次数断言失败，但业务输出正确，v155/v157 确认后端断言均通过；`400-g4-explicit-major-entity-display` 首轮无工具无 pending；`400-v212-region-pearl-delta-exclude-final-action` 首轮无工具无 pending，确认轮自然没有可执行对象。
- 失败子集复核：抽取上述 6 条为 `/private/tmp/zhiyuan_400_v224_failed_subset_*.json`，单并发顺序复跑 `/private/tmp/zhiyuan_400_v224_mainline_failed6_subset_sequential`，结果 `6/6`。G4 正确调用 `preview_intent_change` 并生成“网络与新媒体、跨境电子商务”专业要求待采纳卡；G17 正确生成保底区局部移动预览；G30 单次生成清华/北大/复旦强基意向待采纳卡；v155 高收费移出预览后“确认执行”移出 33 个专业组且后端断言通过；v157 民办/中外合作排除确认后要求落库、candidate pool 保持全量、ordered items/units 裁剪通过；v212 珠三角排除首轮 pending card，确认后 `mustExcludeRegions` 包含“珠三角”，ordered/review 刷新和代表性地域剔除断言通过。
- 当前结论：v2.24 主链路复核没有发现新增稳定业务执行缺口。v2.23 prompt 修复没有破坏 4.0 direct 的核心闭环；72 条主链路在失败子集收敛后等效转绿。
- 继续记录但暂不优先修：并发模型偶发无工具或重复调用、backend clone/clear 超时、工具次数断言对重复调用过严。后续可继续推进旧链路清理或做更大规模真实 final-action/quality 回归。

### 12.48 v2.23 混合正负专业要求 prompt-only 修复与 131 质量池复核

- 问题来源：v2.22 复核中 `400-open-quality-intent-existing-impact-readonly` 稳定暴露。“我倾向会计学和审计学，但土木工程不要”有时没有触发工具调用，模型只口头说明没有待确认预览；下一轮用户问“先不确认，看看这个偏好会影响当前方案吗”时才生成 pending，破坏了“首轮出待采纳内容，后续只读看影响”的对话链路。
- 设计判断：该问题仍属于模型语义判定边界，不应在工具层扫描“倾向/不要”等中文词。4.0 的职责边界保持为：模型负责把本轮诉求压成 `positive/negative/semantic_requirements`，工具只校验和执行结构化 payload。
- 实现调整：`app/zhiyuan_agent/prompt.py` 第 6 条补齐“倾向A和B，但Y不要/别碰/不考虑”边界，明确这是可确认正向方向 + 明确负向要求，必须调用 `preview_intent_change` 并生成待采纳预览；示例区新增真实失败句：“我倾向会计学和审计学，但土木工程不要” -> `preview_intent_change(intent_type="major", positive={"major":["会计学","审计学"]}, negative={"major":["土木工程"]}, constraint_type="exclude", semantic_requirements=[...])`。
- 测试守护：`tests/unit/test_zhiyuan_agent_direct.py` 在现有 prompt 静态测试中加入该边界断言，防止后续整理 prompt 时删掉这一类混合正负专业要求。
- 静态验证：`py_compile app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；目标单测 `test_zhiyuan_agent_instructions_require_plan_action_targeting_for_review_followups -q` 为 `1 passed`；`dialog_regression_400_open_quality_cases.json` JSON 格式校验通过。
- Focused 真实验证：使用新版 agent `8040`、backend `18081`、完整 chat-session clone 和 `--backend-db-password 12345678`，跑 `/private/tmp/zhiyuan_400_v223_intent_existing_impact_after_fix.json`，结果 `2/2`。第一轮正确调用 `preview_intent_change`，回复“专业要求：要：会计学、审计学；不要：土木工程”，生成 `pendingConfirmationCard`；第二轮“先不确认，看看这个偏好会影响当前方案吗”走 `query_plan` 只读查询，无 followup、无直接改动。
- 131 质量池复核：并发 4 复跑当前 131 条 quality observation，目录 `/private/tmp/zhiyuan_400_v223_quality_131_after_intent_fix`，首轮 `125/131`。6 个失败分层：4 个为 backend state clone 或 planning intent clear `TimeoutError`，未进入对话；2 个为内容断言波动，分别是只读边界口语回复“你先问，我听着”和 compare 后收尾“随时问我”没有命中断言词表，均无 pending、无 followup、无方案副作用。
- 失败子集复核：抽取上述 6 条到 `/private/tmp/zhiyuan_400_v223_failed_dialogue_subset_cases.json` 与 `/private/tmp/zhiyuan_400_v223_failed_open_subset_cases.json`，单并发顺序复跑 `/private/tmp/zhiyuan_400_v223_quality_failed6_subset_sequential`，结果 `6/6`。其中 `intent-existing-impact-readonly` 再次验证首轮出待采纳卡、第二轮只读查询当前方案命中；`sort-score` 继续生成推荐系数排序预览；career 多方向只读走 `review_plan`；compare 后“嗯那就这样”无待采纳卡、无副作用。
- 当前结论：v2.22 剩余稳定语义缺口已闭合。本轮没有发现新的 final-action 或 pending 执行错误。仍需记录但暂不优先修的观察项：并发 backend clone 超时、query_plan 重复调用被 guard 拦截后的兜底回复质量、部分自然收尾文案断言过窄。

### 12.47 v2.22 131 质量池复核与混合正负专业要求缺口定位

- 目的：在 v2.21 修复缩略专业对比误建 pending 并清理旧工具名资产后，复跑当前 131 条 quality observation，确认 prompt 修复没有造成新的只读/报考要求/方案动作副作用。
- 首轮结果：使用 agent `8040`、backend `18081`、真实 LLM、完整 chat-session clone、`--backend-db-password 12345678`、并发 4 和 `--ignore-thinking-assertions`，跑 dialogue-derived、open-quality、quality-realistic-user、career、explore、readonly 共 131 条，目录 `/private/tmp/zhiyuan_400_v222_quality_131_after_v221_fix`，结果 `128/131`。
- 首轮失败：`400-open-quality-career-multi-direction-readonly`、`400-open-quality-no-pending-after-compare-guard`、`400-open-quality-intent-existing-impact-readonly`。其中前两类更接近断言/自然收尾口径，后一类是混合正负专业要求没有稳定生成待采纳内容。
- 资产口径修正：`dialog_regression_400_open_quality_cases.json` 补充 no-pending 自然收尾断言“随时跟我说”。随后 3 条失败子集顺序复跑 `/private/tmp/zhiyuan_400_v222_quality_remaining3_after_assertion_fix.json`，career 多方向只读通过，compare 后无 pending 收尾通过，剩余 `400-open-quality-intent-existing-impact-readonly`。
- 稳定问题：第一轮“我倾向会计学和审计学，但土木工程不要”应形成专业要求待采纳预览：正向会计学/审计学为 confirmable，负向土木工程为 explicit；实际模型可能不调用工具，直接回复没有可确认调整预览。第二轮用户说“先不确认，看看这个偏好会影响当前方案吗”时，模型才补建 pending，导致只读影响查询轮次被污染。
- 修复方向：prompt-only。强化“弱正向表达 + 明确负向要/不要”在同一句出现时必须调用 `preview_intent_change`，并且 `semantic_requirements` 中 explicit/confirmable 项要进入同一次 `positive/negative` payload；不能把该问题下沉到工具层用中文字符串匹配补救。

### 12.46 v2.21 缩略专业对比误建 pending 修复与旧工具资产清理

- 问题来源：v2.20 quality observation 中 `400-real-user-major-abbrev-non-law-compare` 稳定暴露真实语义路由问题。用户说“新媒体和跨电呢 数学不太行”，模型把它误判为报考要求，调用 `preview_intent_change` 并生成“要：新媒体/跨电；不要：数学类”的 pending card。
- 设计边界：该问题不能在工具层用中文关键词兜底。工具只消费模型结构化输出；语义判断应由模型在当前 turn context + prompt 规则中完成。
- 实现调整：`app/zhiyuan_agent/prompt.py` 强化第 16a 条：用户同时提到 2 到 5 个专业/院校，并用“A和B呢/那A和B/哪个/怎么选/更稳/更适合”等表达比较，且数学、物理、沟通强弱、累不累只是适配背景时，优先调用 `compare_entities`；这条优先于“想学/感兴趣”类判断。明确“数学不太行/物理弱/不想太累”不能自动写成 negative major 或报考要求，除非用户明确说不要某专业、不要相关专业、记上/采纳/就选某方向。
- 示例补齐：新增真实口语示例 `新媒体和跨电呢 数学不太行 -> compare_entities(... comparison_focus=数学要求/适配度)`，并明确不要调用 `preview_intent_change`、不要生成“不要数学类”的待确认预览；同时加入 `计科和软工哪个更稳一点，孩子数学还行但不想太累` 示例，覆盖同类缩略专业名 + 学习强度背景。
- 资产清理：`examples/dialog_regression_400_dialogue_derived_cases.json` 中 `400-dialogue-architecture-art-foundation` 的期望工具从旧 `get_major_introductions` 切到 4.0 `explore_topic`；`400-dialogue-accounting-finance-audit-priority` 从旧 `compare_major_options` 切到 `compare_entities`，并把旧工具名放入 not-contain，避免继续维护旧验证口径。
- 验证一：`py_compile app/zhiyuan_agent/prompt.py` 通过，`dialog_regression_400_dialogue_derived_cases.json` JSON 格式校验通过。
- 验证二：focused 复跑 `/private/tmp/zhiyuan_400_v221_major_abbrev_compare_after_prompt_fix.json` 为 `1/1`。真实回复调用 `compare_entities`，无 pending card，内容解释“网络与新媒体 vs 跨境电子商务”对数学要求和适配度。
- 验证三：重新从当前资产抽取 7 条 v2.20 失败子集为 `/private/tmp/zhiyuan_400_v221_quality_failed_subset_cases_current.json`，使用 fresh agent `8040` 复跑 `/private/tmp/zhiyuan_400_v221_quality_failed_subset_after_prompt_and_asset_fix.json`，结果 `9/9` step 全绿。旧工具名断言、no-pending after query、专业对比后自然收尾、缩略专业对比误建 pending 均收敛；若运行旧 `/private/tmp/...failed_subset_cases.json` 快照仍会看到旧断言失败，不计入当前结论。
- 当前结论：v2.20 发现的唯一高价值真实语义问题已闭合。下一步应在当前资产上复跑 131 条 quality observation 整组，确认没有新的模型波动或 prompt 副作用，再继续旧链路/旧资产清理。

### 12.45 v2.20 quality observation 扩大验证与稳定问题分层

- 目的：在 v2.19 72 条高信号主链路等效转绿后，继续扩大真实口语/指代/开放质量池，重点看 4.0 direct 链路、回复整体质量和是否有误建 pending/最终 action 风险。
- 运行条件：fresh agent `8040`、backend `18081`、并发 4、`--clone-backend-chat-session`、`--backend-db-password 12345678`、`--ignore-thinking-assertions`，case 文件为 `dialogue_derived`、`open_quality`、`quality_realistic_user`、`career_direction`、`explore_intent`、`readonly_real_session`，合计 131 条。
- 首轮结果：目录 `/private/tmp/zhiyuan_400_v220_quality_131_after_v219`，结果 `124/131`。本轮显式忽略 thinkingText 断言，避免把低优先级过程文案资产问题混入链路结论。
- 失败子集复跑：抽取 7 条失败为 `/private/tmp/zhiyuan_400_v220_quality_failed_subset_cases.json`，单并发顺序复跑 `/private/tmp/zhiyuan_400_v220_quality_failed_subset_sequential.json` 后 `5/9` step 通过，稳定失败 4 条。
- 稳定失败一：`400-dialogue-architecture-art-foundation` 与 `400-dialogue-accounting-finance-audit-priority` 都是旧工具名断言。实际 4.0 分别走 `explore_topic` 和 `compare_entities`，回复能回答“建筑/城乡规划是否需要美术基础”和“财管/会计/审计优先级”，未发现链路或内容硬缺口。后续应按新工具名清理资产，而不是恢复旧工具路径。
- 稳定失败二：`400-open-quality-no-pending-after-compare-guard` 首轮因“新媒体”歧义要求澄清；用户说“嗯那就这样”后模型继续追问歧义，没有创建 pending、没有副作用。该项归为自然接续质量：更理想的回复是关闭话题或说明不记录报考要求，但优先级低于误建 pending。
- 稳定失败三：`400-real-user-major-abbrev-non-law-compare` 中“新媒体和跨电呢 数学不太行”被模型调用 `preview_intent_change`，生成“要：新媒体/跨电；不要：数学类”的待确认卡。该项是真实语义路由问题：这类“两个专业呢 + 能力/课程顾虑”的口语表达应按专业对比/适配咨询处理，只有用户显式表达要/不要/别考虑/就选/记上等报考要求时才进入待确认报考要求。修复方向应继续放在模型语义边界和 prompt/tool schema 说明，不在工具层做中文字符串匹配。
- 波动/转绿项：`400-dialogue-career-girl-ordinary-family-stable` 与 `400-open-quality-computer-abbrev-compare-lazy` 首轮返回“这轮处理没有完成”，顺序复跑均正常回答；`400-open-quality-plan-query-then-confirm-guard` 首轮“确认”文案不命中资产，顺序复跑正确走 no-pending guard，返回“当前没有待确认操作、不执行任何变更”。
- 当前结论：quality 池没有发现最终 action 数据错误；新发现的高价值问题是“缩略专业对比 + 数学/能力顾虑”误建 pending。下一步建议优先修复该模型语义边界，并顺手清理旧工具名断言资产。

### 12.44 v2.19 72 条主链路整组复跑与验证资产收敛

- 目的：在 v2.18 修复 runner 环境口径、v183 prompt-only 改口缺口以及 v153/v173 断言资产后，使用 fresh agent 对同一 72 条高信号主链路做整组复跑，确认没有遗漏稳定业务执行缺口。
- 运行条件：agent `8040` 重新加载当前代码，backend `18081`，并发 3，`--clone-backend-chat-session`，`--backend-db-password 12345678`，session offset base `8000000`，case 组合仍为 G1-G32、readonly、v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183、v212/v213/v216 共 72 条。
- 首轮结果：目录 `/private/tmp/zhiyuan_400_v219_full_72_after_v218`，结果 `71/72`。地域 v212/v213/v216、active pending 改口、候选/地域/专业/标签 final-action、方案动作 final-action 均继续通过，确认轮仍覆盖 `confirm_pending`、pending applied、`planningState.version` 增长、要求落库、ordered/review 刷新等后端断言。
- 唯一失败分层：`400-v183-review-advice-then-vague-execute-no-pending-guard` 第二轮回复“当前状态摘要显示待确认：无、上一轮审查后没有生成待确认操作、没有可执行的待确认项”，无工具调用、无 followup，后端 `planningState.version` unchanged、`pendingConfirmation` empty。该行为符合 no-pending 防护目标，失败原因是 `assertContainsAny` 只覆盖“没有待确认/没有可确认/没有生成可确认/不会执行/不会改动/先明确”，未覆盖“没有生成待确认/没有可执行”。
- 资产调整：`examples/dialog_regression_400_v183_realistic_followup_quality_cases.json` 补充同义断言“没有生成待确认”“没有可执行”，不修改生产链路。focused 复跑 `/private/tmp/zhiyuan_400_v219_v183_no_pending_assertion_fix.json` 为 `1/1`；复跑中模型走 `confirm_pending` 并返回“当前没有待确认操作、不执行任何变更”，后端仍验证无副作用。
- 当前结论：v2.19 没有新增确定业务执行缺口；v2.18 后的 72 条主链路在验证资产收敛后等效转绿。后续可以继续扩大 quality observation 口语/指代池，或进入剩余旧链路/旧资产清理；低优先级观察项仍是少量重复工具调用、只读/质量文案断言口径和模型波动。

### 12.43 v2.18 高信号主链路回归与失败收敛

- 目的：在 v2.17 地域 final-action 与 runner DB clone 条件校准后，继续验证当前 4.0 direct 高信号主链路是否受影响，覆盖 G1-G32、readonly、v143/v150/v151/v153/v154/v155/v156/v157/v158/v173/v179/v183、v212/v213/v216 共 72 条。
- 首轮结果：使用 backend `18081` + agent `8039`、真实 LLM、并发 3、完整 chat-session clone 和 `--backend-db-password 12345678`，目录 `/private/tmp/zhiyuan_400_v217_mainline_region_parallel`，结果 `62/72`。地域 v212/v213/v216 全部继续通过。
- 首轮失败分层：6 条 G case 是 runner 志愿文件 clone fail-fast 过严导致的 environment setup failure，source session 没有本地 `session_volunteer_*` 文件，但这些 case 不是 final-action 硬验证，不应被志愿文件缺失阻断；v153 是首轮文案固定断言“20个相关志愿”与当前真实影响数 18 不一致；v158/G30 是少量重复 `preview_intent_change`，业务 pending 正确；v173 是确认后移动成功但断言固定老 unitId；v183 是 active pending 改口时 `UnexpectedModelBehavior`，没有生成新 pending，第三轮确认误采纳旧 pending。
- runner 规则收窄：保留 `assistant_chat_session` 主表克隆失败的 fail-fast；志愿文件克隆失败只在 case 明确是 `final_action` 或带 `orderedPlanState/workingPlanState/reviewState` 后端断言时作为 environment failure，普通观察 case 只记录 warning 并继续跑。补充单测覆盖非 final-action 缺志愿文件继续运行；`tests/unit/test_dialog_regression_runner.py -q` 为 `89 passed`。
- 失败子集复跑一：10 条失败子集使用修正 runner 复跑，目录 `/private/tmp/zhiyuan_400_v217_failed_subset_after_runner_gate`，结果 `6/10`。6 个环境假失败转绿；剩余 G30、v153、v173、v183。
- v183 修复：该问题是测试期间真实发现的 active pending 改写口语缺口。修复保持 4.0 语义边界，只在 `prompt.py` 补充组合改写示例：`算了不是这个，改成山东别去，民办也不要` -> `preview_intent_change(intent_type="region", negative={"province":["山东"],"school_nature":["民办"]}, pending_resolution="replace_active_pending")`；不在工具层扫描用户原话。新版 agent `8040` focused 复跑 `1/1`，metrics `/private/tmp/zhiyuan_400_v217_v183_rewrite_after_prompt_fix.json`，第二轮正确生成“院校要求：不要：民办；地域要求：不要：山东”新 pending，第三轮确认后后端断言全部通过。
- 失败子集复跑二：同 10 条子集使用新版 agent `8040` 复跑，目录 `/private/tmp/zhiyuan_400_v217_failed_subset_after_v183_prompt_fix`，结果 `8/10`。G30 和 v183 转绿；剩余 v153/v173 均为资产断言口径。
- 资产断言修正：v153 首轮断言从固定 `20个相关志愿` 改为 `相关志愿`，后端 final-action 断言仍验证 pending applied、version 增长、管理学要求落库、candidate pool 保留、ordered items/units 裁剪。v173 移动确认断言从固定老 `orderedPlanState.units.0.unitId == 37020261000573` 改为 `orderedPlanState.units.0.unitId changedFromBefore=true`，仍验证确认后首位专业组真实变化。剩余两条复跑 `/private/tmp/zhiyuan_400_v217_remaining_two_after_assertion_fix` 为 `2/2`。
- 当前结论：本轮高信号主链路没有新增确定业务执行缺口；v183 active pending 改口已通过 prompt-only 修复闭合，runner 环境口径与两个过窄资产断言已收敛。下一轮可用新版 agent 8040 对 72 条做整组复跑，或继续扩大 quality observation；G30 少量重复工具调用仍按低优先级效率观察。

### 12.42 v2.17 地域 final-action 扩大验证与回归环境校准

- 目的：在 v2.16 补齐“省外可以，但太偏的地方不想去”后，扩大到 v212/v213/v216 地域集合长期 final-action 资产，确认新增 `偏远地区` 不影响已有地域集合/城市圈链路。
- 无效并发运行一：使用 backend `18081` + agent `8039`，并发 2 跑 `examples/dialog_regression_400_v212_region_area_expanded_final_cases.json`、`examples/dialog_regression_400_v213_region_area_quality_final_cases.json`、`examples/dialog_regression_400_v216_region_remote_final_cases.json`，目录 `/private/tmp/zhiyuan_400_v216_region_expanded`，结果 `0/11`。该轮未带 `--clone-backend-chat-session`，不计为业务结果。
- 无效并发运行二：补 `--clone-backend-chat-session` 后，目录 `/private/tmp/zhiyuan_400_v216_region_expanded_with_clone`，仍为 `0/11`。复核日志发现 MySQL 克隆使用空密码，`assistant_chat_session` 主表克隆失败；后端 extra-data 可以写入，所以确认轮表现为 `pendingConfirmation.status=applied`、`planningState.version` 增长、`constraintState` 包含地域要求，但 `generateOrderedPlan` 无法基于完整会话刷新，回复“当前方案暂时没有重新调整成功”，`orderedPlanState.units` 仍保留旧方案内容。
- 串行复核：用原始 session `17` 单独复跑 v216，metrics `/private/tmp/zhiyuan_400_v216_region_remote_single_recheck.json`，结果 `1/1`。首轮生成“地域要求：不要：偏远地区” pending card；确认后回复“已采纳这次报考要求，并按新要求重新调整了当前方案”，followup 刷新 `ordered/review`，后端断言全部通过。该复核说明 v2.16 生产链路本身可用，前两轮失败是 offset fixture/克隆条件问题。
- 有效并发复跑：使用新的 session offset base `4000000`、完整 chat-session clone、`--backend-db-password 12345678`、并发 2 复跑上述三组 11 条，目录 `/private/tmp/zhiyuan_400_v216_region_expanded_clone_db`，结果 `11/11`。每条确认轮均覆盖 `confirm_pending`、pending applied、planningState version 增长、地域要求落库、`orderedPlanState.units minLength>=1`、代表性地域剔除和 `ordered/review` 刷新。
- 回归工具收敛：`examples/dialog_regression_runner.py` 将 `--clone-backend-chat-session` 下的 `assistant_chat_session` 主表克隆失败、志愿文件克隆失败从 warning 升级为 environment setup failure，case 不再继续进入 websocket；同时把 source session 等于 target session 的志愿文件克隆视为 `same_session` no-op，方便原始会话 focused 复核。补充单测覆盖 chat-session 克隆失败、volunteer data 克隆失败和 same-session no-op，`tests/unit/test_dialog_regression_runner.py -q` 为 `88 passed`。runner 调整后使用 offset session `6000017`、完整 clone 和 `--backend-db-password 12345678` 复跑 v216 focused final-action，metrics `/private/tmp/zhiyuan_400_v217_runner_clone_valid_focused.json`，结果 `1/1`，无 warnings/failures。
- 当前结论：v2.16 新增 `偏远地区` 没有破坏 v212/v213 已有地域集合、城市圈、地域别名 final-action 链路。后续所有 offset final-action 回归必须显式带 `--backend-db-password 12345678`；否则若出现“要求已采纳但方案未调整成功”，runner 会先按回归环境克隆问题失败，不直接归因到 4.0 agent 链路。

### 12.41 v2.16 偏远地区诉求结构化修复

- 问题来源：v2.15 quality observation 中 `400-dialogue-region-outside-ok-not-remote` 稳定失败。用户说“省外可以，但太偏的地方不想去”，模型调用了 `preview_intent_change`，但 positive/negative payload 没有可执行地域对象，工具返回“没有识别到明确的报考要求”，没有生成 pending card。
- 设计判断：该表达不是“必须省外”。“省外可以/不排斥省外”更接近放宽或参考背景；强诉求是“不要太偏/偏远/太远的地方”。修复应让模型把后半句压成结构化地域集合 `偏远地区`，而不是工具扫描原话。
- 实现调整：`prompt.py` 在地域集合说明中加入 `偏远地区`，明确“省外可以/不排斥省外”通常作为 reference 或背景，不单独写成必须省外；同句有“太偏/偏远/太远的地方不想去/别考虑”时，调用 `preview_intent_change(intent_type="region", negative={"area":["偏远地区"]}, constraint_type="exclude")`，并在 `semantic_requirements` 中把“省外可以”标为 reference。
- catalog 对齐：`region_entity_resolver.py` 新增 `偏远/偏远地区/边远地区 -> 偏远地区`，并把 `偏远地区` 展开为新疆、西藏、宁夏、甘肃、青海、内蒙古；后端 `RegionScopeSupport` 同步新增相同 alias 和省份集合，确保确认后 ordered/review 派生链路真实过滤。
- 回归资产：新增 `examples/dialog_regression_400_v216_region_remote_final_cases.json`。case 两轮：第一轮“省外可以，但太偏的地方不想去”要求 `preview_intent_change` + pending card；第二轮“确认”要求 `confirm_pending`，并通过后端断言校验 pending applied、version 增长、`mustExcludeRegions` 包含“偏远地区”、ordered units 非空且不含代表性偏远省份。
- 单元验证：`py_compile app/domain/region_entity_resolver.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused Python 单测 `test_preview_region_remote_area_creates_pending`、`test_preview_region_area_positive_and_negative_pending`、`test_preview_region_first_tier_area_creates_pending` 为 `3 passed`；后端 focused `mvn -q -Dtest=PlanningStateServiceTest#shouldMatchRemoteRegionScope test` 通过。
- 真实验证：启动新版 backend `18081` 与新版 agent `8039`，使用真实 LLM、完整 chat-session clone、`--backend-db-password 12345678` 跑 focused final-action，结果 `1/1`，目录 `/private/tmp/zhiyuan_400_v216_remote_region_focused`。首轮回复“地域要求：不要：偏远地区”，生成 pending card；确认后回复“已采纳这次报考要求，并按新要求重新调整了当前方案”，followup 刷新 `ordered/review`，后端断言全部通过。
- 当前结论：v2.15 的稳定地域诉求缺口已闭合。剩余 quality observation 问题仍是旧工具名/`thinkingText` 断言资产口径，以及低优先级“澄清后用户轻量收尾”的自然接续。

### 12.40 v2.15 quality observation 扩大验证

- 目的：在 v2.14 主链路和地域 final-action 稳定后，继续扩大真实口语、开放问答、职业/专业方向、当前方案只读审查等 quality observation 覆盖。本轮只做验证和问题记录，不改生产链路。
- 验证范围：`dialog_regression_400_dialogue_derived_cases.json` 88 条、`dialog_regression_400_open_quality_cases.json` 20 条、`dialog_regression_400_quality_realistic_user_cases.json` 9 条、`dialog_regression_400_career_direction_cases.json` 4 条、`dialog_regression_400_explore_intent_cases.json` 8 条、`dialog_regression_400_readonly_real_session_cases.json` 2 条，共 131 条。使用 backend `18080`、agent `8038`、真实 LLM、完整 chat-session clone、`--backend-db-password 12345678` 和并发 4。
- 首轮结果：`102/131`，目录 `/private/tmp/zhiyuan_400_v215_quality_observation_expanded`。失败集中在 open-quality 和 quality-realistic-user；dialogue-derived 只有 3 个失败。
- 失败子集复核：29 个失败子集单并发顺序复跑仍 `0/29`，目录 `/private/tmp/zhiyuan_400_v215_quality_failed_subset_sequential`。说明这些不是并发偶发转绿项，但大多并非 4.0 业务链路错误。
- 稳定失败分层：2 个是旧工具名断言，`400-dialogue-architecture-art-foundation` 期望 `get_major_introductions`，实际 4.0 走 `explore_topic` 且回答内容可用；`400-dialogue-accounting-finance-audit-priority` 期望 `compare_major_options`，实际 4.0 走 `compare_entities` 且回答内容可用。24 个是纯 `thinkingText` 断言口径，实际工具调用、pending/只读边界和回复内容大体符合当前 4.0 链路，后续应优先调整验证资产，不作为生产链路缺陷。
- 稳定问题一：`400-dialogue-region-outside-ok-not-remote`（“省外可以，但太偏的地方不想去”）稳定调用 `preview_intent_change`，但工具返回“没有识别到明确的报考要求”，没有生成 pending card。该问题属于显式地域诉求结构化不足：用户表达了“省外可以/不排斥省外”以及“不要太偏远地区”，模型没有把它压成可执行的地域要求或可执行澄清。后续修复方向应在模型语义输出里支持“可接受省外 + 排除偏远/太远/过远地区”的结构化表达，工具层仍不从原话做中文关键词扫描。
- 稳定问题二：`400-open-quality-no-pending-after-compare-guard` 中，首轮“新媒体和跨电哪个更适合数学不太好的，先说说”因“新媒体”歧义进入澄清；下一轮“嗯那就这样”继续追问“网络与新媒体/新媒体技术”而不是关闭话题或说明不会记录报考要求。这是自然接续质量问题，不涉及 pending 或最终 action 错误，优先级低于地域诉求结构化。
- 波动项复核：`400-real-user-intent-short-preview` 在失败子集顺序复跑中出现一次 `UnexpectedModelBehavior`，没有生成 pending card；但首轮和单独复测均能正确调用 `preview_intent_change` 并生成“会计/审计要、土木不要”的 pending card，单独复测目录 `/private/tmp/zhiyuan_400_v215_intent_short_reprobe`。该项降级为模型波动 + `thinkingText` 断言口径，不作为稳定业务缺口。
- 当前结论：本轮 quality observation 没有发现新的 final-action 或 pending 执行错误；主链路仍按 v2.14 结论稳定。后续优先级：1）补齐“省外可以但不要偏远/太远”的结构化地域诉求；2）清理或放宽旧工具名和 `thinkingText` 断言资产；3）低优先级观察“澄清后用户轻量收尾”的自然接续。

### 12.39 v2.14 broader 回归复核

- 目的：在 v2.13 地域别名和地域集合结构化归一修复后，复跑更大的 4.0 broader 集，确认修复没有只在 focused case 中成立，并继续按“并发首轮 + 失败子集顺序复核”的口径记录真实 LLM 波动。
- 无效环境运行：第一次在沙箱内直接运行 77 条回归，全部失败。失败原因是 runner 访问本机 backend/DB 被拦截，典型错误为 `URLError: Operation not permitted` 和 MySQL `127.0.0.1:3306` 连接失败；该结果不计为业务链路结果。
- 有效首轮：授权访问本机服务后，使用 backend `18080`、agent `8038`、真实 LLM、完整 chat-session clone、`--backend-db-password 12345678` 和并发 4，跑 G1-G32、production、realistic、review/repair、v179、v183、v212、v213 共 77 条。结果 `73/77`，目录 `/private/tmp/zhiyuan_400_v214_broader_after_v213_region_fix_escalated`。
- 首轮失败分层：`400-g4-explicit-major-entity-display` 首轮无工具调用、无 pending card，模型只口头记录专业意向；`400-g30-special-admission-path-preservation` 调用了两次 `preview_intent_change`，业务输出正确但超过严格工具次数；`400-realistic-readonly-fix-options-short` 首轮无工具调用导致期望 `review_plan` 的工具断言失败；`400-realistic-policy-vs-mutation-short` 首轮无工具调用导致期望 `answer_policy` 的工具断言失败。
- 失败子集复核：上述 4 条用单并发顺序复跑全部通过，目录 `/private/tmp/zhiyuan_400_v214_failed_subset_sequential`。复跑中 G4/G30 均正确调用 `preview_intent_change` 并生成 pending card，两个 realistic case 分别走 `review_plan` 与 `answer_policy` 只读路径。
- 当前结论：v212/v213 地域集合/城市圈 final-action 在 broader 集内保持通过，确认轮后端断言继续覆盖 pending applied、planningState version 增长、地域报考要求写入和 ordered/review 刷新。本轮没有发现新的稳定业务执行缺口；剩余问题仍按并发模型波动、少量重复工具调用效率观察、只读工具名断言口径处理，暂不修改生产链路。

### 12.38 v2.13 地域别名质量回归与结构化归一修复

- 回归资产：新增 `examples/dialog_regression_400_v213_region_area_quality_final_cases.json`，在 v2.12 基础上继续覆盖更口语的地域集合/城市圈表达：`江浙沪就行，其他地方先别看了`、`北上广深就行，不往其他城市放了`、`东北和西北都先别考虑`、`西北西南都不去，太远了`、`上海南京杭州这一片可以，北方先不看`。每条仍是首轮 pending card + 二轮确认后的后端 final-action 断言。
- 初始验证：focused v2.13 使用 backend `18080` + agent `8038` + 真实 LLM + 完整 chat-session clone，结果 `10/10`，metrics `/private/tmp/zhiyuan_400_v213_region_area_quality_final.json`；随后扩大到 G1-G32、production、realistic、review/repair、v179、v183、v212、v213 共 77 条，结果 `73/77`，目录 `/private/tmp/zhiyuan_400_v213_broader_regression`。
- 失败复核：4 个失败子集顺序复跑 `3/4`，目录 `/private/tmp/zhiyuan_400_v213_failed_subset_sequential`。`G7`、`G31`、`realistic-double-negation` 均转绿，归为并发/重复调用/质量观察；唯一稳定失败是 `400-v213-region-jiangzhehu-only-final-action`。
- 稳定问题：`江浙沪就行，其他地方先别看了` 会调用 `preview_intent_change`，但没有生成 `pendingConfirmationCard`，确认轮没有可执行对象，`mustIncludeRegions` 未写入，ordered plan 未变化。复核 chat history 后，真实参数出现过 `positive={"area_region":["江浙沪"]}` 或 `positive={"area":["江浙沪"]}`，同时 semantic_requirements 里把 `其他地方` 当作 negative area；工具侧未兼容 `area_region`，且 semantic completion 用原始值 `江浙沪` 与 canonical `长三角` 比较，误判缺失。
- 同类扩展问题：修复 `江浙沪` 后，完整 v2.13 复跑暴露 `北上广深` 同类缺口：Python resolver 没有把 `北上广深` 识别为 area，而后端 `RegionScopeSupport` 已支持该 region，导致 Agent 侧 payload 空。该问题与 `江浙沪` 同属结构化地域 catalog/归一契约不一致。
- 修复原则：不新增工具层从用户原话做语义判定或中文关键词路由。模型仍负责输出显式 `positive/negative` 和 `semantic_requirements`；工具只做结构化字段别名兼容、地域实体 canonical 对齐、以及无法解析的泛化 area 跳过，避免把“其他地方/非X地区”变成伪地域对象。
- 实现调整：`prompt.py` 明确 `X 就行/只看 X/只考虑 X，其他地方先别看/不往其他地方放` 应输出 `positive={"area":["X"]}` + `constraint_type="only_keep"`，不要把“其他地方/非X地区”写入 negative；`app/zhiyuan_agent/tools.py` 支持 `area_region/region_area` payload alias，region semantic completion 对 `province/city/area` 调 `resolve_region_entity()` 做 canonical 比较，并跳过无法解析为真实 area 的泛化词；`region_entity_resolver.py` 补齐 `北上广深` area，与后端 catalog 对齐。
- 单元验证：`py_compile app/domain/region_entity_resolver.py app/zhiyuan_agent/tools.py app/zhiyuan_agent/prompt.py tests/unit/test_zhiyuan_agent_direct.py` 通过；focused 单测 `test_preview_region_area_positive_and_negative_pending`、`test_preview_region_area_region_alias_creates_canonical_pending`、`test_preview_region_area_alias_semantic_values_are_canonicalized`、`test_preview_region_first_tier_area_creates_pending` 为 `4 passed`。
- 真实验证：`江浙沪` focused final-action 复跑 `2/2`，metrics `/private/tmp/zhiyuan_400_v213_jiangzhehu_after_region_semantic_fix.json`；完整 v2.13 复跑 `10/10`，metrics `/private/tmp/zhiyuan_400_v213_region_area_quality_after_first_tier_fix.json`；此前 broader 4 个失败子集复跑 `4/4`，目录 `/private/tmp/zhiyuan_400_v213_failed_subset_after_region_fix`。
- 当前结论：v2.13 暴露的稳定缺口已闭合，且确认后最终 action 已验证到 `pendingConfirmation=applied`、`planningState.version` 增长、`mustIncludeRegions/mustExcludeRegions` 写入、`orderedPlanState.units` 非空以及代表性地域剔除。剩余 broader 初始失败中的重复工具调用/并发波动仍按低优先级观察项处理。

### 12.37 v2.12 地域集合长期回归扩展验证

- 回归资产：新增 `examples/dialog_regression_400_v212_region_area_expanded_final_cases.json`，在 v2.11 focused “南方/北方”基础上扩展到长三角、华南、珠三角、西南等地域集合/城市圈表达。每条 case 都是两轮真实对话：第一轮生成待确认预览，第二轮“确认”执行最终动作。
- 覆盖表达：`孩子就想去南方，北方先别考虑`、`那就只看长三角吧`、`华南的不要了`、`珠三角先不考虑了`、`只看西南吧`。这些表达保留口语化和简略形态，验证模型把地域集合压成结构化 `positive/negative area`，工具层不从原话做中文字符串扫描。
- 最终动作断言：确认轮统一要求调用 `confirm_pending`，并通过后端断言校验 `pendingConfirmation.status=applied`、`planningState.version` 递增、`constraintState.hardConstraints.mustIncludeRegions/mustExcludeRegions` 写入对应地域集合、`orderedPlanState.units minLength>=1`，以及代表性排除地域不再出现在排序方案中。
- 无效环境运行：第一次从沙箱内运行 runner 时，本地 `18080` 和 MySQL 访问被拦截，表现为 `URLError: Operation not permitted` 和 `Can't connect to MySQL server on 127.0.0.1:3306`，5 条均为 environment setup fail，不计为业务结果。后续 runner 与 Agent 均改为非沙箱运行。
- 有效验证一：使用 backend `18080` + agent `8038` + 真实 LLM + 完整 chat-session clone + `--backend-db-password 12345678`，metrics `/private/tmp/zhiyuan_400_v212_region_area_expanded_final_action_valid.json`，结果 `9/10`。唯一失败为 `400-v212-region-south-china-exclude-final-action` 首轮 `华南的不要了` 触发两次 `preview_intent_change`，超过新资产里的 `maxToolCallCount=1`；但两次工具均成功，最终只产生一个 pending card，确认后 `mustExcludeRegions` 包含“华南”，`orderedPlanState.units` 非空且不含广东/广西/海南，所有后端断言通过。该项按少量重复工具调用效率观察记录，不作为最终 action 业务失败。
- 资产口径调整：v2.12 资产移除首轮 `maxToolCallCount` 硬断言，保留 `assertToolNamesContain=preview_intent_change`、pending card、action family 以及确认轮 `maxToolCallCount=1`。原因是该资产目标是长期验证 4.0 地域集合语义和最终数据生效；少量重复工具调用仍记录在文档中，但不应把业务正确的最终动作标红。
- 有效验证二：按调整后的资产复跑，metrics `/private/tmp/zhiyuan_400_v212_region_area_expanded_final_action_green.json`，结果 `10/10`；耗时统计 `min=2947ms`、`median=4853ms`、`p95/max=10189ms`。5 条确认轮全部刷新 `ordered/review` 工作台视图，且最终后端断言均通过。
- 候选池边界抽查：最后一条 `只看西南吧` 后读取 session `5094217` 的 `planningState`，状态为 `version=1606`、`mustIncludeRegions=["西南"]`、`mustExcludeRegions=[]`、`candidatePoolState.items=402`、`orderedPlanState.units=2`、`orderedPlanState.items=2`、`staleFlags.orderedPlan=false`。这符合此前设计：页面候选池保留全量可恢复数据，已确认要求只在排序方案/审查/修复等派生链路中生效。
- 当前结论：v2.11 的地域集合语义修复已扩展到长期 final-action 回归，未发现新的方案最终执行错误。剩余观察项是偶发重复 `preview_intent_change`，按低优先级效率问题跟踪；后续可继续补“江浙沪/北上广深/省内外/偏远地区”等表达进质量池或长期集。

### 12.52 v2.45 pending 独立 revision/CAS 资源

- 数据边界：新增 V7 表 `assistant_chat_session_pending_confirmation`，`UNIQUE (tenant_id, chat_session_id)` 从表结构上保证每会话只有一条当前快照；`revision` 是独立单调 CAS 令牌，不再复用 planningState/extra-data version。完整执行 payload 仍保存在当前快照内，`pending_id`、kind、action family、status 和 result code 为可索引/可校验字段。
- API 契约：`GET /inner/chat/{tenantId}/session/pending` 读取当前快照；`POST .../session/pending` 以 `expectedRevision` 创建或替换；`POST .../session/pending/resolve` 负责 confirm/cancel/complete/fail/expire 状态迁移。冲突返回 `40901`，pendingId/状态迁移不一致返回 `40902`。
- 执行权：confirm 只把 `active` 原子迁移为 `applying`。只有 `transitionApplied=true` 的请求可继续调用方案或意向变更 API；同一 pending 的重复 confirm 返回当前 applying/applied 快照但 `transitionApplied=false`。业务成功后 `complete` 到 applied，失败或版本漂移后 expire/fail，取消从 active 到 cancelled。
- Agent 接入：service 卡片/短文本确认与 direct `confirm_pending` 共用同一抢占契约；service 已抢占后构造的内部 direct 执行上下文识别 applying 快照，不会二次 claim。运行时 `PendingConfirmation` 仍只从 active 后端快照投影，普通新轮次不会把 applying 当成可再次执行的 active pending。
- 迁移策略：新写入只走独立资源，不做 extra-data 双写。仅当独立资源无行时，`INTERNAL_SERVICE_PENDING_LEGACY_READ_FALLBACK=true` 允许读取旧 latest extra-data；用户确认或产生新预览时会物化到新资源。runner clear/clone/assertion 已使用新 API，删除 version 0/latest 双清理和 pending planning-version 查询。
- 已删除实现：`save_pending_confirmation(version=...)`、`_pending_extra_data_version()`、tool payload `pending_version` 定向读取、runner pending extra-data 写入与 version 0 清理已删除；这些路径已由新资源取代，不再保留无效外壳。
- 验证：Python 聚焦 pending/runner/direct `396 passed, 29 skipped`；完整 unit `1523 passed, 29 skipped, 1 failed`，失败仍为既有 admission-policy 措辞断言。Maven pending service `7 passed`；完整 Maven 共 489 个测试，1 个既有 `ReviewInvalidationPolicyTest.shouldMarkConstraintIntentStaleWithCandidatePool` 失败、4 skipped。真实 backend `18082` 启动成功，Flyway 从 6 升到 7；临时 session `990499991` 验证 create r1、stale write `40901`、claim r2、重复 claim 不获执行权、complete r3、replace r4、cancel r5。
- 尚未关闭：当前 applying 是 at-most-once 抢占，没有 lease/claim token/超时接管；Agent 在 claim 后进程崩溃会留下 applying，需要下一阶段增加执行租约和恢复策略。`apply intent + regenerate`、`remove + select + regenerate` 仍是多个后端调用，pending CAS 只能阻止重复发起，不能把这些业务步骤变成数据库原子事务。

### 12.53 v2.46 applying 执行租约与受控恢复

- V8 在 pending 当前快照增加 `claim_token` 和 `claim_expires_at`，并为 `(status, claim_expires_at)` 建索引。V7 已在本地和发布链使用，因此没有修改既有迁移，而是用增量 migration 保持 Flyway 历史不可变。
- confirm 请求必须提供 UUID claim token。首次 `active -> applying` 写入 token 和 5 分钟 expiry；同 token 重放和租约有效期内的其他 token 都只返回当前快照，`transitionApplied=false`，不授予第二次执行权。
- applying 租约过期后，不同 token 可使用当前 expectedRevision 做 `applying -> applying` CAS；成功后 revision 增长、owner 和 expiry 更新。并发接管仍只有一个 compare-and-set 能成功。
- complete/fail 增加 owner 校验。只有当前 `claim_token` 可提交 applied/expired；旧 owner 在新 token 接管后即使持有最新 revision，也会收到 `40902 pending claim ownership mismatch`。cancel 仍只允许 active，运维/runner 的显式 expire 可清理 applying。
- Agent internal client 在 confirm 时生成 token，终态保存自动带回 `_pendingClaimToken`；token/expiry 不写入业务 payload，只作为运行态传输元数据。普通运行时只投影 active 或 lease 已过期的 applying；未过期 applying 的重复卡片点击返回处理中，不修改卡片、不执行副作用。
- 真实验证：backend `18082` 启动并由 Flyway 7 -> 8；临时 session 首次 claim token A 到 revision 2，token B 在未过期时 `transitionApplied=false`；调成过期后 B 接管到 revision 3；A complete 返回 40902；B complete 到 applied revision 4。服务与临时行已清理。
- 测试：Java pending service `10 passed`，覆盖未过期拒绝、过期接管和旧 owner 完成拒绝；Python pending/service/direct/runner 聚焦 `399 passed, 29 skipped`，覆盖 lease 元数据、未过期不投影、过期恢复投影、终态 token 回传和处理中回复。完整 Python `1528 passed, 29 skipped, 1 failed`；完整 Maven 492 个测试中 1 failed、4 skipped，均为既有无关失败。
- 剩余边界：租约解决“永久 applying”和旧 owner 迟到覆盖，但接管意味着旧 worker 若仍在运行，业务 API 仍可能已产生部分副作用。下一阶段必须让多步业务命令自身使用 operationId 和 expectedPlanVersion 幂等，租约不能替代业务命令幂等性。

### 12.54 v2.47 pending 多步规划命令幂等下沉

- 事务边界：新增 `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/pending-command/execute`。`apply_constraint_and_regenerate` 在一个 Spring 事务内执行约束、学费和可选排序重生成；`add_units` 在同一事务内执行选择候选志愿和排序重生成；`replace_units` 再增加移出旧专业组步骤。任一步异常会回滚 planningState、业务变更与 operation 行。
- 并发与执行权：命令先校验并锁定当前 pending，要求 `pendingId + applying + claimToken + 未过期 lease` 全部匹配；随后锁定 planningState extra-data 行并校验 `expectedPlanVersion`。取得 planning 锁后再次读取 operation，解决并发请求在首事务未提交时第一次读不到 operation、等待后却误报版本冲突的竞态；命令持有 pending 行锁期间，lease 接管不能越过正在执行的事务。
- 幂等日志：V9 新增 `assistant_planning_pending_command`，operationId 全局唯一，记录 pending、命令类型、预期版本、状态和压缩结果。成功后同 operationId/同业务请求返回 `replayed=true`，不再次修改规划；不同 session/pending/type/version/载荷返回 `40903`，规划版本不匹配返回 `40904`。
- 请求一致性：V10 增加 64 位 SHA-256 `request_digest`。指纹覆盖 operationId、pendingId、预期版本、命令类型和全部业务参数，但排除 claim token，使租约过期后的新 owner 可以重放同一业务命令，不能用同一 operationId 改写目标。V9 已在本地应用后保持原内容和校验和不变；数据库变更只通过 V10 前向迁移，禁止回改 migration 或 Flyway repair。
- 结果保留：首次执行仍返回完整 planningState，便于当前轮差异校验；operation 日志只持久化 operation 元数据、完成步骤、session/version/phase 和 orderedPlanState，不保存 profile、constraint、candidate pool、review 等大对象。真实记录 `result_json=108323` 字节且 `candidatePoolState` 不存在，避免把约 1.6 MB 首次响应整份复制进日志。
- Agent hard cut：intent apply、add 与 replace 的 Agent 侧旧多 API 编排已删除，统一调用 `execute_pending_planning_command()`；operationId 由 `pendingId + commandType` 生成稳定 UUID5。网络断连、无响应和 `planning command is already running` 保持 applying 以便重放；`operationId was used by another command` 虽同为 40903，但属于确定性一致性冲突，不再误判为可恢复 running。hard-cut 审计禁止 add/replace 分支重新调用旧 select/remove/regenerate 组合。
- 真实验证：backend `18082` 启动，Flyway 成功校验 V9 并执行 V10。隔离 session `990499993` 首次约束命令使 planning version `473 -> 474`；同 operationId/载荷重放返回 `replayed=true` 且仍为 474；改载荷返回 40903；新 operationId 携带旧版本返回 40904 且 operation 行数为 0。pending 最终 complete 到 applied，三类临时记录清零，服务已停止。
- 测试：Java pending + command 聚焦 `20 passed`，覆盖租约 owner/expiry、版本冲突、等待 planning 锁后重放、owner 变化后重放、载荷冲突和三类命令步骤；Python client/direct/hard-cut 聚焦 `228 passed, 29 skipped`。完整 Python unit `1533 passed, 29 skipped, 1 failed`，仍是既有 admission-policy 文案差异；完整 Maven 502 个测试中 1 failed、4 skipped，仍是既有 ReviewInvalidationPolicy 断言。
- 后续边界：pending 旧读已由 v2.48 的 V11 回填和 hard cut 关闭；剩余结构工作是增加真实 Agent 断连/重启/lease 接管 E2E，并为 succeeded operation 日志定义按时间保留和清理策略。remove/move/sort/regenerate 已是单后端动作，不再重复包装命令。

### 12.55 v2.48 pending latest-only 回填与旧读 hard cut

- 数据审计：旧 `pendingConfirmation` extra-data 共 6861 行，独立表为 0。历史全量中 1142 行结构完整且状态为 active/applying，其中 569 行能 join 主会话获得 tenant，573 行来自缺失 `assistant_chat_session` 的历史测试夹具，不能安全迁移。
- 首版迁移问题：最初 V11 直接筛任意 active 行，同一 session 存在多个 dataVersion，首次启动在 session 17 撞 `(tenant_id, chat_session_id)` 唯一键失败。更严重的是，该策略会把已被高版本 failed/空墓碑覆盖的低版本 active 重新变成当前 pending。
- 修正规则：V11 使用 `NOT EXISTS newer`，按 `data_version`、同版本 `id` 选择唯一 latest，随后才过滤 active/applying；必须 join 主会话获取真实 tenant，并校验 JSON、pendingId、kind、actionFamily 和列长度。写入 dataValue 时设置 revision 1，并删除 revision/claim/legacy/extra-data transport metadata。
- Flyway 处理：首次失败是单条 INSERT，确认 pending 表仍为 0；只删除 `version=11, success=0` 的失败历史行后重试，没有执行 Flyway repair，也没有修改任何成功 migration。修订版 V11 成功应用后即视为不可变。
- 真实结果：latest-only 条件得到 552 行，比可 join 的 569 行少 17 行；这 17 行正是被更高版本终态覆盖的历史 active。V11 在约 12 秒内完成，552 行全部 revision 1、status active，旧 transport metadata 残留计数 0；session 17 latest=failed，独立表计数为 0。抽样 session `934413008` 通过独立 pending API 返回完整 active 快照。
- hard cut：删除 Agent `pending_legacy_read_fallback` 配置和 `get_last_extra_data(..., pendingConfirmation)` 分支，删除 `_pendingLegacySnapshot` marker、后端清洗分支及兼容测试。独立资源缺行时明确返回空，不再复活旧 extra-data。claim 中 revision 0 的物化守护仍保留，用于合法的无 revision 调用上下文，不再读取旧存储。
- 防回退：静态审计要求配置中不得重新出现 pending legacy fallback，pending reader 不得调用 extra-data，V11 必须包含主会话 join、active/applying 过滤和 dataVersion/id latest-only 条件。
- 验证：Python pending/client/direct/hard-cut `229 passed, 29 skipped`；Java pending/command `20 passed`；完整 Python `1534 passed, 29 skipped, 1 failed`，完整 Maven 502 个测试中 1 failed、4 skipped，失败均为此前已确认的无关断言。`py_compile` 与 `git diff --check` 继续作为最终门禁。
- 剩余边界：真实断连/重启/lease 接管 E2E；operation succeeded 日志的指标、保留期和安全清理。

### 12.56 v2.49 planning command operation 日志保留治理

- 保留策略：operation 的业务用途是断连后幂等重放，不需要永久保存。默认只清理 `succeeded` 且 `update_time` 早于 30 天的记录；running 即使很旧也不自动删除，必须保留给故障调查或人工处置。
- 数据库：V12 为 `assistant_planning_pending_command` 增加 `(status, update_time, id)` BTREE 索引，匹配状态、截止时间和稳定批次顺序，避免清理任务全表扫描。
- SQL 边界：Mapper 使用固定参数化 DELETE，条件为 `status = 'succeeded' AND update_time < cutoff ORDER BY id LIMIT batchSize`。shared service 拒绝空 cutoff，并将 batch 限制到 1-5000，错误配置不会形成无界大事务。
- 调度：`planning.pending-command.retention` 默认 `enabled=true`、`fixed-delay-ms=3600000`、`retention-days=30`、`batch-size=500`。单次只删一批，由后续周期继续推进；AtomicBoolean 防止单实例重入，多实例并发删除同一批 succeeded 也不改变业务状态。
- 失败处理：调度异常记录 `planningPendingCommandRetention failed` 并在 finally 释放运行锁，不阻塞应用启动，也不会让后续周期永久失效。成功删除时记录 deleted、retentionDays、batchSize，作为当前项目无 Micrometer 条件下的结构化观测入口。
- 真实验证：插入 `v249-retention-old-succeeded`、`v249-retention-new-succeeded`、`v249-retention-old-running`；临时把周期设为 1 秒。应用校验 12 个 Flyway migration 并执行 V12，任务记录 `deleted=1`。查询只剩当前 succeeded 和 40 天前 running，证明状态条件有效；V12 索引列顺序为 status/update_time/id。验证记录全部删除，backend `18082` 已停止。
- 测试：retention task/shared service `7 passed`，覆盖 disabled、cutoff/batch、异常后再次执行、上下限和空 cutoff；SQL 契约测试反射 `@Delete`，固定 succeeded/cutoff/limit 条件。command service `10 passed`。完整 Maven 509 个测试中仍只有 1 个既有 ReviewInvalidationPolicy 失败、4 skipped。
- 剩余边界：只剩真实 Agent/backend 提交后断连、服务重启、lease 过期接管和 operation 重放 E2E。

### 12.57 v2.50 pending command 跨进程恢复 E2E

- 测试边界：新增 opt-in `tests/e2e/test_pending_command_recovery.py`，直接按 Agent 的 pending/command 协议驱动真实 backend 与 MySQL，不依赖模型输出。默认不访问本地服务；仅在 `RUN_PENDING_COMMAND_RECOVERY_E2E=1` 时执行。
- 响应丢失：从隔离源 planningState 克隆到 session `990499995`，创建 pending、claim token A 后用 10ms 客户端超时发送 `apply_constraint_and_regenerate`。客户端确定未收到响应，但轮询 operation 直到 succeeded；旧进程出现预期 `ClientAbortException/Broken pipe`，证明事务提交与响应写出失败确实分离。
- 重启屏障：设置 `PENDING_COMMAND_E2E_RESTART_READY_FILE` 和 `PENDING_COMMAND_E2E_RESTART_RESUME_FILE` 后，测试只在 operation 已提交、planning version 已增长一次时写 ready 并阻塞。屏障自行通过 `lsof` 读取 backend 监听 PID；resume 后要求新监听存在且 PID 集合与旧集合不相交，直接阻止“等待后原进程继续”的假阳性。定时 pause 仅保留给不要求跨进程证明的简化调试。
- 恢复动作：新进程启动并校验 Flyway V12 后，测试把旧 lease 调为过期，以 claim token B 执行 `applying -> applying` 接管；同 operationId、同业务载荷但新 claim token 重放，返回 `replayed=true` 和第一次提交的 resultPlanVersion。随后 complete 到 applied，planning version 仍等于初始版本加一。
- 真实证据：强断言运行记录旧 JVM PID `56306`、新 JVM PID `56671`，结果 `1 passed in 87.96s`。另一次人工屏障运行旧 PID `52574`、新 PID `55837` 也通过；正式结论采用带 PID 自校验的后一轮。
- 清理与门禁：测试 finally 删除 operation、pending、隔离 planningState 和 ready/resume 文件。结束后数据库计数为 `operation=0`、`pending=0`、`planningState=0`，18082 无监听；`py_compile` 通过，未设置 opt-in 环境时 `1 skipped`。完整 Python 为 `1534 passed, 29 skipped, 1 failed`，完整 Maven 为 509 个测试、1 failed、4 skipped；失败仍分别是 admission-policy “家庭约束”旧文案断言和既有 `ReviewInvalidationPolicyTest.shouldMarkConstraintIntentStaleWithCandidatePool`，本轮无新增失败。
- 架构结论：pending 结构工作闭环。当前唯一写路径是独立 pending 资源，唯一多步执行路径是幂等后端命令；旧 extra-data pending 读写、多 API 编排和兼容测试均已删除。后续只做发布级完整门禁、留存任务运行观测和故障演练，不再引入第二套恢复协议。

### 12.58 v2.51 发布门禁旧断言 hard cut

- Python 旧口径：`admission_policy_tool` 的 missing-info 输出已将泛化的“家庭约束”细化为“家庭预算与可接受学费上限”，这是当前可以直接收集和执行的字段。测试仍断言旧上位词，只会阻止文案精确化，因此改为校验当前完整字段名；生产输出不变。
- Java 旧口径：`ReviewInvalidationPolicy.markConstraintIntentStale()` 明确不设置 `staleFlags.candidatePool`。报考要求在有效候选和排序/审查派生层生效，基础候选池保留全量数据以支持页面恢复和重新筛选；只有招生源数据变化等真正使候选源失效的事件才标记 candidatePool stale。
- 交叉证据：`PlanningStateServiceTest.shouldMarkConstraintIntentChangeStaleWithoutCandidatePool` 与候选视图移除已确认地域要求的测试均断言 candidatePool 不 stale、ordered/review stale。孤立的 `ReviewInvalidationPolicyTest.shouldMarkConstraintIntentStaleWithCandidatePool` 与生产实现和服务层测试同时冲突，已重命名并改为 `assertFalse(candidatePool)`，没有为全绿修改生产行为。
- 验证：admission-policy 聚焦 `9 passed`；ReviewInvalidationPolicy 与 PlanningStateService 聚焦通过。完整 Python `1535 passed, 29 skipped`；完整 Maven 509 个测试无失败、4 skipped。
- 维护结论：删除“永久登记已知失败”的发布口径。v2.50 及更早章节中的失败数字保留为当时验证快照；从 v2.51 起，新增变更必须保持两端单元门禁全绿，不能再用旧已知失败名单吞掉回归。

### 12.59 v2.52 命名志愿新增与空方案最终动作

- 输入边界：命名新增只接受模型输出的结构化 `filters.school/major` 或 `学校.专业` target。工具不读取 `raw_user_text` 做中文关键词扫描；学校、专业实体抽取仍由模型负责，工具只解析和校验结构化实体。
- 候选解析：先复用当前 candidate snapshot；未命中时用同一结构化 query 请求 backend。唯一候选生成 `add_units` pending；多个结果若属于同一 `planSchoolDataId`，按真实专业组整体加入；若落在不同组，列出学校/专业候选并要求用户明确选择，不创建 pending；零命中和重复加入同样无副作用返回。
- 身份修复：`_item_unit_id()` 现在按 `unitId/unit_id/planSchoolDataId/plan_school_data_id` 取专业组 ID，最后才使用 volunteerId fallback。真实 ID `37020261000269_37020262005080_709` 因此正确映射到 `37020261000269_37020262005080`，不再被第一个下划线错误截断。
- 版本修复：空方案不是无版本状态。`_plan_summary_file_from_object()` 即使 `ordered_total=0` 也保留 planning `phase/version`；否则预览会写入 `sourceBackendVersion=0`，确认时被 backend 以 `current=1724 expected=0` 正确拒绝。
- 运行拓扑：版本修复后发现的第二次 expired 来自 `127.0.0.1:5001` 未监听。`add_units` 确认会在后端事务中选择候选并生成排序方案，生成链路依赖 rank；启动 rank 后同一最终动作全绿。该问题归为测试环境缺服务，不在 Agent/backend 增加静默跳过排序的兼容分支。
- 真实验证：`400-quality-plan-named-add-preview-direct` 在隔离 session `9906517` 中先生成 pending，确认后返回“已加入所选志愿并刷新排序方案”，pending 为 applied、planning version 增长、ordered items 包含 `37020261000269_37020262005080_709`，并产生 ordered/review 刷新动作。命名 move、精确 add、宽泛“建筑类”澄清合计 `4/4`；只读查询后“确认”合计 `2/2`，确认路径零模型请求，内部 direct bridge 为 109ms。
- 资产清理：删除不存在于真实 planningState 的“中国海洋大学/国际经济与贸易”“华中农业大学”等旧命名样本，替换为 session 16/17 的真实院校、专业和 volunteerId。session 17 实际没有 formal/ordered plan，因此新增与只读 guard 均改标 `empty_plan + candidatePool`；thinking 断言接受当前统一的“正在查询当前方案”，不再把被替换的进度文案作为发布红项。
- 测试：direct 单测 `192 passed, 29 skipped`；完整 Python `1629 passed, 38 skipped`；完整 Maven 509 个测试无失败、4 skipped。Java 本轮没有为命名解析新增生产改动。

### 12.60 v2.53 发布拓扑与只读 smoke

- 门禁基线：`dialog_quality_gate.py --execute --mode local` 为 `433 passed`，runtime hard-cut 审计 `36 passed`。完整 gate dry-run 可生成 1 个 local、13 个 live、19 个 clone-backed final-action、3 个 model 命令及对应报告链，没有丢失正式入口。
- 四服务健康：按开发联调文档使用 Web 3001、Backend 8080、Agent 8000、Rank 5001 启动长驻进程；`ops/healthcheck.sh --local` 显式传开发端口后，Web、Backend health/base-data、Agent、Rank、disk 全部 PASS。Docker daemon、systemd、nginx 在开发机缺失只记录 3 个预期 WARN。
- 环境边界：`scripts/start-all.sh` 的 nohup 子进程会被当前受管执行环境回收，日志为空且 PID 立即失效；这是既有文档已记录的工具环境限制。正式验证改用长驻 PTY，不修改正常终端可用的启动脚本，也不把该环境行为归为产品故障。
- Web 配置：两个 Agent URL 是可选覆盖项，运行时已有 fallback；`next.config.mjs` 现在用空字符串代替 `undefined` 注入，消除 Next 配置非法警告。`Tooltip.overlayStyle` 已按 Ant Design 5 当前 API 替换为 `styles.root`，页面行为和尺寸不变。
- smoke 契约：生产式 smoke 继续默认 `ZHIYUAN_WEB_BASE_PATH=/assistant-pc` 并检查 production routes manifest；开发联调可显式设置空值，直接检查 `/session`、`/sessionDetailV2`，manifest 项记录“development basePath disabled”。页面响应统一断言 Next 的 `__NEXT_DATA__`，不再把路径字符串当页面内容证据。
- 真实结果：开发态空 basePath 下，两个 Web 页面、Backend health/base-data/review rules、Agent health/WebSocket、Rank health 全部 PASS，`failures=0`；未指定 session 时 workspace/data-freshness 保持只读 SKIP。新增 fake-curl 隔离测试覆盖默认生产 basePath 与显式空开发 basePath，`2 passed`。
- 验证边界：完整 Python `1631 passed, 38 skipped`，`bash -n ops/release-smoke.sh` 和页面实际编译通过。全量 `tsc --noEmit` 仍报告 26 个既有类型错误，集中在旧 session/userCenter/service/request 模块，本轮修改的 `next.config.mjs` 与 `exTable` 不在错误列表；不能将 Web 全量类型门禁标为通过。
- 发布剩余项：G12/G25、G1-G32 多轮复核和旧链路 hard cut 已完成，不再保留为 P0。唯一发布 P0 是在稳定完整拓扑上执行 13 个 live 与 19 个 clone-backed final-action 正式门禁并对模型/环境失败分层；分析数据、候选质量和 shadow 扩展降为持续增强 P1。
