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
| 全量 Java | 1227 tests / 0 failures / 0 errors / 9 skipped（含默认 skip 的 env-gated golden） |

golden 回归命令（只读文件，不连库）：

```
STAGED_SOLVER_GOLDEN_FILES="/path/state.json[|/path/pool.json],..." \
  mvn -f zhiyuan-server/pom.xml -Dtest=StagedSolverGoldenTest \
  -DargLine=-Xmx4g test
```

## 3. 已知边界（不阻塞灰度，但切默认前需处理或明确接受）

1. **pending 无 TTL**：过期 pending 只会 409，不会错写；清理策略待 S4/运维。
2. **`solverVersion` 精确相等**：freeze 模式请求与 proposal 同源，部署/回滚
   不打断已冻结 pending；非 freeze 旧预览失败即要求重预览（fail-closed）。
   S4 改 major + digest。
3. **单元档位冲突**：无 tier 目标时 snapshot 也 409 `tier_fact_conflict`；
   等 J5.4/数据侧确认后放宽。
4. **Q13（排除生源省的 safety）与 Q14（单元模式向已有组加专业）**：
   Q14 的 named-add 已按“已有组不增加单元数”处理，add-by-scope 直接跳过
   已有组；Q13 仍待 J5.4 同步 review。
5. **diversity 未实现**：层序保留位置，默认 off。
6. **refill 目标口径**：每档 `max(当前, 池目标)`，所以用户目标 44 时池目标
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
