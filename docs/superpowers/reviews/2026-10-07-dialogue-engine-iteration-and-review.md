# 对话引擎化迭代与独立审查（2026-10-07）

> 性质：当日执行记录 + **独立审查发现清单**（审查方未参与实现，只读）。
> 基线：`81a09d4`（昨夜）→ 当日提交至 `d098da8` 及后续。
> 关联：[10-06 链路打通与恢复](2026-10-06-test-www-chain-recovery.md)、[总计划](../../release-4.0.0-codex-native-zhiyuan-integration-and-frontend-validation-plan.md)。

## 一、当日交付（全部上线演示栈 18290/18291/3201）

| 切片 | 提交 | 关键读数 |
|---|---|---|
| 分数→位次：inner 端点 + 建档/补录自动补保守位次 | `afe9672` | 安徽 600 → 28600–29273（WL）；浙江 610 → 42829–43879 |
| 位次工具 `catalog.get_score_position` + 空档五项/编码一次查规则 | `d437d50` | 空档只给总分 → 追问不硬出卡（三连 110 治愈） |
| 专业方向推荐 `recommendation.preview_majors` + 本科批默认/科类编码规则 | `9061b8f` | Top8 打分（交通运输类 82.5…）；无画像明确不可用 |
| 候选比较 `recommendation.compare_candidates` | `fedb5db` | 6 维 12 格全带来源；幽灵 id 如实报；只读 |
| 规划态读路径 CAS 化 + NPE 家族 + strengthSubjects | `d098da8` | 压测修前 NPE×10/失败×6/覆盖回退实锤 → 修后 293 次全绿、零回退 |
| 前端：心跳判死、流式人话、历史去重、时间线合并、无效 toast | `cbb256d` `a3a6f16` `cf13683` `93d054b` `8bb8b97` `55c0c1b` | 顺序逐对交错、toast 清零、假死 30s 自愈 |

## 二、独立审查发现（2026-10-07，审查方独立于全部实现方）

**结论：无阻断级；高 3 / 中 5 / 低 7 / 疑点 5。** 以下为处置分级：

### 高
- **H1 ProposalCard 不认 `stale_state`**：原样渲染英文机器态 + 按钮复活（F09 的拒绝路径）。
  → **本波修复**（状态映射中文 + 收起按钮 + 与 legacy 卡口径对齐）。
- **H2 写路径仍是整文档读-改-写**：本轮只 CAS 化了读路径；写-写并发仍 lost-update。
  → **专线修复**（写路径统一 CAS；`savePlanningState` 收敛为私有）。
- **H3 submit/export 对缺 volunteerCount 静默产出 0 配额 + ≤15 候补并置 FINISHED**：
  响亮 NPE 被降级成静默持久化坏产物。→ **专线修复**（submit/export 前置校验拒绝）。

### 中
- **M1 失败卡直出 Java 英文内部消息**（含版本号）→ 并入 H1 波（code 作锚点、文案中文）。
- **M2 位次查询失败静默换当年重试**并被新链路落库 → 专线（仅未指定年份才允许回退）。
- **M3 preview「只读」名不副实且字段集≠执行集** → 并入 Java 专线（javadoc + 补位次进预览）。
- **M4 看门狗可能误杀后台标签节流连接** → 并入前端波（visibilitychange 复位/隐藏期跳过）。
- **M5 测试网眼**：F09 断言弱于注释；ProposalCard 无单测 → 并入前端波。

### 低/疑点（择机）
- L1 applying 期间按钮未收；L2 agent 失败文案内部术语；L3 execute 超时 ≠ 未执行的标注；
  L4 导入竞争窄窗非权威读；L5 位次失败静默无 inline 提示；L6 streamText 首匹配小注；
  L7 declined/not_executable 状态漏配。
- D1 CAS 的 SQL 级行为（真库 LONGTEXT 比较/NULL/collation）未测 → 随 H2 专线补真库用例；
  D2 overlay CAS 连输路径无测试；D3 F09 终态实际码；D4 H3 可达性；D5 后台节流真机验证。

### 审查确认无误的关键假设（摘）
CAS 为真比较集（含 dataVersion+dataValue）；撞键赢家语义正确；测试替身是忠实双；
pong 契约完好（ping 不刷新自己）；时间线合并不变量成立；testid 回归面未破裂；
工具诚实口径（不可用不造数）；补录闭环形状正确；SMS 旁路默认关闭。

## 三、独立 e2e 回归读数（全天重建，2026-10-07 晚补录）
回归线 agent 会话已不可达（无法复述），以下按留档重建：

| 轮次 | 时间 | 契约（13） | 写路径（6） |
|---|---|---|---|
| r1（无后缀） | 17:05 / 17:07 | 12/13 —— **F10 刷新恢复待答卡失败** | 6/6 通过，EXIT=0 |
| r2 | 17:20 / 17:22 | 12/13 —— **F10 同表象失败（稳定复现）** | 5/6 —— F14 偶发（重连后新消息未达服务端） |
| r3 | 17:25–17:27 | ——（未跑） | 0/6 —— 提案卡全未渲染 |
| r3-write2 | 17:30–17:32 | —— | 6/6 通过，EXIT=0（替身重启 + 新盐 + runId 匹配后） |

- **稳定回归候选 = F10**：两轮独立运行、同表象（刷新后 `clarification-card` 未随流回放重现；事件在流里、桥请求仍在；其余 12 条全绿）。归因待排查（今日前端改动引入 vs 既有问题）。
- r3 写路径 0/6：`/tmp/verify-run-write4.sh` 自注"修正 run-id 错配"；重启替身 + runId 匹配 + 新盐后全绿 → 初判夹具/编排态问题，非产品回归（待复核）。
- F14：4 次执行中 1 次失败（r2；重连后 send 未达服务端、`turn-progress` 缺席），其余 3 次通过 → 偶发，记观察。
- 证据：`/tmp/e2e-verify-c4-verify-20261007{,-r2,-r3}-{contract,write}.log` 及 `-STATUS`、`-*-artifacts/`（失败快照：r2 F10、r2 F14、r3 六条）。
- **F10 根因（独立只读排查定稿）**：`clarification.requested` 被以 **codex 原生回合号**（`turn_N`）写流——`fbb281c`（10-06 21:41"事件自带 turnId 优先"，`session_runtime.py:127`）让原生号直通；而刷新补发 `_replay_active_turn` 的过滤（`server.py:676-678`）只认业务 UUID → 回放时该事件被滤掉、卡不重现。窗口：最后全绿 `/tmp/contract-run-1.log`=10-06 12:03 → `fbb281c` 当晚落地 → 今日 r1/r2 为改动后首跑；**与今日前端改动无关**（逐条排除）。副产物：卡被画进原生号另块（F02 因 resolved 后空回合不渲染而侥幸仍绿）。修复方向：broker 边界翻译原生→业务号（勿回退通道盖章）+ 同回合 turnId 一致性不变量测试；补发过滤可加双号防御（非充分）。证据：`/tmp/stream-900022.txt`、r2 error-context、`git show fbb281c -- app/gateway/session_runtime.py`。

## 五、凌晨交接（2026-10-08）

**总状态：10-07 开的全部线已闭环、已上线、用户侧亲验通过**（900040"补足到 80"实测：面板 45 → **80 个专业组** ✓）。

### 已在线（演示栈 3917aa7 谱系 / standardtest bc1e216）
| 项 | 载体 | 证据 |
|---|---|---|
| F10 刷新恢复 | 18291 | r4 契约 13/13 + 浏览器验证 |
| H3/M2/M3 + 35ddbf5 | 18290（后换 h2build jar） | 单测；沙箱 write 6/6 |
| 前端波 H1/M1/M4/M5 | 3201（dev 直读工作树） | 单测 25/25 + 118/118；沙箱 13/13 + 6/6 |
| H2 写路径 CAS | 18290（h2build jar，pid 11888） | 959 单测；D1 8/8；e2e 6/6×2；并发压测；**用户实测 applied → 80** |
| 回滚镜像重建 | docker `zhiyuan-web:prod-3.1.1-hotfix-mobile` = `6637123e69a2` | 冒烟 login 200 |
| 10-08 晚批：契约枚举 `906d5dd` / 前端卡 `f63378d` / 打字确认执行器 `ed471d3` | 18291 + 3201(dev 直读) | 单测 2142 绿（4 既有红已 pristine 复现）；18291 pid 27837 health 200；**用户真栈重试待验** |
| 10-09 晚批：84009 兜底 `76c8662` / 失败码归一 `9de0131` / 死卡纠错回合 `bb5151d` | 18290(pid 28482) + 18291(pid 10268) + 3201(dev) | 兜底**用户实测通过**（19:09 applied code=0，日志 `demo fallback prepareType=PREDICT`，取数 total=929）；归一 26→29 测试 / 纠错 +5 例且 pristine 基线对照 — 全绿 |
| 10-09 深夜：对话口径改造 `ebd049f`（17 文件） | zhiyuan-agent skills + 18291(pid 425) + 插件 cachebuster `…20261009112526` | 2024 单测绿（1 既有红复现无关）；口径源头 design §14；**新线程/新会话生效**，待用户新会话实测 |
| 10-09 深夜二批：确认交互三件套 `2d27455`(web) / `0441790`(agent) | 3201(dev 直读) + 18291(pid 6186) | 双通道等价话术＋applied 自动续接（`cont-` 回合，不落用户消息、proposalRef 幂等、非 applied 不触发）；前端 loading 状态机＋冷加载卡吃事件流（超时 `PROPOSAL_DECISION_TIMEOUT_MS` 可调）；web 154/154、续接+15 例全绿（4 既有红同 pristine）；**待用户验收：打字确认→翻终态＋自动续接** |

### 修复队列（优先级）
1. **代理叙述与预览矛盾**（助手说"从零补满" vs 预览卡"45→80"，后者对）——代理侧口径修。
2. **方案调整预览无逐条明细**（`affectedUnitIds` 空）——后端预览增强（确认前看不到具体哪 35 条）。
3. **900047 缺各科成绩 → 补录 prepare 110 死锁 + 无填写交互**（体验缺口待修）；**数据修复已完成 ✅**（2026-10-08 早，经用户点名授权：`userScoreDetail.subjectScoreList` 空 → 物理78/化学82/生物77，走 `add-extra-data` 写入（记录 id 815），回读验证总分/省份/批次等其余字段一字未动）。
4. H2 遗留：collation 迁移评估（H2-WRITE-CAS-PLAN §6）；checkDataFreshness 保守合并收敛。
5. F02 偶发观察（1 次 30s 超时未复现）；沙箱事件流 24h TTL 跨轮残留（遇"卡串轮"换盐/epoch）。
6. `/tmp` 构建缓存清理（rebuild-311-web ~3G / h2build / **f09fix 先留**——它是 18290 回退件）。
7. **pending 行残留旧字段 + blocked 提案物化成 active**（2026-10-08 晚定位，会话 10041979）：`PendingConfirmationSharedService.compareAndSet` 走 `update`+NOT_NULL → 显式置 null 不进 SET，医学卡 40906/claimToken 残留；`prepareUserGoalProposal`/`buildActiveEntity` 对 blocked 提案照样 upsert 成 requiresConfirmation=true（模型据此误报"已提交"）。**Java 批次（用户已拍板随下批）**：改显式 `set(col, null)`/IGNORED 策略 + blocked 不物化。**10-09 新证**：成功行（status=applied / resolvedAction=complete）也挂着旧 84009——残留会污染任何按 resultCode 读的读者。
8. **契约下一轮收紧**（`906d5dd` 只收域/键/kind/ordering/scope）：`values` 为空、include `min_count=0`、priority 规则多于 1 条、`ProposalScope.scopeType`——现仍属"Java 拒→blocked 卡"一族。
9. `skills/codex/developer_instructions.md` 只在 thread/start 注入、resume 不重发 → 旧线程缺"未拿到 result 不得称已提交"护栏（`ed471d3` 新增）；考虑 resume 时补发。
10. 前端既存不自洽（未动，一行可翻）：`isSettledProposalStatus('active')=true` 会把"待处理"恢复卡在新回合后收起——与 MessageList 注释相冲，待产品决策。
11. **新会话「更新成绩」84009（VOLUNTEER 取数策略缺失，数据侧老账）**（2026-10-09 复现，会话 10041980）：成绩卡 `scoreUpdateRequest` 无 prepareType → `fillProvinceDefaultsIfMissing` 按省策略**实时推导** → 上游已切 2027 新季 = VOLUNTEER → 演示会员 900002 只有 PREDICT 取数策略 → 上游 84009。**已临时绕过**：`76c8662` 加 flag `demo.prepare-type-fallback`（**默认空=关**；仅 18290 本地启动参数 `--demo.prepare-type-fallback=PREDICT` 注入；兜底点仅 `fillProvinceDefaultsIfMissing`，顺序=显式/存量→兜底→省策略）。**边界**：建会话默认与两处 `toProgramQuery` null 默认未接；**存量已写死 VOLUNTEER 的会话仍 84009**。**真解（后续慢慢修）**：①数据侧给合成会员补 VOLUNTEER 取数策略（数据口）；②切季后的模式/年份口径统一（关联 §六② 用户裁决）。
12. **失败文案/事件码统一**（2026-10-09）：`proposal_reference_mismatch` 文案写死"已有更新的预览"，在"无新预览"场景不贴切（`9de0131` 只做了码归一）；网关事件 code 有两种形态（turn 级 `裸码: 明细` 复合串、actionResult 级裸码）——建议生产者统一（裸码+明细分置），前端归一保留作防御。
13. **major-recommend 载荷级原始数值**（2026-10-09 标记，未改）：Java `ChatController.java:213-217` 的 `POST /chat/{tenantId}/major-recommend` 直接返回含原始 `score`/`dimensions` 的 `MajorRecommendItem`；**zhiyuan-web 当前无调用**——未来若接入前端展示，需先做"数值→人话"映射（对齐 10-09 口径，与 `ebd049f` 的指令层改造配套）。
14. **admissionFacts.group_code 契约与数据源缺口**（2026-10-09 实测，会话 10041981 19:51 轮）：模型输出的 8 条 `admissionFacts` 均缺 `group_code`（专业组代码）→ 校验拒 → **修复回合救回但耗时 ~5 分钟**；助手自述"专业组代码这一层仍未随数据返回"。即**契约必填 vs 数据源不提供**的系统性错配——院校事实类输出每轮都可能先撞一次再修复。修法（二选一，倾向①）：①`group_code` 改可空/占位（保留"以省考试院公布为准"口径）；②数据侧补字段（数据批次跟进）。→ **已修 ✅**：`5e6df78`（契约放宽：缺=显式未知放行、提供时必须合法；instruction 随启动生效；+6 测试零回归；18291 pid 16804）。Java 侧复核：组代码**真缺**（`AdmissionFactDTO.groupCode` 声明未接线、全仓无赋值，docs 自记"悬空字段"）→ **端到端接线（候选→招生单元映射 + DTO/证据补字段）另排 Java/数据批次**。
15. **无正式方案会话的"同档前置"预览必 blocked + 话术矛盾**（2026-10-09 实测，10041981 19:56）：模型对无方案新会话提议 `prioritize_within_tier` → Java blocked `user_goal_target_not_found`（"当前还没有正式方案，不能生成同档前置预览"），而模型同轮文字已说"我按这个把初稿排出来了"（模型在提议时不知会被拒，结构性缺口）。修法：①指令层——无正式方案时不得承诺/提议"同档前置"，先走出方案流程；②（可选）`user_goal_target_not_found` 走一次澄清/纠错回合。注：字段合法性已由 `906d5dd` 保证（rollout 实测 `region/city`，非 location.region）。
16. **直辖市城市筛选命中缺失（假否定）**（2026-10-09 审计实测，10041981）：`filters.cityNames` 按 `cityName` **精确匹配**，而直辖市数据存**区级名**（浦东/松江/虹口/海淀 等）→ 查"上海"命中不了上海院校；助手对用户断言"上海/深圳没有筛出财经计划"=**假否定**（池内上海：会计≥5、金融≥4；工具查询 total=7 而模型只看前 5 条亦为诱因）。修法：①筛选层做直辖市→区级展开 / 城市字段规范化（先定位归属：agent 工具 or Java 查询链）；②指令层加"查询为 0/异常少时不得断言'没有'，先排除口径"。影响面=任何直辖市相关查询与叙述。→ **已修 ✅**：`f7f0cd3`（真凶=Java 过滤层 cityName contains 匹配；修在 agent 侧 `internal_client.py` 做直辖市→区县展开 `_MUNICIPALITY_DISTRICTS`(GB/T 2260)，candidate-pool / preview / catalog 三处；只读实测 上海+会计 **0→8**、北京+会计 **0→5**、四城市+会计 **7→20**、目录 **0→44**；18 新测试零回归；**18291 pid 23014**）。**边界**：区名/地级市重名（"朝阳"）本层不区分；Java `addFilterGroup/allowedCities` 的 UI 过滤选项仍只列区名（Java 批次）；"查询为 0 别断言没有"属指令层（同条②）。
17. **推荐叙述越界断言（指令层收口）**（2026-10-09 审计）：实测 4 处——"冲档里唯一的公办"（池反驳：东北石油+兰州理工 2 所）、"稳档计划最多"（池反驳：湘潭理工 90 个）、"上海/深圳没筛出"（同 16）、"广州软件学院（广州）"漏掉事实限定"**江门校区**"。修法（与 15 合并为一批 skills 修改）：最值/唯一/否定类断言必须先逐条核对；校区等限定字段不得省略；查询口径异常先自查再下结论。
18. **admission_evidence_missing 硬失败类**（2026-10-13 实测 ×2，会话 10041981）：模型把**「专业+大学」方案行键**（`canonicalMajorVolunteerId` = `planSchoolDataId + "_" + (planMajorDataId|majorId)`，如 `43020271000088_43020272000269`）当成招生单元号填进 `admissionFacts`，而该轮 `evidenceRefs: []`（preview 工具 200 但无证据签发）→ 与证据逐字匹配永不可能 → 硬失败（用户只见通用文案）。**两套 ID 口径定稿**：①「专业+大学」= A_B 行键（取单元只取第一个 `_` 前段，`WorkingPlanMutationSupport.resolveWorkingPlanUnitId`）；②「院校专业组」= 按 planSchoolDataId 聚合、`schoolUnitId` **单值**。→ **已修 ✅**：`832c53c`（`admission_evidence_missing`/`admission_mode_mismatch` 进**修复回合名单**；hint 说明三条出路——补证据引用并把 unit 改对 / 拆多条事实 / 删无证据事实；指令条同口径；前端人话文案；18291 pid **22479**）。validator 匹配逻辑**未动**（本就要求逐字相等，正确）。
19. **同档前置"只支持一条"死卡**（2026-10-13 实测，10041981）：模型把多层偏好（"北京→财经→沪广深"）塞进一次提案 → Java `priority_rule_invalid`「当前只支持一条同档前置规则；多个有先后层级的优先目标需要先明确顺序」→ blocked 死卡（**新文案体系首次真栈完整亮相：解释/明细/建议/系统提示齐**）。→ **已修 ✅**：`898ba28`（权威约束=Java `PriorityRuleSupport.java:38`，契约层 `priority_rules` 原**无条数约束**是缺口。修法选**网关投递前守卫 + 一次修复回合**（>1 条→修复 hint"只保留最重要一条/先问顺序分步"；修复仍多条→**原样放行**、维持 blocked 卡兜底，不引入新失败路径——故未走契约 `max_length=1`，那会产生 pydantic 二次失败的失控路径）。契约 description 也已写明口径（进模型侧 schema）。+4 测试零回归；18291 pid **3704**）。
20. **调整预览卡面"引擎话"未人话化 + 无逐条明细**（2026-10-13 实测，10041981）：ready 卡面文案"当前方案命中 1 个目标专业组；确认后将其中 1 个在各自冲稳保档内前移，**消除 11 处同档逆序**"——"命中/同档逆序"是排序引擎内部指标，直接上卡面违反 10-09「面向用户说人话、禁甩内部数值」口径；且**不说命中的是哪一个组**（与 §五-2 affectedUnitIds 空同源）。修法（Java/后端批次）：预览 summary 改人话（"把 1 个北京院校专业组在所在档位内前移；档内顺序会一并理顺"）+ 明细里带上命中的具体院校专业组名。
21. **意向权威字段与全链一致性（侦查定稿 + 拍板 A+C+清理）**（2026-10-13，10041981）：实机——apply 只写 `hardPlanningObjectives.priorityRules`；引擎已消费（orderedPlan 北京组保档第12位→**第1位**、前移 11，`orderReason=hard_priority_rank_before`，与卡面"消除 11 处逆序"吻合）；**候选池/overlay 不重算**（冻结在池生成时，25 个北京组排序不体现）；横幅/模型快照均不读 hardPlanningObjectives（**横幅=根因**）。**权威= `hardPlanningObjectives` + `hardConstraints`**（4.0 design §14.3/14.7）；`softPreferences` **已废→legacy 只读**（现网无写者、写链强制 constraint 模式）；`derivedPreferences` 死、`planAdjustmentState` 休眠（清读/写分支、**保留字段**兼容旧会话）。**拍板：A+C+清理**——A 横幅改读 hardPlanningObjectives 派生标签（前端，即时）；C 快照补字段（Java，**随 Java 批部署**，避免打断测试）；清理=保守标记死写分支。**D（优先规则联动候选面板）暂不做**（产品后续另议）。
22. **模型线程失忆（重启/掐断后新建线程、对话历史丢失）**（2026-10-13 实测，10041981）：19:19:33 部署重启掐断"1"回合 → 19:23:41 用户重发时 codex **新建 rollout**（`rollout-2026-10-13T19-23-41-*.jsonl`，无历史；今日序列 18:50/19:07/19:23），模型回复"你回的「1」我这边没接到对应的选项"（UI 有历史、模型看不到）。嫌疑=重启/被掐断回合致线程未 resume 而 thread/start 新建。修法（侦查中）：恢复语义=resume 原线程；不可 resume 时重放历史/显式告知。顺带核实续接回合（cont-*）消息是否入线程历史。
23. **优先规则的 preview/apply 不对称 + failed 无跟话**（2026-10-13 实测，10041981 19:31）："学费≤2万"优先规则 **preview=ready**、用户确认后 **apply 失败 `409 priority_target_not_in_plan: 当前方案没有命中优先目标`**（方案内无 ≤2万 命中项；模型事前已提示"不好凑齐"仍提交）→ ①预览期未拦"零命中"（与 apply 口径不对称）；②**失败结果不触发助手跟话**（续接机制目前只覆盖 applied），用户只见失败卡。修法：a. 网关续接扩展到 failed（nudge=如实解释+替代路径，已派）；b. 指令层：优先类提案前先确认命中目标数 ≥1，0 命中先谈口径；c. Java：preview 与 apply 的命中校验对齐。
24. **学费类诉求被"优先规则"误表达 → 两连 409**（2026-10-13 实测，10041981 19:31/19:33）：学费≤2万/≤3万 两次都走 `prioritize_within_tier` → 同码 409。**语义根因**：优先规则**只能重排方案内已有条目**；方案 45 组中无任何 ≤3万 条目（太湖学院/广州城市理工等在池内、未进方案），模型却对用户说"一下就把兜底档填起来了"——**文案预支未生效操作结果**。修法：a. 指令层——预算/学费类诉求 → **筛选/替换/补档类操作**，禁用优先规则表达（已追加给在飞代理）；b. 预览期拦"零命中"（合并 23）；c. 文案不得把未进方案的候选说成已安排。

### 环境守卫与回退
- `oom_score_adj`：18290/18090 = -500；18291/18091 = -400（内存再紧时优先牺牲测试进程）。
- 18290 回退：`bash /tmp/restart-18290-bc1e216.sh`（bc1e216 jar 在 /tmp/f09fix）；**回退"无兜底"行为**：`bash /tmp/restart-18290-6e7.sh`；10-09 起 18290 运行 jar 在 `/tmp/zyfallbackbuild`，后续重启用 `/tmp/restart-18290-fallback.sh`。
- 演示入口：`http://10.218.4.10:3201/login`（13000000002，任意码）→ `…/sessionDetailV2?chatSessionId=…&userId=900002&page=1&pageSize=10`。
- F10 沙箱重建：`/tmp/restart-18294-r4.sh`（现停机）。

## 六、模式/年份/data-fresh 口径核查（2026-10-08，双仓只读专线）

**① 模式判定**：无"日历切阶段"——模式 = 上游按省签发策略（`/hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy` → `prepareType`）→ 持久化（前端 `customerDetailSession.ts:43-70` 策略优先；后端 `ScoreCatalogService.java:279/304`）。今日实测 = **PREDICT**；"高考期间才 VOLUNTEER"无代码依据（VOLUNTEER 开关=策略已发布+权益；本环境 VOLUNTEER 会 84009）。⚠️ **术语三义冲突**：代码 PREDICT=模拟填报 / VOLUNTEER=智能填报（与口语"智能模式=PREDICT"相反）；desc 自身混用（PREDICT/智能填报 170 次、PREDICT/模拟填报 28 次、VOLUNTEER/智能填报 18 次）→ 口径须先统一。

**② 数据年份**：主路径 **2026**（examYear 缺省=当年；demo 日志 573×2026 / 0×2025）。**PREDICT(模拟填报) 按 3.1.0 设计用 2025 志愿数据**；release-4.0.0 文档已自认冲突并定方向"按 prepareType+实际 examYear 统一" → **口径待用户裁决**。硬编码残留：`PlanningStateService.java:6516`；web `index.tsx:139/176/589/601`、`WorkspacePanel:242-251`；agent `score_query_tool.py:285` / `internal_client.py:2061` / `batch_subject_mapping.py:126/163`。实测反例：会话 10041940（examYear=2025 由调用方带入）。

**③ hl-wish 对照**：口径源头——模式 = |已发布策略行| 的 prepareType（`VolunteerPolicyServiceImpl.java:256-279`）；年份 = 策略行 year/baseYear/convertYear（非硬编码）。zhiyuan 已对齐"策略优先"、未对齐"年份读字段"；对齐建议：年份字段化 + 删硬编码 + 术语统一。

**④ data-freshness**：定位 = **VOLUNTEER-only**（`DataFreshnessSchedulePolicy.java:18-29`：VOLUNTEER + GOING/WAIT；120/180/300 分档）；PREDICT 静默宽容；后台总闸默认关（本地栈关）。"高考期间"仅行业习惯，非代码判据。**已修**：前端模式判定顺序 bug（先判 `智能填报` 字样 → PREDICT 误判 VOLUNTEER → 误弹"2026年招生计划数据已更新"/planYear 2026，与后端"2025"摘要同页矛盾；两文件两份拷贝）→ `8661756`（`utils/prepareTypeText.mjs` code 优先 + 5 条回归单测）。

**⑤ 远端复核（2026-10-08，fetch 比对）**：`git fetch` 后克隆点→origin/master/release 窗口共 64 个提交（至 09-22）；**模式/年份链五个关键文件零改动**（PrepareType / `SelectSubjectPolicyServiceImpl` / `VolunteerPolicyServiceImpl` / `PreBatchPolicyTypeServiceImpl` / `PlanDataTypeEnum`）；唯一变动的 `MemberScoreServiceImpl` 为"成绩流水 + 填写次数配额（按期间配置、自然年重算）+ 批次线校验 + 换票对照最新流水"，其模式/年份用法（`convertYear` / `volunteerPolicy.getYear()` / `PrepareType`）与原一致 → **按用户裁决：维持当前口径**（PREDICT=模拟填报用 2025 志愿数据按 3.1.0 设计；zhiyuan 年份硬编码清理不启动）。动向记录：hl-wish 新增"成绩变更配额"机制——若 zhiyuan C 端（补录/换票）需与上游对齐再跟进。

**⑥ 空会话"更新成绩"84009 根因（2026-10-08 上午实测）**：用户实测路径——空档案会话（10041975，安徽/507 分）出"成绩核对卡"→点确认→**执行 failed、code=84009「当前策略已失效」**、卡转 expired。证据链：① 卡载荷 `scoreUpdateRequest` 无 prepareType；② 后端 `fillProvinceDefaultsIfMissing`（`ChatSessionBizService:547-570`）**按省策略实时推导**（`ScoreCatalogService.provinceDefaultsOrNull:270` → `gaotuClient.getSubjectPolicy`，非静态表）→ 日志 `filled province prepareType=VOLUNTEER province=340000`；③ 执行时 `ProgramPageReq(... prepareType=VOLUNTEER, score=507 ...)` → 上游 `84009`；④ 网关 `execute stage response: status=failed code=84009`。**上游直连实测（noToken 口子）：今日 330000/340000/360000 三省策略均 = `VOLUNTEER` + `year=2027`** —— 上游已切新一届填报季；本环境**合成会员只有 PREDICT 取数策略**（演示通道老账"待数据侧补齐 VOLUNTEER 策略"）→ 策略优先推出的 VOLUNTEER 补录，确认拉数必断。**非本地代码 bug**（填充忠实策略）；影响面=任意新建/无档案会话的补录确认；旧会话（携带 PREDICT）不受影响。另注：policy `year=2027`——"年份按策略字段取"落地后新会话将取 2027（新周期），与"26 年"属不同届，文案口径需留意。**卡片顺序**：已修 `MessageList`（提案卡移至终态答案/错误之后——文案在上、卡在下；用户实测原顺序不对）。**提案卡卡片壳**：两个渲染点套 `.turnLiveCard`（白底圆角浅边投影；用户实测"很裸/灰字不是卡片样式"）——`e74ca6f`。**空会话候选池 NPE**（用户实测点"生成候选池"报 null、池子未生成）：`VolunteerFilterChain.buildQueryCondition:57` 对 `subjectList`（从零档案整个缺失 = null ✗）直接 `.stream()` → NPE；已做空值兼容（缺失=无选科信息，下游天然放行）——`d31646e` 已部署（部署时旧进程优雅停机超 45s、脚本保守拒杀致 1-2 分钟中断，需把 `/tmp/restart-18290*.sh` 的等待窗口放宽/二次强杀，记待办）。**代理侧逻辑缺口（用户口径）**：优势科目可由 `subjectScoreList` 自动推断（选考三科中较高者），不该反问用户；选考明细缺失亦应优先推导——记入代理线待办。**空会话自举 110 toast**（用户实测"下载志愿数据文件失败"提示）：`initial-plan/generate` 在空档案会话上走到读志愿文件（本地无文件 + OSS 本地禁用）→ 抛 110 基础设施文案 → 前端该调用静默清单只有 `[-1,404]` → toast 弹出 ✗ → **加入 110 静默**（WorkspacePanel 自举调用点）；**后端待办**：无档案/无文件时该读路径宜优雅返回空而非抛 110（`VolunteerBizService:502` / `ChatSessionBizService:1355` 的 `loadFinal…`/`load…` 抛点）。**补录卡去重**（用户补充"成绩更新确认卡从没正常显示过"）：`diff.summary` 一句话摘要与 `diff.scoreUpdate` 结构化块同源、九成重复 → **有结构化块时不再铺摘要**（信息不丢；`examYear` 补进结构化元信息行；`proposal-summary` testid 与既有断言核对无冲突）——`ProposalCard.tsx`。**冷加载兜底卡增强 + 失效卡交互**（用户实测"下面还有个'方案调整预览/已过期'"与"打字确认→提示'当前对话引擎不可用'"）：① 兜底卡此前只传 `proposalRef` → 落兜底标题、明细全丢 ✗ → `LastProposalVo` 增 `kind`/`scoreSummary`（`ChatSessionBizService.buildLastProposal`），前端拼出"更新成绩"+结构化明细；② 回合级失败事件此前统一落"当前对话引擎暂时不可用" ✗ → `MessageList` 对带 code 的 `turn.error` 走 `proposalFailureText`（与失败卡同一张 code→中文表）——打字"确认"撞已失效卡时显示"这张确认已经失效（会话里已有更新的预览），请用最新预览重新确认"。

## 四、pending（更新）
- **F10 已修复并推送 ✅**：`072ff5c`（broker 边界原生→业务号翻译 + 回放过滤防御放行 + 2 条新单测；全量 unit 2012 passed，唯一红为既有 dialog_quality_gate 夹具问题）。沙箱 r4 契约 **13/13 全绿（F10 回绿）**，日志 `/tmp/e2e-verify-c4-verify-20261007-r4-contract.log`；Redis db9 数据佐证澄清事件已同盖业务 UUID。✅ **已部署演示栈 18291**（19:50 重启，pid 32605，health 200；env 先抓活进程快照再搬运、与 demo 姿势逐项比对；启动日志 `codex_write vs MCP_MODE=readonly` 警告经查为历史常态、非本次引入）。备注：沙箱事件流 24h TTL 跨轮残留，若遇"卡串轮"先换盐/epoch。
- **Java 专线交付 ✅**：H3 `ab4a292` / M2 `90cacec` / M3 `92fbf90` 实现+单测绿；H2 按授权止步，交 D1 真库 SQL 用例 8/8（`2c5a96e`；写共享库的既有表、仅自建随机 session id/随机 key，复核残留 0）与 `H2-WRITE-CAS-PLAN.md`（17 调用点分类+三策略+DoD）。全量单测 931/0/7skip。写路径沙箱 e2e 5/6，唯一红 F09 已移交前端波（嫌疑=WIP 用例/夹具 turnId 覆盖，非本波后端改动）。
- **演示栈 18290（Java 后端）19:59 被内核 OOM 杀死**（今晚并行负载 + 无 swap；dmesg 实锤 19:59:33 杀 pid 31744、RSS 2.8G；20:10/20:18 同因连杀两只 Chromium）→ 已用 `/tmp/restart-18290.sh` 重启（pid 22119，health 200），**jar 含 H3/M2/M3（即三项已上线演示栈）**；`oom_score_adj=-500` 保护。同因降载：**F10 沙箱（18293/18294/3202）已停**（腾 ~1.6G）。
- **前端波交付 ✅**：`41d37e6`（H1/M1 提案卡认 stale_state/失败码、中文口径、按钮收起）/ `8b2e5dd`（M4 看门狗跳过后台节流）/ `bc1e216`（M5 F09 断言补强）+ **跨线真根因 `35ddbf5`**（服务端 prepare upsert 带 CAS 修订号，7 行，与补录路径 `7d23ade` 同口径——此前转述的"turnId 覆盖"嫌疑被证伪）。单测 25/25 + 118/118；沙箱 e2e **契约 13/13 + 写 6/6（F09 首次全断言绿）**。**已部署演示栈**：服务端用 `/tmp/f09fix` 源码树（与 bc1e216 逐字节一致、即沙箱实测同一构件）重建 jar 重启 18290（pid 16146，health 200，OOM 保护 -500）；前端为 3201 dev 直读工作树（刷新即生效）。前端波沙箱（3205/18301-18304）已停（腾内存 + 给 H2 让路）。F09 绿依赖 `35ddbf5`，若回退会回红。
- **runner 补丁**：`scripts/run-codex-e2e-in-container.sh` 补透传 `ZHIYUAN_E2E_CONTROL_URL`（此前 fixtures 闸门控制会默认打到 18293 沙箱，易串线）。
- **运维插曲**：20:55 同波 OOM 连坐 18090（test-www Java 后端）→ 用户点名后按 `bc1e216` 同款 jar 重启（pid 22566，health 200；`smoke-standardtest-web-proxy` **14 项全绿**）；同批给 18090/18091/18291 设 `oom_score_adj` 保护（-500/-400/-400）。
- **H2 演示栈真实验收 ✅（2026-10-07 夜）**：用户实测 900040 全链——发"帮我补足到 80 个志愿" → 提案卡（21:57:50 prepare；`proposal.preview` seq 189）→ 用户点确认（22:13:43）→ `conversationAction.result: status=applied, code=0, newStateVersion=5` → 规划态 **units=80**（45 原有 + 补入 35，`strategy=fill_missing_count`）。事件流（Redis db9）与 DB 双证据；卡片渲染核对正常（标题/摘要/状态均可读）。
- **夜间新发现（演示验证副产品）**：① **助理叙述与预览卡矛盾**——卡说"当前方案有 45 个专业组…补入 35 个"（对，且实际执行一致），助手文案却说"你现在的志愿表还是空的、从零补满"（错）→ 代理侧口径修；② "方案调整预览"**无逐条明细**（`affectedUnitIds` 空）→ 后端预览增强点（确认前看不到具体哪 35 条）；③ **900047 成绩行缺各科成绩** → 补录 prepare 被 `validateCreateSessionReq`(110「请填写各科成绩后再创建会话」) 挡死、且无填写交互（"要成绩才能出卡 vs 卡用来填成绩"死锁，校验为 `d413a31` 时代老逻辑、非今晚引入）→ 体验缺口 + 该行数据修复待用户批准。
- **H2 写路径统一 CAS 交付 ✅**：`167d4a8`（实现：17 落点按站点策略收口 `savePlanningState`；基线载体 `baselineDataValue`；观测锚点 `logWriteCasSkipped`）→ `8489844`（15 条防覆盖单测）→ `c4d23cd`（D1 ⑧ 翻转：CAS 挡第二写者/重读合并两者都在；类 8/8）→ `9b1a9d8`（交付记录+裁决回填）。模块全量 **959 绿 / 0F / 5skip**；沙箱写路径 e2e **6/6 ×2 轮**（runId r8，新盐复跑）+ 并发压测（32 并发：8 响亮 40901 / 24 成功 / 0 5xx；跨域风暴无整文档覆盖；version 精确增长）。偏离 2 处已注明（`applyFixProposal` 有意 FAIL_CONFLICT；`checkDataFreshness` 保守合并待收敛）。**已部署演示栈 18290**（用户点名；`/tmp/h2build` 从推入点干净构建的 jar，pid 11888，health 200，OOM 保护 -500；回退=换回 `/tmp/f09fix` 的 bc1e216 jar）；standardtest 18090 观察后再跟。另修共享脚本小雷：`stop-codex-local.sh` 缺 pid 文件时裸 `return` 在 `set -e` 下中断整个停链（已修：pid 缺失分支改 `return 0`）。
- 磁盘救援：**已执行（用户批准"全批"）**——binlog.000001–000010 已 PURGE（~9.8G），过期 30d→2d 已 `SET PERSIST`（重启不丢）；Docker 四个旧镜像/容器已删（~4.1G）；/tmp 995 个旧文件（0.73G，清单存 `/tmp/cleanup-manifest-20261007.txt`）与 head-build（0.24G）已删。**剩余 15G / 62%**（清理前 752MB）。
