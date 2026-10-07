# H2 专线：写路径 CAS 化的**实施计划**（附 D1 真库读数）

> 来源：`docs/superpowers/reviews/2026-10-07-dialogue-engine-iteration-and-review.md` §二 H2/D1。
> 状态（2026-10-07 深夜）：**H2 已按本计划落地并全绿**——commit `167d4a8`（实现）/
> `8489844`（单测）/ `c4d23cd`（D1 ⑧ 翻转），读数与遗留见 §6。上半程"先交真库用例 +
> 精确实施计划"的判定保持不变（统一 CAS 是每站点独立冲突语义的结构化重构）。基线 `92fbf90`
> （H3/M2/M3 已在 `ab4a292`/`90cacec`/`92fbf90` 落地）。

## 0. 为什么没在这一波直接改代码（判定依据）

`savePlanningState` 已是私有（`PlanningStateService.java:7416`），但它现在的语义是
"**内存快照整文档 `updateById`**"。要让写路径"统一 CAS"，每个调用点都必须先回答三件事，
而答案**逐站点不同**：

1. **基线是谁**：方法开头那次 `loadPlanningState` 读到的行值（还是嵌套写之后的最新值）；
2. **CAS 输了怎么办**：重放（仅当变换是纯内存且幂等）/ 重读最新后**只合并本方法的域字段** /
   响亮冲突（用户动作不许静默丢）；
3. **嵌套写怎么处理**：本类里有"外层 load → 内层 `generateOrderedPlan`（自己也 load+save）
   → 外层再 save 自己那份 2208 年之前的快照"的形状（`reorderWorkingPlanInternal`，
   `PlanningStateService.java:2208→2216→2228`），外层快照**必然**落后。

17 个落盘点里混着：纯内存变换（可重放）、带外部副作用的（拉上游几百 ms、记行为事件、
生成 Excel）、读入口的懒写、以及上面这种嵌套写。机械统一会让"覆盖"变成"静默不写"或
"重复副作用"，比现状更坏——这正是任务里"不要半拉子重构"要避免的。故本波只交：
**D1 真库用例（已绿）+ 本计划**。

## 1. D1 已交付（真库，隔离库 `zhiyuan_codex_local` @ 13306）

`zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/shared/ChatSessionExtraDataCasSqlBehaviorIntegrationTest.java`
（8/8 绿；运行方式见类头注释，缺 `CONVERSATION_TEST_DB_URL` 整类 skip 不记为通过）。

实测钉住的 SQL 级事实（对 H2 设计有约束力）：

| # | 事实 | 含义 |
|---|---|---|
| ① | 行仍是读到的值 → CAS 赢；where 带 chat_session_id/data_key/data_version，别的会话同键行不动 | 基本语义成立 |
| ② | 并发写者先落盘 → CAS 输且**不覆盖对方** | 读路径"不覆盖并发写"的底座是实的 |
| ③ | `expected=null` ⇔ `IS NULL`，两条分支互斥；空壳行补值后第二次 null 期望必须输 | 懒导入两条 CAS 分支正确 |
| ④ | 同值重写（new == expected）**返回 true**（Connector/J `useAffectedRows=false` → "匹配行数"口径） | 幂等补写不会被误报冲突；CAS 的 true 只说明"值还是我读到的那份" |
| ⑤ | 列 collation 实测 `utf8mb4_0900_ai_ci`：**只差大小写的改动对 CAS 等于"没改过"** | ⚠ 开放决策 1（见 §4）：旧快照仍能通过比较把只差大小写的并发写覆盖 |
| ⑥ | 同列 NO PAD：只有尾随空格差异 → **不匹配**（CAS 输，方向安全） | 字符串比较按列 collation 走，逐条实测 |
| ⑦ | 两线程各持同一快照并发 CAS：**恰一个赢**，库里是赢家整文档（无字段级混合） | 真并发下防线成立 |
| ⑧ | 两个"整文档读-改-写"写者无条件 `updateById`：后写者把先写者改动**整体**冲掉 | **H2 的证据**（可执行）；H2 落地后这条断言应翻转，不删 |

## 2. 现状清单（17 个落盘点 → 分类与策略）

分类：**A** 纯内存重放安全；**B** 带副作用/昂贵拉取（不可重放整方法）；
**C** 重读最新 + 只合并本方法域字段；**E** 嵌套写（外层基线必然过期）。

| file:line | 方法 | 形态 | 类别 | 建议策略 |
|---|---|---|---|---|
| `PlanningStateService:521` | `syncProfileStateFromLegacy`(markStale=false) | load→hydrate→save | A | CAS 输：重读重放 ≤3（hydrate 幂等，只补空） |
| `:518→2451` | `touchAndSavePreference` | +version +stale | A | 同上（重放一次会多 bump 版本 → 定口径见 §4-3） |
| `:570` | `applyScoreDetailUpdate`（补录） | load→hydrate→mark stale→save | A | 重读重放 ≤3；最终输 → 响亮失败（用户动作） |
| `:604` | `getCandidateViewState` | **读入口懒写**（仅缺视图时） | A | CAS 输：重读后判空，已有就不写（本就是"只补缺"） |
| `:622` | `updateCandidateViewState` | 用户动作，纯内存 | A | 重读重放（把 req 的视图套到最新态）≤3，最终输 → 409xx |
| `:642` | `generateInitialRecommendation`（页面自举） | 内含 overlay 刷新（外部拉数，已带 CAS） | B+C | 不重放整方法：重读最新 → 只写 `initialRecommendationState`/phase/version |
| `:661` | `analyzePlanAdjustment` | 同上（重建需要以最新态为基） | B+C | 重读最新 → 以最新态重算（内存）→ CAS |
| `:713` | `exportOrderedPlan` | 副作用=行为事件落库 + 生成 Excel | B | 不可重放：事件落盘与 state 落盘拆开；state 写走 C，事件写幂等键 |
| `:1489` | `generateCandidatePool` | 上游 recommend 几百 ms | B+C | 重读最新 → 只写候选池域字段（version 以最新 +1） |
| `:2228` | `reorderWorkingPlanInternal` | **E**：内层 `generateOrderedPlan` 已 save | E | 外层改用内层返回的最新态为基线（或去掉外层重复 save） |
| `:2442` | `runReview` | 内部 `resolveEffectiveCandidates` 读外部 | B+C | 重读最新 → 以最新态重算 checks → CAS |
| `:5958` | `checkDataFreshness` | 内含上游 hash 查询；changed 才写 | B+C | 重读最新 → 只合并 dataFreshness 域字段 |
| `:6049` | `markUnsupportedDataFreshnessCurrent` | 纯内存 | A | 重读重放 |
| `:8341` | `persistRecommendationOverlay`（行缺失分支） | 首建 | 保持 | 首建 INSERT 语义不动（撞键已有兜底） |
| `:12251/:12261` | `saveWorkingPlanState`/`saveOrderedState` | 被 9 个写入口复用的收敛点 | 收敛点 | 落盘改走 CAS；**基线由 state 携带**（见 §3） |

调用方分布（决定改动面）：`PendingPlanningCommandBizService:150-206`（确认链执行段、
`generateOrderedPlan`）、`IntegrationSessionService:165`、以及本类内 9 处
`saveWorkingPlanState`/`saveOrderedState` 调用。

## 3. 设计（草案）

1. **基线载体**：`PlanningStateDTO` 增 `@JSONField(serialize=false, deserialize=false) String baselineDataValue`。
   由 `loadPlanningState`/`loadPlanningStateReadOnly` 填充——**懒导入/读路径补写之后**以
   "实际落在库里的那串"为准（否则写者拿到的基线一上手就是过期的）。
2. **`savePlanningState` 语义**：有基线 → `updateDataValueIfUnchanged(rowRef, baseline, newValue)`
   并返回 boolean；无基线（首建/导入）→ 现状路径（INSERT + DuplicateKey 读回赢家）。
3. **三个显式策略**（每站点写死一种，不许默认）：
   - `RETRY_REPLAY`：纯内存变换，CAS 输 → 重读 → 重新施加变换 → 再 CAS（≤3 次）；
   - `MERGE_LATEST`：重读最新 → 只覆盖本方法的域字段 → CAS（≤3 次）；
   - `FAIL_CONFLICT`：用户动作最终输 → 抛 409 家族（沿用 `40901/40906` 语义面），
     绝不静默丢。
4. **不变量**（测试要钉的）：任何写法不得"内存快照整文档覆盖最新行"；嵌套写之后
   外层必须刷新基线（内层返回的 state 即最新）；读入口（`getCandidateViewState` 类）
   只许"只补缺"。
5. **不做**：不动读路径既有 CAS（`loadPlanningState(5373)/persistImportedPlanningState(5418)/
   savePlanningStateIfUnchanged(5479)/persistRecommendationOverlay(8332)`）；不动 DTO 的
   JSON 形状（baseline 字段不序列化）。

## 4. 开放决策（需裁决，H2 开工前定）——均已裁决

1. **`data_value` 列 collation**：维持 `utf8mb4_0900_ai_ci`（D1 ⑤：只差大小写的并发写
   检测不到）还是迁 `utf8mb4_bin`（比较改逐字节）？迁移代价：一次 DDL（大表锁评估）+
   读路径 CAS 从"赢"变"输"的边角会更多（方向安全，但补写会更常放弃）。
   → **裁决：维持 `utf8mb4_0900_ai_ci` 不动**；迁移评估记入 §6 遗留。
2. **冲突的对外语义**：`FAIL_CONFLICT` 抛什么码、前端/网关拿它做什么（重试提示 or 409 卡）。
   → **裁决：沿用 `40901`/`40906` 语义面，不新增错误码；前端/网关本波不动**。
3. **version 递增口径**：重读/合并后以最新为基 +1（允许跳号）——现状本就允许跳号，
   建议写进不变量。
   → **裁决：以最新为基 +1（允许跳号），写成不变量，测试钉住**。

## 5. 验收（H2 落地时的 DoD）

- 单测：§2 表里每个落盘点至少一条"并发写者先落盘 → 本写不覆盖对方字段 / 或响亮冲突"。
- 真库：本波第 ⑧ 条翻转（改成"CAS 挡住第二个写者 / 重读合并后两者都在"）。
- e2e：写路径 6 条（F07 后半/F08/F09/F13/补录/F14）照常全绿 + 复刻 d098da8 的并发压测
  （写路径版：页面自举 × 补录 × 候选池刷新交叉）。
- 观测：CAS 输/放弃落盘的日志计数（现在读路径有 `planningStateCasSave skipped`，写路径要有同类锚点）。

## 6. 交付记录（2026-10-07 深夜，分支 `wip/2026-09-28-p2-write-loop-green`）

实现 `167d4a8` / 单测 `8489844` / D1 翻转 `c4d23cd`（均已推 origin）。

**三段策略落点**（file:line 为交付时点）：

- 收敛点：`savePlanningState`（~7888）+ `handleInsertRace`（~7944）+
  `logWriteCasSkipped`（~7973，reason=`row_changed_under_us`，观测锚点 ✓）+
  `WRITE_CAS_ATTEMPTS=3` / `saveWithReplay`（~7982/~7994）/ `writeCasConflict`（~8009）。
- `RETRY_REPLAY`：draft 四连 select/remove/lock/ban（~2151-2264）、`generateOrderedPlan`（~2290）、
  `applyScoreDetailUpdate`（~560）、`updateCandidateViewState`（~648）、
  `touchAndSavePreference/Constraint`（~2795/~2819）、profile 懒同步、
  `markUnsupportedDataFreshnessCurrent`（~6461，A 类：只记日志不抛）。
- `MERGE_LATEST`（只合并本方法域字段）：`generateCandidatePool`（~1565）、
  `runReview`（~2723）、`analyzePlanAdjustment`、`checkDataFreshness`（~6273-6397，
  `data_freshness_check`/`…_merge` 循环）、`generateInitialRecommendation`（B+C）、
  `exportOrderedPlan`（~768，副作用先行，CAS 输记账后仍出 Excel）、
  `persistRecommendationOverlay`（~8896，写后刷新基线，防同调用内二次 CAS 拿旧基线）。
- `FAIL_CONFLICT`（`40901` 家族，无新码）：`generateOrderedPlan` 耗尽、draft 四连耗尽、
  偏好/约束耗尽、`applyFixProposal`；E 类 `reorderWorkingPlanInternal`（~2427-2456）以
  **内层 `generateOrderedPlan` 返回态**为基线，attempt>0 才 reload。
- 读入口只补缺：`getCandidateViewState`（~627）。基线载体：`PlanningStateDTO.baselineDataValue`
  （不序列化；lombok 1.16.16 → `@EqualsAndHashCode(exclude = {...})`）。

**DoD 读数**：

- 单测：§2 每落点 ≥1 条"并发写者先落盘"钉子，15 条新测（`PlanningStateServiceTest` ~9082-9466）；
  类套 216 绿 0F/0E/3skip，模块全量 959 绿 0F/0E/5skip。
- 真库（13306）：⑧ 翻转前 = 后写者整文档覆盖、先写者全丢；翻转后
  `casWritePathBlocksSecondWriterAndMergeKeepsBoth` = CAS 挡住第二个写者、重读合并后两者都在；8/8 绿。
- e2e（自建沙箱 3203/18297/18295/18296/18298，runId `p2-20261007-r8`）：写路径 6 条两轮全绿
  （r8-1 6/6 1.9m；r8-2 6/6 1.8m）：F07 后半 / F08 / F09 / F13 / 补录成绩 / F14 假死。
- 写路径并发压测（d098da8 写版）：32 并发调用 → 8 次响亮 `40901`（HTTP 200）/24 成功/0 5xx；
  跨域风暴后候选池/初始推荐/overlay 三域都在（无整文档覆盖）；同域 4 写者 ×4 轮后最终视图 =
  某一个提交者的整份（无混合），version 随成功写精确增长。

**遗留**：

1. `data_value` collation 维持 `utf8mb4_0900_ai_ci`：迁 `utf8mb4_bin` = 一次大表 DDL +
   读路径 CAS 更多"方向安全"的输；D1 ⑤ 大小写边角仍在（只差大小写的并发写检测不到），
   未做迁移。
2. 修复应用链 `applySupportedFixProposalStrategy`（~1098-1102）的 FAIL_CONFLICT 是有意偏离
   计划策略：变换依赖同一份快照上刚算出的冻结排序结果，重放风险高，用户动作输不起 →
   不覆盖并发写、响亮冲突（代码内有注释说明）。
3. `checkDataFreshness` 的域合并为保守实现（整体重放本方法的域写），后续可收敛为严格的
   "只合并 dataFreshness 域"。
4. 测试侧：`PlanningStateServiceTest.DEFAULT_CAS_ANSWER` 现会在一命中的 CAS 里同步行对象
   新值（真库行为：命中即落盘）；`PlanningInitialPlanGenerationTest` /
   `PlanningStateSuggestionMappingTest` 的 store 桩补齐 CAS 双写与 id 回填。
