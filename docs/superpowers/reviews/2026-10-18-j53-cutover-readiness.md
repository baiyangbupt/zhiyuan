# J5.3 solver 切流前检查单与回滚手册（2026-10-18）

状态：**实现完成、复审修复完成、默认 shadow-only**。本文只覆盖 J5.3
staged solver 的灰度/回滚，不改变产品口径。

关联文档：

- 设计：`docs/superpowers/specs/2026-10-18-j53-solver-design.md`
- 评审：`docs/superpowers/reviews/2026-10-18-j53-solver-design-review.md`
- 提交：`bfb3200 feat(planning): implement J5.3 staged deterministic solver`

## 1. 当前默认值与开关

| 开关 | 默认 | 作用 |
|---|---|---|
| `solver.v2.shadow` | 关 | 旧 solver 生效，新 solver 只记录差异；异常吞掉 |
| `solver.v2.paths` | 空 | 逗号列表：`fill,initial,add,remove,replace,scope,refill` |
| `planning.user-goal.freeze-apply.enabled` | 关 | 预览冻结 proposal + 请求指纹，apply 优先回放 |

当前运行时：`-Dsolver.v2.shadow=true`，`solver.v2.paths` 与 freeze 均关闭
（Java pid 12938，2026-10-18 23:00）。

切流顺序建议：`shadow` → `fill` → `initial` → `add/remove/replace/scope`
→ `refill` → `freeze-apply` → 默认值。每一步单独观察、单独回滚。

## 2. 已通过的验收

| 项 | 证据 |
|---|---|
| S0a 快照/shadow/fixture | 单测 + 900018/28/38/900040/900045 shadow 零差异 |
| S0b 冻结回放 | 900040 fill 80→85；900045 fill 42→44（remove 4/add 6） |
| 范围类冻结 | 900045 `only_keep 浙江` READY、无 canonical 三件套，apply 成功 |
| 请求指纹 | 改 scope 请求 → `409 user_goal_request_changed` |
| S1 fill | 900040 覆盖预览；900045 preview/apply 一致 |
| S2 initial | 900040 forceRegenerate 80/80 set/order 一致 |
| S3 add/remove/replace | 900040 80→81 / 80→79 / 80→80，均 ready |
| S3 scope | 最终代码：900040 `add_units_by_scope` 浙江 80→82，日志 `staged dry-run scope ... selected=82 remove=0 add=2` |
| S3 refill | 最终代码：900045 42/45 缺口，日志 `refill staged solver applied: session=900045 target=45 current=42 added=16`；命令 steps 含 `working_plan_refilled`，postcondition=true，version 15→19，ordered 45 |
| 大池 | golden 10041983（12,510 候选）ready 80，`candidate_cap_applied`，239ms |
| golden 回归 | 900018/28/38/900040/900045/900016/900047/10041981/10041983/10041984 全部 ready；两次运行 selected 完全一致 |
| golden 指标对比 | `StagedSolverGoldenComparisonTest`：5 个 legacy-ready 会话五维（coverage/tierDev/churn/protectDef/utility）全部不劣；10041983 同一补偿安全候选宇宙 staged utility 4995 vs legacy 4937；另 5 个 legacy no_change 会话指标逐项相同 |
| 全量 Java | 1241 tests / 0 failures / 0 errors / 10 skipped（含默认 skip 的 env-gated golden） |

golden 回归命令（只读文件，不连库）：

```
STAGED_SOLVER_GOLDEN_FILES="/path/state.json[|/path/pool.json],..." \
  mvn -f zhiyuan-server/pom.xml -Dtest=StagedSolverGoldenTest \
  -DargLine=-Xmx4g test
```

## 3. 已知边界（不阻塞灰度，但切默认前需处理或明确接受）

1. **pending TTL 已实现**：`planning.pending.ttl-minutes` 默认 1440（24h），
   `<=0` 关闭。只过期 `active` 行，锚点取 **update_time**（缺失回退
   create_time）——tenant/session 只有一行，create_time 永不重置，按它计
   会让 24h 后重新 upsert 的 active 行被下一次读立即判过期。CAS 成
   `expired`；`applying` 的 claim 租约完全不碰。读路径
   `getActiveOrApplying` 过期后返回 null，`getCurrent` 返回 expired（upsert
   仍可按 revision 接续），旧 revision 确认会在 CAS 处 40902。
2. **`solverVersion` 兼容（S4 已落）**：结果/提案/请求/pending/gateway 带
   可选 `hardObjectiveVersion`（staged 写，legacy null）。两侧都非空时按
   major + canonicalObjectiveDigest + proposal↔solverResult 绑定判断，请求侧
   solverVersion 不再精确相等；任一侧缺失回退旧精确三件套，旧 pending 不受
   影响。部署/回滚跨版本冻结回放因此不再必 409。
3. **单元档位冲突**：无 tier 目标时 snapshot 也 409 `tier_fact_conflict`；
   等 J5.4/数据侧确认后放宽。
4. **Q13 / Q14 已收口（2026-10-18 深夜）**：
   - Q13：生源省被 `mustExcludeRegions` / `mustExcludeRegionIds` 明确排除时，
     `SafetyFloorSupport` 返回 `not_applicable` / `minLocalProtect=0` /
     `province_excluded`；判据直接复用 `RepairCandidateEligibility` 的区域
     排除（名字 + ID，ID 优先）。ID 从候选池里同省候选的 `provinceId` 取；
     池里没有同省候选时只走名字判据，不会误判。省名匹配用
     `RegionScopeSupport`（规范化身份 + 大区表，不做双向子串放大）。
     **J5.4 首片已落**：review 的 `safety_guard` 改为 `ReviewSafetyGuard`
     委托同一 `SafetyFloorSupport`，`not_applicable` 不再被 review 硬拦；
     solver 的本省匹配也切到 `RegionScopeSupport.sameRegionName`。
   - Q14：named-add 的纯加入与替换都支持换入已有组；目标总数按
     **新增单元数**（`addedUnitIds - currentUnitIds`）计算，不再把“已有组
     加专业”算成 +1 个单元。`addedUnitCount` 仍展示涉及多少个组。
     solver 输入前把已在 retained 里的 entityId 从 available 剔除，避免
     旧路径 duplicate entityId 把 preview 误 block。
     add-by-scope 继续跳过已有组（不会产生重复 entityId）。
5. **safety 口径已定**：solver 软层、review hard/hard、postcondition
   `safetyResult` 只报告，不因 safety 缺口回滚 apply。
6. **diversity 未实现**：层序保留位置，默认 off。
7. **refill 目标口径**：每档 `max(当前, 池目标)`，所以用户目标 44 时池目标
   45 会补到 45——这是既有 refill 语义，不是 solver 引入。

## 4. 切流操作

1. 备份目标会话：
   `assistant_chat_session_extra_data(planningState)` 原始 `HEX(data_value)`，
   同时清点 `assistant_chat_session_pending_confirmation`。
2. 重启 Java，只加一个 path：
   ```
   java -Dsolver.v2.shadow=true -Dsolver.v2.paths=fill ...
   ```
3. 观察：
   - `solver.shadow` 差异日志（shadow 与切流 path 互斥）；
   - blocked 诊断码：`candidate_shortage` / `candidate_cap_core_over_limit` /
     `solver_infeasible_after_cap` / `solver_timeout`；
   - `candidate_cap_applied` 的 original/solved/dropped。
4. 跑该 path 的 preview→apply golden；apply 后置校验必须通过。
5. 再扩下一个 path，不一次性全开。

## 5. 回滚

1. 去掉 `solver.v2.paths` 对应项（或整个参数），重启 Java。
2. freeze 已开启时，未确认的 pending：
   - 有 `frozenProposal`：去掉 freeze flag 后走旧“重新生成再应用”路径；
   - 无 `frozenProposal`：按旧 pending 兼容逻辑处理。
   已 apply 的会话不回滚方案，只回退后续执行路径。
3. 恢复验收时改动的会话：用第 4 节的 HEX 备份执行
   `UPDATE ... SET data_value=CONVERT(UNHEX('...') USING utf8mb4) ...`，
   并删除该会话的 pending 行。
4. 健康检查：`/gaotu-assistant-bot/inner/ops/health` 200，确认 cmdline 只剩
   `-Dsolver.v2.shadow=true`。

## 6. 本次真栈改动记录

- 900045：44→42（移 2 组）→ fill/freeze 42→44（remove 4/add 6）→
  only_keep 浙江 44→4 → 恢复 14/44。
- 900045：42/45 缺口 → refill 到 45（version 19）→ 恢复 14/44。
- 900040：仅只读预览（fill INFO、scope 80→82），未落盘；保持 5/80。
- 临时 pending 行（refill 验收）已随恢复删除。

## 7. 灰度上线记录（2026-10-18 深夜，localtest）

按 §1 顺序逐档重启并验收，最终运行时：

```
-Dsolver.v2.shadow=true
-Dsolver.v2.paths=fill,initial,add,remove,replace,scope,refill
-Dplanning.user-goal.freeze-apply.enabled=true
```

（Java pid 27011；health 200；启动日志 0 ERROR。S4 版本兼容/20k 学费/
fill 契约字段已在此进程生效；agent 18291 的 gateway 透传代码已提交，
待其下次重启激活。）

| 档位 | 验收 | 结果 |
|---|---|---|
| fill | 900045 移 2 组制造缺口 → fill 44 | staged `selected=44 remove=0 add=2`，apply 后 44 组、version 18；恢复 14/44 |
| initial | 900040 `forceRegenerate=true, overwriteExistingDraft=false` | staged `selected=80 candidates=120`，80 组/336 条保持；恢复 5/80 |
| add | 900040 点名加入西安工程大学第506组 | staged `selected=81 remove=0 add=1`，80→81 |
| scope | 900040 add-by-scope 浙江 2 | staged `selected=82 remove=0 add=2`，80→82 |
| refill | 900045 42/45 缺口走真实 pending command | staged `target=45 current=42 added=16`，version 19，postcondition=true；恢复 14/44 |
| freeze-apply | 900045 only_keep 浙江（无 canonical 三件套） | READY → apply 成功 44→4 组，version 17；恢复 14/44 |

注意：`overwriteExistingDraft=true` 会按 80 个选中条目重建为 44 个专业组
（每条目=专业、组内可多专业），这是 initial 重建语义，不是 staged solver
差异；灰度验收使用 `overwriteExistingDraft=false` 保持原 80 组。

## 8. 清理就绪盘点（2026-10-19）

- pending 表共 82 行：active 16、applying 3、applied 45、cancelled 6、
  expired 12。active/applying 中 plan_change 14/2、score_update 1/1、
  career_update 1。**19 行 active/applying 全部没有 frozenProposal /
  frozenSelectionDigest / frozenRequestDigest / hardObjectiveVersion**；
  freeze flag 开启后没有新的 frozen pending 产生（灰度期间无真实确认）。
- 3 条 applying 的 claim 已过期 265–583 小时；TTL 按设计不碰 applying，
  需要 reconcile 而不是 TTL。
- `assistant_planning_pending_command` 67 行全部 succeeded：
  apply_constraint_and_regenerate 24、update_score_detail 25、
  apply_plan_change_proposal 12、move 3、add/remove/replace 各 1；
  0 running/stale。
- 当前 Java 日志：0 次 `user_goal_frozen` / `solver_input_stale` / 409。
- **2026-10-19 已排空**：对 19 条 active/applying 逐会话调用
  `/session/pending/reconcile`；16 条 active → expired，2 条 applying
  plan_change → expired (`operation_result_unknown`)，1 条 applying
  score_update → applied。当前 active=0、applying=0。
- **frozen 覆盖已验证**：900045 制造缺口后 prepare，pending data_value 同时含
  `frozenProposal`/`frozenSelectionDigest`/`frozenRequestDigest`/
  `hardObjectiveVersion`；apply 成功 44 组，随后恢复 14/44。
- **legacy apply 删除闸门**：排空与 frozen 覆盖已满足；仅剩 24h soak
  （墙钟下限 2026-10-19 23:52，且要求期间零 `user_goal_frozen`/
  `solver_input_stale`/409/apply 失败）。删除前仍保留
  `isLegacyCanonicalProposal` 与精确版本回退。
- agent 18291 已于 2026-10-19 重启（pid 914，health 200），
  gateway `hardObjectiveVersion` 透传已激活。
